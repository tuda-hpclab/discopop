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
#include "../hybrid_analysis/bb_deps.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

// hybrid analysis: reports an execution of the basic block whose dependencies
// handed over under bbIndex have their sources in the same execution of that
// basic block (or no source instruction at all, INIT). Both ends of these
// dependencies therefore carry the current callpath state.
void __dp_report_bb(uint32_t bbIndex) {
  DP_CALLBACK_SCOPE(REPORT_BB);

#ifdef DP_RTLIB_VERBOSE
  std::cout << "bbIndex: " << std::to_string(bbIndex) << '\n';
#endif

  const uint32_t state = current_callpath_state_id_for_bb_reports();
  bbList->record(bbIndex, state, state);
}
}

} // namespace __dp
