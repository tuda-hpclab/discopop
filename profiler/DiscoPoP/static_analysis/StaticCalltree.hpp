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
#include <stdint.h>

#include <algorithm>
#include <iostream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

class StaticCalltreeNode {
 private:
  uint32_t node_id_;
  bool type_;  // 0: Function; 1: Call instruction
  // TODO: other types for loop iterations might be a good idea!
  std::string function_name_;
  int32_t instruction_id_;
  std::string label_;  // precomputed once in the constructor; see get_label()

 public:
  std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>>
      successors;  // first element of the pairs is the trigger instructionID for the transition
  std::vector<StaticCalltreeNode*> predecessors;
  // function nodes of functions instrumented in this module: instruction id of the function's
  // __dp_func_entry call, which identifies the function at runtime (0 otherwise)
  int32_t function_entry_instruction_id = 0;
  // node of a loop iteration state "<function>_loopstate<digits>" of a function
  bool is_loopstate = false;
  // true if the node is the node of a function (not a loop iteration state) and no call
  // instruction of the module leads to it. Its loop iteration states lead back to it on loop
  // exits, so predecessors of other kinds do not count.
  bool IsUncalledFunction() {
    if (type_ || is_loopstate) {
      return false;
    }
    for (auto pred : predecessors) {
      if (pred->GetType()) {
        return false;
      }
    }
    return true;
  }
  StaticCalltreeNode(uint32_t node_id_arg, bool type_arg, std::string function_name_arg, int32_t instruction_id_arg)
      : node_id_(node_id_arg),
        type_(type_arg),
        function_name_(std::move(function_name_arg)),
        instruction_id_(instruction_id_arg) {
    // type 0: function -> functionName; type 1: call instruction -> "call_<instructionID>"
    label_ = type_ ? ("call_" + std::to_string(instruction_id_)) : function_name_;
  }
  void Print();
  const std::string& GetLabel();
  bool GetType() const;
  void RegisterSuccessor(StaticCalltreeNode* succ, int32_t trigger_instruction_id);
};

class StaticCalltree {
 private:
  uint32_t node_count_ = 0;

 public:
  std::unordered_map<std::string, StaticCalltreeNode*> function_map;
  std::unordered_map<int32_t, StaticCalltreeNode*> instruction_map;
  StaticCalltree();
  ~StaticCalltree();
  // owns its nodes: a copy would delete them twice, so it can only be moved (buildStaticCalltree
  // returns it by value)
  StaticCalltree(StaticCalltree&& other) noexcept
      : node_count_(other.node_count_),
        function_map(std::move(other.function_map)),
        instruction_map(std::move(other.instruction_map)) {
    other.function_map.clear();
    other.instruction_map.clear();
  }
  StaticCalltree(const StaticCalltree&) = delete;
  StaticCalltree& operator=(const StaticCalltree&) = delete;
  StaticCalltreeNode* GetOrInsertFunctionNode(const std::string& function_name);
  StaticCalltreeNode* GetOrInsertFunctionNode(std::string function_nam, const std::string& loop_iteration_instance);
  StaticCalltreeNode* GetOrInsertInstructionNode(int32_t instruction_id);
  void Print();
  std::string ToDotString();
  void AddEdge(StaticCalltreeNode* source, StaticCalltreeNode* target, int32_t trigger_instruction_id);
};
