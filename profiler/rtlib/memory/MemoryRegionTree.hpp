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

#include "../DPUtils.hpp"

#define get_char_at_level(addr, level) ((((addr) << ((level) * 4)) >> 60) & 0x000000000000000F)

inline ADDR get_level_shifting_mask(int level) {
  switch (level) {
  case 0:
    return 0xF000000000000000;
  case 1:
    return 0x0F00000000000000;
  case 2:
    return 0x00F0000000000000;
  case 3:
    return 0x000F000000000000;
  case 4:
    return 0x0000F00000000000;
  case 5:
    return 0x00000F0000000000;
  case 6:
    return 0x000000F000000000;
  case 7:
    return 0x0000000F00000000;
  case 8:
    return 0x00000000F0000000;
  case 9:
    return 0x000000000F000000;
  case 10:
    return 0x0000000000F00000;
  case 11:
    return 0x00000000000F0000;
  case 12:
    return 0x000000000000F000;
  case 13:
    return 0x0000000000000F00;
  case 14:
    return 0x00000000000000F0;
  case 15:
    return 0x000000000000000F;
  default:
    return 0xFFFFFFFFFFFFFFFF;
  }
}

inline int get_shift(int level) {
  switch (level) {
  case 0:
    return 60;
  case 1:
    return 56;
  case 2:
    return 52;
  case 3:
    return 48;
  case 4:
    return 44;
  case 5:
    return 40;
  case 6:
    return 36;
  case 7:
    return 32;
  case 8:
    return 28;
  case 9:
    return 24;
  case 10:
    return 20;
  case 11:
    return 16;
  case 12:
    return 12;
  case 13:
    return 8;
  case 14:
    return 4;
  case 15:
    return 0;
  default:
    return -1;
  }
}

namespace __dp {

class MRTNode {
public:
  MRTNode(const ADDR first_addr, const ADDR last_addr, const short level)
      : first_addr(first_addr), last_addr(last_addr), level(level) {}

  ADDR get_first_addr() const noexcept { return first_addr; }

  ADDR get_last_addr() const noexcept { return last_addr; }

  void set_memory_region_id(const unsigned int memory_region_id) noexcept { this->memory_region_id = memory_region_id; }

  unsigned int get_memory_region_id() const noexcept { return memory_region_id; }

  short get_level() const noexcept { return level; }

  const std::array<MRTNode *, 16> &get_children() const noexcept { return children; }

  void delete_child(const unsigned int index) {
    delete children[index];
    children[index] = nullptr;
  }

  MRTNode *get_child(const unsigned int index) const noexcept { return children[index]; }

  int get_child_index(const ADDR addr) const noexcept {
    if (addr < first_addr || addr > last_addr) {
      return -1;
    }

    const auto shift = get_shift(level);
    const auto mask = get_level_shifting_mask(level);
    const auto index = (addr & mask) >> shift;

    return index;
  }

  void add_child(const unsigned int index) {
    assert(children[index] == nullptr && "Child already exists");

    const auto shift = get_shift(level);

    const auto child_start = first_addr | (static_cast<ADDR>(index) << shift);
    const auto child_end = child_start | ((1ULL << shift) - 1ULL);

    children[index] = new MRTNode(child_start, child_end, level + 1);
  }

private:
  ADDR first_addr = 0x0000000000000000;
  ADDR last_addr = 0x7FFFFFFFFFFFFFFF;

  unsigned int memory_region_id = 0U;
  unsigned short level = 65535;

  std::array<MRTNode *, 16> children = {};
};

class MemoryRegionTree {
public:
  MemoryRegionTree() { root = new MRTNode(0x0000000000000000, 0x7FFFFFFFFFFFFFFF, 0); }

  MemoryRegionTree(const MemoryRegionTree &) = delete;
  MemoryRegionTree &operator=(const MemoryRegionTree &) = delete;

  MemoryRegionTree(MemoryRegionTree &&other) noexcept {
    root = other.root;
    other.root = nullptr;
  }

  MemoryRegionTree &operator=(MemoryRegionTree &&other) noexcept {
    auto *temp = root;
    root = other.root;
    other.root = temp;
    return *this;
  }

  ~MemoryRegionTree() {
    delete_nodes(root);
    delete root;
  }

  MRTNode *get_root() noexcept { return root; }

  const MRTNode *get_root() const noexcept { return root; }

  void allocate_region(const ADDR start, const ADDR end, const unsigned int memory_region_id) {
    assert(start <= end && "Invalid memory region");
    assert(memory_region_id != 0 && "Invalid memory region id");
    allocate(start, end, memory_region_id, root);
  }

  unsigned int get_memory_region_id(const ADDR addr) {
    auto *node = root;

    while (true) {
      if (node->get_memory_region_id() != 0) {
        if (addr >= node->get_first_addr() && addr <= node->get_last_addr()) {
          return node->get_memory_region_id();
        }

        return 0xFFFF'FFFFU;
      }

      const auto index = node->get_child_index(addr);
      if (index == -1) {
        return 0xFFFF'FFFFU;
      }

      const auto child = node->get_child(index);
      if (child == nullptr) {
        return 0xFFFF'FFFFU;
      }

      node = child;
    }

    return 0xFFFF'FFFFU;
  }

  std::string get_memory_region_id_string(const ADDR addr, const char *fallback) {
    const auto memory_region_id = get_memory_region_id(addr);
    if (memory_region_id == 0xFFFF'FFFFU) {
      return fallback;
    }

    return std::to_string(memory_region_id);
  }

  void free_region(const ADDR start) {
    // NOTE: Given an allocation [start, end], this function can also handle
    // free(x) for x in (start, end]. Not sure if this functionality is
    // required.

    const auto memory_region_id = get_memory_region_id(start);
    if (memory_region_id == 0xFFFF'FFFFU) {
      return;
    }

    // This actually searches the whole tree again, but it's fine for now
    const auto clean_root = free(start, memory_region_id, root);

    // We never delete the root node
  }

private:
  static void allocate(const ADDR start, const ADDR end, const unsigned int memory_region_id, MRTNode *node) {
    assert(node != nullptr && "Node is null");
    assert(start >= node->get_first_addr() && end <= node->get_last_addr() && "Invalid memory region for node");

    if (start == node->get_first_addr() && end == node->get_last_addr()) {
      // This assert is valid once dp_delete is implemented
      // assert(node->get_memory_region_id() == 0 && "Memory region already
      // allocated");
      node->set_memory_region_id(memory_region_id);

      return;
    }

    const auto child_start_index = node->get_child_index(start);
    const auto child_end_index = node->get_child_index(end);

    for (auto index = child_start_index; index <= child_end_index; ++index) {
      if (node->get_child(index) == nullptr) {
        node->add_child(index);
      }

      auto *child = node->get_child(index);

      const auto child_start = child->get_first_addr();
      const auto child_end = child->get_last_addr();

      const auto clamped_start = std::max(start, child_start);
      const auto clamped_end = std::min(end, child_end);

      allocate(clamped_start, clamped_end, memory_region_id, child);
    }
  }

  static bool free(const ADDR start, const unsigned int memory_region_id, MRTNode *node) {
    assert(node != nullptr && "Node is null");

    const auto memory_region_id_node = node->get_memory_region_id();
    if (memory_region_id_node == memory_region_id) {
      // node is a leaf with the correct id -> free it
      node->set_memory_region_id(0);

      return true;
    }

    if (memory_region_id_node != 0) {
      // node is a leaf with a different id -> Overstepped the allocation
      return false;
    }

    const auto start_index = node->get_child_index(start);
    if (start_index == -1) {
      // start is not in the node -> Technically a bug?
      return false;
    }

    for (auto index = start_index; index < 16; index++) {
      auto *child = node->get_child(index);
      if (child == nullptr) {
        // We might need to clean node -> no return here
        break;
      }

      const auto belongs_to_allocation = free(start, memory_region_id, child);
      if (!belongs_to_allocation) {
        // We found a child that doesn't belong to the allocation -> We are done
        return false;
      }

      // Child belongs to the allocation -> Free it
      node->delete_child(index);
    }

    for (auto i = 0; i < 16; i++) {
      if (node->get_child(i) != nullptr) {
        // There are still children -> We do not need to clean node
        return false;
      }
    }

    // There are no children left -> Clean node
    return true;
  }

  static void delete_nodes(MRTNode *node) {
    if (node == nullptr) {
      return;
    }

    for (auto i = 0; i < 16; i++) {
      auto *child = node->get_child(i);
      if (child != nullptr) {
        delete_nodes(child);
        delete child;
      }
    }
  }

  MRTNode *root{};
};

} // namespace __dp
