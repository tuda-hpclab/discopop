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

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "Immortal.hpp"
#include "output_paths.hpp"
#include "runtimeFunctionsGlobals.hpp"

namespace dp {

namespace {
// the callpath state of a caller, restored when the entered function is left
struct CallstateFrame {
  CallState* caller_state;
  bool caller_frozen;
  // the entered function
  int32_t function_entry_id;
};

// only the thread which initialized the callpath state tracking changes the state
thread_local bool callstate_owner = false;
// instruction id of the latest call of this thread which has not entered an instrumented function yet
thread_local int32_t pending_call_instruction = 0;
// the following are used by the owner thread only. They are written on every function entry and
// exit, so they get cache lines of their own: sharing one with a global the worker threads read
// for every dependency (e.g. DP_DEBUG in addDep, which a different link layout put next to
// the frozen flag) doubled LULESH's profiling time through false sharing.
struct alignas(64) CallstateHotData {
  std::vector<CallstateFrame> frames;
  bool frozen = false;
};
// Immortal (see Immortal.hpp): the runtime starts from .init_array, before this translation unit's
// own dynamic initializers, and the destructors of the target's global objects still enter and leave
// functions after a plain global would have been destroyed. Constructed by reset_callstate_tracking,
// which also makes the calling thread the owner; every other use is behind the owner check.
ImmortalStorage<CallstateHotData> callstate_hot_storage;
CallstateHotData& callstate_hot = callstate_hot_storage.value;
bool callstate_hot_constructed = false;

// the target of the transition triggered by instructionID, following a fall-through transition
CallState* GetTransitionTargetWithFallthrough(CallState* state, int32_t instruction_id) {
  CallState* transition_target = state->GetTransitionTarget(instruction_id);
  if (transition_target) {
    // check if a fall-through transition (i.e. instructionID '0') exists
    CallState* fallthrough_transition_target = transition_target->GetFallthroughTransitionTarget();
    if (fallthrough_transition_target) {
      // TODO: this fallthrough could be implemented statically by redirecting the edges accordingly
      transition_target = fallthrough_transition_target;
    }
  }
  return transition_target;
}
}  // namespace

void UpdateCallstate(int32_t instruction_id) {
  if (!callstate_owner || callstate_hot.frozen) {
    return;
  }
  CallState* transition_target = GetTransitionTargetWithFallthrough(current_callpath_state, instruction_id);
  if (transition_target) {
    current_callpath_state = transition_target;
  }
}

void ResetCallstateTracking(CallState* initial_state) {
  current_callpath_state = initial_state;
  if (!callstate_hot_constructed) {
    callstate_hot_storage.Construct();
    callstate_hot_constructed = true;
  }
  callstate_hot.frames.clear();
  callstate_hot.frozen = false;
  pending_call_instruction = 0;
  callstate_owner = true;
}

void InitializeCurrentCallpathState() {
  // open input file
  // create graph by parsing the file line by line
  const std::string path = ProfilerOutputPath("initial_stateID.txt");
  std::ifstream file(path);
  std::string line;
  // The pass writes this file only once it has found a call path labelled "main" (see
  // static_callpaths::save_initial_path), so it can be missing or empty -- and then the id below used to be
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
    } catch (const std::logic_error&) {
      continue;
    }
  }
  if (!initial_state_found) {
    std::cerr << "DiscoPoP: could not read an initial call state from " << path
              << ". Reported call states will be incorrect!\n";
  }
  ResetCallstateTracking(call_state_graph->GetOrRegisterNode(current_callpath_state_id));
}

void RegisterCallForCallstate(int32_t instruction_id) { pending_call_instruction = instruction_id; }

void EnterFunctionForCallstate(int32_t function_entry_id) {
  const int32_t call_instruction = pending_call_instruction;
  pending_call_instruction = 0;
  if (!callstate_owner) {
    return;
  }
  callstate_hot.frames.push_back({current_callpath_state, callstate_hot.frozen, function_entry_id});

  CallState* target = nullptr;
  if (call_instruction != 0 && !callstate_hot.frozen) {
    target = GetTransitionTargetWithFallthrough(current_callpath_state, call_instruction);
    // the call's transition is valid only if it leads into the entered function. Otherwise the
    // callee was not the entered function (a call into code without instrumentation, which called
    // back into instrumented code) or is not known in the caller's translation unit.
    if (target && target->GetFunctionEntryId() != function_entry_id) {
      target = nullptr;
    }
  }
  if (!target && call_state_graph) {
    target = call_state_graph->GetFunctionEntryState(function_entry_id);
  }
  if (target) {
    current_callpath_state = target;
    callstate_hot.frozen = false;
  } else {
    // the state of the entered function is unknown: keep the caller's state, do not transition
    callstate_hot.frozen = true;
  }
}

void LeaveFunctionForCallstate() {
  pending_call_instruction = 0;
  if (!callstate_owner || callstate_hot.frames.empty()) {
    return;
  }
  current_callpath_state = callstate_hot.frames.back().caller_state;
  callstate_hot.frozen = callstate_hot.frames.back().caller_frozen;
  callstate_hot.frames.pop_back();
}

void ResumeFunctionForCallstate(int32_t function_entry_id) {
  pending_call_instruction = 0;
  if (!callstate_owner) {
    return;
  }
  // the frame of the function's latest instance
  std::size_t frame_count = callstate_hot.frames.size();
  while (frame_count > 0 && callstate_hot.frames[frame_count - 1].function_entry_id != function_entry_id) {
    --frame_count;
  }
  if (frame_count == 0) {
    // not entered (e.g. the function was entered before the tracking started): keep everything
    return;
  }
  // leave the functions entered by it
  while (callstate_hot.frames.size() > frame_count) {
    LeaveFunctionForCallstate();
  }
}

bool CallstateTransitionsFrozen() { return callstate_hot_constructed && callstate_hot.frozen; }

std::size_t CallstateFrameCount() { return callstate_hot_constructed ? callstate_hot.frames.size() : 0; }

}  // namespace dp
