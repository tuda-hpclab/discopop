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

#include "../DPTypes.hpp"

namespace __dp {

// The three steps of shutting the runtime down, in the order __dp_finalize performs them. They
// are separate so that the order is readable in one place; see runtime_shutdown.cpp.

// Reports an exit for every function the target is still inside. Calls __dp_func_exit and
// therefore expects the pthread compatibility lock NOT to be held.
void unwind_function_stack(LID lid);

// Writes everything the later phases read: the loops, the iteration and branch counters, the
// functions, the allocations and the dependencies, plus the profiling time. Expects the lock to
// be held.
void write_results(LID lid);

// Releases what __dp_init created and moves the runtime to Terminated, after which every callback
// returns early. Does not release the Timers instance: the caller still measures itself.
void release_runtime();

} // namespace __dp
