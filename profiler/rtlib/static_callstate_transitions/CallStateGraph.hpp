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
#include "CallState.hpp"
#include <cstdint>
#include <iostream>
#include <string>
#include <unordered_map>

class CallStateGraph {
private:
  std::unordered_map<std::int32_t, CallState *> node_map;
  // function entry instruction id -> state of the function's own root call path (the function
  // without callers in its translation unit), used when a function is entered without a
  // matching call transition (call from another translation unit, indirect call, callback)
  std::unordered_map<std::int32_t, CallState *> function_entry_states;
  void read_function_entries(const std::string &path);

public:
  CallStateGraph();
  ~CallStateGraph();
  CallState *get_or_register_node(std::int32_t call_state_id);
  void register_transition(std::int32_t source_call_state_id, std::int32_t trigger_instruction,
                           std::int32_t target_call_state_id);
  void register_implicit_return_transition(std::int32_t source_call_state_id, std::int32_t target_call_state_id);
  // marks the state as the entry state of an instance of the function with the given entry id
  void register_state_function(std::int32_t call_state_id, std::int32_t function_entry_id);
  // registers the root entry state of the function with the given entry id
  void register_function_entry_state(std::int32_t function_entry_id, std::int32_t call_state_id);
  // the root entry state of the function, or nullptr if it has none
  CallState *get_function_entry_state(std::int32_t function_entry_id);
};
