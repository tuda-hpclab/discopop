#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/MemoryRegionTree.hpp"

#include <cstdint>
#include <vector>

class MemoryRegionTreeTest : public ::testing::Test {};

TEST_F(MemoryRegionTreeTest, testConstructor) {
  const auto tree = __dp::MemoryRegionTree{};

  const auto *root = tree.get_root();

  ASSERT_EQ(root->get_first_addr(), 0x0000000000000000LL);
  ASSERT_EQ(root->get_last_addr(), 0x7FFFFFFFFFFFFFFFLL);
  ASSERT_EQ(root->get_memory_region_id(), 0);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion1) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x7FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1234;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), memory_region_id);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion2) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x0FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x2345;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 1; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }

  auto child = root->get_child(0);

  ASSERT_EQ(child->get_memory_region_id(), memory_region_id);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(child->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion3) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x1000000000000000LL;
  const auto end_addr = 0x3FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x2345;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_child(0), nullptr);
  ASSERT_NE(root->get_child(1), nullptr);
  ASSERT_NE(root->get_child(2), nullptr);
  ASSERT_NE(root->get_child(3), nullptr);
  ASSERT_EQ(root->get_child(4), nullptr);
  ASSERT_EQ(root->get_child(5), nullptr);
  ASSERT_EQ(root->get_child(6), nullptr);
  ASSERT_EQ(root->get_child(7), nullptr);
  ASSERT_EQ(root->get_child(8), nullptr);
  ASSERT_EQ(root->get_child(9), nullptr);
  ASSERT_EQ(root->get_child(10), nullptr);
  ASSERT_EQ(root->get_child(11), nullptr);
  ASSERT_EQ(root->get_child(12), nullptr);
  ASSERT_EQ(root->get_child(13), nullptr);
  ASSERT_EQ(root->get_child(14), nullptr);
  ASSERT_EQ(root->get_child(15), nullptr);

  auto *child1 = root->get_child(1);
  auto *child2 = root->get_child(2);
  auto *child3 = root->get_child(3);

  ASSERT_EQ(child1->get_memory_region_id(), memory_region_id);
  ASSERT_EQ(child2->get_memory_region_id(), memory_region_id);
  ASSERT_EQ(child3->get_memory_region_id(), memory_region_id);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(child1->get_child(i), nullptr);
    ASSERT_EQ(child2->get_child(i), nullptr);
    ASSERT_EQ(child3->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion4) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x1000000000000000LL;
  const auto end_addr = 0x2CFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1111;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_child(0), nullptr);
  ASSERT_NE(root->get_child(1), nullptr);
  ASSERT_NE(root->get_child(2), nullptr);
  ASSERT_EQ(root->get_child(3), nullptr);
  ASSERT_EQ(root->get_child(4), nullptr);
  ASSERT_EQ(root->get_child(5), nullptr);
  ASSERT_EQ(root->get_child(6), nullptr);
  ASSERT_EQ(root->get_child(7), nullptr);
  ASSERT_EQ(root->get_child(8), nullptr);
  ASSERT_EQ(root->get_child(9), nullptr);
  ASSERT_EQ(root->get_child(10), nullptr);
  ASSERT_EQ(root->get_child(11), nullptr);
  ASSERT_EQ(root->get_child(12), nullptr);
  ASSERT_EQ(root->get_child(13), nullptr);
  ASSERT_EQ(root->get_child(14), nullptr);
  ASSERT_EQ(root->get_child(15), nullptr);

  auto *child1 = root->get_child(1);
  auto *child2 = root->get_child(2);

  ASSERT_EQ(child1->get_memory_region_id(), memory_region_id);
  ASSERT_EQ(child2->get_memory_region_id(), 0);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(child1->get_child(i), nullptr);
  }

  for (auto i = 0; i < 13; i++) {
    ASSERT_NE(child2->get_child(i), nullptr);
    for (auto *gc : child2->get_child(i)->get_children()) {
      ASSERT_EQ(gc, nullptr);
    }

    ASSERT_EQ(child2->get_child(i)->get_memory_region_id(), memory_region_id);
  }

  for (auto i = 13; i < 16; i++) {
    ASSERT_EQ(child2->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion5) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x13542698001FAB52LL;
  const auto end_addr = 0x13542698001FAB52LL;
  const auto memory_region_id = 0x1111;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  auto *node = tree.get_root();

  while (true) {
    const auto node_start = node->get_first_addr();
    const auto node_end = node->get_last_addr();

    if (node_start == start_addr && node_end == end_addr) {
      ASSERT_EQ(node->get_memory_region_id(), memory_region_id);
      ASSERT_EQ(node_start, start_addr);
      ASSERT_EQ(node_end, end_addr);

      for (auto i = 0; i < 16; i++) {
        ASSERT_EQ(node->get_child(i), nullptr);
      }
      break;
    }

    auto counter = 0;
    __dp::MRTNode *new_node = nullptr;

    for (auto i = 0; i < 16; i++) {
      auto *child = node->get_child(i);
      if (child != nullptr) {
        new_node = child;
        counter++;
      }
    }

    node = new_node;

    ASSERT_EQ(counter, 1);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion6) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5000000000000000LL;
  const auto end_addr_2 = 0x5FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_child(0), nullptr);
  ASSERT_NE(root->get_child(1), nullptr);
  ASSERT_EQ(root->get_child(2), nullptr);
  ASSERT_EQ(root->get_child(3), nullptr);
  ASSERT_EQ(root->get_child(4), nullptr);
  ASSERT_NE(root->get_child(5), nullptr);
  ASSERT_EQ(root->get_child(6), nullptr);
  ASSERT_EQ(root->get_child(7), nullptr);
  ASSERT_EQ(root->get_child(8), nullptr);
  ASSERT_EQ(root->get_child(9), nullptr);
  ASSERT_EQ(root->get_child(10), nullptr);
  ASSERT_EQ(root->get_child(11), nullptr);
  ASSERT_EQ(root->get_child(12), nullptr);
  ASSERT_EQ(root->get_child(13), nullptr);
  ASSERT_EQ(root->get_child(14), nullptr);
  ASSERT_EQ(root->get_child(15), nullptr);

  auto *child1 = root->get_child(1);
  auto *child5 = root->get_child(5);

  ASSERT_EQ(child1->get_memory_region_id(), memory_region_id_1);
  ASSERT_EQ(child5->get_memory_region_id(), memory_region_id_2);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(child1->get_child(i), nullptr);
    ASSERT_EQ(child5->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testAllocateRegion7) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5300000000000000LL;
  const auto end_addr_2 = 0x53FFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_child(0), nullptr);
  ASSERT_NE(root->get_child(1), nullptr);
  ASSERT_EQ(root->get_child(2), nullptr);
  ASSERT_EQ(root->get_child(3), nullptr);
  ASSERT_EQ(root->get_child(4), nullptr);
  ASSERT_NE(root->get_child(5), nullptr);
  ASSERT_EQ(root->get_child(6), nullptr);
  ASSERT_EQ(root->get_child(7), nullptr);
  ASSERT_EQ(root->get_child(8), nullptr);
  ASSERT_EQ(root->get_child(9), nullptr);
  ASSERT_EQ(root->get_child(10), nullptr);
  ASSERT_EQ(root->get_child(11), nullptr);
  ASSERT_EQ(root->get_child(12), nullptr);
  ASSERT_EQ(root->get_child(13), nullptr);
  ASSERT_EQ(root->get_child(14), nullptr);
  ASSERT_EQ(root->get_child(15), nullptr);

  auto *child1 = root->get_child(1);
  ASSERT_EQ(child1->get_memory_region_id(), memory_region_id_1);

  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(child1->get_child(i), nullptr);
  }

  auto *child5 = root->get_child(5);
  ASSERT_EQ(child5->get_memory_region_id(), 0);

  for (auto i = 0; i < 16; i++) {
    if (i == 3) {
      ASSERT_NE(child5->get_child(i), nullptr);
      ASSERT_EQ(child5->get_child(i)->get_memory_region_id(), memory_region_id_2);

      for (auto j = 0; j < 16; j++) {
        ASSERT_EQ(child5->get_child(i)->get_child(j), nullptr);
      }
    } else {
      ASSERT_EQ(child5->get_child(i), nullptr);
    }
  }
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionId1) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x7FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1234;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  ASSERT_EQ(tree.get_memory_region_id(0x0000000000000000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x7FFFFFFFFFFFFFFFLL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x5687140000000000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x3FF0000000000000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x1000000000000000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x5000000000000000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x4FFFFFFFFFFFFFFFLL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x622516846acd64b6LL), memory_region_id);
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionId2) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x7FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1234;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  ASSERT_EQ(tree.get_memory_region_id(0x8000000000000000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xFFFFFFFFFFFFFFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xA687140000000000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xCFF0000000000000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x9000000000000000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xE000000000000000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xDFFFFFFFFFFFFFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0xF22516846acd64b6LL), 0xFFFF'FFFFU);
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionId3) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x1000'0000'0000'0000LL;
  const auto end_addr = 0x2000'0000'0000'0000LL;
  const auto memory_region_id = 12;

  tree.allocate_region(start_addr, end_addr, 12);

  ASSERT_EQ(tree.get_memory_region_id(0x0000'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1000'0000'0000'0000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x5687'1400'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x3FF0'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1242'0000'0000'0000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x2000'0000'0000'0000LL), memory_region_id);
  ASSERT_EQ(tree.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x8225'1684'6ac4'd4b6LL), 0xFFFF'FFFFU);
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionId4) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x2000000000000000LL;
  const auto end_addr_2 = 0x2FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  ASSERT_EQ(tree.get_memory_region_id(0x0000'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1000'0000'0000'0000LL), memory_region_id_1);
  ASSERT_EQ(tree.get_memory_region_id(0x5687'1400'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x3FF0'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1242'0000'0000'0000LL), memory_region_id_1);
  ASSERT_EQ(tree.get_memory_region_id(0x2000'0000'0000'0000LL), memory_region_id_2);
  ASSERT_EQ(tree.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x2225'1684'6ac4'd4b6LL), memory_region_id_2);
  ASSERT_EQ(tree.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL), memory_region_id_2);
  ASSERT_EQ(tree.get_memory_region_id(0x3000'0000'0000'0000LL), 0xFFFF'FFFFU);
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionId5) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5300000000000000LL;
  const auto end_addr_2 = 0x53FFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  ASSERT_EQ(tree.get_memory_region_id(0x0000'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1000'0000'0000'0000LL), memory_region_id_1);
  ASSERT_EQ(tree.get_memory_region_id(0x5687'1400'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x3FF0'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x1242'0000'0000'0000LL), memory_region_id_1);
  ASSERT_EQ(tree.get_memory_region_id(0x2000'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x2225'1684'6ac4'd4b6LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x3000'0000'0000'0000LL), 0xFFFF'FFFFU);
  ASSERT_EQ(tree.get_memory_region_id(0x5300'0000'0000'0000LL), memory_region_id_2);
  ASSERT_EQ(tree.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL), memory_region_id_2);
  ASSERT_EQ(tree.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL), memory_region_id_2);
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionIdStr1) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x7FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1234;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  ASSERT_EQ(tree.get_memory_region_id_string(0x0000000000000000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x7FFFFFFFFFFFFFFFLL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5687140000000000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3FF0000000000000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1000000000000000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5000000000000000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x4FFFFFFFFFFFFFFFLL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x622516846acd64b6LL, "fallback"), std::to_string(memory_region_id));
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionIdStr2) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;
  const auto end_addr = 0x7FFFFFFFFFFFFFFFLL;
  const auto memory_region_id = 0x1234;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  ASSERT_EQ(tree.get_memory_region_id_string(0x8000000000000000LL, "fallback1"), std::string("fallback1"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xFFFFFFFFFFFFFFFFLL, "fallback2"), std::string("fallback2"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xA687140000000000LL, "fallback3"), std::string("fallback3"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xCFF0000000000000LL, "fallback4"), std::string("fallback4"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x9000000000000000LL, "fallback5"), std::string("fallback5"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xE000000000000000LL, "fallback6"), std::string("fallback6"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xDFFFFFFFFFFFFFFFLL, "fallback7"), std::string("fallback7"));
  ASSERT_EQ(tree.get_memory_region_id_string(0xF22516846acd64b6LL, "fallback8"), std::string("fallback8"));
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionIdStr3) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x1000'0000'0000'0000LL;
  const auto end_addr = 0x2000'0000'0000'0000LL;
  const auto memory_region_id = 12;

  tree.allocate_region(start_addr, end_addr, 12);

  ASSERT_EQ(tree.get_memory_region_id_string(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1000'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1242'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2000'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id));
  ASSERT_EQ(tree.get_memory_region_id_string(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x8225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionIdStr4) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x2000000000000000LL;
  const auto end_addr_2 = 0x2FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  ASSERT_EQ(tree.get_memory_region_id_string(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1000'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_1));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1242'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_1));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2000'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_2));
  ASSERT_EQ(tree.get_memory_region_id_string(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2225'1684'6ac4'd4b6LL, "fallback"), std::to_string(memory_region_id_2));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::to_string(memory_region_id_2));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3000'0000'0000'0000LL, "fallback"), std::string("fallback"));
}

TEST_F(MemoryRegionTreeTest, testGetMemoryRegionIdStr5) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5300000000000000LL;
  const auto end_addr_2 = 0x53FFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  ASSERT_EQ(tree.get_memory_region_id_string(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1000'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_1));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x1242'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_1));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x3000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(tree.get_memory_region_id_string(0x5300'0000'0000'0000LL, "fallback"), std::to_string(memory_region_id_2));
  ASSERT_EQ(tree.get_memory_region_id_string(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::to_string(memory_region_id_2));
  ASSERT_EQ(tree.get_memory_region_id_string(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::to_string(memory_region_id_2));
}

TEST_F(MemoryRegionTreeTest, testFreeRegion1) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000000000000000LL;

  tree.free_region(start_addr);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion2) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x7FFFFFFFFFFFFFFFLL;

  tree.free_region(start_addr);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion3) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x9472dcab36975afaLL;

  tree.free_region(start_addr);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion4) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x1000'0000'0000'0000LL;
  const auto end_addr = 0x1FFF'FFFF'FFFF'FFFFLL;
  const auto memory_region_id = 0x1111;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  tree.free_region(start_addr);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion5) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr = 0x0000'0000'0000'0000LL;
  const auto end_addr = 0x7FFF'FFFF'FFFF'FFFFLL;
  const auto memory_region_id = 0x1111;

  tree.allocate_region(start_addr, end_addr, memory_region_id);

  tree.free_region(start_addr);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion6) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5300000000000000LL;
  const auto end_addr_2 = 0x53FFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  tree.free_region(start_addr_1);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_child(0), nullptr);
  ASSERT_EQ(root->get_child(1), nullptr);
  ASSERT_EQ(root->get_child(2), nullptr);
  ASSERT_EQ(root->get_child(3), nullptr);
  ASSERT_EQ(root->get_child(4), nullptr);
  ASSERT_NE(root->get_child(5), nullptr);
  ASSERT_EQ(root->get_child(6), nullptr);
  ASSERT_EQ(root->get_child(7), nullptr);
  ASSERT_EQ(root->get_child(8), nullptr);
  ASSERT_EQ(root->get_child(9), nullptr);
  ASSERT_EQ(root->get_child(10), nullptr);
  ASSERT_EQ(root->get_child(11), nullptr);
  ASSERT_EQ(root->get_child(12), nullptr);
  ASSERT_EQ(root->get_child(13), nullptr);
  ASSERT_EQ(root->get_child(14), nullptr);
  ASSERT_EQ(root->get_child(15), nullptr);

  auto *child5 = root->get_child(5);
  ASSERT_EQ(child5->get_memory_region_id(), 0);

  for (auto i = 0; i < 16; i++) {
    if (i == 3) {
      ASSERT_NE(child5->get_child(i), nullptr);
      ASSERT_EQ(child5->get_child(i)->get_memory_region_id(), memory_region_id_2);

      for (auto j = 0; j < 16; j++) {
        ASSERT_EQ(child5->get_child(i)->get_child(j), nullptr);
      }
    } else {
      ASSERT_EQ(child5->get_child(i), nullptr);
    }
  }
}

TEST_F(MemoryRegionTreeTest, testFreeRegion7) {
  auto tree = __dp::MemoryRegionTree{};

  const auto start_addr_1 = 0x1000000000000000LL;
  const auto end_addr_1 = 0x1FFFFFFFFFFFFFFFLL;
  const auto memory_region_id_1 = 0x1111;

  const auto start_addr_2 = 0x5300000000000000LL;
  const auto end_addr_2 = 0x53FFFFFFFFFFFFFFLL;
  const auto memory_region_id_2 = 0x2222;

  tree.allocate_region(start_addr_1, end_addr_1, memory_region_id_1);
  tree.allocate_region(start_addr_2, end_addr_2, memory_region_id_2);

  tree.free_region(start_addr_1);
  tree.free_region(start_addr_2);

  auto *root = tree.get_root();

  ASSERT_EQ(root->get_memory_region_id(), 0);
  for (auto i = 0; i < 16; i++) {
    ASSERT_EQ(root->get_child(i), nullptr);
  }
}
