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

#include <vector>

#include "DiscoPoP.hpp"
#include "llvm_compat.hpp"

using llvm::CallBase;
using llvm::CallInst;
using llvm::cast;
using llvm::DebugLoc;
using llvm::Instruction;
using llvm::InvokeInst;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LoadInst;
using llvm::Value;

void DiscoPoP::InstrumentPosixMemalign(CallBase* to_instrument) {
  // add instrumentation for calls to posix_memalign
  LID const lid = dputil::GetLid(to_instrument, file_id);
  if (lid == 0) {
    return;
  }

  // Determine correct placement for the call to __dp_new
  Instruction* next_inst = nullptr;
  if (isa<CallInst>(to_instrument)) {
    next_inst = llvmcompat::NextInstruction(to_instrument);
  } else if (isa<InvokeInst>(to_instrument)) {
    // Invoke instructions are always located at the end of a basic block.
    // Invoke instructions may throw errors, in which case the successor is a
    // "landing pad" basic block. If no error is thrown, the control flow is
    // resumed at a "normal destination" basic block. Set the first instruction
    // of the normal destination as nextInst in order to add the Instrumentation
    // at the correct location.
    next_inst = &*cast<InvokeInst>(to_instrument)->getNormalDest()->getFirstNonPHIOrDbg();
  }

  IRBuilder<> irb(next_inst);

  std::vector<Value*> args;
  args.push_back(LidConstant(lid));

  // posix_memalign returns the block through its first argument, a void** out parameter. That
  // argument is the address of the caller's pointer variable, not of the allocation, so the
  // address of the block has to be loaded from it -- which is only possible after the call.
  LoadInst* allocated = irb.CreateLoad(char_ptr_, to_instrument->getArgOperand(0));
  // The load belongs to the instrumentation, not to the program. runOnBasicBlock walks the block
  // it inserts into and would reach the load again; without a debug location it has no LID, which
  // is what makes instrumentLoad leave it alone instead of reporting a read the program never made.
  allocated->setDebugLoc(DebugLoc());
  Value* start_addr = irb.CreatePtrToInt(allocated, int64_);
  Value* end_addr = start_addr;
  Value* num_bytes = to_instrument->getArgOperand(2);

  args.push_back(start_addr);
  args.push_back(end_addr);  // currently unused
  args.push_back(num_bytes);

  irb.CreateCall(dp_new_, args, "");
}
