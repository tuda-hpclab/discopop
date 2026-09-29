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

#include "LoopTableEntry.hpp"

#include <cstdint>
#include <iostream>
#include <vector>

namespace __dp {

struct LoopTable {
public:
  LoopTable() { contents.reserve(32); }

  const LoopTableEntry &top() const { return contents.back(); }

  LoopTableEntry &non_const_top() { return contents.back(); }

  const LoopTableEntry &first() const { return contents[0]; }

  const LoopTableEntry &topMinusN(const std::size_t n) const { return contents[contents.size() - 1 - n]; }

  void pop() { contents.pop_back(); }

  bool empty() const { return contents.empty(); }

  bool is_single_exit(const std::int32_t loopID) const {
    if (empty())
      return true;

    if (top().loopID != loopID)
      return true;

    return false;
  }

  void correct_func_level(const std::int32_t func_level) {
    if (top().funcLevel != func_level) {
#ifdef DP_DEBUG
      std::cout << "WARNING: changing funcLevel of Loop " << top().loopID << " from " << top().funcLevel << " to "
                << func_level << std::endl;
#endif
      contents.back().funcLevel = func_level;
    }
  }

  void push(const LoopTableEntry newElement) { contents.push_back(newElement); }

  std::size_t size() const { return contents.size(); }

  LID update_lid(const LID old_lid) const {
    auto lid = old_lid;

    if (empty()) {
      return lid | (((LID)0xFF) << 56);
    }

    // store loop iteration metadata (last 8 bits for loop id, 1 bit to mark
    // loop iteration count as valid, last 7 bits for loop iteration) last 8
    // bits are sufficient, since metadata is only used to check for different
    // iterations, not exact values. first 32 bits of lid are reserved for
    // metadata and thus empty

    if (size() > 0) {
      lid = lid | (((LID)(first().loopID & 0xFF)) << 56);    // add masked loop id
      lid = lid | (((LID)(top().get_count() & 0x7F)) << 48); // add masked loop count
      lid = lid | (LID)0x0080000000000000;                   // mark loop count valid
    }

    if (size() > 1) {
      lid = lid | (((LID)(topMinusN(1).get_count() & 0x7F)) << 40); // add masked loop count
      lid = lid | (LID)0x0000800000000000;                          // mark loop count valid
    }

    if (size() > 2) {
      lid = lid | (((LID)(topMinusN(2).get_count() & 0x7F)) << 32); // add masked loop count
      lid = lid | (LID)0x0000008000000000;                          // mark loop count valid
    }

    return lid;
  }

  void increment_top_count() { contents.back().increment_count(); }

  void debug_output() const {
#ifdef DP_DEBUG
    if (empty())
      std::cout << "Loop Stack is empty." << endl;
    else {
      std::cout << "TOP: (" << std::dec << top().funcLevel << ")";
      std::cout << "Loop " << top().loopID << "." << std::endl;
    }
#endif
  }

private:
  std::vector<LoopTableEntry> contents;
};

} // namespace __dp
