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

/******* Instrumentation function *******/
extern "C" {

// hybrid analysis
void __dp_report_bb_pair(int32_t counter, uint32_t bbIndex);
// End HA
}

} // namespace __dp
