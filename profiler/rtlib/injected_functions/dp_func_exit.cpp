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

void __dp_func_exit(LID lid, int32_t isExit) {
  if (!profiling_active()) {
    if (DP_DEBUG) {
      cout << "Exiting function LID " << std::dec << dputil::decodeLID(lid);
      cout << " but the runtime is not running. Destructors?" << endl;
    }
    return;
  }

  DP_CALLBACK_SCOPE(FUNC_EXIT);

  loop_manager->clean_function_exit(function_manager->get_current_stack_level(), lid);

  function_manager->reset_call(lid);
  function_manager->decrease_stack_level();

  // TEST
  // clear information on allocated stack addresses
#if DP_STACK_ACCESS_DETECTION
  const auto last_addresses = memory_manager->pop_last_stack_address();
#endif

  // clearStackAccesses goes through __dp_read / __dp_write, which take the lock themselves
  dp_scope.unlock();

#if DP_STACK_ACCESS_DETECTION
  clearStackAccesses(last_addresses.first,
                     last_addresses.second); // insert accesses with LID 0 to the queues
#endif

  dp_scope.relock();

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
  // released before the last statement, as the hand written unlock() here was
  dp_scope.unlock();

  update_callstate_from_func_exit(1); // 1 is the dummy instruction id for leaving a function
}
}

} // namespace __dp
