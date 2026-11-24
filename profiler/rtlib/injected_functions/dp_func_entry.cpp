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

#include "dp_func_entry.hpp"

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

void __dp_func_entry(LID lid, std::int32_t is_start, std::int32_t function_entry_id) {
  DP_CALLBACK_SCOPE(FUNC_ENTRY);

  stack_frames.Push();

  // The runtime is up before the first callback: it is brought up from .init_array, see
  // lifecycle/runtime_startup.cpp. No lazy initialization is needed here.
  function_manager->RegisterFunctionStart(lid);

  // follow the pending call into this function (or switch to the function's own root state)
  EnterFunctionForCallstate(function_entry_id);

  if (is_start) {
    *out << "START " << dputil::DecodeLid(lid) << std::endl;
  }

  // Reset last call tracker
  function_manager->LogCall(0);
}
}

}  // namespace dp
