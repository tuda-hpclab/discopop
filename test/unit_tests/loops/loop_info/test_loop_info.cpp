#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopInfo.hpp"

// Tests for old version (i.e., capturing functionality)

class LoopInfoTest : public ::testing::Test {};

TEST_F(LoopInfoTest, testZeroInitialization) {
  const auto li = __dp::loop_info_t{};

  ASSERT_EQ(li.line_nr_, 0);
  ASSERT_EQ(li.loop_id_, 0);
  ASSERT_EQ(li.file_id_, 0);
}

TEST_F(LoopInfoTest, testInitialization) {
  const auto li = __dp::loop_info_t{1, 2, 3};

  ASSERT_EQ(li.line_nr_, 1);
  ASSERT_EQ(li.loop_id_, 2);
  ASSERT_EQ(li.file_id_, 3);
}

TEST_F(LoopInfoTest, testInitializationWithNegativeValues) {
  const auto li = __dp::loop_info_t{-1, -2, -3};

  ASSERT_EQ(li.line_nr_, -1);
  ASSERT_EQ(li.loop_id_, -2);
  ASSERT_EQ(li.file_id_, -3);
}

TEST_F(LoopInfoTest, testEquality) {
  const auto li1 = __dp::loop_info_t{1, 2, 3};
  const auto li2 = __dp::loop_info_t{1, 2, 3};
  const auto li3 = __dp::loop_info_t{1, 2, 4};
  const auto li4 = __dp::loop_info_t{1, 3, 3};
  const auto li5 = __dp::loop_info_t{2, 2, 3};

  ASSERT_EQ(li1, li1);

  ASSERT_EQ(li1, li2);
  ASSERT_NE(li1, li3);
  ASSERT_NE(li1, li4);
  ASSERT_NE(li1, li5);

  ASSERT_EQ(li2, li1);
  ASSERT_NE(li3, li1);
  ASSERT_NE(li4, li1);
  ASSERT_NE(li5, li1);
}
