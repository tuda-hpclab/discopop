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

/******* Runtime startup *******/
extern "C" {

// Brings the runtime up. Not an instrumented callback: the pass inserts no call to it. It runs
// from the .init_array entry in runtime_startup.cpp, before the first global constructor of the
// target program.
void __dp_init();
}

} // namespace __dp
