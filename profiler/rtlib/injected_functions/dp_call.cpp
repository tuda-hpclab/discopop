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

void __dp_call(LID lid, int32_t instructionID, int8_t isLibraryFunction) {
  DP_CALLBACK_SCOPE(CALL);

  // The location of the call site, which the function manager pairs with the entry of the
  // function that is about to run and reports as "<call site> BGN func <entry>". It used to
  // be handed the instruction id, which decodeLID then read as a location and printed as
  // "0:<id>".
  function_manager->log_call(lid);

  // exclude library functions from callstate updates due to the missing instrumented function exit
  // and the resulting inconsistent callstate after returning
  if (!isLibraryFunction) {
    update_callstate_from_call(instructionID);
  }
}
}

} // namespace __dp
