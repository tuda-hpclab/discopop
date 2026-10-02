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

// whether the latest call of this thread updated the callpath state (see __dp_call)
thread_local bool last_call_updated_callstate = false;
// per active instrumented function of this thread: whether it was entered through such a call
thread_local std::vector<bool> function_entered_through_callstate_update;

void register_call_for_callstate(bool updates_callstate) { last_call_updated_callstate = updates_callstate; }

void enter_function_for_callstate() {
  function_entered_through_callstate_update.push_back(last_call_updated_callstate);
  last_call_updated_callstate = false;
}

bool leave_function_for_callstate() {
  if (function_entered_through_callstate_update.empty()) {
    return false;
  }
  bool entered_through_callstate_update = function_entered_through_callstate_update.back();
  function_entered_through_callstate_update.pop_back();
  return entered_through_callstate_update;
}

} // namespace __dp
