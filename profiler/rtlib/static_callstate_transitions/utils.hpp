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
#include "../runtimeFunctionsGlobals.hpp"

namespace __dp {
// Callpath state tracking. The state follows the calls, loops and returns of the thread which
// initialized the profiler (other threads record its current state, but do not change it).
//
// A call only remembers its instruction id (register_call_for_callstate). The transition happens
// when an instrumented function is entered (enter_function_for_callstate), so that only calls
// which actually reach an instrumented function change the state. Calls into code without
// instrumentation (library functions, indirect calls to them) leave it unchanged. On entry, the
// state follows the call's transition if the transition leads to the entered function, and else
// switches to the root state of the entered function (e.g. a call from another translation unit,
// an indirect or virtual call, a callback from library code), see callpath_function_entries.txt.
// If the function has no root state either, the state is kept and frozen until the function is
// left. Leaving a function restores the state and freeze flag of its caller.
void update_callstate(int32_t instructionID);
void initialize_current_callpath_state();
// makes the calling thread the one tracking callpath states, starting from the given state
void reset_callstate_tracking(CallState *initial_state);
void register_call_for_callstate(int32_t instructionID);
void enter_function_for_callstate(int32_t function_entry_id);
void leave_function_for_callstate();
// at a landing pad of the function with the given entry id: the functions entered after its latest
// instance were left by an exception, so their states are discarded and the state of that instance
// at its call into them is restored
void resume_function_for_callstate(int32_t function_entry_id);
// for tests: whether transitions are disabled, and the number of entered functions
bool callstate_transitions_frozen();
std::size_t callstate_frame_count();
} // namespace __dp
