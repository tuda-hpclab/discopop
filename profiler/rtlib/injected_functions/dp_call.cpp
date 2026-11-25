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

#include "dp_call.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "static_callstate_transitions/utils.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_call(LID lid, std::int32_t instruction_id) {
  DP_CALLBACK_SCOPE(CALL);

  // The location of the call site and its instruction id, which the function manager pairs with
  // the entry of the function that is about to run and reports as
  // "<call site> BGN func <entry> <instruction id>". It used to be handed the instruction id only,
  // which decodeLID then read as a location and printed as "0:<id>".
  function_manager->LogCall(lid, instruction_id);

  // the callpath state transition happens when the callee enters an instrumented function, see
  // enter_function_for_callstate. A callee without instrumentation does not change the state.
  RegisterCallForCallstate(instruction_id);

  // the call library accesses made during it are attributed to (see StackFrames::LibraryAccessAttribution)
  stack_frames.SetCallInstruction(instruction_id);
}
}

}  // namespace dp
