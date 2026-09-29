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

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_incr_taken_branch_counter(char *source_and_target, int cmp_res, int active_on) {
  if (!dpInited || targetTerminated) {
    return;
  }

  if (cmp_res == active_on) {
    if (cuec.count(source_and_target) == 0) {
      cuec[source_and_target] = 1;
    } else {
      cuec[source_and_target] = cuec[source_and_target] + 1;
    }
  }
}
}

} // namespace __dp
