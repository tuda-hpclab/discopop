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
#include <utility>
#include <vector>

#include "dp_reduction/ReductionInstrumenter.hpp"
#include "dp_reduction/dp_reduction.hpp"

using llvm::BasicBlock;
using llvm::cast;
using llvm::errs;
using llvm::Function;
using llvm::isa;
using llvm::LoopInfo;
using llvm::StoreInst;
using llvm::Value;

// Goes through all instructions in a loop and determines if they might be
// suitable for reduction.
// An entry is added to the 'loops_' vector and for each suitable instruction,
// an entry is added to the 'instructions_' vector.
void dp_reduction::ReductionInstrumenter::InstrumentLoop(Function& f, int file_id, llvm::Loop* loop, LoopInfo& li) {
  // Whatever becomes of this loop, its subloops are loops of their own. Both early returns
  // below used to take them with it, so a loop that could not be described made every loop
  // inside it disappear as well. Called where the recursion used to sit on the path that
  // keeps the loop, so the order in which loop ids are handed out does not change.
  const auto instrument_subloops = [&]() {
    for (llvm::Loop* sub_loop : loop->getSubLoops()) {
      InstrumentLoop(f, file_id, sub_loop, li);
    }
  };

  auto loc = loop->getStartLoc();
  if (!dp_reduction::LocExists(loc)) {
    // Nothing can be said about a loop that has no location: it is left out of
    // loop_meta.txt and gets no __dp_loop_incr, so its iterations are never counted.
    // Worth a word, because the location comes off the terminator of the loop's
    // preheader -- a branch inserted in front of it without a debug location silently
    // empties the file for a whole module, and that looks like nothing at all.
    errs() << "WARNING: DiscoPoP: loop without a source location, not instrumented."
           << " File: " << file_id << " Function: " << f.getName() << "\n";
    instrument_subloops();
    return;
  }

  auto basic_blocks = loop->getBlocks();
  // basic_blocks[1] is the only one addressed by index, so two blocks are enough. Asking
  // for three dropped every while and do-while loop whose body is a single block -- no
  // entry in loop_meta.txt, no __dp_loop_incr, no iteration count -- while the same loop
  // with an if in its body was profiled.
  if (basic_blocks.size() < 2) {
    instrument_subloops();
    return;
  }
  // add an entry to the 'loops_' vector
  LoopInfoT loop_info;
  loop_info.line_nr = loc.getLine();
  loop_info.file_id = file_id;
  loop_info.first_body_instr = &(*basic_blocks[1]->begin());

  const std::string loop_end_line = dp_reduction::CFA(f, loop, file_id);
  loop_info.end_line = loop_end_line;
  loop_info.function_name = std::string((basic_blocks[1]->getParent()->getName()));
  loop_info.loop_id = services_.get_loop_id(loop);

  loops_.push_back(loop_info);

  instrument_subloops();
  // The key corresponds to the variable that is loaded / stored.
  // The value points to the actual load / store instruction.
  std::map<llvm::Value*, llvm::Instruction*> load_instructions;
  std::map<llvm::Value*, llvm::Instruction*> store_instructions;

  // Scan all instructions in the loop's basic blocks to find the load and
  // store instructions.
  for (std::size_t i = 0; i < basic_blocks.size(); ++i) {
    llvm::BasicBlock* const bb = basic_blocks[i];

    // Skip the loop's own control blocks and look at its body only. These used to be
    // recognised by the names clang gives them in a for loop, for.cond and for.inc, which
    // ties the analysis to one source construct and to names that nothing guarantees --
    // half of a block that something has split answers to neither of them.
    if (bb == loop->getHeader() || loop->isLoopLatch(bb)) {
      continue;
    }

    for (auto instr_it = bb->begin(); instr_it != bb->end(); ++instr_it) {
      llvm::Instruction* instr = &(*instr_it);

      auto opcode = instr->getOpcode();
      if (opcode != llvm::Instruction::Store && opcode != llvm::Instruction::Load) {
        continue;
      }

      // Add an entry to the corresponding map or invalidate an already
      // existing entry, if the same instruction is executed on multiple
      // lines.
      llvm::Value* operand = dp_reduction::GetVar(instr);
      if (operand) {
        std::map<llvm::Value*, llvm::Instruction*>* map_ptr =
            (opcode == llvm::Instruction::Store) ? &store_instructions : &load_instructions;
        if (!map_ptr->insert(std::make_pair(operand, instr)).second) {
          if ((*map_ptr)[operand]) {
            const llvm::DebugLoc new_loc = instr->getDebugLoc();
            const llvm::DebugLoc old_loc = (*map_ptr)[operand]->getDebugLoc();

            if (!dp_reduction::LocExists(new_loc) || !dp_reduction::LocExists(old_loc)) {
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
  std::vector<InstrInfoT> candidates;
  for (auto it = load_instructions.begin(); it != load_instructions.end(); ++it) {
    if (!it->second) {
      continue;
    }

    auto it2 = store_instructions.find(it->first);
    if (it2 != store_instructions.end() && it2->second) {
      const llvm::DebugLoc load_loc = it->second->getDebugLoc();
      const llvm::DebugLoc store_loc = it2->second->getDebugLoc();
      if (!dp_reduction::LocExists(load_loc) || !dp_reduction::LocExists(store_loc)) {
        continue;
      }
      if (load_loc.getLine() > store_loc.getLine()) {
        continue;
      }
      if (load_loc.getLine() == loop_info.line_nr || store_loc.getLine() == loop_info.line_nr) {
        continue;
      }

      if (loop_info.end_line == "LOOPENDNOTFOUND") {
        errs() << "WARNING: Loop end not found! File: " << file_id << " Function: " << f.getName()
               << " Start line: " << loop_info.start_line << "\n";
        continue;
      }
      if (loop_info.line_nr > std::stoul(loop_info.end_line)) {
        continue;
      }

      // Check if both load and store insts belong to the loop
      if (load_loc.getLine() < loop_info.line_nr || load_loc.getLine() > std::stoul(loop_info.end_line)) {
        continue;
      }
      if (store_loc.getLine() < loop_info.line_nr || store_loc.getLine() > std::stoul(loop_info.end_line)) {
        continue;
      }

      if (it->first->hasName()) {
        InstrInfoT info;
        info.var_name = services_.get_variable_name(it->second);
        info.loop_line_nr = loop_info.line_nr;
        info.file_id = file_id;
        info.store_inst = llvm::dyn_cast<llvm::StoreInst>(it2->second);
        info.load_inst = llvm::dyn_cast<llvm::LoadInst>(it->second);

        candidates.push_back(info);
      }
    }
  }

  // now check if the variables are part of a reduction operation
  for (auto candidate : candidates) {
    const int index = isa<StoreInst>(candidate.load_inst) ? 1 : 0;
    std::string var_name_load = "LOAD";
    std::string var_type_load = "SCALAR";
    const llvm::DebugLoc loc = (candidate.load_inst)->getDebugLoc();

    var_name_load = services_.get_variable_name(candidate.load_inst);
    var_type_load = dp_reduction::DetermineVariableType(candidate.load_inst);
    if (llvm::isa<llvm::GetElementPtrInst>(candidate.load_inst->getOperand(index))) {
      if (var_type_load.find("ARRAY,") == std::string::npos || var_name_load.find(".addr") == std::string::npos ||
          var_type_load.find("**") != std::string::npos) {
        continue;
      }
      if (var_type_load.find("ARRAY,") != std::string::npos || var_name_load.find(".addr") != std::string::npos ||
          var_type_load.find("STRUCT,") != std::string::npos || var_type_load.find("**") != std::string::npos) {
        llvm::Instruction* load_instr = nullptr;
        llvm::Instruction* instr = dp_reduction::GetReductionInstr(candidate.store_inst, &load_instr);
        if (instr) {
          candidate.load_inst = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation = dp_reduction::GetCharForOpcode(instr);
        } else {
          continue;
        }
      }
    } else {
      if (var_type_load.find("ARRAY,") != std::string::npos || var_name_load.find(".addr") != std::string::npos ||
          var_type_load.find("STRUCT,") != std::string::npos || var_type_load.find("**") != std::string::npos) {
        llvm::Instruction* load_instr = nullptr;
        llvm::Instruction* instr = dp_reduction::GetReductionInstr(candidate.store_inst, &load_instr);
        if (instr) {
          candidate.load_inst = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation = dp_reduction::GetCharForOpcode(instr);
        } else {
          // We should ignore store instructions that are not associated with a
          // load e.g., pbvc[i] = c1s;
          continue;
        }
      } else {
        llvm::Instruction* load_instr = nullptr;
        llvm::Instruction* instr = dp_reduction::GetReductionInstr(candidate.store_inst, &load_instr);
        if (instr) {
          candidate.load_inst = llvm::cast<llvm::LoadInst>(load_instr);
          candidate.operation = dp_reduction::GetCharForOpcode(instr);
        } else {
          // We want to find max or min reduction operations
          // We want to find the basicblock that contains the load instruction
          // Then, we traverse the whole function to check if the reduction
          // operation is > or <
          BasicBlock* bb = (candidate.load_inst)->getParent();
          const std::string bb_name = bb->getName().str();

          // Ignore loops. Only look for conditional blocks
          if (bb_name.find("if") != std::string::npos || bb_name.find("for") != std::string::npos) {
            // e.g. in lulesh.cc: "if (domain.vdov(indx) != Real_t(0.)) { if (
            // dtf < dtcourant_tmp ) { dtcourant_tmp = dtf ; courant_elem  =
            // indx ; }}"

            // check if loaded value is used in the store instruction to prevent
            // "false positives"
            if (dp_reduction::CheckValueUsage(candidate.store_inst->getValueOperand(),
                                              cast<Value>(candidate.load_inst))) {
              candidate.operation = '>';
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
