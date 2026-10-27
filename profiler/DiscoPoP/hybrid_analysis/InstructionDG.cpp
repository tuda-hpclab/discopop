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

#include "InstructionDG.hpp"

#include <set>
#include <string>
#include <unordered_map>
#include <utility>

#include "DPUtils.hpp"

using llvm::AllocaInst;
using llvm::cast;
using llvm::DebugLoc;
using llvm::dyn_cast;
using llvm::Instruction;
using llvm::isa;
using llvm::LoadInst;
using llvm::MDNode;
using llvm::MDString;
using llvm::StoreInst;
using llvm::Value;

InstructionDG::InstructionDG(dputil::VariableNameFinder* vnf, InstructionCFG* cfg, std::int32_t fid)
    : vnf_(vnf), cfg_(cfg), fid_(fid) {
  for (auto edge : cfg_->GetInEdges(cfg_->GetExit())) {
    // check for nullptr
    if (edge->GetSrc()) {
      RecursiveDepFinder(new std::set<Instruction*>(), edge->GetSrc()->GetItem());
    }
  }
}

void InstructionDG::RecursiveDepChecker(std::set<Instruction*>* checked_instructions, Instruction* i, Instruction* c) {
  if (cfg_->IsEntryOrExit(c)) {
    return;
  }
  checked_instructions->insert(c);
  Value *v, *w;
  if (isa<AllocaInst>(i)) {
    v = dyn_cast<Value>(i);
  } else {
    v = i->getOperand(isa<StoreInst>(i) ? 1 : 0);
  }

  if (isa<AllocaInst>(c)) {
    w = dyn_cast<Value>(c);
  } else {
    w = c->getOperand(isa<StoreInst>(c) ? 1 : 0);
  }

  if (v == w && (isa<StoreInst>(i) || isa<StoreInst>(c))) {
    Graph::AddEdge(i, c);
    return;
  }
  for (auto edge : cfg_->GetInEdges(c)) {
    if (checked_instructions->find(edge->GetSrc()->GetItem()) == checked_instructions->end()) {
      RecursiveDepChecker(checked_instructions, i, edge->GetSrc()->GetItem());
    }
  }
}

void InstructionDG::RecursiveDepFinder(std::set<Instruction*>* checked_instructions, Instruction* i) {
  if (cfg_->IsEntryOrExit(i) || checked_instructions->find(i) != checked_instructions->end()) {
    return;
  }
  checked_instructions->insert(i);
  if (isa<StoreInst>(i) || isa<LoadInst>(i)) {
    Graph::AddInstructionNode(i);
  }
  for (auto edge : cfg_->GetInEdges(i)) {
    if (isa<StoreInst>(i) || isa<LoadInst>(i)) {
      RecursiveDepChecker(new std::set<Instruction*>(), i, edge->GetSrc()->GetItem());
    }
    RecursiveDepFinder(checked_instructions, edge->GetSrc()->GetItem());
  }
}

void InstructionDG::HighlightInstructionNode(Instruction* instr) { highlighted_instruction_nodes_.insert(instr); }

std::string InstructionDG::GetInstructionLine(Instruction* i) const {
  if (DebugLoc dl = i->getDebugLoc()) {
    return std::to_string(dl->getLine());
  }
  return std::to_string(i->getFunction()->getSubprogram()->getLine());
}

bool InstructionDG::EdgeIsInit(Edge<Instruction*>* e) {
  Instruction* j = e->GetDst()->GetItem();

  if (isa<AllocaInst>(j)) {
    return true;
  }
  return false;
}

std::string InstructionDG::GetInitEdgeInstructionLine(Edge<Instruction*>* e) const {
  return GetInstructionLine(e->GetSrc()->GetItem());
}

std::string InstructionDG::GetValueNameAndMemRegIdFromEdge(
    Edge<Instruction*>* e,
    std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map) {
  Instruction* i = e->GetSrc()->GetItem();
  return static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].first + "(" +
         static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
}

std::string InstructionDG::EdgeToDpDep(
    Edge<Instruction*>* e,
    std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map) {
  // staticValueNameToMemRegIDMap maps: <SSA variable name> TO (original
  // variable name, statically assigned MemReg ID)
  Instruction* i = e->GetSrc()->GetItem();
  Instruction* j = e->GetDst()->GetItem();

  std::string dep_type;
  if (isa<AllocaInst>(j)) {
    dep_type = "INIT";
    return std::to_string(fid_) + ":" + GetInstructionLine(i) + " " + "NOM" + " " + dep_type + " *|" +
           static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
               .first  // use original variable name instead of LLVM IR SSA name
           + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
  }
  if (DebugLoc dl = j->getDebugLoc()) {
    dep_type = (isa<LoadInst>(i) ? std::string("R") : std::string("W")) + "A" +
               (isa<LoadInst>(j) ? std::string("R") : std::string("W"));
    return std::to_string(fid_) + ":" + GetInstructionLine(i) + " " + "NOM" + " " + dep_type + " " +
           std::to_string(fid_) + ":" + GetInstructionLine(j) + "|" +
           static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
               .first  // use original variable name instead of LLVM IR SSA name
           + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
  }
  dep_type = (isa<LoadInst>(i) ? std::string("R") : std::string("W")) + "A" +
             (isa<LoadInst>(j) ? std::string("R") : std::string("W"));
  return std::to_string(fid_) + ":" + GetInstructionLine(i) + " " + "NOM" + " " + dep_type + " " +
         std::to_string(fid_) + ":" + GetInstructionLine(j) + "|" +
         static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
             .first  // use original variable name instead of LLVM IR SSA name
         + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
}

std::string InstructionDG::EdgeToInstructionBasedDpDep(
    Edge<Instruction*>* e,
    std::unordered_map<std::string, std::pair<std::string, std::string>>& static_value_name_to_mem_reg_id_map) {
  // staticValueNameToMemRegIDMap maps: <SSA variable name> TO (original
  // variable name, statically assigned MemReg ID)
  Instruction* i = e->GetSrc()->GetItem();
  Instruction* j = e->GetDst()->GetItem();

  // get unique instruction ids from metadata
  MDNode* n_i = i->getMetadata("dp.md.instr.id");
  std::string unique_instruction_id_i = cast<MDString>(n_i->getOperand(0))->getString().str();
  // cleanup metadata string to get the pure id
  unique_instruction_id_i.replace(0, 15, "");  // replaces "dp.md.instr.id:" with ""

  MDNode* n_j = j->getMetadata("dp.md.instr.id");
  std::string unique_instruction_id_j = cast<MDString>(n_j->getOperand(0))->getString().str();
  // cleanup metadata string to get the pure id
  unique_instruction_id_j.replace(0, 15, "");  // replaces "dp.md.instr.id:" with ""

  std::string dep_type;
  if (isa<AllocaInst>(j)) {
    dep_type = "INIT";
    return unique_instruction_id_i + " " + "NOM" + " " + dep_type + " *|" +
           static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
               .first  // use original variable name instead of LLVM IR SSA name
           + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
  }
  if (DebugLoc dl = j->getDebugLoc()) {
    dep_type = (isa<LoadInst>(i) ? std::string("R") : std::string("W")) + "A" +
               (isa<LoadInst>(j) ? std::string("R") : std::string("W"));
    return unique_instruction_id_i + " " + "NOM" + " " + dep_type + " " + unique_instruction_id_j + "|" +
           static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
               .first  // use original variable name instead of LLVM IR SSA name
           + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
  }
  dep_type = (isa<LoadInst>(i) ? std::string("R") : std::string("W")) + "A" +
             (isa<LoadInst>(j) ? std::string("R") : std::string("W"));
  return unique_instruction_id_i + " " + "NOM" + " " + dep_type + " " + unique_instruction_id_j + "|" +
         static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)]
             .first  // use original variable name instead of LLVM IR SSA name
         + "(" + static_value_name_to_mem_reg_id_map[vnf_->GetVarName(i)].second + ")";
}

void InstructionDG::DumpToDot(const std::string& target_path) {
  // Write the graph to a DOT file
  std::ofstream dot_stream;
  dot_stream.open(target_path);

  dot_stream << "digraph g {\n";
  // Create all nodes in DOT format
  for (auto inst_node : GetInstructionNodes()) {
    std::string label = "label=\"" + std::to_string(Graph::GetInstructionNodeIndex(inst_node)) + "\\n";
    Instruction* instr = inst_node->GetItem();
    if (isa<StoreInst>(instr)) {
      if (DebugLoc dl = instr->getDebugLoc()) {
        label += "write(";
      } else {
        label += "init(";
      }
    } else if (isa<LoadInst>(instr)) {
      label += "read(";
    } else {
      label += "alloca(";
    }
    label += vnf_->GetVarName(instr);
    label += ") ";

    if (DebugLoc dl = instr->getDebugLoc()) {
      label += std::to_string(dl.getLine());
      label += ", ";
      label += std::to_string(dl.getCol());
    } else if (isa<StoreInst>(instr)) {
      label += std::to_string(instr->getFunction()->getSubprogram()->getLine()) + "\n";
    }
    label += "\"";
    if (highlighted_instruction_nodes_.find(instr) != highlighted_instruction_nodes_.end()) {
      label += ",fillcolor=cyan,style=filled";
    }

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
