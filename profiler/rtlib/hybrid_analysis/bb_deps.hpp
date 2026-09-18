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

#include <vector>

namespace __dp {

// The registry behind __dp_add_bb_deps: one dependency string per instrumented module, handed
// over from a module constructor and parsed once the target has terminated. See bb_deps.cpp for
// why its storage is managed by hand.

// The registered strings. Constructed on first use, so the module constructors may call it in any
// order, and long before the runtime itself is up.
std::vector<const char *> &registered_bb_dep_strings();

// Merges the dependencies of every registered string whose basic block was actually executed into
// the collected dependencies. Must run after the target has terminated, when bbList is complete,
// and before the dependencies are written out.
void process_registered_bb_deps();

// Releases the registry. Called from destroy_immortal_globals(), once process_registered_bb_deps()
// has consumed it.
void release_registered_bb_deps();

} // namespace __dp
