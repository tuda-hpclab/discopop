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

#include "../runtimeFunctions.hpp"
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

void __dp_func_entry(LID lid, int32_t isStart) {
  if (!profiling_active()) {
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_func_entry");
#endif

  // The runtime is up before the first callback: it is brought up from .init_array, see
  // dp_init.cpp. No lazy initialization is needed here.
  function_manager->register_function_start(lid);

#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::FUNC_ENTRY);
#endif

#if DP_STACK_ACCESS_DETECTION
  memory_manager->enter_new_function();
  memory_manager->enterScope("function", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
  call_tree.enter_function(lid);
#endif

  if (isStart)
    *out << "START " << dputil::decodeLID(lid) << endl;

  // Reset last call tracker
  function_manager->log_call(0);
}
}

} // namespace __dp
