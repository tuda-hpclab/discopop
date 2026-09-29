#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopCounter.hpp"

// Tests for old version (i.e., capturing functionality)

class LoopCounterTest : public ::testing::Test {};

TEST_F(LoopCounterTest, testInit) {
  const auto lc = __dp::LoopCounter{};

  const auto loop_counters = lc.get_loop_counters();
  EXPECT_EQ(loop_counters.size(), 0);
}

TEST_F(LoopCounterTest, testIncreaseLoopCounter) {
  auto lc = __dp::LoopCounter{};

  lc.incr_loop_counter(0);
  lc.incr_loop_counter(1);
  lc.incr_loop_counter(0);

  const auto loop_counters = lc.get_loop_counters();
  EXPECT_EQ(loop_counters.size(), 2);
  EXPECT_EQ(loop_counters[0], 2);
  EXPECT_EQ(loop_counters[1], 1);

  lc.incr_loop_counter(4);
  lc.incr_loop_counter(3);
  lc.incr_loop_counter(9);

  const auto loop_counters2 = lc.get_loop_counters();
  EXPECT_EQ(loop_counters2.size(), 10);
  EXPECT_EQ(loop_counters2[0], 2);
  EXPECT_EQ(loop_counters2[1], 1);
  EXPECT_EQ(loop_counters2[2], 0);
  EXPECT_EQ(loop_counters2[3], 1);
  EXPECT_EQ(loop_counters2[4], 1);
  EXPECT_EQ(loop_counters2[5], 0);
  EXPECT_EQ(loop_counters2[6], 0);
  EXPECT_EQ(loop_counters2[7], 0);
  EXPECT_EQ(loop_counters2[8], 0);
  EXPECT_EQ(loop_counters2[9], 1);
}
