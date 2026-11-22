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

#pragma once

#include <cstdint>
#include <vector>

#include "runtimeFunctionsGlobals.hpp"
#include "runtimeFunctionsTypes.hpp"

namespace dp {

// The registry behind __dp_add_bb_deps: one dependency string per instrumented module, handed
// over from a module constructor and parsed once the target has terminated. See bb_deps.cpp for
// why its storage is managed by hand.

// The registered strings. Constructed on first use, so the module constructors may call it in any
// order, and long before the runtime itself is up.
std::vector<const char*>& RegisteredBbDepStrings();

// Merges the dependencies of every registered string whose basic block was actually executed into
// the collected dependencies, once per distinct pair of callpath states the executions were
// reported with. Must run after the target has terminated, when bbList is complete, and before the
// dependencies are written out.
void ProcessRegisteredBbDeps();

// Releases the registry. Called from destroy_immortal_globals(), once process_registered_bb_deps()
// has consumed it.
void ReleaseRegisteredBbDeps();

// the id of the current callpath state, or 0 if none is known yet. Used to
// attribute the executions reported by __dp_report_bb / __dp_report_bb_pair.
inline std::uint32_t CurrentCallpathStateIdForBbReports() { return current_callpath_state_id; }

// merges the dependencies of the given handed over dependency strings into
// out, once per reported execution in reported whose basic block index they are
// registered under. The sink of each dependency gets the reported sink state,
// its source the reported source state (an INIT dependency has no source and
// keeps "*"), in the "<instruction id>@<callpath state id>" notation of the
// dynamically profiled dependencies.
void MergeBbDeps(const std::vector<const char*>& dep_strings, const ReportedBBSet& reported, StringDepMap& out);

}  // namespace dp
