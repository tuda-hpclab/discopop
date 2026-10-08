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

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

// Brings the runtime up. Runs from .init_array before the first global constructor of the target,
// see dp_init.cpp; __dp_func_entry calls it as well, as a safety net.
void __dp_init();
}

} // namespace __dp
