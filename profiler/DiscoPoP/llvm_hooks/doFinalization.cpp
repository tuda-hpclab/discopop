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

#include "llvm/Transforms/Utils/ModuleUtils.h"

bool DiscoPoP::doFinalization(Module &M) {
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
