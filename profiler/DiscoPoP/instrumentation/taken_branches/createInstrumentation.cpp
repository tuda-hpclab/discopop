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

#include <map>
#include <string>
#include <vector>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::BranchInst;
using llvm::cast;
using llvm::ConstantInt;
using llvm::IRBuilder;
using llvm::isa;
using llvm::Region;
using llvm::Value;

void DiscoPoP::CreateTakenBranchInstrumentation(Region* top_region,
                                                std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map) {
  /* Create calls to count taken branches inbetween CUs during execution */
  for (Region::block_iterator bb = top_region->block_begin(); bb != top_region->block_end(); ++bb) {
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<BranchInst>(instruction)) {
        BranchInst* branch_inst = cast<BranchInst>(instruction);
        // check for conditional branches, as unconditional ones can be ignored
        // for counting
        if (!branch_inst->isUnconditional()) {
          // branchInst is conditional
          // prepare IRBuilder to insert instrumentation
          IRBuilder<> irb(branch_inst);
          // get BBId and CU IDS of the source
          const std::string source_bb_id = bb->getName().str();
          for (auto source_cu : bb_id_to_cu_ids_map[source_bb_id]) {
            // get BBIds of all targets
            for (unsigned int i = 0; i < branch_inst->getNumSuccessors(); i++) {
              const std::string successor_bb_id = branch_inst->getSuccessor(i)->getName().str();
              // get CUs of all targets
              for (auto target_cu : bb_id_to_cu_ids_map[successor_bb_id]) {
                // add instrumentation prior to the branch instruction
                std::vector<Value*> args;
                const std::string source_and_target = source_cu->id + ";" + target_cu->id;
                args.push_back(GetOrInsertVarNameDynamic(source_and_target, irb));
                args.push_back(branch_inst->getCondition());
                const bool counter_active_on_cmp_value = (i == 0 ? 1 : 0);
                args.push_back(ConstantInt::get(int32_, counter_active_on_cmp_value));
                irb.CreateCall(dp_taken_branch_counter_incr_, args);
              }
            }
          }
        }
      }
    }
  }
}
