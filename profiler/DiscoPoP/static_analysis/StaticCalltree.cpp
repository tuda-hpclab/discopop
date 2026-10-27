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

#include "StaticCalltree.hpp"

#include <algorithm>
#include <iostream>
#include <string>
#include <vector>

void StaticCalltreeNode::Print() {
  std::cout << "Node: ID: " << node_id_ << " Type: " << type_ << " Name: " << function_name_
            << " instructionID: " << instruction_id_ << "\n";
}

const std::string& StaticCalltreeNode::GetLabel() { return label_; }

bool StaticCalltreeNode::GetType() const { return type_; }

void StaticCalltreeNode::RegisterSuccessor(StaticCalltreeNode* succ, int32_t trigger_instruction_id) {
  // check if trigger is already registered
  if (successors.find(trigger_instruction_id) != successors.end()) {
    // already registered
  } else {
    // register trigger
    const std::vector<StaticCalltreeNode*> tmp;
    successors[trigger_instruction_id] = tmp;
  }

  // check if succ is already registered
  if (std::find(successors[trigger_instruction_id].begin(), successors[trigger_instruction_id].end(), succ) !=
      successors[trigger_instruction_id].end()) {
    // already registered
    return;
  }
  // register successor
  successors[trigger_instruction_id].push_back(succ);
  succ->predecessors.push_back(this);
}

StaticCalltree::StaticCalltree() { std::cout << "constructing StaticCalltree.\n"; }

StaticCalltree::~StaticCalltree() {
  // delete CalltreeNodes
  for (const auto& pair : function_map) {
    delete pair.second;
  }
  for (auto pair : instruction_map) {
    delete pair.second;
  }
}

StaticCalltreeNode* StaticCalltree::GetOrInsertFunctionNode(const std::string& function_name) {
  if (function_map.count(function_name) == 0) {
    //        std::cout << "first encountered function name: " << function_name << "\n";
    StaticCalltreeNode* node_ptr = new StaticCalltreeNode(node_count_++, 0, function_name, 0);
    function_map[function_name] = node_ptr;
    return node_ptr;
  }
  //        std::cout << "Retrieve function name: " << function_name << "\n";
  return function_map[function_name];
}

StaticCalltreeNode* StaticCalltree::GetOrInsertFunctionNode(std::string function_name,
                                                            const std::string& loop_iteration_instance) {
  function_name = function_name + "_loopstate" + loop_iteration_instance;

  if (function_map.count(function_name) == 0) {
    //        std::cout << "first encountered function name: " << function_name << "\n";
    StaticCalltreeNode* node_ptr = new StaticCalltreeNode(node_count_++, 0, function_name, 0);
    node_ptr->is_loopstate = true;
    function_map[function_name] = node_ptr;
    return node_ptr;
  }
  //        std::cout << "Retrieve function name: " << function_name << "\n";
  return function_map[function_name];
}

StaticCalltreeNode* StaticCalltree::GetOrInsertInstructionNode(int32_t instruction_id) {
  if (instruction_map.count(instruction_id) == 0) {
    //        std::cout << "first encountered instruction id: " << instructionID << "\n";
    StaticCalltreeNode* node_ptr = new StaticCalltreeNode(node_count_++, 1, "", instruction_id);
    instruction_map[instruction_id] = node_ptr;
    return node_ptr;
  }
  //        std::cout << "Retrieve instruction id: " << instructionID << "\n";
  return instruction_map[instruction_id];
}

// trigger_instructionID = 0 -> no trigger required
void StaticCalltree::AddEdge(StaticCalltreeNode* source, StaticCalltreeNode* target, int32_t trigger_instruction_id) {
  source->RegisterSuccessor(target, trigger_instruction_id);
}

void StaticCalltree::Print() {
  std::cout << "Calltree: \n";

  std::cout << "Calltree end.\n";
}

std::string StaticCalltree::ToDotString() {
  std::string result = "";
  result += "diGraph G {\n";
  // add function nodes and successors
  for (const auto& pair : function_map) {
    auto node_ptr = pair.second;
    for (const auto& succ_pair : node_ptr->successors) {
      const int32_t trigger_instruction_id = succ_pair.first;
      auto node_label = node_ptr->GetLabel();
      // remove . from label for .dot compatibility
      std::replace(node_label.begin(), node_label.end(), '.', '_');

      for (auto succ : succ_pair.second) {
        auto succ_label = succ->GetLabel();
        std::replace(succ_label.begin(), succ_label.end(), '.', '_');
        result += "  " + node_label + " -> " + succ_label;
        if (trigger_instruction_id != 0) {
          result += " [label = " + std::to_string(trigger_instruction_id) + "]";
        }
        result += ";\n";
      }
    }
  }
  // add call instruction nodes and successors
  for (auto pair : instruction_map) {
    auto node_ptr = pair.second;
    for (const auto& succ_pair : node_ptr->successors) {
      const int32_t trigger_instruction_id = succ_pair.first;
      auto node_label = node_ptr->GetLabel();

      // remove . from label for .dot compatibility
      std::replace(node_label.begin(), node_label.end(), '.', '_');

      for (auto succ : succ_pair.second) {
        auto succ_label = succ->GetLabel();
        std::replace(succ_label.begin(), succ_label.end(), '.', '_');
        result += "  " + node_label + " -> " + succ_label;
        if (trigger_instruction_id != 0) {
          result += " [label = " + std::to_string(trigger_instruction_id) + "]";
        }
        result += ";\n";
      }
    }
  }
  result += "}\n";
  return result;
}
