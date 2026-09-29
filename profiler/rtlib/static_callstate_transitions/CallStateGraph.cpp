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
#include <string>

CallStateGraph::CallStateGraph() {
  auto start_time = std::chrono::high_resolution_clock::now();
  // open input file
  std::string tmp_2(getenv("DOT_DISCOPOP_PROFILER"));
  tmp_2 += "/callpath_state_transitions.txt";
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
    std::string source_callstate_id_str = line.substr(0, pos);
    line = line.substr(pos + 1);
    // get trigger instruction
    pos = line.find(' ');
    if (pos == std::string::npos) {
      continue;
    }
    std::string trigger_instruction_id_str = line.substr(0, pos);
    line = line.substr(pos + 1);
    // get target id
    std::string target_callstate_id_str = line;
    // register transition in CallStateGraph
    register_transition(std::stoi(source_callstate_id_str), std::stoi(trigger_instruction_id_str),
                        std::stoi(target_callstate_id_str));
  }
  // Transitions triggered by the dummy "return" instruction id are stored separately and without
  // that id (see DiscoPoP::save_path_state_transitions). Without them no function return updates
  // the call state, so a missing file must not pass silently.
  std::string tmp_3(getenv("DOT_DISCOPOP_PROFILER"));
  tmp_3 += "/callpath_state_return_targets.txt";
  std::ifstream return_targets_file(tmp_3);
  if (!return_targets_file) {
    std::cerr << "DiscoPoP: could not open " << tmp_3 << ". Reported call states will be incorrect!\n";
  }
  while (std::getline(return_targets_file, line)) {
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::size_t pos = line.find(' ');
    if (pos == std::string::npos) {
      continue;
    }
    std::string source_callstate_id_str = line.substr(0, pos);
    std::string target_callstate_id_str = line.substr(pos + 1);
    register_implicit_return_transition(std::stoi(source_callstate_id_str), std::stoi(target_callstate_id_str));
  }
  auto end_time = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time);
  std::cout << "[CallStateGraph()]: " << ((double)duration.count() / 1000.0) << "s" << std::endl;
}

CallStateGraph::~CallStateGraph() {
  auto start_time = std::chrono::high_resolution_clock::now();
  // delete nodes
  for (auto pair : node_map) {
    delete pair.second;
  }
  auto end_time = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time);
  std::cout << "[~CallStateGraph()]: " << ((double)duration.count() / 1000.0) << "s" << std::endl;
}

CallState *CallStateGraph::get_or_register_node(std::int32_t call_state_id) {
  if (node_map.find(call_state_id) == node_map.end()) {
    CallState *node = new CallState(call_state_id);
    node_map[call_state_id] = node;
    return node;
  }
  return node_map[call_state_id];
}

void CallStateGraph::register_transition(std::int32_t source_call_state_id, std::int32_t trigger_instruction,
                                         std::int32_t target_call_state_id) {
  CallState *source = get_or_register_node(source_call_state_id);
  CallState *target = get_or_register_node(target_call_state_id);
  source->register_transition(trigger_instruction, target);
}

void CallStateGraph::register_implicit_return_transition(std::int32_t source_call_state_id,
                                                         std::int32_t target_call_state_id) {
  CallState *source = get_or_register_node(source_call_state_id);
  CallState *target = get_or_register_node(target_call_state_id);
  source->register_implicit_return_transition(target);
}
