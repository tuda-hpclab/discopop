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
#include <set>
#include <string>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::CallInst;
using llvm::isa;
using llvm::LoadInst;
using llvm::Region;
using llvm::StoreInst;

// recieves the region and outputs all variables and variables crossing basic
// block boundaries in the region.
void DiscoPoP::PopulateGlobalVariablesSet(Region* top_region, std::set<std::string>& global_variables_set) {
  std::map<std::string, BasicBlock*> variable_to_bb_map;
  bool is_global_variable = false;
  for (Region::block_iterator bb = top_region->block_begin(); bb != top_region->block_end(); ++bb) {
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<LoadInst>(instruction) || isa<StoreInst>(instruction) || isa<CallInst>(instruction)) {
        // NOTE: changed 'instruction' to '&*instruction'
        const std::string var_name = DetermineVariableNameStatic(&*instruction, is_global_variable, false, "");

        if (is_global_variable) {  // add it if it is a global variable in the
                                   // program
          program_global_variables_set_.insert(var_name);
        }

        if (variable_to_bb_map.find(var_name) != variable_to_bb_map.end()) {
          // this var has already once recordded. check for bb id
          if (variable_to_bb_map[var_name] != *bb) {
            // global variable found. Insert into the globalVariablesSet
            global_variables_set.insert(var_name);
          }
        } else {
          // record usage of the variable.
          variable_to_bb_map.insert(std::pair<std::string, BasicBlock*>(var_name, *bb));
        }
      }
    }
  }
}
