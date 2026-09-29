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

#include "utils.hpp"
#include "../runtimeFunctionsGlobals.hpp"

namespace __dp {

void update_callstate_from_call(int32_t instructionID) {
  // check if callstate update is currently disabled
  if (calls_without_executed_transitions.back() != 0) {
    // disabled, increment counter
    calls_without_executed_transitions[calls_without_executed_transitions.size() - 1] += 1;
    return;
  }

  // check if a transition exists
  CallState *transition_target = current_callpath_state->get_transition_target(instructionID);
  if (transition_target) {
    // transition found

    // check if a fall-through transition (i.e. instructionID '0') exists
    CallState *fallthrough_transition_target = transition_target->get_transition_target(0);
    if (fallthrough_transition_target) {
      // overwrite transition target with the fallthrough
      // TODO: this fallthrough could be implemented statically by redirecting the edges accordingly
      transition_target = fallthrough_transition_target;
    }

    // update current callstate
    current_callpath_state = transition_target;
    calls_without_executed_transitions.push_back(0);
  } else {
    // no transition found
    // increment the current counter in calls_without_executed_transitions, thereby temporarily disabling the state
    // transitioning
    calls_without_executed_transitions[calls_without_executed_transitions.size() - 1] += 1;
  }
}

void update_callstate_from_func_exit(int32_t instructionID) {
  // check if callstate update is currently disabled
  if (calls_without_executed_transitions.back() > 0) {
    // disabled, decrease counter
    calls_without_executed_transitions[calls_without_executed_transitions.size() - 1] -= 1;
    return;
  }

  // check if a transition exists
  CallState *transition_target = current_callpath_state->get_transition_target(instructionID);
  if (!transition_target && instructionID == 1) {
    transition_target = current_callpath_state->get_implicit_return_transition_target();
  }
  if (transition_target) {
    // transition found
    // update current callstate
    current_callpath_state = transition_target;
    calls_without_executed_transitions.pop_back();
  } else {
    // no transition found
    // issue an error message
    //cerr << "No transition found from state " << current_callpath_state->get_id() << " via instruction "
    //     << instructionID << "!\n";
    //cerr << "State might be incorrect from here on!\n";
  }
}

void update_callstate(int32_t instructionID) {
  // check if callstate update is currently disabled
  if (calls_without_executed_transitions.back() != 0) {
    // disabled
    return;
  }
  // check if a transition exists
  CallState *transition_target = current_callpath_state->get_transition_target(instructionID);
  if (transition_target) {
    // transition found

    // check if a fall-through transition (i.e. instructionID '0') exists
    CallState *fallthrough_transition_target = transition_target->get_transition_target(0);
    if (fallthrough_transition_target) {
      // overwrite transition target with the fallthrough
      // TODO: this fallthrough could be implemented statically by redirecting the edges accordingly
      transition_target = fallthrough_transition_target;
    }

    // update current callstate
    current_callpath_state = transition_target;
  }
  // update current callstate
}

void initialize_current_callpath_state() {
  // open input file
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/initial_stateID.txt";
  // create graph by parsing the file line by line
  std::ifstream file(tmp);
  std::string line;
  int32_t current_callpath_state_id;
  while (std::getline(file, line)) {
    current_callpath_state_id = stoi(line);
  }
  current_callpath_state = call_state_graph->get_or_register_node(current_callpath_state_id);
  calls_without_executed_transitions.push_back(0);
}

} // namespace __dp
