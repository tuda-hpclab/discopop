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

#include "CallStateGraph.hpp"

#include <chrono>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "output_paths.hpp"

namespace {

// The parser drops whatever it cannot make sense of -- a line short of a field is skipped below. A
// field that is not a number is the same kind of damage, and both input files are written with
// ios_base::app, so a truncated or left over line is exactly what it looks like. It must not throw:
// this constructor runs from __dp_init, where an escaping exception takes the instrumented program
// down before it has started.
bool ParseId(const std::string& text, std::int32_t& result) {
  try {
    std::size_t consumed = 0;
    result = std::stoi(text, &consumed);
    return consumed > 0;
  } catch (const std::logic_error&) {
    return false;
  }
}

}  // namespace

CallStateGraph::CallStateGraph() {
#ifdef DP_RTLIB_VERBOSE
  const auto start_time = std::chrono::high_resolution_clock::now();
#endif
  // open input file
  const std::string tmp_2 = dp::ProfilerOutputPath("callpath_state_transitions.txt");
  // create graph by parsing the file line by line
  std::ifstream file(tmp_2);
  if (!file) {
    std::cerr << "DiscoPoP: could not open " << tmp_2 << ". Reported call states will be incorrect!\n";
  }
  std::string line;
  while (std::getline(file, line)) {
    // process line
    if (line.empty() || line[0] == '#') {
      // ignore empty and comment lines
      continue;
    }
    // get source id
    std::size_t pos = line.find(' ');
    if (pos == std::string::npos) {
      continue;
    }
    const std::string source_callstate_id_str = line.substr(0, pos);
    line = line.substr(pos + 1);
    // get trigger instruction
    pos = line.find(' ');
    if (pos == std::string::npos) {
      continue;
    }
    const std::string trigger_instruction_id_str = line.substr(0, pos);
    line = line.substr(pos + 1);
    // get target id
    const std::string target_callstate_id_str = line;
    // register transition in CallStateGraph
    std::int32_t source_callstate_id = 0;
    std::int32_t trigger_instruction_id = 0;
    std::int32_t target_callstate_id = 0;
    if (!ParseId(source_callstate_id_str, source_callstate_id) ||
        !ParseId(trigger_instruction_id_str, trigger_instruction_id) ||
        !ParseId(target_callstate_id_str, target_callstate_id)) {
      continue;
    }
    RegisterTransition(source_callstate_id, trigger_instruction_id, target_callstate_id);
  }
  // Transitions triggered by the dummy "return" instruction id are stored separately and without
  // that id (see static_callpaths::save_path_state_transitions). Without them no function return updates
  // the call state, so a missing file must not pass silently.
  const std::string tmp_3 = dp::ProfilerOutputPath("callpath_state_return_targets.txt");
  std::ifstream return_targets_file(tmp_3);
  if (!return_targets_file) {
    std::cerr << "DiscoPoP: could not open " << tmp_3 << ". Reported call states will be incorrect!\n";
  }
  while (std::getline(return_targets_file, line)) {
    if (line.empty() || line[0] == '#') {
      continue;
    }
    const std::size_t pos = line.find(' ');
    if (pos == std::string::npos) {
      continue;
    }
    const std::string source_callstate_id_str = line.substr(0, pos);
    const std::string target_callstate_id_str = line.substr(pos + 1);
    std::int32_t source_callstate_id = 0;
    std::int32_t target_callstate_id = 0;
    if (!ParseId(source_callstate_id_str, source_callstate_id) ||
        !ParseId(target_callstate_id_str, target_callstate_id)) {
      continue;
    }
    RegisterImplicitReturnTransition(source_callstate_id, target_callstate_id);
  }
  ReadFunctionEntries(dp::ProfilerOutputPath("callpath_function_entries.txt"));
#ifdef DP_RTLIB_VERBOSE
  // The instrumented program writes its own output to this stream, so a measurement of the runtime's
  // own startup does not belong there unconditionally. It stays behind the switch the rest of the
  // runtime keeps its diagnostics behind.
  const auto end_time = std::chrono::high_resolution_clock::now();
  const auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time);
  std::cout << "[CallStateGraph()]: " << (static_cast<double>(duration.count()) / 1000.0) << "s" << std::endl;
#endif
}

// Reads callpath_function_entries.txt (see static_callpaths::save_function_entries), lines:
//   S <state_id> <function_entry_instruction_id>   the state is the entry state of a function instance
//   E <function_entry_instruction_id> <state_id>   the root entry state of the function
// Without it, functions are entered only through call transitions of their own translation unit.
void CallStateGraph::ReadFunctionEntries(const std::string& path) {
  std::ifstream file(path);
  if (!file) {
    std::cerr << "DiscoPoP: could not open " << path << ". Reported call states will be incorrect!\n";
    return;
  }
  std::string kind;
  std::int32_t first;
  std::int32_t second;
  std::string line;
  while (std::getline(file, line)) {
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::istringstream fields(line);
    if (!(fields >> kind >> first >> second)) {
      continue;
    }
    if (kind == "S") {
      RegisterStateFunction(first, second);
    } else if (kind == "E") {
      RegisterFunctionEntryState(first, second);
    }
  }
}

void CallStateGraph::RegisterStateFunction(std::int32_t call_state_id, std::int32_t function_entry_id) {
  GetOrRegisterNode(call_state_id)->SetFunctionEntryId(function_entry_id);
}

void CallStateGraph::RegisterFunctionEntryState(std::int32_t function_entry_id, std::int32_t call_state_id) {
  CallState* state = GetOrRegisterNode(call_state_id);
  state->SetFunctionEntryId(function_entry_id);
  function_entry_states_[function_entry_id] = state;
}

CallState* CallStateGraph::GetFunctionEntryState(std::int32_t function_entry_id) {
  auto pos = function_entry_states_.find(function_entry_id);
  if (pos == function_entry_states_.end()) {
    return nullptr;
  }
  return pos->second;
}

CallStateGraph::~CallStateGraph() {
#ifdef DP_RTLIB_VERBOSE
  const auto start_time = std::chrono::high_resolution_clock::now();
#endif
  // delete nodes
  for (auto pair : node_map_) {
    delete pair.second;
  }
#ifdef DP_RTLIB_VERBOSE
  const auto end_time = std::chrono::high_resolution_clock::now();
  const auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time);
  std::cout << "[~CallStateGraph()]: " << (static_cast<double>(duration.count()) / 1000.0) << "s" << std::endl;
#endif
}

CallState* CallStateGraph::GetOrRegisterNode(std::int32_t call_state_id) {
  if (node_map_.find(call_state_id) == node_map_.end()) {
    CallState* node = new CallState(call_state_id);
    node_map_[call_state_id] = node;
    return node;
  }
  return node_map_[call_state_id];
}

void CallStateGraph::RegisterTransition(std::int32_t source_call_state_id, std::int32_t trigger_instruction,
                                        std::int32_t target_call_state_id) {
  CallState* source = GetOrRegisterNode(source_call_state_id);
  CallState* target = GetOrRegisterNode(target_call_state_id);
  source->RegisterTransition(trigger_instruction, target);
}

void CallStateGraph::RegisterImplicitReturnTransition(std::int32_t source_call_state_id,
                                                      std::int32_t target_call_state_id) {
  CallState* source = GetOrRegisterNode(source_call_state_id);
  CallState* target = GetOrRegisterNode(target_call_state_id);
  source->RegisterImplicitReturnTransition(target);
}
