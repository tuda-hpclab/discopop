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

#include "dp_report_bb_pair.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "hybrid_analysis/bb_deps.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

// hybrid analysis: reports an execution of the basic block holding the sinks of
// the dependencies handed over under bbIndex, whose sources lie in an earlier
// execution of another (or the same) basic block of the same function
// invocation. semaphore is the value __dp_bb_state returned when that source
// basic block was executed most recently in this invocation, or 0 if it was not
// executed yet, in which case no dependency exists.
void __dp_report_bb_pair(std::int32_t semaphore, std::uint32_t bb_index) {
  DP_CALLBACK_SCOPE(REPORT_BB_PAIR);

  if (semaphore) {
    bb_list->Record(bb_index, static_cast<std::uint32_t>(semaphore) - 1, CurrentCallpathStateIdForBbReports());
  }
}

// hybrid analysis: called at the end of each basic block holding sources of the
// dependencies reported by __dp_report_bb_pair. Its result is stored in the
// function's semaphore for that block: the current callpath state id + 1, so
// that 0 keeps meaning "not executed" (also before the profiler is initialized,
// as no dependency is reported then either).
std::uint32_t __dp_bb_state() {
  // the semaphore half of the pair reports, so it belongs to REPORT_BB_PAIR in a benchmark build
  if (!CallbackBodyEnabled(CallbackId::REPORT_BB_PAIR) || !ProfilingActive() || current_callpath_state == nullptr) {
    return 0;
  }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
  return current_callpath_state_id + 1;
}
}

}  // namespace dp
