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

// Goes through all instructions in a loop and determines if they might be
// suitable for reduction.
// An entry is added to the 'loops_' vector and for each suitable instruction,
// an entry is added to the 'instructions_' vector.
void DiscoPoP::instrument_loop(Function &F, int file_id, llvm::Loop *loop, LoopInfo &LI,
                               map<string, string> *trueVarNamesFromMetadataMap) {

  auto loc = loop->getStartLoc();
  if (!dp_reduction_loc_exists(loc)) {
    return;
  }

  auto basic_blocks = loop->getBlocks();
  if (basic_blocks.size() < 3) {
    return;
  }
  // add an entry to the 'loops_' vector
  loop_info_t loop_info;
  loop_info.line_nr_ = loc.getLine();
  loop_info.file_id_ = file_id;
  loop_info.first_body_instr_ = &(*basic_blocks[1]->begin());

  std::string loopEndLine = dp_reduction_CFA(F, loop, file_id);
  loop_info.end_line = loopEndLine;
  loop_info.function_name = string((basic_blocks[1]->getParent()->getName()));
  loop_info.loop_id = get_or_register_loop_id(loop);

  loops_.push_back(loop_info);

  // call 'instrument_loop' on all its subloops
  auto const sub_loops = loop->getSubLoops();
  for (auto loop_it = sub_loops.begin(); loop_it != sub_loops.end(); ++loop_it) {
    instrument_loop(F, file_id, *loop_it, LI, trueVarNamesFromMetadataMap);
  }
  // The key corresponds to the variable that is loaded / stored.
  // The value points to the actual load / store instruction.
  std::map<llvm::Value *, llvm::Instruction *> load_instructions;
  std::map<llvm::Value *, llvm::Instruction *> store_instructions;

  // Scan all instructions in the loop's basic blocks to find the load and
  // store instructions.
  for (size_t i = 0; i < basic_blocks.size(); ++i) {
    llvm::BasicBlock *const bb = basic_blocks[i];

    std::string bb_name = bb->getName().str();
    if ((std::strncmp("for.inc", bb_name.c_str(), 7) == 0) || (std::strncmp("for.cond", bb_name.c_str(), 8) == 0)) {
      continue;
    }

    for (auto instr_it = bb->begin(); instr_it != bb->end(); ++instr_it) {
      llvm::Instruction *instr = &(*instr_it);

      auto opcode = instr->getOpcode();
      if (opcode != llvm::Instruction::Store && opcode != llvm::Instruction::Load) {
        continue;
      }

      // Add an entry to the corresponding map or invalidate an already
      // existing entry, if the same instruction is executed on multiple
      // lines.
      llvm::Value *operand = dp_reduction_get_var(instr);
      if (operand) {
        std::map<llvm::Value *, llvm::Instruction *> *map_ptr =
            (opcode == llvm::Instruction::Store) ? &store_instructions : &load_instructions;
        if (!map_ptr->insert(std::make_pair(operand, instr)).second) {
          if ((*map_ptr)[operand]) {
            llvm::DebugLoc new_loc = instr->getDebugLoc();
            llvm::DebugLoc old_loc = (*map_ptr)[operand]->getDebugLoc();

            if (!dp_reduction_loc_exists(new_loc) || !dp_reduction_loc_exists(old_loc)) {
              (*map_ptr)[operand] = nullptr;
            } else if (new_loc.getLine() != old_loc.getLine()) {
              (*map_ptr)[operand] = nullptr;
            }
          }
        }
      }
    }
  }

  // only keep the instructions that satisfy the following conditions :
  // - a variable that is read must also be written in the loop
  // - a variable must not be read or written more than once
  // - the store instruction comes after the load instruction
  std::vector<instr_info_t> candidates;
  for (auto it = load_instructions.begin(); it != load_instructions.end(); ++it) {
    if (!it->second)
      continue;

    auto it2 = store_instructions.find(it->first);
    if (it2 != store_instructions.end() && it2->second) {
      llvm::DebugLoc load_loc = it->second->getDebugLoc();
      llvm::DebugLoc store_loc = it2->second->getDebugLoc();
      if (!dp_reduction_loc_exists(load_loc) || !dp_reduction_loc_exists(store_loc))
        continue;
      if (load_loc.getLine() > store_loc.getLine())
        continue;
      if (load_loc.getLine() == loop_info.line_nr_ || store_loc.getLine() == loop_info.line_nr_)
        continue;

      if (loop_info.end_line == "LOOPENDNOTFOUND") {
        errs() << "WARNING: Loop end not found! File: " << file_id << " Function: " << F.getName()
               << " Start line: " << loop_info.start_line << "\n";
        continue;
      }
      if (loop_info.line_nr_ > std::stoul(loop_info.end_line))
        continue;

      // Check if both load and store insts belong to the loop
      if (load_loc.getLine() < loop_info.line_nr_ || load_loc.getLine() > std::stoul(loop_info.end_line))
        continue;
      if (store_loc.getLine() < loop_info.line_nr_ || store_loc.getLine() > std::stoul(loop_info.end_line))
        continue;

      if (it->first->hasName()) {
        instr_info_t info;
        info.var_name_ = dp_reduction_determineVariableName(it->second, trueVarNamesFromMetadataMap);
        info.loop_line_nr_ = loop_info.line_nr_;
        info.file_id_ = file_id;
        info.store_inst_ = llvm::dyn_cast<llvm::StoreInst>(it2->second);
        info.load_inst_ = llvm::dyn_cast<llvm::LoadInst>(it->second);

        candidates.push_back(info);
      }
    }
  }

  // now check if the variables are part of a reduction operation
  for (auto candidate : candidates) {
    int index = isa<StoreInst>(candidate.load_inst_) ? 1 : 0;
    string varNameLoad = "LOAD";
    string varTypeLoad = "SCALAR";
    llvm::DebugLoc loc = (candidate.load_inst_)->getDebugLoc();

    varNameLoad = dp_reduction_determineVariableName(candidate.load_inst_, trueVarNamesFromMetadataMap);
    varTypeLoad = dp_reduction_determineVariableType(candidate.load_inst_);
    if (llvm::isa<llvm::GetElementPtrInst>(candidate.load_inst_->getOperand(index))) {
      if (varTypeLoad.find("ARRAY,") == std::string::npos || varNameLoad.find(".addr") == std::string::npos ||
          varTypeLoad.find("**") != std::string::npos) {
        continue;
      } else if (varTypeLoad.find("ARRAY,") != std::string::npos || varNameLoad.find(".addr") != std::string::npos ||
                 varTypeLoad.find("STRUCT,") != std::string::npos || varTypeLoad.find("**") != std::string::npos) {
        llvm::Instruction *load_instr = nullptr;
        llvm::Instruction *instr = dp_reduction_get_reduction_instr(candidate.store_inst_, &load_instr);
        if (instr) {
          candidate.load_inst_ = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation_ = dp_reduction_get_char_for_opcode(instr);
        } else {
          continue;
        }
      }
    } else {
      if (varTypeLoad.find("ARRAY,") != std::string::npos || varNameLoad.find(".addr") != std::string::npos ||
          varTypeLoad.find("STRUCT,") != std::string::npos || varTypeLoad.find("**") != std::string::npos) {
        llvm::Instruction *load_instr = nullptr;
        llvm::Instruction *instr = dp_reduction_get_reduction_instr(candidate.store_inst_, &load_instr);
        if (instr) {
          candidate.load_inst_ = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation_ = dp_reduction_get_char_for_opcode(instr);
        } else {
          // We should ignore store instructions that are not associated with a
          // load e.g., pbvc[i] = c1s;
          continue;
        }
      } else {
        llvm::Instruction *load_instr = nullptr;
        llvm::Instruction *instr = dp_reduction_get_reduction_instr(candidate.store_inst_, &load_instr);
        if (instr) {
          candidate.load_inst_ = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation_ = dp_reduction_get_char_for_opcode(instr);
        } else {
          // We want to find max or min reduction operations
          // We want to find the basicblock that contains the load instruction
          // Then, we traverse the whole function to check if the reduction
          // operation is > or <
          BasicBlock *BB = (candidate.load_inst_)->getParent();
          string bbName = BB->getName().str();

          // Ignore loops. Only look for conditional blocks
          if (bbName.find("if") != std::string::npos || bbName.find("for") != std::string::npos) {
            // e.g. in lulesh.cc: "if (domain.vdov(indx) != Real_t(0.)) { if (
            // dtf < dtcourant_tmp ) { dtcourant_tmp = dtf ; courant_elem  =
            // indx ; }}"

            // check if loaded value is used in the store instruction to prevent
            // "false positives"
            if (check_value_usage(candidate.store_inst_->getValueOperand(), cast<Value>(candidate.load_inst_))) {
              candidate.operation_ = '>';
            } else {
              continue;
            }
          } else {
            continue;
          }
        }
      }
    }
    instructions_.push_back(candidate);
  }
}
