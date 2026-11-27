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

#include <cstdint>

#include "DPTypes.hpp"

namespace dp {

extern "C" {

// The writes of the size bytes from addr on, at every stride-th byte (from addr on), each passed to __dp_write as an
// access of its own (lid is the instruction id, kLibraryAccessInstructionId for library code). Inserted for the
// memory intrinsics of library code (memcpy, memmove, memset). A store is recorded at its first byte only, so the
// stride is the alignment the intrinsic guarantees (at most 8): the elements of an array of pointers are copied at
// their first bytes, those of a char array at every byte. Bytes in between would hold writes no other store ever
// replaces, and a later range would read them as dependencies on whatever was copied there before.
void __dp_write_range(LID lid, ADDR addr, int64_t size, int64_t stride, const char* var);
}

}  // namespace dp
