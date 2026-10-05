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

#include <fstream>
#include <string>
#include <vector>

namespace __dp {

namespace {
// the callpath state of a caller, restored when the entered function is left
struct CallstateFrame {
  CallState *caller_state;
  bool caller_frozen;
  // the entered function
  int32_t function_entry_id;
};

// only the thread which initialized the callpath state tracking changes the state
thread_local bool callstate_owner = false;
// instruction id of the latest call of this thread which has not entered an instrumented function yet
thread_local int32_t pending_call_instruction = 0;
// the following are used by the owner thread only
std::vector<CallstateFrame> callstate_frames;
bool callstate_frozen = false;

// the target of the transition triggered by instructionID, following a fall-through transition
CallState *get_transition_target_with_fallthrough(CallState *state, int32_t instructionID) {
  CallState *transition_target = state->get_transition_target(instructionID);
  if (transition_target) {
    // check if a fall-through transition (i.e. instructionID '0') exists
    CallState *fallthrough_transition_target = transition_target->get_transition_target(0);
    if (fallthrough_transition_target) {
      // TODO: this fallthrough could be implemented statically by redirecting the edges accordingly
      transition_target = fallthrough_transition_target;
    }
  }
  return transition_target;
}
} // namespace

void update_callstate(int32_t instructionID) {
  if (!callstate_owner || callstate_frozen) {
    return;
  }
  CallState *transition_target = get_transition_target_with_fallthrough(current_callpath_state, instructionID);
  if (transition_target) {
    current_callpath_state = transition_target;
  }
}

void reset_callstate_tracking(CallState *initial_state) {
  current_callpath_state = initial_state;
  callstate_frames.clear();
  callstate_frozen = false;
  pending_call_instruction = 0;
  callstate_owner = true;
}

void initialize_current_callpath_state() {
  // open input file
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/initial_stateID.txt";
  // create graph by parsing the file line by line
  std::ifstream file(tmp);
  std::string line;
  int32_t current_callpath_state_id = 0;
  while (std::getline(file, line)) {
    current_callpath_state_id = stoi(line);
  }
  reset_callstate_tracking(call_state_graph->get_or_register_node(current_callpath_state_id));
}

void register_call_for_callstate(int32_t instructionID) { pending_call_instruction = instructionID; }

void enter_function_for_callstate(int32_t function_entry_id) {
  int32_t call_instruction = pending_call_instruction;
  pending_call_instruction = 0;
  if (!callstate_owner) {
    return;
  }
  callstate_frames.push_back({current_callpath_state, callstate_frozen, function_entry_id});

  CallState *target = nullptr;
  if (call_instruction != 0 && !callstate_frozen) {
    target = get_transition_target_with_fallthrough(current_callpath_state, call_instruction);
    // the call's transition is valid only if it leads into the entered function. Otherwise the
    // callee was not the entered function (a call into code without instrumentation, which called
    // back into instrumented code) or is not known in the caller's translation unit.
    if (target && target->get_function_entry_id() != function_entry_id) {
      target = nullptr;
    }
  }
  if (!target && call_state_graph) {
    target = call_state_graph->get_function_entry_state(function_entry_id);
  }
  if (target) {
    current_callpath_state = target;
    callstate_frozen = false;
  } else {
    // the state of the entered function is unknown: keep the caller's state, do not transition
    callstate_frozen = true;
  }
}

void leave_function_for_callstate() {
  pending_call_instruction = 0;
  if (!callstate_owner || callstate_frames.empty()) {
    return;
  }
  current_callpath_state = callstate_frames.back().caller_state;
  callstate_frozen = callstate_frames.back().caller_frozen;
  callstate_frames.pop_back();
}

void resume_function_for_callstate(int32_t function_entry_id) {
  pending_call_instruction = 0;
  if (!callstate_owner) {
    return;
  }
  // the frame of the function's latest instance
  std::size_t frame_count = callstate_frames.size();
  while (frame_count > 0 && callstate_frames[frame_count - 1].function_entry_id != function_entry_id) {
    --frame_count;
  }
  if (frame_count == 0) {
    // not entered (e.g. the function was entered before the tracking started): keep everything
    return;
  }
  // leave the functions entered by it
  while (callstate_frames.size() > frame_count) {
    leave_function_for_callstate();
  }
}

bool callstate_transitions_frozen() { return callstate_frozen; }

std::size_t callstate_frame_count() { return callstate_frames.size(); }

} // namespace __dp
