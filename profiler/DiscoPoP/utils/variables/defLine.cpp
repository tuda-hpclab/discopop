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

#include <queue>
#include <string>
#include <unordered_set>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::DbgVariableRecord;
using llvm::filterDbgVars;
using llvm::Instruction;
using llvm::predecessors;

std::string DiscoPoP::DetermineVariableDefLine(Instruction* i) {
  std::string var_def_line{"LineNotFound"};

  bool is_global = false;
  std::string var_name = DetermineVariableNameStatic(&*i, is_global, true, "");
  var_name = (var_name.find(".addr") == var_name.npos) ? var_name : var_name.erase(var_name.find(".addr"), 5);

  const std::string var_type = DetermineVariableType(&*i);
  //  std::cout << "\tvarName: " << varName << "\n";
  //  std::cout << "\tvarType: " << varType << "\n";

  // search in prior Instructions and Basic Blocks for Debug records for varName to get defLines
  bool found_var = false;

  BasicBlock* current_bb = i->getParent();
  Instruction* current_inst = i;
  std::unordered_set<BasicBlock*> visited;
  std::unordered_set<BasicBlock*> added_to_queue;
  std::queue<BasicBlock*> queue;
  while (current_inst) {
    visited.insert(current_bb);

    auto dbg_record_range = current_inst->getDbgRecordRange();
    auto dbg_variable_range = filterDbgVars(dbg_record_range);
    for (DbgVariableRecord& dvr : dbg_variable_range) {
      const std::string ir_var_name = dvr.getValue()->getName().str();
      const std::string src_var_name = dvr.getVariable()->getName().str();
      //      std::cout << "\t\t-> DbgRecord: IRVarName: " << IRVarName << "\n";
      //      std::cout << "\t\t\t-> VarType: " << DVR.getVariable()->getType()->getName().str() << "\n";
      //      std::cout << "\t\t\t-> SRCVarName: " << SRCVarName << "\n";
      //      outs() << "\t\t\t-> ValueType: ";
      //      DVR.getValue()->getType()->print(outs());
      //      outs() << "\n";

      std::string type_str;
      llvm::raw_string_ostream rso(type_str);
      dvr.getValue()->getType()->print(rso);

      if ((var_name == src_var_name) && (var_type == rso.str())) {
        found_var = true;
        var_def_line = std::to_string(file_id) + ":" + std::to_string(dvr.getDebugLoc().getLine());
        break;
      }
    }

    if (found_var) {
      break;
    }
    // proceed to prior instruction / basic block
    auto prior_inst = current_inst->getPrevNode();
    if (prior_inst == nullptr) {
      // check if prior basic block exists
      for (auto prior_bb : predecessors(current_bb)) {
        if (visited.count(prior_bb)) {
          continue;
        }
        if (added_to_queue.count(prior_bb)) {
          continue;
        }
        queue.push(prior_bb);
        added_to_queue.insert(prior_bb);
      }

      BasicBlock* selected_prior_bb = nullptr;
      if (queue.size() > 0) {
        selected_prior_bb = queue.front();
        queue.pop();
        // get last instruction of prior BasicBlock as prior_inst
        prior_inst = selected_prior_bb->getTerminator();  // &(prior_bb->back());
      } else {
        // no prior, non-visited basic block exists
        break;
      }
    }

    current_inst = prior_inst;
    if (current_inst != nullptr) {
      current_bb = current_inst->getParent();
    }
  }

  if ((var_def_line == "LineNotFound") && (program_global_variables_set_.count(var_name))) {
    var_def_line = "GlobalVar";
  }

  return var_def_line;
}
