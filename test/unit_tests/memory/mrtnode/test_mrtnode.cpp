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

  node.delete_child(0);
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

  node.delete_child(3);
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

TEST_F(MRTNodeTest, testDeleteChild) {
  const auto start_addr = 0x1000000000000000LL;
  const auto end_addr = 0x1FFFFFFFFFFFFFFFLL;

  auto node = __dp::MRTNode(start_addr, end_addr, 1);

  node.add_child(0);
  node.add_child(3);

  node.delete_child(0);

  ASSERT_EQ(node.get_child(0), nullptr);
  ASSERT_NE(node.get_child(3), nullptr);

  // a node does not free its children, so the tree has to reach every one of them
  node.delete_child(3);
  ASSERT_EQ(node.get_child(3), nullptr);

  // and deleting an empty slot is a no-op rather than a double free
  node.delete_child(3);
  ASSERT_EQ(node.get_child(3), nullptr);
}

TEST_F(MRTNodeTest, testAddChildAfterDeletingIt) {
  auto node = __dp::MRTNode(0x1000000000000000LL, 0x1FFFFFFFFFFFFFFFLL, 1);

  node.add_child(5);
  node.delete_child(5);

  // add_child asserts on an occupied slot, so it is only legal again once the slot was cleared
  node.add_child(5);
  ASSERT_NE(node.get_child(5), nullptr);
  ASSERT_EQ(node.get_child(5)->get_first_addr(), 0x1500000000000000LL);
  ASSERT_EQ(node.get_child(5)->get_last_addr(), 0x15FFFFFFFFFFFFFFLL);

  node.delete_child(5);
}

TEST_F(MRTNodeTest, testTheLevelHelpersSelectOneNibbleEach) {
  for (auto level = 0; level < 16; ++level) {
    const auto mask = get_level_shifting_mask(level);
    const auto shift = get_shift(level);

    ASSERT_EQ(shift, 60 - level * 4) << level;

    // every level masks out exactly the nibble its shift brings down to the bottom
    ASSERT_EQ((mask >> shift) & 0xF, 0xF) << level;
    ASSERT_EQ(mask & ~(static_cast<ADDR>(0xF) << shift), 0) << level;
  }
}

TEST_F(MRTNodeTest, testTheLevelHelpersFallBackOutsideTheAddressWidth) {
  // an address has 16 nibbles, so there is no level 16. Both helpers answer with a sentinel rather
  // than reading past the end of their switch.
  for (const auto level : {-1, 16, 17, 1000}) {
    ASSERT_EQ(get_level_shifting_mask(level), static_cast<ADDR>(0xFFFFFFFFFFFFFFFF)) << level;
    ASSERT_EQ(get_shift(level), -1) << level;
  }
}

TEST_F(MRTNodeTest, testTheNibbleMacroOnlyAgreesWithTheLevelHelpersBelowTheSignBit) {
  // get_char_at_level is a second formulation of the nibble get_child_index reads out of an address
  // through the two level helpers. Nothing in the tree uses it.
  const auto addresses = {0x0LL, 0x1234567890ABCDEFLL, 0x0FEDCBA987654321LL, 0x7FFFFFFFFFFFFFFFLL};

  for (const auto address : addresses) {
    for (auto level = 0; level < 16; ++level) {
      const auto by_macro = get_char_at_level(address, level);
      const auto by_helpers = (address & get_level_shifting_mask(level)) >> get_shift(level);

      ASSERT_EQ(by_macro, by_helpers) << std::hex << address << " @ " << std::dec << level;
    }
  }

  // above it the two part ways: the macro masks the nibble out, while the helpers shift a negative
  // masked address arithmetically and sign extend it. This is why the root of the tree spans
  // [0, 0x7FFFFFFFFFFFFFFF] and no address with the top bit set ever reaches get_child_index.
  const auto negative_address = static_cast<ADDR>(0x8000000000000000ULL);

  ASSERT_EQ(get_char_at_level(negative_address, 0), 8);
  ASSERT_EQ((negative_address & get_level_shifting_mask(0)) >> get_shift(0), -8);
}
