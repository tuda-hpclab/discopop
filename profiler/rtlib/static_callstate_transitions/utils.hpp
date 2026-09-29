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
#include "../runtimeFunctionsGlobals.hpp"

namespace __dp {
void update_callstate_from_call(int32_t instructionID);
void update_callstate_from_func_exit(int32_t instructionID);
void update_callstate(int32_t instructionID);
void initialize_current_callpath_state();
} // namespace __dp
