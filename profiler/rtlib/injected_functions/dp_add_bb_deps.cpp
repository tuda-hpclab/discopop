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

#include "dp_add_bb_deps.hpp"

#include "../hybrid_analysis/bb_deps.hpp"

namespace __dp {

/******* Instrumentation function *******/
extern "C" {
// hybrid analysis
//
// Called once per instrumented module, from a module constructor. Only records
// the string: at that point the profiling infrastructure is not initialized yet
// and no basic block has been reported, so nothing could be decided here. The
// string is a constant in the module's own image and thus outlives the program.
// Deliberately takes no lock: this runs during static initialization, where
// locking a global mutex would depend on that mutex already being constructed,
// and where the program is still single-threaded anyway.
void __dp_add_bb_deps(char *depStringPtr) {
  if (depStringPtr == nullptr) {
    return;
  }
  registered_bb_dep_strings().push_back(depStringPtr);
}
// End HA
}

} // namespace __dp
