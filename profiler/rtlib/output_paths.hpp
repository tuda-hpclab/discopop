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

#include <string>

namespace __dp {

// Path of `file` inside the profiler's output directory.
//
// __dp_init runs from .init_array, before any other code of an instrumented program, and pins
// DOT_DISCOPOP / DOT_DISCOPOP_PROFILER down there (see dp_init.cpp). Every place in the runtime
// that reads or writes a result file can therefore rely on the directory being known, and none of
// them has to repeat the "set it if the target did not" dance.
//
// Note that this holds for the runtime only. The LLVM pass writes into the same directory at
// compile time, where no __dp_init has run, so its own lookup in share/lib/DPUtils.cpp keeps
// establishing the variables itself.
std::string profiler_output_path(const std::string &file);

} // namespace __dp
