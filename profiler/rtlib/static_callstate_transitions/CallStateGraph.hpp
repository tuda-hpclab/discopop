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
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "CallState.hpp"

class CallStateGraph {
 private:
  std::unordered_map<std::int32_t, CallState*> node_map_;
  // function entry instruction id -> state of the function's own root call path (the function
  // without callers in its translation unit), used when a function is entered without a
  // matching call transition (call from another translation unit, indirect call, callback)
  // indexed by the function entry id (instruction ids are counted densely over the program), nullptr if none
  std::vector<CallState*> function_entry_states_;
  void ReadFunctionEntries(const std::string& path);

 public:
  CallStateGraph();
  ~CallStateGraph();
  CallState* GetOrRegisterNode(std::int32_t call_state_id);
  void RegisterTransition(std::int32_t source_call_state_id, std::int32_t trigger_instruction,
                          std::int32_t target_call_state_id);
  void RegisterImplicitReturnTransition(std::int32_t source_call_state_id, std::int32_t target_call_state_id);
  // marks the state as the entry state of an instance of the function with the given entry id
  void RegisterStateFunction(std::int32_t call_state_id, std::int32_t function_entry_id);
  // registers the root entry state of the function with the given entry id
  void RegisterFunctionEntryState(std::int32_t function_entry_id, std::int32_t call_state_id);
  // the root entry state of the function, or nullptr if it has none
  CallState* GetFunctionEntryState(std::int32_t function_entry_id);
};
