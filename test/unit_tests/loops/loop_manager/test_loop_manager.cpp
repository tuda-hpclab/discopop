#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopManager.hpp"

#include <algorithm>
#include <sstream>
#include <string>
#include <vector>

// Tests for old version (i.e., capturing functionality)

class LoopManagerTest : public ::testing::Test {};

namespace {

// output() walks an unordered_map, so the order of the records is not part of its contract.
std::vector<std::string> sorted_output_lines(__dp::LoopManager &lm) {
  std::ostringstream stream;
  lm.output(stream);

  std::vector<std::string> lines;
  std::istringstream reader{stream.str()};
  std::string line;
  while (std::getline(reader, line)) {
    lines.push_back(line);
  }

  std::sort(lines.begin(), lines.end());
  return lines;
}

} // namespace

TEST_F(LoopManagerTest, testInitialization) {
  auto lm = __dp::LoopManager();
  ASSERT_TRUE(lm.empty());

  for (auto i = 0; i < 10; i++) {
    for (auto j = 1; j < 1024; j *= 2) {
      ASSERT_NO_THROW(lm.clean_function_exit(i, j));
    }
  }

  for (auto i = 0; i < 100; i++) {
    ASSERT_TRUE(lm.is_new_loop(i));
  }

  for (auto i = 0; i < 100; i++) {
    ASSERT_TRUE(lm.is_single_exit(i));
  }
}

TEST_F(LoopManagerTest, testCreateNewLoop) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 3, 0);
  lm.create_new_loop(2, 2, 1);
  lm.create_new_loop(1, 3, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  ASSERT_FALSE(lm.empty());
}

TEST_F(LoopManagerTest, testIsNewLoop) {
  auto lm = __dp::LoopManager();

  lm.create_new_loop(1, 3, 0);
  lm.create_new_loop(2, 2, 1);
  lm.create_new_loop(1, 3, 0);

  ASSERT_TRUE(lm.is_new_loop(1));
  ASSERT_TRUE(lm.is_new_loop(2));
  ASSERT_FALSE(lm.is_new_loop(3));
}

TEST_F(LoopManagerTest, testIterateLoop) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 3, 0);
  lm.create_new_loop(2, 2, 1);
  lm.create_new_loop(1, 3, 0);

  lm.iterate_loop(1);
  lm.iterate_loop(2);
  lm.iterate_loop(1);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  ASSERT_EQ(table.top().get_count(), 3);
  ASSERT_EQ(table.topMinusN(1).get_count(), 0);
  ASSERT_EQ(table.topMinusN(2).get_count(), 0);
}

TEST_F(LoopManagerTest, testCleanFunctionExit) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 3, 0);
  lm.create_new_loop(2, 2, 1);
  lm.create_new_loop(1, 3, 0);

  lm.clean_function_exit(0, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  lm.clean_function_exit(2, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  lm.clean_function_exit(1, 12);

  ASSERT_EQ(table.size(), 2);
  ASSERT_EQ(loops.size(), 2);

  const auto it = loops.find(0);
  ASSERT_NE(it, loops.end());

  const auto loop = it->second;

  ASSERT_EQ(loop->end, 12);
  ASSERT_EQ(loop->maxIterationCount, 0);
  ASSERT_EQ(loop->nEntered, 1);
  ASSERT_EQ(loop->total, 0);
}

TEST_F(LoopManagerTest, testExitLoop) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 2, 3);
  lm.create_new_loop(4, 5, 6);
  lm.create_new_loop(7, 8, 9);
  lm.create_new_loop(10, 11, 12);
  lm.create_new_loop(13, 14, 15);

  lm.iterate_loop(1);
  lm.iterate_loop(4);
  lm.iterate_loop(7);
  lm.iterate_loop(10);
  lm.iterate_loop(13);

  lm.exit_loop(15);
  lm.exit_loop(12);
  lm.exit_loop(9);

  ASSERT_EQ(table.size(), 2);
  ASSERT_EQ(loops.size(), 5);

  const auto loop_3 = *loops.find(3)->second;
  const auto loop_6 = *loops.find(6)->second;
  const auto loop_9 = *loops.find(9)->second;
  const auto loop_12 = *loops.find(12)->second;
  const auto loop_15 = *loops.find(15)->second;

  ASSERT_EQ(loop_3.end, 0);
  ASSERT_EQ(loop_6.end, 0);
  ASSERT_EQ(loop_9.end, 9);
  ASSERT_EQ(loop_12.end, 12);
  ASSERT_EQ(loop_15.end, 15);

  ASSERT_EQ(loop_3.maxIterationCount, 0);
  ASSERT_EQ(loop_6.maxIterationCount, 0);
  ASSERT_EQ(loop_9.maxIterationCount, 0);
  ASSERT_EQ(loop_12.maxIterationCount, 0);
  ASSERT_EQ(loop_15.maxIterationCount, 5);

  ASSERT_EQ(loop_3.nEntered, 0);
  ASSERT_EQ(loop_6.nEntered, 0);
  ASSERT_EQ(loop_9.nEntered, 1);
  ASSERT_EQ(loop_12.nEntered, 1);
  ASSERT_EQ(loop_15.nEntered, 1);

  ASSERT_EQ(loop_3.total, 0);
  ASSERT_EQ(loop_6.total, 0);
  ASSERT_EQ(loop_9.total, 0);
  ASSERT_EQ(loop_12.total, 0);
  ASSERT_EQ(loop_15.total, 5);
}

TEST_F(LoopManagerTest, testIsSingleExit) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 2, 3);
  lm.create_new_loop(4, 5, 6);
  lm.create_new_loop(7, 8, 9);
  lm.create_new_loop(10, 11, 12);
  lm.create_new_loop(13, 14, 15);

  lm.iterate_loop(1);
  lm.iterate_loop(4);
  lm.iterate_loop(7);
  lm.iterate_loop(10);
  lm.iterate_loop(13);

  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.is_single_exit(i), lm.is_single_exit(i));
  }

  lm.exit_loop(15);
  ASSERT_FALSE(lm.empty());

  lm.exit_loop(12);
  ASSERT_FALSE(lm.empty());

  lm.exit_loop(9);
  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.is_single_exit(i), lm.is_single_exit(i));
  }

  lm.exit_loop(3);
  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.is_single_exit(i), lm.is_single_exit(i));
  }
}

TEST_F(LoopManagerTest, testCorrectFuncLevel) {
  auto lm = __dp::LoopManager();

  const auto &table = lm.get_stack();
  const auto &loops = lm.get_loops();

  lm.create_new_loop(1, 2, 3);
  lm.create_new_loop(4, 5, 6);
  lm.create_new_loop(7, 8, 9);
  lm.create_new_loop(10, 11, 12);
  lm.create_new_loop(13, 14, 15);

  lm.iterate_loop(1);
  lm.iterate_loop(4);
  lm.iterate_loop(7);
  lm.iterate_loop(10);
  lm.iterate_loop(13);

  lm.correct_func_level(103);

  const auto &loop_3 = table.topMinusN(4);
  const auto &loop_6 = table.topMinusN(3);
  const auto &loop_9 = table.topMinusN(2);
  const auto &loop_12 = table.topMinusN(1);
  const auto &loop_15 = table.topMinusN(0);

  ASSERT_EQ(loop_3.funcLevel, 1);
  ASSERT_EQ(loop_6.funcLevel, 4);
  ASSERT_EQ(loop_9.funcLevel, 7);
  ASSERT_EQ(loop_12.funcLevel, 10);
  ASSERT_EQ(loop_15.funcLevel, 103);

  lm.exit_loop(15);

  lm.correct_func_level(104);

  ASSERT_EQ(loop_3.funcLevel, 1);
  ASSERT_EQ(loop_6.funcLevel, 4);
  ASSERT_EQ(loop_9.funcLevel, 7);
  ASSERT_EQ(loop_12.funcLevel, 104);
  ASSERT_EQ(loop_15.funcLevel, 103);
}

TEST_F(LoopManagerTest, testOutputWithoutLoops) {
  auto lm = __dp::LoopManager();

  ASSERT_TRUE(sorted_output_lines(lm).empty());
}

TEST_F(LoopManagerTest, testOutputSingleEntry) {
  auto lm = __dp::LoopManager();

  lm.create_new_loop(1, 2, 3);
  lm.iterate_loop(1);
  lm.iterate_loop(1);
  lm.iterate_loop(1);
  lm.exit_loop(12);

  // <begin> BGN loop <total> <entered> <average> <maximum>
  const std::vector<std::string> expected{"0:12 END loop", "0:3 BGN loop 3 1 3 3"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputSeveralEntries) {
  auto lm = __dp::LoopManager();

  lm.create_new_loop(1, 2, 3);
  lm.iterate_loop(1);
  lm.iterate_loop(1);
  lm.exit_loop(10);

  // the same loop is entered a second time and runs longer
  lm.create_new_loop(1, 2, 3);
  for (auto i = 0; i < 5; ++i) {
    lm.iterate_loop(1);
  }
  lm.exit_loop(10);

  // 7 iterations across 2 entries, so 3 on average (integer division), at most 5 in one entry
  const std::vector<std::string> expected{"0:10 END loop", "0:3 BGN loop 7 2 3 5"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputSeveralLoops) {
  auto lm = __dp::LoopManager();

  lm.create_new_loop(1, 2, 3);
  lm.create_new_loop(1, 5, 6);
  lm.iterate_loop(1);
  lm.exit_loop(9);
  lm.iterate_loop(1);
  lm.iterate_loop(1);
  lm.exit_loop(12);

  // the inner loop runs once, the outer one twice: only the innermost entry is iterated
  const std::vector<std::string> expected{"0:12 END loop", "0:3 BGN loop 2 1 2 2", "0:6 BGN loop 1 1 1 1",
                                          "0:9 END loop"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputLoopThatWasNeverLeft) {
  auto lm = __dp::LoopManager();

  // entered, iterated, never exited -- nEntered stays 0, which the average must not be divided by
  lm.create_new_loop(1, 2, 3);
  lm.iterate_loop(1);
  lm.iterate_loop(1);

  // the end line is unknown, which decodeLID reports as '*'
  const std::vector<std::string> expected{"* END loop", "0:3 BGN loop 0 0 0 0"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}
