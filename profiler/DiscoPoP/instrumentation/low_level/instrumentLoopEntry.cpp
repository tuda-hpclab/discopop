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

void DiscoPoP::instrumentLoopEntry(BasicBlock *bb, int32_t id) {
  BasicBlock *currentBB = bb;
  vector<Value *> args;
  LID lid = 0;

  // Take care of the order of instrumentation functions for loop entry
  // and exit. Loop exit must appear before the next loop entry.
  // Usually every loop has a .end block as the exit block, thus the
  // exit of a loop will not be the entry of another loop. The first if
  // check is just in case the blocks are organized in a abnormal way.
  for (BasicBlock::iterator BI = currentBB->begin(), EI = currentBB->end(); BI != EI; ++BI) {
    if (isa<CallInst>(BI)) {
      Function *tmpF = (cast<CallInst>(BI))->getCalledFunction();
      StringRef tmpFn = tmpF->getName();
      if (tmpFn.find("__dp_loop_exit") != string::npos)
        continue;
    }
    lid = getLID(&*BI, fileID);
    if (lid > 0 && !isa<PHINode>(BI)) {
      args.push_back(ConstantInt::get(Int32, lid));
      args.push_back(ConstantInt::get(Int32, id));
      args.push_back(ConstantInt::get(Int32, 0));  // instruction id will be replaced after the assignment of unique instruction ids
#if LLVM_VERSION_MAJOR >= 22
      CallInst::Create(DpLoopEntry, args, "", BI);
#else
      CallInst::Create(DpLoopEntry, args, "", &*BI);
#endif
      break;
    }
  }
  // assert((lid > 0) && "Loop entry is not instrumented because LID are all
  // invalid for the whole basic block.");
}
