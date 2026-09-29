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
#include <unordered_set>
#include <queue>

string DiscoPoP::determineVariableDefLine(Instruction *I) {
  string varDefLine{"LineNotFound"};

  bool isGlobal = false;
  string varName = determineVariableName_static(&*I, isGlobal, true, "");
  varName = (varName.find(".addr") == varName.npos) ? varName : varName.erase(varName.find(".addr"), 5);

  string varType = determineVariableType(&*I);
//  std::cout << "\tvarName: " << varName << "\n";
//  std::cout << "\tvarType: " << varType << "\n";

  // search in prior Instructions and Basic Blocks for Debug records for varName to get defLines
  bool found_var = false;

  BasicBlock* current_bb = I->getParent();
  Instruction* current_inst = I;
  std::unordered_set<BasicBlock*> visited;
  std::unordered_set<BasicBlock*> added_to_queue;
  std::queue<BasicBlock*> queue;
  while(current_inst){
    visited.insert(current_bb);

    auto dbg_record_range = current_inst->getDbgRecordRange();
    auto dbg_variable_range = filterDbgVars(dbg_record_range);
    for(DbgVariableRecord &DVR : dbg_variable_range){
      std::string IRVarName = DVR.getValue()->getName().str();
      std::string SRCVarName = DVR.getVariable()->getName().str();
//      std::cout << "\t\t-> DbgRecord: IRVarName: " << IRVarName << "\n";
//      std::cout << "\t\t\t-> VarType: " << DVR.getVariable()->getType()->getName().str() << "\n";
//      std::cout << "\t\t\t-> SRCVarName: " << SRCVarName << "\n";
//      outs() << "\t\t\t-> ValueType: ";
//      DVR.getValue()->getType()->print(outs());
//      outs() << "\n";

      std::string type_str;
      llvm::raw_string_ostream rso(type_str);
      DVR.getValue()->getType()->print(rso);

      if((varName == SRCVarName) && (varType == rso.str())){
        found_var = true;
        varDefLine = to_string(fileID) + ":" + to_string(DVR.getDebugLoc().getLine());
        break;
      }
    }

    if(found_var) {
      break;
    }
    else {
      // proceed to prior instruction / basic block
      auto prior_inst = current_inst->getPrevNode();
      if(prior_inst == nullptr){
        // check if prior basic block exists
        for(auto prior_bb : predecessors(current_bb)){
          if(visited.count(prior_bb)){
            continue;
          }
          if(added_to_queue.count(prior_bb)){
            continue;
          }
          queue.push(prior_bb);
          added_to_queue.insert(prior_bb);
        }

        BasicBlock* selected_prior_bb = nullptr;
        if(queue.size() > 0){
          selected_prior_bb = queue.front();
          queue.pop();
          // get last instruction of prior BasicBlock as prior_inst
          prior_inst = selected_prior_bb->getTerminator();  // &(prior_bb->back());
        }
        else{
          // no prior, non-visited basic block exists
          break;
        }
      }

      current_inst = prior_inst;
      if(current_inst != nullptr){
        current_bb = current_inst->getParent();
      }

    }
  }

  if((varDefLine == "LineNotFound") && (programGlobalVariablesSet.count(varName))){
    varDefLine = "GlobalVar";
  }

  return varDefLine;
}
