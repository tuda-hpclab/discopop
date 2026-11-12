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
#include "runtimeFunctionsGlobals.hpp"

namespace dp {
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
void UpdateCallstate(int32_t instruction_id);
// sets current_callpath_state and current_callpath_state_id
void SetCurrentCallpathState(CallState* state);
void InitializeCurrentCallpathState();
// makes the calling thread the one tracking callpath states, starting from the given state
void ResetCallstateTracking(CallState* initial_state);
// instruction id of the latest call of this thread which has not entered an instrumented function yet
extern constinit thread_local int32_t pending_call_instruction;
// inline: runs on every call of the program
inline void RegisterCallForCallstate(int32_t instruction_id) { pending_call_instruction = instruction_id; }
void EnterFunctionForCallstate(int32_t function_entry_id);
void LeaveFunctionForCallstate();
// at a landing pad of the function with the given entry id: the functions entered after its latest
// instance were left by an exception, so their states are discarded and the state of that instance
// at its call into them is restored
void ResumeFunctionForCallstate(int32_t function_entry_id);
// for tests: whether transitions are disabled, and the number of entered functions
bool CallstateTransitionsFrozen();
std::size_t CallstateFrameCount();
}  // namespace dp
