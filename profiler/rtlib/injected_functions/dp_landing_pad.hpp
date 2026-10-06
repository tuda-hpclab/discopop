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

extern "C" {

// called at the start of every landing pad (exception cleanup or catch handler) of an instrumented
// function. functionEntryID identifies the function, as for __dp_func_entry.
void __dp_landing_pad(int32_t functionEntryID);
}

} // namespace __dp
