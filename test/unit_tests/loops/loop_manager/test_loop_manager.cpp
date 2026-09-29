#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopManager.hpp"

// Tests for old version (i.e., capturing functionality)

class LoopManagerTest : public ::testing::Test {};

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
