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

// The pass records the absolute path of the .discopop directory it wrote the static data to (DOT_DISCOPOP of the
// compilation, or the nearest .discopop of the project if it was not set) in every module it instruments, as a constant
// string with this name; the runtime of the instrumented program uses it when DOT_DISCOPOP is not set, so a program
// started from any directory writes its results to where the static data is (like the path gcov bakes into the object
// code). Shared by the pass, which defines the symbol (weak, so several modules agree on one), and the runtime, which
// references it weakly.
constexpr const char* kDotDiscopopDefaultSymbol = "__dp_dot_discopop_default";
