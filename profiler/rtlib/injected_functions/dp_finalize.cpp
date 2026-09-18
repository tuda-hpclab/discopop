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

#include "dp_finalize.hpp"

#include "../DPTypes.hpp"

#include "../runtimeFunctionsGlobals.hpp"

#include "../lifecycle/runtime_shutdown.hpp"

#include "../../share/include/debug_print.hpp"
#include "../../share/include/timer.hpp"

#include <mutex>

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_finalize(LID lid) {
  // Reached twice when the target leaves through a function that does not return to main: once
  // from the call the pass puts in front of it, and once from the .fini_array entry.
  if (!profiling_active()) {
    return;
  }

  // The only callback that does not use DP_CALLBACK_SCOPE. Its timer prints the whole report when
  // it is destroyed, so it has to be gone before the Timers instance it points to is released --
  // which is what the inner scope is for.
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::unique_lock<std::mutex> lock(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_finalize");
#endif

  {
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::FINALIZE, true);
#endif

    // unwind_function_stack goes through __dp_func_exit, which takes the lock itself
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    lock.unlock();
#endif
    unwind_function_stack(lid);
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    lock.lock();
#endif

    write_results(lid);
    release_runtime();
  }

  // Outside the scope above, so the FINALIZE timer has printed its report by now.
  delete timers;
  timers = nullptr;
}
}

} // namespace __dp
