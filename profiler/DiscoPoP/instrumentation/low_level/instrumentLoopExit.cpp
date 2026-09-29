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

void DiscoPoP::instrumentLoopExit(BasicBlock *bb, int32_t id) {
  BasicBlock *currentBB = bb;
  vector<Value *> args;
  LID lid = 0;

  for (BasicBlock::iterator BI = currentBB->begin(), EI = currentBB->end(); BI != EI; ++BI) {
    lid = getLID(&*BI, fileID);
    if (lid > 0 && !isa<PHINode>(BI)) {
      args.push_back(ConstantInt::get(Int32, lid));
      args.push_back(ConstantInt::get(Int32, id));
      args.push_back(ConstantInt::get(Int32, 0));  // instruction id will be replaced after the assignment of unique instruction ids
#if LLVM_VERSION_MAJOR >= 22
      CallInst::Create(DpLoopExit, args, "",
                       currentBB->begin()); // always insert to the beiginning
#else
      CallInst::Create(DpLoopExit, args, "",
                       &*currentBB->begin()); // always insert to the beiginning
#endif
      break;
    }
  }
}
