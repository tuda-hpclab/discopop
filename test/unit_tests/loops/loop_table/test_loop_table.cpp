#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopTable.hpp"

#include <iostream>
#include <sstream>
#include <string>

// Tests for old version (i.e., capturing functionality)

class LoopTableTest : public ::testing::Test {};

namespace {

// The debug output of the loop table goes to std::cout and is only written when DP_DEBUG is set,
// which is off for every other test. Both helpers put back what they found.
class CoutCapture {
public:
  CoutCapture() : previous(std::cout.rdbuf(buffer.rdbuf())) {}
  ~CoutCapture() { std::cout.rdbuf(previous); }

  CoutCapture(const CoutCapture &) = delete;
  CoutCapture &operator=(const CoutCapture &) = delete;

  std::string str() const { return buffer.str(); }

private:
  std::ostringstream buffer;
  std::streambuf *previous;
};

class DebugFlag {
public:
  explicit DebugFlag(bool value) : previous(__dp::DP_DEBUG) { __dp::DP_DEBUG = value; }
  ~DebugFlag() { __dp::DP_DEBUG = previous; }

  DebugFlag(const DebugFlag &) = delete;
  DebugFlag &operator=(const DebugFlag &) = delete;

private:
  const bool previous;
};

} // namespace

TEST_F(LoopTableTest, testInitialization) {
  const auto lt = __dp::LoopTable{};

  ASSERT_EQ(lt.size(), 0);
  ASSERT_TRUE(lt.empty());

  for (auto lid = 0; lid < 10; ++lid) {
    ASSERT_TRUE(lt.is_single_exit(lid));
  }

  ASSERT_NO_THROW(lt.debug_output());
}

TEST_F(LoopTableTest, testPushBack) {
  auto lt = __dp::LoopTable{};

  lt.push(__dp::LoopTableEntry{1, 2, 3, 0});
  ASSERT_EQ(lt.size(), 1);
  ASSERT_FALSE(lt.empty());
  for (auto lid = 0; lid < 10; ++lid) {
    if (lid == 2) {
      continue;
    }
    ASSERT_TRUE(lt.is_single_exit(lid));
  }
  ASSERT_FALSE(lt.is_single_exit(2));

  lt.push(__dp::LoopTableEntry{4, 5, 6, 0});
  ASSERT_EQ(lt.size(), 2);
  ASSERT_FALSE(lt.empty());
  for (auto lid = 0; lid < 10; ++lid) {
    if (lid == 5) {
      continue;
    }
    ASSERT_TRUE(lt.is_single_exit(lid));
  }
  ASSERT_FALSE(lt.is_single_exit(5));

  ASSERT_NO_THROW(lt.debug_output());
}

TEST_F(LoopTableTest, testGetters) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};

  lt.push(first_entry);
  lt.push(second_entry);

  ASSERT_NO_THROW(lt.debug_output());

  const auto top_entry_from_lt = lt.top();
  ASSERT_EQ(top_entry_from_lt, second_entry);

  const auto first_entry_from_lt = lt.first();
  ASSERT_EQ(first_entry_from_lt, first_entry);

  const auto top_minus_0_entry_from_lt = lt.topMinusN(0);
  ASSERT_EQ(top_minus_0_entry_from_lt, second_entry);

  const auto top_minus_1_entry_from_lt = lt.topMinusN(1);
  ASSERT_EQ(top_minus_1_entry_from_lt, first_entry);

  ASSERT_EQ(lt.size(), 2);
  ASSERT_FALSE(lt.empty());

  lt.pop();

  const auto top_entry_from_lt_after_pop = lt.top();
  ASSERT_EQ(top_entry_from_lt_after_pop, first_entry);

  const auto first_entry_from_lt_after_pop = lt.first();
  ASSERT_EQ(first_entry_from_lt_after_pop, first_entry);

  const auto top_minus_0_entry_from_lt_after_pop = lt.topMinusN(0);
  ASSERT_EQ(top_minus_0_entry_from_lt_after_pop, first_entry);

  ASSERT_EQ(lt.size(), 1);
  ASSERT_FALSE(lt.empty());

  ASSERT_NO_THROW(lt.debug_output());

  lt.pop();

  ASSERT_EQ(lt.size(), 0);
  ASSERT_TRUE(lt.empty());
}

TEST_F(LoopTableTest, testCorrectFunctionLevel) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};

  lt.push(first_entry);
  lt.push(second_entry);

  lt.correct_func_level(7);

  const auto top_entry_from_lt = lt.top();
  ASSERT_EQ(top_entry_from_lt, __dp::LoopTableEntry(7, 5, 6, 0));

  lt.pop();

  const auto top_entry_from_lt_after_pop = lt.top();
  ASSERT_EQ(top_entry_from_lt_after_pop, first_entry);

  lt.pop();

  ASSERT_TRUE(lt.empty());

  lt.push(first_entry);
  lt.push(second_entry);

  lt.correct_func_level(4);

  const auto top_entry_from_lt_2 = lt.top();
  ASSERT_EQ(top_entry_from_lt_2, second_entry);

  lt.pop();

  const auto top_entry_from_lt_after_pop_2 = lt.top();
  ASSERT_EQ(top_entry_from_lt_after_pop_2, first_entry);

  lt.pop();

  ASSERT_TRUE(lt.empty());
}

TEST_F(LoopTableTest, testIncrementTopCount) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};

  lt.push(first_entry);
  lt.push(second_entry);

  lt.increment_top_count();

  const auto top_entry_from_lt = lt.top();
  ASSERT_EQ(top_entry_from_lt, __dp::LoopTableEntry(4, 5, 7, 0));

  lt.pop();

  const auto top_entry_from_lt_after_pop = lt.top();
  ASSERT_EQ(top_entry_from_lt_after_pop, first_entry);

  lt.pop();

  ASSERT_TRUE(lt.empty());

  lt.push(first_entry);
  lt.push(second_entry);

  const auto top_entry_from_lt_2 = lt.top();
  ASSERT_EQ(top_entry_from_lt_2, second_entry);

  lt.pop();

  lt.increment_top_count();

  const auto top_entry_from_lt_after_pop_2 = lt.top();
  ASSERT_EQ(top_entry_from_lt_after_pop_2, __dp::LoopTableEntry(1, 2, 4, 0));

  lt.pop();

  ASSERT_TRUE(lt.empty());
}

TEST_F(LoopTableTest, testUpdateLidSize0) {
  auto lt = __dp::LoopTable{};

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b1111'1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b1111'1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b1111'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'1111'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize1) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};

  lt.push(first_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'0011'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize2) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};

  lt.push(first_entry);
  lt.push(second_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'0110'1111'0011'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize3) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};
  const auto third_entry = __dp::LoopTableEntry{7, 8, 9, 0};

  lt.push(first_entry);
  lt.push(second_entry);
  lt.push(third_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1000'1001'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1000'1001'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1000'1001'1000'0110'1000'0011'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'1001'1111'0110'1111'0011'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize4) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};
  const auto third_entry = __dp::LoopTableEntry{7, 8, 9, 0};
  const auto fourth_entry = __dp::LoopTableEntry{10, 11, 12, 0};

  lt.push(first_entry);
  lt.push(second_entry);
  lt.push(third_entry);
  lt.push(fourth_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1000'1100'1000'1001'1000'0110'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1000'1100'1000'1001'1000'0110'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1000'1100'1000'1001'1000'0110'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'1100'1111'1001'1111'0110'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize5) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};
  const auto third_entry = __dp::LoopTableEntry{7, 8, 9, 0};
  const auto fourth_entry = __dp::LoopTableEntry{10, 11, 12, 0};
  const auto fifth_entry = __dp::LoopTableEntry{13, 14, 15, 0};

  lt.push(first_entry);
  lt.push(second_entry);
  lt.push(third_entry);
  lt.push(fourth_entry);
  lt.push(fifth_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testUpdateLidSize6) {
  auto lt = __dp::LoopTable{};

  const auto first_entry = __dp::LoopTableEntry{1, 2, 3, 0};
  const auto second_entry = __dp::LoopTableEntry{4, 5, 6, 0};
  const auto third_entry = __dp::LoopTableEntry{7, 8, 9, 0};
  const auto fourth_entry = __dp::LoopTableEntry{10, 11, 12, 0};
  const auto fifth_entry = __dp::LoopTableEntry{13, 14, 15, 0};
  const auto sixth_entry = __dp::LoopTableEntry{16, 17, 18, 0};

  lt.push(first_entry);
  lt.push(second_entry);
  lt.push(third_entry);
  lt.push(fourth_entry);
  lt.push(fifth_entry);
  lt.push(sixth_entry);

  const auto lid_1 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010'1001'0010'1000'1111'1000'1100'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_2 = 0b1111'0010'1001'0010'1000'1111'1000'1100'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto expected_lid_3 = 0b0000'0010'1001'0010'1000'1111'1000'1100'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111'1001'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010'1111'0010'1111'1111'1111'1100'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto expected_lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto expected_lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto expected_lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  ASSERT_EQ(expected_lid_1, lt.update_lid(lid_1));
  ASSERT_EQ(expected_lid_2, lt.update_lid(lid_2));
  ASSERT_EQ(expected_lid_3, lt.update_lid(lid_3));
  ASSERT_EQ(expected_lid_4, lt.update_lid(lid_4));
  ASSERT_EQ(expected_lid_5, lt.update_lid(lid_5));
  ASSERT_EQ(expected_lid_6, lt.update_lid(lid_6));
  ASSERT_EQ(expected_lid_7, lt.update_lid(lid_7));
  ASSERT_EQ(expected_lid_8, lt.update_lid(lid_8));
}

TEST_F(LoopTableTest, testNonConstTop) {
  auto lt = __dp::LoopTable{};
  lt.push(__dp::LoopTableEntry{1, 2, 3, 4});

  lt.non_const_top().increment_count();

  ASSERT_EQ(lt.top().get_count(), 4);
}

TEST_F(LoopTableTest, testCorrectFunctionLevelKeepsAMatchingLevel) {
  auto lt = __dp::LoopTable{};
  const auto entry = __dp::LoopTableEntry{1, 2, 3, 4};
  lt.push(entry);

  const DebugFlag debug{true};
  const CoutCapture capture{};

  lt.correct_func_level(1);

  ASSERT_EQ(lt.top(), entry);
  ASSERT_TRUE(capture.str().empty());
}

TEST_F(LoopTableTest, testCorrectFunctionLevelReportsTheChange) {
  auto lt = __dp::LoopTable{};
  lt.push(__dp::LoopTableEntry{1, 2, 3, 4});

  const DebugFlag debug{true};
  const CoutCapture capture{};

  lt.correct_func_level(7);

  ASSERT_EQ(lt.top().funcLevel, 7);
  ASSERT_EQ(capture.str(), "WARNING: changing funcLevel of Loop 2 from 1 to 7\n");
}

TEST_F(LoopTableTest, testDebugOutputOfAnEmptyTable) {
  const auto lt = __dp::LoopTable{};

  const DebugFlag debug{true};
  const CoutCapture capture{};

  lt.debug_output();

  ASSERT_EQ(capture.str(), "Loop Stack is empty.\n");
}

TEST_F(LoopTableTest, testDebugOutputOfTheTopEntry) {
  auto lt = __dp::LoopTable{};
  lt.push(__dp::LoopTableEntry{1, 2, 3, 4});
  lt.push(__dp::LoopTableEntry{5, 6, 7, 8});

  const DebugFlag debug{true};
  const CoutCapture capture{};

  lt.debug_output();

  ASSERT_EQ(capture.str(), "TOP: (5)Loop 6.\n");
}

TEST_F(LoopTableTest, testDebugOutputStaysSilentWithoutTheFlag) {
  auto lt = __dp::LoopTable{};
  lt.push(__dp::LoopTableEntry{1, 2, 3, 4});

  const DebugFlag debug{false};
  const CoutCapture capture{};

  lt.debug_output();
  lt.correct_func_level(7);

  ASSERT_EQ(lt.top().funcLevel, 7);
  ASSERT_TRUE(capture.str().empty());
}
