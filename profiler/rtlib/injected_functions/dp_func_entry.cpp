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

#include "dp_init.hpp"

#ifdef __linux__
#include <linux/limits.h>
#endif

#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_func_entry(LID lid, int32_t isStart, int32_t functionEntryID) {
  if (targetTerminated) {
    // prevent deleting generated results after the main function has been
    // exited. This might happen, e.g., if a destructor of a global struct is
    // called after exiting the main function.
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_func_entry");
#endif

  if (!dpInited) {
    // Safety net. The runtime is normally brought up from .init_array, long before the
    // first callback, see dp_init.cpp -- this covers a build in which that constructor
    // did not make it into the link.
    __dp_init();
  } else if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "Entering function LID " << std::dec << dputil::decodeLID(lid);
      cout << " but target program has returned from main(). Destructors?" << endl;
    }
  } else {
    function_manager->register_function_start(lid);
  }

  // follow the pending call into this function (or switch to the function's own root state)
  enter_function_for_callstate(functionEntryID);

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
