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

void DiscoPoP::instrumentRealloc(CallBase *toInstrument) {
  // add instrumentation for calls to realloc
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

  // deallocate the block that was handed in
  args.push_back(ConstantInt::get(Int32, lid));
  Value *oldAddr = IRB.CreatePtrToInt(toInstrument->getArgOperand(0), Int64);
  args.push_back(oldAddr);
  IRB.CreateCall(DpDelete, args, "");
  args.clear();

  // allocate the block that came back. realloc is free to move the allocation, so the returned
  // pointer is the only one that describes it; registering the old address instead leaves the
  // runtime tracking a range the program no longer uses.
  args.push_back(ConstantInt::get(Int32, lid));
  Value *startAddr = IRB.CreatePtrToInt(toInstrument, Int64);
  Value *endAddr = startAddr;
  Value *numBytes = toInstrument->getArgOperand(1);
  args.push_back(startAddr);
  args.push_back(endAddr); // currently unused
  args.push_back(numBytes);

  IRB.CreateCall(DpNew, args, "");
}
