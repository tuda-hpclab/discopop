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

#include "dp_alloca.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "lid_utils.hpp"
#include "runtimeFunctionsGlobals.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_alloca(LID /*lid*/, char* var, ADDR start_addr, ADDR /*end_addr*/, std::int64_t num_bytes,
                 std::int64_t /*num_elements*/) {
  DP_CALLBACK_SCOPE(ALLOCA);

  // the variable belongs to the frame of the function executing the alloca, see memory/StackFrames.hpp
  stack_frames.Register(start_addr, start_addr + num_bytes, var);
}
}

}  // namespace dp
