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

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

// hybrid analysis: reports an execution of the basic block holding the sinks of
// the dependencies handed over under bbIndex, whose sources lie in an earlier
// execution of another (or the same) basic block of the same function
// invocation. semaphore is the value __dp_bb_state returned when that source
// basic block was executed most recently in this invocation, or 0 if it was not
// executed yet, in which case no dependency exists.
void __dp_report_bb_pair(int32_t semaphore, uint32_t bbIndex) {
  if (!dpInited || targetTerminated) {
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_report_bb_pair");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::REPORT_BB_PAIR);
#endif

  if (semaphore) {
    bbList->record(bbIndex, ((uint32_t)semaphore) - 1, current_callpath_state_id_for_bb_reports());
  }
}

// hybrid analysis: called at the end of each basic block holding sources of the
// dependencies reported by __dp_report_bb_pair. Its result is stored in the
// function's semaphore for that block: the current callpath state id + 1, so
// that 0 keeps meaning "not executed" (also before the profiler is initialized,
// as no dependency is reported then either).
uint32_t __dp_bb_state() {
  if (!dpInited || targetTerminated || current_callpath_state == nullptr) {
    return 0;
  }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
  return ((uint32_t)current_callpath_state->get_id()) + 1;
}
}

} // namespace __dp
