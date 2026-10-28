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

#include "dp_loop_entry.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "static_callstate_transitions/utils.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_loop_entry(LID lid, std::int32_t loop_id, std::int32_t instruction_id) {
  DP_CALLBACK_SCOPE(LOOP_ENTRY);

  const auto function_stack_level = function_manager->GetCurrentStackLevel();
  const auto is_new_loop = loop_manager->IsNewLoop(function_stack_level, loop_id);

  if (is_new_loop) {
    loop_manager->CreateNewLoop(function_stack_level, loop_id, lid);

  } else {
    // The same loop iterates again
    loop_manager->IterateLoop(function_stack_level);

    // Handle error made in instrumentation.
    // The entry of a loop from a deeper function level than the one recorded for the loop on top
    // is a new loop (see IsNewLoop). When the recorded level is higher or the levels differ for
    // another reason, two possible errors happen during instrumentation:
    // 1) the loop entry is wrong, earlier than the real place;
    // 2) the return of at least one function call inside the loop is missing (the landing pad
    //    closes the levels of the functions an exception leaves).
    // So far it seems the first case happens sometimes but the second case has never been
    // seen. Thus whenever we encounter such problem, we trust the current FuncStackLevel and
    // update top().funcLevel.

    loop_manager->CorrectFuncLevel(function_stack_level);
  }

  UpdateCallstate(instruction_id);
}
}

}  // namespace dp
