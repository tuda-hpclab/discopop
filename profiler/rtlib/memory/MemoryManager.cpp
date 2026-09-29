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

#include "MemoryManager.hpp"

#include "../runtimeFunctionsGlobals.hpp"

std::string __dp::MemoryManager::allocate_memory(const LID line_id, const ADDR start_address, const ADDR end_address,
                                                 const std::int64_t number_bytes, const std::int64_t number_elements) {
  const auto memory_region_id = get_next_free_memory_region_id();
  const auto memory_region_id_str = std::to_string(memory_region_id);

  allocatedMemRegTree.allocate_region(start_address, end_address, memory_region_id);
  allocatedMemoryRegions.emplace_back(line_id, memory_region_id_str, start_address, end_address, number_bytes,
                                      number_elements);

  if (start_address < smallestAllocatedADDR) {
    smallestAllocatedADDR = start_address;
  }

  if (end_address > largestAllocatedADDR) {
    largestAllocatedADDR = end_address;
  }

  return memory_region_id_str;
}

std::string __dp::MemoryManager::allocate_stack_memory(const LID line_id, const ADDR start_address,
                                                       const ADDR end_address, const std::int64_t number_bytes,
                                                       const std::int64_t number_elements) {
  const auto memory_region_id = get_next_free_memory_region_id();
  const auto memory_region_id_str = std::to_string(memory_region_id);

  allocatedMemRegTree.allocate_region(start_address, end_address, memory_region_id);
  allocatedMemoryRegions.emplace_back(line_id, memory_region_id_str, start_address, end_address, number_bytes,
                                      number_elements);

  if (start_address < smallestAllocatedADDR) {
    smallestAllocatedADDR = start_address;
  }

  if (end_address > largestAllocatedADDR) {
    largestAllocatedADDR = end_address;
  }

  if (number_elements >= 0) {
    assert(start_address <= end_address && "start_address <= end_address is violated!");
    // update stack base address, if not already set
    update_stack_addresses(start_address, end_address);
  }

  return memory_region_id_str;
}
