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

#include "../DPTypes.hpp"

#include "../runtimeFunctionsGlobals.hpp"

#include "../callback_scope.hpp"
#include "../static_callstate_transitions/utils.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_call(LID instructionID) {
  DP_CALLBACK_SCOPE(CALL);

  function_manager->log_call(instructionID);

  // the callpath state transition happens when the callee enters an instrumented function, see
  // enter_function_for_callstate. A callee without instrumentation does not change the state.
  register_call_for_callstate(instructionID);
}
}

} // namespace __dp
