/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#include "../DiscoPoP.hpp"

#include "llvm/Transforms/Utils/BasicBlockUtils.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"

namespace {

// Makes one report of a basic block happen on the first pass through that block only, by moving the
// call that was inserted for it into `if (<semaphore> && !reported) { ...; reported = 1; }`.
//
// The runtime collects the reported indices in a set and only ever asks whether an index is in it,
// so every report after the first one leaves that set exactly as it was -- see __dp_report_bb and
// process_registered_bb_deps. Repeating them is not free, though: these two callbacks sit at the end
// of a basic block rather than at a memory access, which makes them by a wide margin the most
// frequently called of all. Measured over the programs in benchmark/pass_overhead they were 531 of
// 906 million calls, and between them they carried 375 distinct indices.
//
// One flag per call site rather than one per index: bbDepCount is incremented once per report
// inserted, so no two call sites ever announce the same index.
//
// The flag is read and written without synchronization, as the set behind it already was. It is
// only ever written to one, so two threads racing on it cannot lose that write; the worst a race can
// do is let both of them report, which is what every pass through the block did before.
//
// Both branches take over the debug location of the terminator they end up in front of. Llvm reads
// the location of a loop off the terminator of its preheader, so a branch without one there hides
// the loop from anything that asks afterwards.
void guardReport(Module &module, IntegerType *flagType, CallInst *report, Value *semaphore) {
  GlobalVariable *reported =
      new GlobalVariable(module, flagType, /*isConstant=*/false, GlobalValue::PrivateLinkage,
                         ConstantInt::get(flagType, 0), ".dp_bb_reported");

  // Taken before the split, which moves this terminator into the tail half and leaves the branch to
  // it behind in the block the report sits in.
  BasicBlock *block = report->getParent();
  const DebugLoc blockEnd = block->getTerminator()->getDebugLoc();

  IRBuilder<> builder(report);
  builder.SetCurrentDebugLocation(blockEnd);
  Value *guard = builder.CreateIsNull(builder.CreateLoad(flagType, reported));
  if (semaphore != nullptr) {
    guard = builder.CreateAnd(builder.CreateIsNotNull(semaphore), guard);
  }

#if LLVM_VERSION_MAJOR >= 22
  Instruction *guarded = SplitBlockAndInsertIfThen(guard, report->getIterator(), false);
  report->moveBefore(guarded->getIterator());
  new StoreInst(ConstantInt::get(flagType, 1), reported, false, guarded->getIterator());
#else
  Instruction *guarded = SplitBlockAndInsertIfThen(guard, report, false);
  report->moveBefore(guarded);
  new StoreInst(ConstantInt::get(flagType, 1), reported, false, guarded);
#endif
  block->getTerminator()->setDebugLoc(blockEnd);
  guarded->setDebugLoc(blockEnd);
}

} // namespace

bool DiscoPoP::doFinalization(Module &M) {
  // Report every basic block on the first pass through it rather than on every one, see guardReport.
  //
  // Deliberately here rather than where the reports are inserted: a guard splits the block it sits
  // in, and everything this pass does after inserting them runs on the instrumented module. The
  // removal of the instrumentation of the omitted instructions identifies the call it erases as the
  // instruction next to the load or store it belongs to, and instrument_loop walks the blocks of a
  // loop and skips the ones whose name begins with for.cond or for.inc -- a half of a split block
  // answers to neither. Both of them quietly produced different profiling results.
  for (const auto &report : insertedBBReports) {
    guardReport(M, Int8, report.first, report.second);
  }
  insertedBBReports.clear();

  // unique InstructionID assignment
  // write the current count of unique instructions to a file to avoid duplication between modules.
  outInstructionIDCounter = new std::ofstream();
  std::string tmp0(getenv("DOT_DISCOPOP_PROFILER"));
  tmp0 += "/DP_InstructionIDCounter.txt";
  outInstructionIDCounter->open(tmp0.data(), std::ios_base::out);
  if (outInstructionIDCounter && outInstructionIDCounter->is_open()) {
    *outInstructionIDCounter << InstructionIDCounter;
    outInstructionIDCounter->flush();
    outInstructionIDCounter->close();
  }
  // unique InstructionID assignment end

  // unique CallpathStateID assignment
  // write the current count of unique callpath states to a file to avoid duplication between modules.
  outCallpathStateIDCounter = new std::ofstream();
  std::string tmp01(getenv("DOT_DISCOPOP_PROFILER"));
  tmp01 += "/DP_CallpathStateIDCounter.txt";
  outCallpathStateIDCounter->open(tmp01.data(), std::ios_base::out);
  if (outCallpathStateIDCounter && outCallpathStateIDCounter->is_open()) {
    *outCallpathStateIDCounter << CallpathStateIDCounter;
    outCallpathStateIDCounter->flush();
    outCallpathStateIDCounter->close();
  }
  // unique CallpathStateID assignment end

  // CUGeneration
  // write the current count of CUs to a file to avoid duplicate CUs.
  outCUIDCounter = new std::ofstream();
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/DP_CUIDCounter.txt";
  outCUIDCounter->open(tmp.data(), std::ios_base::out);
  if (outCUIDCounter && outCUIDCounter->is_open()) {
    *outCUIDCounter << CUIDCounter;
    outCUIDCounter->flush();
    outCUIDCounter->close();
  }
  // CUGeneration end

  // DPInstrumentationOmission
  // Hand the dependencies of the instructions whose profiling was omitted over
  // to the runtime. Their __dp_read / __dp_write / __dp_alloca calls have been
  // erased (see runOnFunction), so this string is the only remaining record of
  // those dependencies.
  //
  // bbDepString covers the functions of THIS module only, and a module which
  // does not define main has no __dp_finalize call to attach the handover to.
  // Attaching it there therefore silently dropped the dependencies of every
  // translation unit but one, which turned e.g. a reduction variable in a
  // non-main file into an apparently private one. Registering from a module
  // constructor reaches every translation unit regardless of compilation order;
  // the runtime only records the string there and parses it during
  // __dp_finalize, once it knows which basic blocks were executed.
  if (!bbDepString.empty()) {
    Function *registration =
        Function::Create(FunctionType::get(Void, false), GlobalValue::InternalLinkage,
                         "__dp_register_bb_deps." + M.getModuleIdentifier(), &M);
    IRBuilder<> builder(BasicBlock::Create(M.getContext(), "entry", registration));
    Value *V = builder.CreateGlobalStringPtr(StringRef(bbDepString), ".dp_bb_deps");
    builder.CreateCall(M.getOrInsertFunction("__dp_add_bb_deps", Void, CharPtr), {V});
    builder.CreateRetVoid();
    appendToGlobalCtors(M, registration, 0);
  }
  // write the current count of BBs to a file to avoid duplicate BBids
  outBBDepCounter = new std::ofstream();
  std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
  tmp2 += "/DP_BBDepCounter.txt";
  outBBDepCounter->open(tmp2.data(), std::ios_base::out);
  if (outBBDepCounter && outBBDepCounter->is_open()) {
    *outBBDepCounter << bbDepCount;
    outBBDepCounter->flush();
    outBBDepCounter->close();
  }

  // DPInstrumentationOmission end
  return true;
}
