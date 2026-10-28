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

#include "dp_landing_pad.hpp"

#include <cstddef>
#include <mutex>

#include "callback_scope.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "static_callstate_transitions/utils.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

// An exception unwinds the stack without running the __dp_func_exit of the functions it leaves.
// Their callpath states are discarded here, when the landing pad of the function which continues
// is reached. Their loops and function levels are closed as well: the entry of a loop from a function
// level above the one of the loop on top of the loop stack starts a new loop (the entry of a recursive
// instance, see LoopManager::IsNewLoop), so a level left too high would turn every later iteration of a
// loop of the continuing function into a loop of its own.
void __dp_landing_pad(int32_t function_entry_id) {
  DP_CALLBACK_SCOPE(LANDING_PAD);

  const std::size_t frames_before = CallstateFrameCount();
  ResumeFunctionForCallstate(function_entry_id);
  const std::size_t frames_after = CallstateFrameCount();

  // one level per function left; the end line of a loop which is left this way is not known
  for (std::size_t left = frames_before - frames_after; left > 0; --left) {
    loop_manager->CleanFunctionExit(function_manager->GetCurrentStackLevel(), 0);
    function_manager->DecreaseStackLevel();
  }
}
}

}  // namespace dp
