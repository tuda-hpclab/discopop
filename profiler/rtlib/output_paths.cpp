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

#include "output_paths.hpp"

#include <cassert>
#include <cstdlib>

namespace __dp {

std::string profiler_output_path(const std::string &file) {
  const char *const directory = getenv("DOT_DISCOPOP_PROFILER");
  assert(directory != nullptr && "DOT_DISCOPOP_PROFILER is unset, so __dp_init did not run");
  if (directory == nullptr) {
    // Constructing a std::string from a null pointer is undefined, and the callers are about to
    // open a file. Fall back to the default __dp_init would have set, so a release build writes
    // its results somewhere predictable instead of crashing.
    return ".discopop/profiler/" + file;
  }
  return std::string(directory) + "/" + file;
}

} // namespace __dp
