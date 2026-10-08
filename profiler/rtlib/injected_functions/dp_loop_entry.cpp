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

void __dp_loop_entry(LID lid, int32_t loopID, int32_t instruction_id) {
  DP_CALLBACK_SCOPE(LOOP_ENTRY);

  const auto function_stack_level = function_manager->get_current_stack_level();
  const auto is_new_loop = loop_manager->is_new_loop(loopID);

  if (is_new_loop) {
    loop_manager->create_new_loop(function_stack_level, loopID, lid);

#if DP_STACK_ACCESS_DETECTION
    // the loop scope spans the whole loop, the iteration scope one pass through the body. Both are
    // opened here, and every further entry below replaces only the iteration one.
    memory_manager->enterScope("loop", lid);
    memory_manager->enterScope("loop_iteration", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
    call_tree.enter_loop(lid);
    call_tree.enter_iteration(0);
#endif

  } else {
    // The same loop iterates again
    loop_manager->iterate_loop(function_stack_level);

    // Handle error made in instrumentation.
    // When recorded loopStack->top().funcLevel is different
    // with the current FuncStackLevel, two possible errors
    // happen during instrumentation:
    // 1) the loop entry is wrong, earlier than the real place;
    // 2) return of at least one function call inside the loop
    //    is missing.
    // So far it seems the first case happens sometimes but
    // the second case has never been seen. Thus whenever we
    // encounter such problem, we trust the current FuncStackLevel
    // and update top().funcLevel.

    loop_manager->correct_func_level(function_stack_level);

#if DP_STACK_ACCESS_DETECTION
    memory_manager->leaveScope("loop_iteration", lid);
    memory_manager->enterScope("loop_iteration", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
    call_tree.enter_iteration(0);
#endif
  }

  update_callstate(instruction_id);
}
}

} // namespace __dp
