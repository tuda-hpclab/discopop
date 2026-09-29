#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopTableEntry.hpp"

// Tests for old version (i.e., capturing functionality)

class LoopTableEntryTest : public ::testing::Test {};

TEST_F(LoopTableEntryTest, testInitialization) {
  const auto lte = __dp::LoopTableEntry{1, 2, 3, 4};

  ASSERT_EQ(lte.funcLevel, 1);
  ASSERT_EQ(lte.loopID, 2);
  ASSERT_EQ(lte.get_count(), 3);
  ASSERT_EQ(lte.begin, 4);
}

TEST_F(LoopTableEntryTest, testNegativeInitialization) {
  const auto lte = __dp::LoopTableEntry{-1, -2, -3, -4};

  ASSERT_EQ(lte.funcLevel, -1);
  ASSERT_EQ(lte.loopID, -2);
  ASSERT_EQ(lte.get_count(), -3);
  ASSERT_EQ(lte.begin, -4);
}

TEST_F(LoopTableEntryTest, testLongInitialization) {
  const auto lte = __dp::LoopTableEntry{1'000'000'000, 1'500'000'000, 2'000'000'000, 4'000'000'000LL};

  ASSERT_EQ(lte.funcLevel, 1'000'000'000);
  ASSERT_EQ(lte.loopID, 1'500'000'000);
  ASSERT_EQ(lte.get_count(), 2'000'000'000);
  ASSERT_EQ(lte.begin, 4'000'000'000LL);
}

TEST_F(LoopTableEntryTest, testNegativeLongInitialization) {
  const auto lte = __dp::LoopTableEntry{-1'000'000'000, -1'500'000'000, -2'000'000'000, -4'000'000'000LL};

  ASSERT_EQ(lte.funcLevel, -1'000'000'000);
  ASSERT_EQ(lte.loopID, -1'500'000'000);
  ASSERT_EQ(lte.get_count(), -2'000'000'000);
  ASSERT_EQ(lte.begin, -4'000'000'000LL);
}

TEST_F(LoopTableEntryTest, testEquality) {
  const auto lte1 = __dp::LoopTableEntry{1, 2, 3, 4};
  const auto lte2 = __dp::LoopTableEntry{1, 2, 3, 4};
  const auto lte3 = __dp::LoopTableEntry{1, 2, 3, 5};
  const auto lte4 = __dp::LoopTableEntry{1, 2, 4, 4};
  const auto lte5 = __dp::LoopTableEntry{1, 3, 3, 4};
  const auto lte6 = __dp::LoopTableEntry{2, 2, 3, 4};

  ASSERT_EQ(lte1, lte1);

  ASSERT_EQ(lte1, lte2);
  ASSERT_NE(lte1, lte3);
  ASSERT_NE(lte1, lte4);
  ASSERT_NE(lte1, lte5);
  ASSERT_NE(lte1, lte6);

  ASSERT_EQ(lte2, lte1);
  ASSERT_NE(lte3, lte1);
  ASSERT_NE(lte4, lte1);
  ASSERT_NE(lte5, lte1);
  ASSERT_NE(lte6, lte1);
}
