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

#include "../../share/include/debug_print.hpp"
#include "../../share/include/timer.hpp"
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
  if (!dpInited || targetTerminated) {
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_call");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::CALL);
#endif

  function_manager->log_call(instructionID);

  // the callpath state transition happens when the callee enters an instrumented function, see
  // enter_function_for_callstate. A callee without instrumentation does not change the state.
  register_call_for_callstate(instructionID);
}
}

} // namespace __dp
