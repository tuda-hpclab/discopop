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

#include "InstructionCFG.hpp"

#include <set>
#include <string>
#include <utility>

using llvm::AllocaInst;
using llvm::BasicBlock;
using llvm::DebugLoc;
using llvm::Function;
using llvm::Instruction;
using llvm::isa;
using llvm::LoadInst;
using llvm::ReturnInst;
using llvm::StoreInst;
using llvm::successors;

InstructionCFG::InstructionCFG(dputil::VariableNameFinder* vnf, Function& f) : vnf_(vnf) {
  entry_ = Graph::AddInstructionNode(reinterpret_cast<Instruction*>(kEntry));
  exit_ = Graph::AddInstructionNode(reinterpret_cast<Instruction*>(kExit));
  Instruction* previous_instruction;
  for (BasicBlock& bb : f) {
    // Add current block's store/load/call-instructions and declarations to
    // graph
    previous_instruction = nullptr;
    for (Instruction& i : bb) {
      if (isa<StoreInst>(i) || isa<LoadInst>(i) || isa<AllocaInst>(&i)) {
        if (previous_instruction != nullptr) {
          Graph::AddEdge(previous_instruction, &i);
        }
        previous_instruction = &i;
      }
    }
    // Add edges from last instruction in current block to first instruction all
    // the successor blocks
    if (previous_instruction != nullptr) {
      std::set<std::pair<BasicBlock*, Instruction*>> visited;
      FindAndAddFirstRelevantInstructionInSuccessorBlocks(&bb, previous_instruction, &visited);
    }
  }
  // Conect entry/exit nodes
  for (auto inst_node : Graph::GetInstructionNodes()) {
    if (inst_node != entry_ && inst_node != exit_) {
      if (Graph::GetInEdges(inst_node).empty()) {
        Graph::AddEdge(entry_, inst_node);
      } else if (Graph::GetOutEdges(inst_node).empty()) {
        Graph::AddEdge(inst_node, exit_);
      }
    }
  }
}

void InstructionCFG::FindAndAddFirstRelevantInstructionInSuccessorBlocks(
    BasicBlock* bb, Instruction* previous_instruction, std::set<std::pair<BasicBlock*, Instruction*>>* visited) {
  // Check for and break out of cycles
  const std::pair<BasicBlock*, Instruction*> tmp_pair = std::make_pair(bb, previous_instruction);
  const bool already_visited = visited->find(tmp_pair) != visited->end();
  if (already_visited) {
    return;
  }
  // register visited node
  visited->insert(tmp_pair);

  for (BasicBlock* s : successors(bb)) {
    for (Instruction& i : *s) {
      if (isa<StoreInst>(i) || isa<LoadInst>(i)) {
        Graph::AddEdge(previous_instruction, &i);
        goto next;
      } else if (isa<AllocaInst>(&i)) {
        Graph::AddEdge(previous_instruction, &i);
        goto next;
      } else if (isa<ReturnInst>(&i)) {
        Graph::AddEdge(Graph::GetInstructionNode(previous_instruction), exit_);
      }
    }
    if (s != bb) {
      FindAndAddFirstRelevantInstructionInSuccessorBlocks(s, previous_instruction, visited);
    }
  next: {}
  }
}

void InstructionCFG::HighlightInstructionNode(Instruction* instr) { highlighted_instruction_nodes_.insert(instr); }

void InstructionCFG::DumpToDot(const std::string& target_path) {
  // Write the graph to a DOT file
  std::ofstream dot_stream;
  dot_stream.open(target_path);
  dot_stream << "digraph{";
  // Create all nodes in DOT format
  for (auto inst_node : GetInstructionNodes()) {
    std::string label;
    DebugLoc dl;
    Instruction* instr;
    if (inst_node == entry_) {
      label = "label=ENTRY";
      goto printInstructionNode;
    }
    if (inst_node == exit_) {
      label = "label=EXIT";
      goto printInstructionNode;
    }
    label = "label=\"" + std::to_string(Graph::GetInstructionNodeIndex(inst_node)) + "\\n";
    instr = inst_node->GetItem();
    dl = instr->getDebugLoc();
    if (isa<StoreInst>(instr) || isa<LoadInst>(instr)) {
      if (isa<StoreInst>(instr)) {
        if (DebugLoc dl = instr->getDebugLoc()) {
          label += "write(";
        } else {
          label += "init(";
        }
      } else {
        label += "read(";
      }
      label += vnf_->GetVarName(instr);
      label += ") ";

      if (dl) {
        label += std::to_string(dl.getLine());
        label += ", ";
        label += std::to_string(dl.getCol());
      } else {
        label += std::to_string(instr->getFunction()->getSubprogram()->getLine());
      }
      label += "\"";
      if (highlighted_instruction_nodes_.find(instr) != highlighted_instruction_nodes_.end()) {
        label += "\",fillcolor=cyan,style=filled";
      }
    } else if (isa<AllocaInst>(instr)) {
      label += "alloca(" + vnf_->GetVarName(instr) + ")";
      label += "\",shape=rectangle,fillcolor=wheat,style=filled";
    } else {
      label += "?\"";
    }

  printInstructionNode:
    dot_stream << "\t\"" << GetInstructionNodeIndex(inst_node) << "\" [" << label << "];\n";
  }
  dot_stream << "\n\n";

  // Now print all outgoing edges and their labels
  for (auto e : GetEdges()) {
    dot_stream << "\t\"" << GetInstructionNodeIndex(e->GetSrc()) << "\" -> \"" << GetInstructionNodeIndex(e->GetDst())
               << "\";\n";
  }
  dot_stream << "}";
  dot_stream.close();
}
