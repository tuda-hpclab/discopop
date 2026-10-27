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

#pragma once

#include <set>
#include <string>
#include <utility>

#include "DPUtils.hpp"
#include "InstructionCFG.hpp"
#include "unordered_map"

class InstructionDG : public Graph<llvm::Instruction*> {
 private:
  dputil::VariableNameFinder* vnf_;
  InstructionCFG* cfg_;
  std::set<llvm::Instruction*> highlighted_instruction_nodes_;
  int32_t fid_;

  void RecursiveDepChecker(std::set<llvm::Instruction*>* checked_instructions, llvm::Instruction* i,
                           llvm::Instruction* c);

  void RecursiveDepFinder(std::set<llvm::Instruction*>* checked_instructions, llvm::Instruction* i);

 public:
  InstructionDG(dputil::VariableNameFinder* vnf, InstructionCFG* cfg, int32_t fid);

  bool EdgeIsInit(Edge<llvm::Instruction*>* e);

  std::string EdgeToDpDep(
      Edge<llvm::Instruction*>* e,
      std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map);
  std::string EdgeToInstructionBasedDpDep(
      Edge<llvm::Instruction*>* e,
      std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map);

  void HighlightInstructionNode(llvm::Instruction* instr);

  void DumpToDot(const std::string& target_path);

  std::string GetInstructionLine(llvm::Instruction* i) const;

  std::string GetInitEdgeInstructionLine(Edge<llvm::Instruction*>* e) const;

  std::string GetValueNameAndMemRegIdFromEdge(
      Edge<llvm::Instruction*>* e,
      std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map);
};
