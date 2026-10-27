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

#include <llvm/Support/raw_ostream.h>

#include <cstdint>
#include <set>
#include <string>

#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/DebugLoc.h"
#include "llvm/IR/Instructions.h"
#include "llvm/Support/Debug.h"

#include "DPUtils.hpp"
#include "Graph.hpp"

class InstructionCFG : public Graph<llvm::Instruction*> {
 private:
  // the artificial instructions the CFG starts and ends with: ids, not addresses of instructions
  static constexpr std::uintptr_t kEntry = 1000000;
  static constexpr std::uintptr_t kExit = 2000000;

  InstructionNode<llvm::Instruction*>* entry_;
  InstructionNode<llvm::Instruction*>* exit_;
  dputil::VariableNameFinder* vnf_;
  std::set<llvm::Instruction*> highlighted_instruction_nodes_;

  void FindAndAddFirstRelevantInstructionInSuccessorBlocks(
      llvm::BasicBlock* bb, llvm::Instruction* previous_instruction,
      std::set<std::pair<llvm::BasicBlock*, llvm::Instruction*>>* visited);

 public:
  InstructionCFG(dputil::VariableNameFinder* vnf, llvm::Function& f);

  InstructionNode<llvm::Instruction*>* GetEntry() const { return entry_; }

  InstructionNode<llvm::Instruction*>* GetExit() { return exit_; }

  bool IsEntryOrExit(llvm::Instruction* i) {
    return Graph::GetInstructionNode(i) == entry_ || Graph::GetInstructionNode(i) == exit_;
  }

  void HighlightInstructionNode(llvm::Instruction* instr);

  void DumpToDot(const std::string& target_path);
};
