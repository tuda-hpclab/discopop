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

namespace __dp {

// For loop tracking
struct LoopTableEntry {
  LoopTableEntry(std::int32_t function_level, std::int32_t loop_id, std::int32_t number_hits, LID begin_line)
      : funcLevel(function_level), loopID(loop_id), count(number_hits), begin(begin_line) {
#if DP_CALLTREE_PROFILING
    dependency_metadata_calculation_enabled = true;
#endif
  }

  std::int32_t funcLevel;
  std::int32_t loopID;
  LID begin;

  bool operator==(const LoopTableEntry &other) const noexcept {
    return funcLevel == other.funcLevel && loopID == other.loopID && count == other.count && begin == other.begin;
  }

  bool operator!=(const LoopTableEntry &other) const noexcept { return !(*this == other); }

  std::int32_t get_count() const noexcept { return count; }

  void increment_count() noexcept { ++count; }

#if DP_CALLTREE_PROFILING
  void set_dependency_metadata_calculation_enabled(bool value) { dependency_metadata_calculation_enabled = value; }

  bool get_dependency_metadata_calculation_enabled() const { return dependency_metadata_calculation_enabled; }
#endif

private:
  std::int32_t count;
#if DP_CALLTREE_PROFILING
  bool dependency_metadata_calculation_enabled;
#endif
};

} // namespace __dp
