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

#include "../static_callstate_transitions/utils.hpp"

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_loop_incr(const int loop_id, int32_t instruction_id) {
  if (!dpInited || targetTerminated) {
    return;
  }

  if (loop_manager->is_done()) {
    return;
  }

  loop_manager->incr_loop_counter(loop_id);

  update_callstate(instruction_id);
}
}

} // namespace __dp
