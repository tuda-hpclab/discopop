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

#include <cstdint>
#include <unordered_map>

namespace __dp {

// For loop merging
// Assumption: no more than one loops can begin at the same line
struct LoopRecord {
  LoopRecord(LID e, std::int32_t t, std::int32_t n) : end(e), total(t), nEntered(n) {}

  LID end;
  std::int32_t total;
  std::int32_t nEntered;

  // maximum iterations executed during a single loop entry
  std::int32_t maxIterationCount = 0;

  bool operator==(const LoopRecord &other) const noexcept {
    return end == other.end && total == other.total && nEntered == other.nEntered &&
           maxIterationCount == other.maxIterationCount;
  }

  bool operator!=(const LoopRecord &other) const noexcept { return !(*this == other); }
};

typedef std::unordered_map<LID, LoopRecord *> LoopRecords;

} // namespace __dp
