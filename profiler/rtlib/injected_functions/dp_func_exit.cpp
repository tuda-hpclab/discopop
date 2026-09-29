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

void __dp_func_exit(LID lid, int32_t isExit) {
  if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "Exiting function LID " << std::dec << dputil::decodeLID(lid);
      cout << " but target program has returned from main(). Destructors?" << endl;
    }
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.lock();
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_func_exit");
#endif
#ifdef DP_INTERNAL_TIMER
  timers->start(TimerRegion::FUNC_EXIT);
  const auto timer = Timer(timers, TimerRegion::FUNC_EXIT);
#endif

  loop_manager->clean_function_exit(function_manager->get_current_stack_level(), lid);

  function_manager->reset_call(lid);
  function_manager->decrease_stack_level();

  // TEST
  // clear information on allocated stack addresses
#if DP_STACK_ACCESS_DETECTION
  const auto last_addresses = memory_manager->pop_last_stack_address();
#endif

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.unlock();
#endif

#if DP_STACK_ACCESS_DETECTION
  clearStackAccesses(last_addresses.first,
                     last_addresses.second); // insert accesses with LID 0 to the queues
#endif

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.lock();
#endif

#if DP_STACK_ACCESS_DETECTION
  memory_manager->leaveScope("function", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
  call_tree.exit_function();
#endif
  // !TEST

  if (isExit == 0) {
    function_manager->register_function_end(lid);
  }

  if (DP_DEBUG) {
    cout << "Exiting fucntion LID " << std::dec << dputil::decodeLID(lid) << endl;
    cout << "Function stack level = " << std::dec << function_manager->get_current_stack_level() << endl;
  }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.unlock();
#endif

  update_callstate_from_func_exit(1); // 1 is the dummy instruction id for leaving a function
}
}

} // namespace __dp
