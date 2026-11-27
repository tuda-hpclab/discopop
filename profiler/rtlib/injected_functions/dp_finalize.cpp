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

#include <mutex>

#include "DPTypes.hpp"
#include "debug_print.hpp"
#include "lifecycle/runtime_shutdown.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "timer.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_finalize(LID lid) {
  // Reached twice when the target leaves through a function that does not return to main: once
  // from the call the pass puts in front of it, and once from the .fini_array entry.
  if (!ProfilingActive()) {
    return;
  }

  // The only callback that does not use DP_CALLBACK_SCOPE. Its timer prints the whole report when
  // it is destroyed, so it has to be gone before the Timers instance it points to is released --
  // which is what the inner scope is for.
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::unique_lock<std::mutex> lock(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("__dp_finalize");
#endif

  {
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::kFinalize, true);
#endif

    // unwind_function_stack goes through __dp_func_exit, which takes the lock itself
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    lock.unlock();
#endif
    UnwindFunctionStack(lid);
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    lock.lock();
#endif

    // Not around UnwindFunctionStack: it leaves the open functions through __dp_func_exit, which would return at once.
    const RuntimeSection runtime_section;
    WriteResults(lid);
    ReleaseRuntime();
  }

  // Outside the scope above, so the FINALIZE timer has printed its report by now.
  delete timers;
  timers = nullptr;
}
}

}  // namespace dp
