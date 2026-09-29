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

#ifdef SKIP_DUP_INSTR
// hybrid analysis
void __dp_decl(LID lid, ADDR addr, char *var, ADDR lastaddr, int64_t count);
// End HA
#else
// hybrid analysis
void __dp_decl(LID lid, ADDR addr, char *var);
// End HA
#endif
}

} // namespace __dp
