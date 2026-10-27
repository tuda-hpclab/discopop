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
#include <vector>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::Instruction;
using llvm::isa;
using llvm::LoadInst;
using llvm::Region;
using llvm::StoreInst;

void DiscoPoP::FillCuVariables(Region* top_region, std::set<std::string>& global_variables_set,
                               std::vector<CU*>& /*CUVector*/,
                               std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map) {
  LID lid;
  std::string var_name, var_type, var_def_line;
  bool is_global_var = false;
  // Changed TerminatorInst to Instuction
  const Instruction* t_inst;
  std::string successor_bb;

  for (Region::block_iterator bb = top_region->block_begin(); bb != top_region->block_end(); ++bb) {
    CU* last_cu = bb_id_to_cu_ids_map[bb->getName().str()].back();  // get the last CU in the basic block
    // get all successor basic blocks for bb
    t_inst = bb->getTerminator();
    for (unsigned i = 0, n_succ = t_inst->getNumSuccessors(); i < n_succ; ++i) {
      // get the name of successor basicBlock
      successor_bb = t_inst->getSuccessor(i)->getName().str();
      // get the first CU of the successor basicBlock and record its ID in
      // current CU's successorCUs
      last_cu->successor_cus.push_back(bb_id_to_cu_ids_map[successor_bb].front()->id);
    }

    auto bb_cu = bb_id_to_cu_ids_map[bb->getName().str()].begin();
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<LoadInst>(instruction) || isa<StoreInst>(instruction)) {
        // NOTE: changed 'instruction' to '&*instruction'
        lid = dputil::GetLid(&*instruction, file_id);
        if (lid == 0) {
          continue;
        }
        // NOTE: changed 'instruction' to '&*instruction', next 2 lines
        var_name = DetermineVariableNameStatic(&*instruction, is_global_var, false, "");
        var_type = DetermineVariableType(&*instruction);

        // (2025-10-30) removed due to llvm 19 compatibility
        /*
        int index = isa<StoreInst>(&*instruction) ? 1 : 0;

        Type *variableType = (&*instruction)->getOperand(index)->getType();
        while (variableType->isPointerTy()) {
          variableType = variableType->getPointerElementType();
        }
        string varSizeInBytes = to_string(variableType->getScalarSizeInBits() / 8);
        */

        var_def_line = DetermineVariableDefLine(&*instruction);

        const bool read_access = isa<LoadInst>(instruction);
        const bool write_access = isa<StoreInst>(instruction);

        const Variable v(var_name, var_type, var_def_line, read_access, write_access);

        if (lid > (*bb_cu)->end_line) {
          bb_cu = std::next(bb_cu, 1);
        }
        if (global_variables_set.count(var_name) || program_global_variables_set_.count(var_name)) {
          (*bb_cu)->global_variable_names.insert(v);
        } else {
          (*bb_cu)->local_variable_names.insert(v);
        }
      }
    }
  }
}
