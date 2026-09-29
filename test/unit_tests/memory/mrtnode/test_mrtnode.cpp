#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/MemoryRegionTree.hpp"

#include <cstdint>
#include <vector>

class MRTNodeTest : public ::testing::Test {};

TEST_F(MRTNodeTest, testConstructor) {
  const auto start_addr = 0x1234567890ABCDEFLL;
  const auto end_addr = 0x2234567890ABCDEFLL;
  const auto level = 0x1234;

  const auto node = __dp::MRTNode(start_addr, end_addr, level);

  ASSERT_EQ(node.get_first_addr(), start_addr);
  ASSERT_EQ(node.get_last_addr(), end_addr);
  ASSERT_EQ(node.get_level(), level);
  ASSERT_EQ(node.get_memory_region_id(), 0);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(node.get_child(i), nullptr);
  }

  for (const auto *child : node.get_children()) {
    ASSERT_EQ(child, nullptr);
  }
}

TEST_F(MRTNodeTest, testGetChildIndex) {
  const auto start_addr = 0x1200000000000000LL;
  const auto end_addr = 0x12FFFFFFFFFFFFFFLL;

  const auto level = 2;

  const auto node = __dp::MRTNode(start_addr, end_addr, level);

  const auto base_addr = 0x010000000000000LL;
  for (auto i = 0; i < 16; i++) {
    const auto inquiry_addr = start_addr + (base_addr * i);
    const auto calculated_index = node.get_child_index(inquiry_addr);

    ASSERT_EQ(calculated_index, i);
  }

  ASSERT_EQ(node.get_child_index(start_addr - 1), -1);
  ASSERT_EQ(node.get_child_index(end_addr + 1), -1);
  ASSERT_EQ(node.get_child_index(0x1100000000000000LL), -1);
  ASSERT_EQ(node.get_child_index(0x1400000000000000LL), -1);
  ASSERT_EQ(node.get_child_index(0x1863453534300000LL), -1);
  ASSERT_EQ(node.get_child_index(0x0000000000000000LL), -1);
  ASSERT_EQ(node.get_child_index(0x1000000000000000LL), -1);
  ASSERT_EQ(node.get_child_index(0x2000000000000000LL), -1);
  ASSERT_EQ(node.get_child_index(0xEFFFFFFFFFFFFFFFLL), -1);
}

TEST_F(MRTNodeTest, testAddChild0) {
  const auto start_addr = 0x1000000000000000LL;
  const auto end_addr = 0x1FFFFFFFFFFFFFFFLL;

  const auto level = 1;

  auto node = __dp::MRTNode(start_addr, end_addr, level);

  node.add_child(0);

  for (auto i = 0; i < 16; i++) {
    if (i == 0) {
      ASSERT_NE(node.get_child(i), nullptr);
      ASSERT_EQ(node.get_child(i)->get_first_addr(), 0x1000000000000000LL)
          << std::hex << node.get_child(i)->get_first_addr();
      ASSERT_EQ(node.get_child(i)->get_last_addr(), 0x10FFFFFFFFFFFFFFLL)
          << std::hex << node.get_child(i)->get_last_addr();
      ASSERT_EQ(node.get_child(i)->get_level(), 2);

      for (auto j = 0; j < 16; j++) {
        ASSERT_EQ(node.get_child(i)->get_child(j), nullptr);
      }
    } else {
      ASSERT_EQ(node.get_child(i), nullptr);
    }
  }
}

TEST_F(MRTNodeTest, testAddChild1) {
  const auto start_addr = 0x2E00000000000000LL;
  const auto end_addr = 0x2EFFFFFFFFFFFFFFLL;

  const auto level = 2;

  auto node = __dp::MRTNode(start_addr, end_addr, level);

  node.add_child(3);

  for (auto i = 0; i < 16; i++) {
    if (i == 3) {
      ASSERT_NE(node.get_child(i), nullptr);
      ASSERT_EQ(node.get_child(i)->get_first_addr(), 0x2E30000000000000LL)
          << std::hex << node.get_child(i)->get_first_addr();
      ASSERT_EQ(node.get_child(i)->get_last_addr(), 0x2E3FFFFFFFFFFFFFLL)
          << std::hex << node.get_child(i)->get_last_addr();
      ASSERT_EQ(node.get_child(i)->get_level(), 3);

      for (auto j = 0; j < 16; j++) {
        ASSERT_EQ(node.get_child(i)->get_child(j), nullptr);
      }
    } else {
      ASSERT_EQ(node.get_child(i), nullptr);
    }
  }
}

TEST_F(MRTNodeTest, testSetMemoryRegionId) {
  const auto start_addr = 0x1000000000000000LL;
  const auto end_addr = 0x1FFFFFFFFFFFFFFFLL;

  const auto level = 1;

  auto node = __dp::MRTNode(start_addr, end_addr, level);

  const auto memory_region_id = 0x1234;
  node.set_memory_region_id(memory_region_id);

  ASSERT_EQ(node.get_memory_region_id(), memory_region_id);
}
