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

void DiscoPoP::createTakenBranchInstrumentation(Region *TopRegion, map<string, vector<CU *>> &BBIDToCUIDsMap) {
  /* Create calls to count taken branches inbetween CUs during execution */
  for (Region::block_iterator bb = TopRegion->block_begin(); bb != TopRegion->block_end(); ++bb) {
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<BranchInst>(instruction)) {
        BranchInst *branchInst = cast<BranchInst>(instruction);
        // check for conditional branches, as unconditional ones can be ignored
        // for counting
        if (!branchInst->isUnconditional()) {
          // branchInst is conditional
          // prepare IRBuilder to insert instrumentation
          IRBuilder<> IRB(branchInst);
          // get BBId and CU IDS of the source
          string source_BBID = bb->getName().str();
          for (auto source_cu : BBIDToCUIDsMap[source_BBID]) {
            // get BBIds of all targets
            for (unsigned int i = 0; i < branchInst->getNumSuccessors(); i++) {
              string successor_BBID = branchInst->getSuccessor(i)->getName().str();
              // get CUs of all targets
              for (auto target_cu : BBIDToCUIDsMap[successor_BBID]) {
                // add instrumentation prior to the branch instruction
                vector<Value *> args;
                string source_and_target = source_cu->ID + ";" + target_cu->ID;
                args.push_back(getOrInsertVarName_dynamic(source_and_target, IRB));
                args.push_back(branchInst->getCondition());
                bool counter_active_on_cmp_value = (i == 0 ? 1 : 0);
                args.push_back(ConstantInt::get(Int32, counter_active_on_cmp_value));
                IRB.CreateCall(DpTakenBranchCounterIncr, args);
              }
            }
          }
        }
      }
    }
  }
}
