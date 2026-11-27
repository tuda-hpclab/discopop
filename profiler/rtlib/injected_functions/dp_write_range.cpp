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

#include "dp_write_range.hpp"

#include <cstdint>

#include "dp_write.hpp"

namespace dp {

extern "C" {

void __dp_write_range(LID lid, ADDR addr, int64_t size, int64_t stride, const char* var) {
  // no callback scope of its own: it would mark the runtime as entered, and __dp_write would return at once. Each
  // __dp_write opens its own, checks whether profiling is active and attributes a library access by its own frame,
  // which lies below this one and so below every frame of the library as well
  const int64_t step = stride > 0 ? stride : 1;
  for (int64_t offset = 0; offset < size; offset += step) {
#ifdef SKIP_DUP_INSTR
    __dp_write(lid, addr + static_cast<ADDR>(offset), const_cast<char*>(var), 0, 0);
#else
    __dp_write(lid, addr + static_cast<ADDR>(offset), var);
#endif
  }
}
}

}  // namespace dp
