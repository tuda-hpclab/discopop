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

void __dp_loop_exit(LID lid, int32_t loopID, int32_t instruction_id) {
  if (!dpInited || targetTerminated) {
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_loop_exit");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::LOOP_EXIT);
#endif

  if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "__dp_loop_exit() is not executed since target program has "
              "returned from main()."
           << endl;
    }
    return;
  }

  // __dp_loop_exit() can be called without __dp_loop_entry()
  // being called. This can happen when a loop is encapsulated
  // by an "if" structure, and the condition of "if" fails
  if (loop_manager->is_single_exit(loopID)) {
    if (DP_DEBUG) {
      std::cout << "Ignored single exit of loop " << loop_manager->get_current_loop_id() << endl;
    }
    return;
  }

  // See comments in __dp_loop_entry() for explanation.
  const auto function_stack_level = function_manager->get_current_stack_level();
  loop_manager->correct_func_level(function_stack_level);
  loop_manager->exit_loop(lid);

#if DP_STACK_ACCESS_DETECTION
  memory_manager->leaveScope("loop", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
  call_tree.exit_loop();
#endif

  update_callstate(instruction_id);
}
}

} // namespace __dp
