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

// A location id (LID) names an instruction of the instrumented program: the id of its file in the upper
// bits and its line in the lower LIDSIZE bits, i.e. (file id << LIDSIZE) + line. The runtime adds its
// metadata (call path state, loop iterations) above, see LIDMETADATASIZE. Use dputil::encodeLID to build
// one; it checks that file id and line fit.
// Shared by the LLVM pass, which writes the LIDs into the instrumentation, and the runtime, which decodes them.
using LID = std::int64_t;
using ADDR = std::int64_t;

// Number of bits for holding the line number in a LID
constexpr int kLidSize = 18;

// Number of bits for holding LID Metadata (Column + Loop ID + Loop Iteration)
constexpr int kLidMetadataSize = 32;

// Number of bits for holding the location (file id and line number) of a LID
constexpr int kLidLocationSize = 64 - kLidMetadataSize;

// Number of bits for holding the file id in a LID
constexpr int kFileIdSize = kLidLocationSize - kLidSize;

// Number of lines in a single file: the lines 0 to MAXLNO - 1 can be encoded. Has to be 2^LIDSIZE.
constexpr int kMaxLno = 1 << kLidSize;

// Highest file id that can be encoded. File id 0 means "no file".
constexpr int kMaxFileId = (1 << kFileIdSize) - 1;

// The instruction id the pass passes to __dp_read / __dp_write for an access in library code (DP_LIBRARY_DIRS, see
// dputil::IsInLibraryDirs). Library code has no instruction ids of its own (they start at 2): the runtime attributes
// the access to the last call instruction of the innermost frame of project code, i.e. to the call that entered the
// library.
constexpr std::int64_t kLibraryAccessInstructionId = 0;

static_assert(kLidLocationSize == 32, "the location of a LID is 32 bits wide: the runtime masks it with 0xFFFFFFFF");
static_assert(kLidSize > 0 && kFileIdSize > 0, "a LID needs bits for both its line and its file id");
