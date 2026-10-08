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

void __dp_func_entry(LID lid, int32_t isStart, int32_t functionEntryID) {
  DP_CALLBACK_SCOPE(FUNC_ENTRY);

  // The runtime is up before the first callback: it is brought up from .init_array, see
  // lifecycle/runtime_startup.cpp. No lazy initialization is needed here.
  function_manager->register_function_start(lid);

  // follow the pending call into this function (or switch to the function's own root state)
  enter_function_for_callstate(functionEntryID);

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
