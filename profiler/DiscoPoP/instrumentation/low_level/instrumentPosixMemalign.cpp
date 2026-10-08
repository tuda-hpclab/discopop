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

#include "../../DiscoPoP.hpp"

void DiscoPoP::instrumentPosixMemalign(CallBase *toInstrument) {
  // add instrumentation for calls to posix_memalign
  LID lid = getLID(toInstrument, fileID);
  if (lid == 0)
    return;

  // Determine correct placement for the call to __dp_new
  Instruction *nextInst = nullptr;
  if (isa<CallInst>(toInstrument)) {
#if LLVM_VERSION_MAJOR >= 22
    nextInst = toInstrument->getNextNode();
#else
    nextInst = toInstrument->getNextNonDebugInstruction();
#endif
  } else if (isa<InvokeInst>(toInstrument)) {
    // Invoke instructions are always located at the end of a basic block.
    // Invoke instructions may throw errors, in which case the successor is a
    // "landing pad" basic block. If no error is thrown, the control flow is
    // resumed at a "normal destination" basic block. Set the first instruction
    // of the normal destination as nextInst in order to add the Instrumentation
    // at the correct location.
    nextInst = &*cast<InvokeInst>(toInstrument)->getNormalDest()->getFirstNonPHIOrDbg();
  }

  IRBuilder<> IRB(nextInst);

  vector<Value *> args;
  args.push_back(ConstantInt::get(Int32, lid));

  // posix_memalign returns the block through its first argument, a void** out parameter. That
  // argument is the address of the caller's pointer variable, not of the allocation, so the
  // address of the block has to be loaded from it -- which is only possible after the call.
  LoadInst *allocated = IRB.CreateLoad(CharPtr, toInstrument->getArgOperand(0));
  // The load belongs to the instrumentation, not to the program. runOnBasicBlock walks the block
  // it inserts into and would reach the load again; without a debug location it has no LID, which
  // is what makes instrumentLoad leave it alone instead of reporting a read the program never made.
  allocated->setDebugLoc(DebugLoc());
  Value *startAddr = IRB.CreatePtrToInt(allocated, Int64);
  Value *endAddr = startAddr;
  Value *numBytes = toInstrument->getArgOperand(2);

  args.push_back(startAddr);
  args.push_back(endAddr); // currently unused
  args.push_back(numBytes);

  IRB.CreateCall(DpNew, args, "");
}
