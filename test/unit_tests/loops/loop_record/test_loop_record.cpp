#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopRecord.hpp"

// Tests for old version (i.e., capturing functionality)

class LoopRecordTest : public ::testing::Test {};

TEST_F(LoopRecordTest, testInitialization) {
  const auto lr = __dp::LoopRecord{1, 2, 3};

  ASSERT_EQ(lr.end, 1);
  ASSERT_EQ(lr.total, 2);
  ASSERT_EQ(lr.nEntered, 3);
  ASSERT_EQ(lr.maxIterationCount, 0);
}

TEST_F(LoopRecordTest, testNegativeInitialization) {
  const auto lr = __dp::LoopRecord{-1, -2, -3};

  ASSERT_EQ(lr.end, -1);
  ASSERT_EQ(lr.total, -2);
  ASSERT_EQ(lr.nEntered, -3);
  ASSERT_EQ(lr.maxIterationCount, 0);
}

TEST_F(LoopRecordTest, testLongInitialization) {
  const auto lr = __dp::LoopRecord{4'000'000'000LL, 1'000'000'000LL, 2'000'000'000LL};

  ASSERT_EQ(lr.end, 4'000'000'000LL);
  ASSERT_EQ(lr.total, 1'000'000'000LL);
  ASSERT_EQ(lr.nEntered, 2'000'000'000LL);
  ASSERT_EQ(lr.maxIterationCount, 0);
}

TEST_F(LoopRecordTest, testLongNegativeInitialization) {
  const auto lr = __dp::LoopRecord{-4'000'000'000LL, -1'000'000'000LL, -2'000'000'000LL};

  ASSERT_EQ(lr.end, -4'000'000'000LL);
  ASSERT_EQ(lr.total, -1'000'000'000LL);
  ASSERT_EQ(lr.nEntered, -2'000'000'000LL);
  ASSERT_EQ(lr.maxIterationCount, 0);
}

TEST_F(LoopRecordTest, testEquality) {
  const auto lr1 = __dp::LoopRecord{1, 2, 3};
  const auto lr2 = __dp::LoopRecord{1, 2, 3};
  const auto lr3 = __dp::LoopRecord{1, 2, 4};
  const auto lr4 = __dp::LoopRecord{1, 3, 3};
  const auto lr5 = __dp::LoopRecord{2, 2, 3};

  ASSERT_EQ(lr1, lr1);

  ASSERT_EQ(lr1, lr2);
  ASSERT_NE(lr1, lr3);
  ASSERT_NE(lr1, lr4);
  ASSERT_NE(lr1, lr5);

  ASSERT_EQ(lr2, lr1);
  ASSERT_NE(lr3, lr1);
  ASSERT_NE(lr4, lr1);
  ASSERT_NE(lr5, lr1);
}
