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

using llvm::BasicBlock;
using llvm::CallInst;
using llvm::ConstantInt;
using llvm::Loop;
using llvm::Value;

void DiscoPoP::InstrumentLoopExit(BasicBlock* bb, std::int32_t id, Loop* l) {
  // see getLoopExitLID for exit blocks without a valid LID of their own
  LID const lid = GetLoopExitLid(bb, l);
  if (lid == 0) {
    return;
  }
  std::vector<Value*> args;
  args.push_back(LidConstant(lid));
  args.push_back(ConstantInt::get(int32_, id));
  args.push_back(
      ConstantInt::get(int32_, 0));  // instruction id will be replaced after the assignment of unique instruction ids
  CallInst::Create(dp_loop_exit_, args, "",
                   bb->begin());  // always insert to the beiginning
}
