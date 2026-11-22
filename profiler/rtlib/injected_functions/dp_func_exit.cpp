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

#include "dp_func_exit.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "static_callstate_transitions/utils.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_func_exit(LID lid, std::int32_t is_exit) {
  if (!ProfilingActive()) {
    if (dp_debug) {
      std::cout << "Exiting function LID " << std::dec << dputil::DecodeLid(lid);
      std::cout << " but the runtime is not running. Destructors?" << std::endl;
    }
    return;
  }

  DP_CALLBACK_SCOPE(FUNC_EXIT);

  loop_manager->CleanFunctionExit(function_manager->GetCurrentStackLevel(), lid);

  function_manager->ResetCall(lid);
  function_manager->DecreaseStackLevel();

  if (is_exit == 0) {
    function_manager->RegisterFunctionEnd(lid);
  }

#ifdef DP_DEBUG  // runs for every event, so only built with the build option DP_DEBUG
std::cout << "Exiting fucntion LID " << std::dec << dputil::DecodeLid(lid) << std::endl;
std::cout << "Function stack level = " << std::dec << function_manager->GetCurrentStackLevel() << std::endl;
#endif
  // restore the callpath state of the caller, still under the lock (released with dp_scope)
  LeaveFunctionForCallstate();
}
}

}  // namespace dp
