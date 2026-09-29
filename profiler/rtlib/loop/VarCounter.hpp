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

namespace __dp {

struct VarCounter {
  unsigned int counters_[2] = {0, 0};
  long long mem_addr_ = 0;
  bool valid_ = true;

  bool operator==(const VarCounter &other) const noexcept {
    return counters_[0] == other.counters_[0] && counters_[1] == other.counters_[1] && mem_addr_ == other.mem_addr_ &&
           valid_ == other.valid_;
  }

  bool operator!=(const VarCounter &other) const noexcept { return !(*this == other); }
};

} // namespace __dp
