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
#include "../output_paths.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace __dp {

void update_callstate_from_call(int32_t instructionID) {
  // initialize_current_callpath_state() pushes the base entry this reads, and a target that never
  // reached it has no call state to keep either
  if (calls_without_executed_transitions.empty()) {
    return;
  }

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
  // initialize_current_callpath_state() pushes the base entry this reads, and a target that never
  // reached it has no call state to keep either
  if (calls_without_executed_transitions.empty()) {
    return;
  }

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
    // The base entry stays. unwind_function_stack() calls __dp_func_exit until the function stack
    // level has passed zero, so a target leaves more functions than __dp_call ever announced; popping
    // past the base entry used to leave the vector with its end before its start, where size() reads
    // back as SIZE_MAX and every later back() or [size() - 1] is out of bounds.
    if (calls_without_executed_transitions.size() > 1) {
      calls_without_executed_transitions.pop_back();
    }
  } else {
    // no transition found
    // issue an error message
    //cerr << "No transition found from state " << current_callpath_state->get_id() << " via instruction "
    //     << instructionID << "!\n";
    //cerr << "State might be incorrect from here on!\n";
  }
}

void update_callstate(int32_t instructionID) {
  // initialize_current_callpath_state() pushes the base entry this reads, and a target that never
  // reached it has no call state to keep either
  if (calls_without_executed_transitions.empty()) {
    return;
  }

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
  // create graph by parsing the file line by line
  const std::string path = profiler_output_path("initial_stateID.txt");
  std::ifstream file(path);
  std::string line;
  // The pass writes this file only once it has found a call path labelled "main" (see
  // DiscoPoP::save_initial_path), so it can be missing or empty -- and then the id below used to be
  // read without ever having been written, which sends a garbage state into the graph. State 0 is
  // the defined fallback: it has no transitions, so the reported call state simply stays put.
  int32_t current_callpath_state_id = 0;
  bool initial_state_found = false;
  while (std::getline(file, line)) {
    // a line that is not a number is skipped rather than thrown over: this runs from __dp_init,
    // where an escaping exception takes the instrumented program down
    try {
      std::size_t consumed = 0;
      const int32_t parsed = std::stoi(line, &consumed);
      if (consumed == 0) {
        continue;
      }
      current_callpath_state_id = parsed;
      initial_state_found = true;
    } catch (const std::logic_error &) {
      continue;
    }
  }
  if (!initial_state_found) {
    std::cerr << "DiscoPoP: could not read an initial call state from " << path
              << ". Reported call states will be incorrect!\n";
  }
  current_callpath_state = call_state_graph->get_or_register_node(current_callpath_state_id);
  calls_without_executed_transitions.push_back(0);
}

} // namespace __dp
