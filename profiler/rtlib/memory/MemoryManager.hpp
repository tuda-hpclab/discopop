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
#include "../DPUtils.hpp"

#include "MemoryRegionTree.hpp"
#include "Scope.hpp"

#include <cstdint>
#include <limits>
#include <ostream>
#include <stack>
#include <utility>

namespace __dp {

class MemoryManager {
public:
  MemoryManager() {
    nextFreeMemoryRegionId = 1;

    smallestAllocatedADDR = std::numeric_limits<ADDR>::max();
    largestAllocatedADDR = std::numeric_limits<ADDR>::min();
  }

  MemoryManager(const MemoryManager &other) = delete;
  MemoryManager(MemoryManager &&other) = delete;

  MemoryManager &operator=(const MemoryManager &other) = delete;
  MemoryManager &operator=(MemoryManager &&other) = delete;

  std::int64_t get_next_free_memory_region_id() noexcept {
    const auto old_value = nextFreeMemoryRegionId;
    nextFreeMemoryRegionId++;
    return old_value;
  }

  void enter_new_function() { stackAddrs.emplace(0, 0); }

  void update_stack_addresses(const ADDR start, const ADDR end) {
    auto &top = stackAddrs.top();
    if (top.first == 0) {
      top.first = start;
    } else if (top.first > start) {
      top.first = start;
    }

    if (top.second == 0) {
      top.second = end;
    } else if (top.second < end) {
      top.second = end;
    }
  }

  std::pair<ADDR, ADDR> pop_last_stack_address() {
    const auto val = stackAddrs.top();
    stackAddrs.pop();
    return val;
  }

  bool is_stack_access(const ADDR address) noexcept {
    if (stackAddrs.empty()) {
      return false;
    }

    const auto &addrs = stackAddrs.top();
    if (addrs.first == 0 || addrs.second == 0) {
      return false;
    }

    return addrs.first <= address && address <= addrs.second;
    // return address <= addrs.first && addrs.second <= address;
  }

  void enterScope(std::string type, const LID debug_lid) { scopeManager.enterScope(type.c_str(), debug_lid); }

  void leaveScope(std::string type, const LID debug_lid) { scopeManager.leaveScope(type.c_str(), debug_lid); }

  void registerStackRead(const ADDR address, const LID debug_lid, const char *debug_var) {
    scopeManager.registerStackRead(address, debug_lid, debug_var);
  }

  void registerStackWrite(const ADDR address, const LID debug_lid, const char *debug_var) {
    scopeManager.registerStackWrite(address, debug_lid, debug_var);
  }

  bool isFirstWrittenInScope(const ADDR addr, const bool currentAccessIsWrite) {
    return scopeManager.isOwnedByScope(addr, currentAccessIsWrite);
  }

  bool positiveScopeChangeOccuredSinceLastAccess(const ADDR addr) {
    return scopeManager.positiveScopeChangeOccuredSinceLastAccess(addr);
  }

  const Scope &getCurrentScope() { return scopeManager.getCurrentScope(); }

  std::size_t number_open_scopes() const noexcept { return scopeManager.number_open_scopes(); }

  std::string get_memory_region_id(const ADDR addr, std::string fallback) {
    return allocatedMemRegTree.get_memory_region_id_string(addr, fallback.c_str());
  }

  std::string allocate_memory(const LID line_id, const ADDR start_address, const ADDR end_address,
                              const std::int64_t number_bytes, const std::int64_t number_elements);

  std::string allocate_stack_memory(const LID line_id, const ADDR start_address, const ADDR end_address,
                                    const std::int64_t number_bytes, const std::int64_t number_elements);

  void allocate_dummy_region() { allocatedMemoryRegions.emplace_back(0, std::string("%%dummy%%"), 0, 0, 0, 0); }

  std::size_t get_number_allocations() { return allocatedMemoryRegions.size(); }

  const std::vector<std::tuple<LID, std::string, std::int64_t, std::int64_t, std::int64_t, std::int64_t>> &
  get_allocated_memory_regions() {
    return allocatedMemoryRegions;
  }

  void output_memory_regions(std::ostream &stream) {
    for (const auto &memoryRegion : allocatedMemoryRegions) {
      const auto lid = get<0>(memoryRegion);
      const auto &id = get<1>(memoryRegion);
      const auto num_bytes = get<4>(memoryRegion);

      dputil::decodeLID(lid, stream);
      stream << ' ' << id << ' ' << num_bytes << endl;
    }
  }

  ADDR get_smallest_allocated_addr() const noexcept { return smallestAllocatedADDR; }

  ADDR get_largest_allocated_addr() const noexcept { return largestAllocatedADDR; }

private:
  std::int64_t nextFreeMemoryRegionId; // 0 is reserved as the identifier for
                                       // "no region" in the MemoryRegionTree

  ADDR smallestAllocatedADDR;
  ADDR largestAllocatedADDR;

  std::stack<std::pair<ADDR, ADDR>> stackAddrs; // track stack adresses for entered functions

  ScopeManager scopeManager;

  MemoryRegionTree allocatedMemRegTree;

  // (LID, identifier, startAddr, endAddr, numBytes, numElements)
  std::vector<std::tuple<LID, std::string, std::int64_t, std::int64_t, std::int64_t, std::int64_t>>
      allocatedMemoryRegions;
};

} // namespace __dp
