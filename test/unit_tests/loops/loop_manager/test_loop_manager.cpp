#include <gtest/gtest.h>

#include "loop/LoopManager.hpp"
#include "loop/Makros.hpp"

#include <algorithm>
#include <sstream>
#include <string>
#include <vector>

// Tests for old version (i.e., capturing functionality)

class LoopManagerTest : public ::testing::Test {};

namespace {

// output() walks an unordered_map, so the order of the records is not part of its contract.
std::vector<std::string> sorted_output_lines(dp::LoopManager &lm) {
  std::ostringstream stream;
  lm.Output(stream);

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
  auto lm = dp::LoopManager();
  ASSERT_TRUE(lm.empty());

  for (auto i = 0; i < 10; i++) {
    for (auto j = 1; j < 1024; j *= 2) {
      ASSERT_NO_THROW(lm.CleanFunctionExit(i, j));
    }
  }

  for (auto i = 0; i < 100; i++) {
    ASSERT_TRUE(lm.IsNewLoop(0, i));
  }

  for (auto i = 0; i < 100; i++) {
    ASSERT_TRUE(lm.IsSingleExit(i));
  }
}

TEST_F(LoopManagerTest, testCreateNewLoop) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();
  const auto &loops = lm.GetLoops();

  lm.CreateNewLoop(1, 3, 0);
  lm.CreateNewLoop(2, 2, 1);
  lm.CreateNewLoop(1, 3, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  ASSERT_FALSE(lm.empty());
}

TEST_F(LoopManagerTest, testIsNewLoop) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 3, 0);
  lm.CreateNewLoop(2, 2, 1);
  lm.CreateNewLoop(1, 3, 0);

  ASSERT_TRUE(lm.IsNewLoop(1, 1));
  ASSERT_TRUE(lm.IsNewLoop(1, 2));
  ASSERT_FALSE(lm.IsNewLoop(1, 3));
}

TEST_F(LoopManagerTest, testTheEntryOfARecursiveInstanceOfTheLoopOnTopIsANewLoop) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 3, 0);

  // from the function of the loop: the next iteration
  ASSERT_FALSE(lm.IsNewLoop(1, 3));
  // from a recursive call of the function (a deeper level): an instance of the loop of its own
  ASSERT_TRUE(lm.IsNewLoop(2, 3));
  ASSERT_TRUE(lm.IsNewLoop(5, 3));
}

TEST_F(LoopManagerTest, testIterateLoop) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();
  const auto &loops = lm.GetLoops();

  lm.CreateNewLoop(1, 3, 0);
  lm.CreateNewLoop(2, 2, 1);
  lm.CreateNewLoop(1, 3, 0);

  lm.IterateLoop(1);
  lm.IterateLoop(2);
  lm.IterateLoop(1);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  ASSERT_EQ(table.Top().GetCount(), 3);
  ASSERT_EQ(table.TopMinusN(1).GetCount(), 0);
  ASSERT_EQ(table.TopMinusN(2).GetCount(), 0);
}

TEST_F(LoopManagerTest, testCleanFunctionExit) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();
  const auto &loops = lm.GetLoops();

  lm.CreateNewLoop(1, 3, 0);
  lm.CreateNewLoop(2, 2, 1);
  lm.CreateNewLoop(1, 3, 0);

  lm.CleanFunctionExit(0, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  lm.CleanFunctionExit(2, 0);

  ASSERT_EQ(table.size(), 3);
  ASSERT_EQ(loops.size(), 2);

  lm.CleanFunctionExit(1, 12);

  ASSERT_EQ(table.size(), 2);
  ASSERT_EQ(loops.size(), 2);

  const auto it = loops.find(0);
  ASSERT_NE(it, loops.end());

  const auto loop = it->second;

  ASSERT_EQ(loop->end, 12);
  ASSERT_EQ(loop->max_iteration_count, 0);
  ASSERT_EQ(loop->n_entered, 1);
  ASSERT_EQ(loop->total, 0);
}

TEST_F(LoopManagerTest, testExitLoop) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();
  const auto &loops = lm.GetLoops();

  lm.CreateNewLoop(1, 2, 3);
  lm.CreateNewLoop(4, 5, 6);
  lm.CreateNewLoop(7, 8, 9);
  lm.CreateNewLoop(10, 11, 12);
  lm.CreateNewLoop(13, 14, 15);

  lm.IterateLoop(1);
  lm.IterateLoop(4);
  lm.IterateLoop(7);
  lm.IterateLoop(10);
  lm.IterateLoop(13);

  lm.ExitLoop(15);
  lm.ExitLoop(12);
  lm.ExitLoop(9);

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

  ASSERT_EQ(loop_3.max_iteration_count, 0);
  ASSERT_EQ(loop_6.max_iteration_count, 0);
  ASSERT_EQ(loop_9.max_iteration_count, 0);
  ASSERT_EQ(loop_12.max_iteration_count, 0);
  ASSERT_EQ(loop_15.max_iteration_count, 5);

  ASSERT_EQ(loop_3.n_entered, 0);
  ASSERT_EQ(loop_6.n_entered, 0);
  ASSERT_EQ(loop_9.n_entered, 1);
  ASSERT_EQ(loop_12.n_entered, 1);
  ASSERT_EQ(loop_15.n_entered, 1);

  ASSERT_EQ(loop_3.total, 0);
  ASSERT_EQ(loop_6.total, 0);
  ASSERT_EQ(loop_9.total, 0);
  ASSERT_EQ(loop_12.total, 0);
  ASSERT_EQ(loop_15.total, 5);
}

TEST_F(LoopManagerTest, testIsSingleExit) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();

  lm.CreateNewLoop(1, 2, 3);
  lm.CreateNewLoop(4, 5, 6);
  lm.CreateNewLoop(7, 8, 9);
  lm.CreateNewLoop(10, 11, 12);
  lm.CreateNewLoop(13, 14, 15);

  lm.IterateLoop(1);
  lm.IterateLoop(4);
  lm.IterateLoop(7);
  lm.IterateLoop(10);
  lm.IterateLoop(13);

  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.IsSingleExit(i), lm.IsSingleExit(i));
  }

  lm.ExitLoop(15);
  ASSERT_FALSE(lm.empty());

  lm.ExitLoop(12);
  ASSERT_FALSE(lm.empty());

  lm.ExitLoop(9);
  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.IsSingleExit(i), lm.IsSingleExit(i));
  }

  lm.ExitLoop(3);
  ASSERT_FALSE(lm.empty());

  for (auto i = 0; i < 20; i++) {
    ASSERT_EQ(table.IsSingleExit(i), lm.IsSingleExit(i));
  }
}

TEST_F(LoopManagerTest, testCorrectFuncLevel) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();

  lm.CreateNewLoop(1, 2, 3);
  lm.CreateNewLoop(4, 5, 6);
  lm.CreateNewLoop(7, 8, 9);
  lm.CreateNewLoop(10, 11, 12);
  lm.CreateNewLoop(13, 14, 15);

  lm.IterateLoop(1);
  lm.IterateLoop(4);
  lm.IterateLoop(7);
  lm.IterateLoop(10);
  lm.IterateLoop(13);

  lm.CorrectFuncLevel(103);

  const auto &loop_3 = table.TopMinusN(4);
  const auto &loop_6 = table.TopMinusN(3);
  const auto &loop_9 = table.TopMinusN(2);
  const auto &loop_12 = table.TopMinusN(1);
  const auto &loop_15 = table.TopMinusN(0);

  ASSERT_EQ(loop_3.func_level, 1);
  ASSERT_EQ(loop_6.func_level, 4);
  ASSERT_EQ(loop_9.func_level, 7);
  ASSERT_EQ(loop_12.func_level, 10);
  ASSERT_EQ(loop_15.func_level, 103);

  lm.ExitLoop(15);

  lm.CorrectFuncLevel(104);

  ASSERT_EQ(loop_3.func_level, 1);
  ASSERT_EQ(loop_6.func_level, 4);
  ASSERT_EQ(loop_9.func_level, 7);
  ASSERT_EQ(loop_12.func_level, 104);
  ASSERT_EQ(loop_15.func_level, 103);
}

TEST_F(LoopManagerTest, testOutputWithoutLoops) {
  auto lm = dp::LoopManager();

  ASSERT_TRUE(sorted_output_lines(lm).empty());
}

TEST_F(LoopManagerTest, testOutputSingleEntry) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 2, 3);
  lm.IterateLoop(1);
  lm.IterateLoop(1);
  lm.IterateLoop(1);
  lm.ExitLoop(12);

  // <begin> BGN loop <total> <entered> <average> <maximum>
  const std::vector<std::string> expected{"0:12 END loop", "0:3 BGN loop 3 1 3 3"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputSeveralEntries) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 2, 3);
  lm.IterateLoop(1);
  lm.IterateLoop(1);
  lm.ExitLoop(10);

  // the same loop is entered a second time and runs longer
  lm.CreateNewLoop(1, 2, 3);
  for (auto i = 0; i < 5; ++i) {
    lm.IterateLoop(1);
  }
  lm.ExitLoop(10);

  // 7 iterations across 2 entries, so 3 on average (integer division), at most 5 in one entry
  const std::vector<std::string> expected{"0:10 END loop", "0:3 BGN loop 7 2 3 5"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputSeveralLoops) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 2, 3);
  lm.CreateNewLoop(1, 5, 6);
  lm.IterateLoop(1);
  lm.ExitLoop(9);
  lm.IterateLoop(1);
  lm.IterateLoop(1);
  lm.ExitLoop(12);

  // the inner loop runs once, the outer one twice: only the innermost entry is iterated
  const std::vector<std::string> expected{"0:12 END loop", "0:3 BGN loop 2 1 2 2", "0:6 BGN loop 1 1 1 1",
                                          "0:9 END loop"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testOutputLoopThatWasNeverLeft) {
  auto lm = dp::LoopManager();

  // entered, iterated, never exited -- nEntered stays 0, which the average must not be divided by
  lm.CreateNewLoop(1, 2, 3);
  lm.IterateLoop(1);
  lm.IterateLoop(1);

  // the end line is unknown, which DecodeLid reports as '*'
  const std::vector<std::string> expected{"* END loop", "0:3 BGN loop 0 0 0 0"};
  ASSERT_EQ(sorted_output_lines(lm), expected);
}

TEST_F(LoopManagerTest, testGetCurrentLoopId) {
  auto lm = dp::LoopManager();

  lm.CreateNewLoop(1, 2, 3);
  ASSERT_EQ(lm.GetCurrentLoopId(), 2);

  lm.CreateNewLoop(1, 5, 6);
  ASSERT_EQ(lm.GetCurrentLoopId(), 5);

  lm.ExitLoop(9);
  ASSERT_EQ(lm.GetCurrentLoopId(), 2);
}

TEST_F(LoopManagerTest, testGetCurrentLoopIdWithoutLoop) {
  auto lm = dp::LoopManager();

  ASSERT_TRUE(lm.empty());
  ASSERT_EQ(lm.GetCurrentLoopId(), -1);

  // and again after the only loop has been left
  lm.CreateNewLoop(1, 2, 3);
  lm.ExitLoop(9);

  ASSERT_TRUE(lm.empty());
  ASSERT_EQ(lm.GetCurrentLoopId(), -1);
}

TEST_F(LoopManagerTest, testIsDone) {
  auto lm = dp::LoopManager();

  ASSERT_FALSE(lm.IsDone());

  lm.SetDone();
  ASSERT_TRUE(lm.IsDone());

  // the latch only ever closes
  lm.SetDone();
  ASSERT_TRUE(lm.IsDone());
}

TEST_F(LoopManagerTest, testLoopCounters) {
  auto lm = dp::LoopManager();

  ASSERT_TRUE(lm.GetLoopCounters().empty());

  lm.IncrLoopCounter(0);
  lm.IncrLoopCounter(2);
  lm.IncrLoopCounter(0);

  const std::vector<unsigned int> expected{2, 0, 1};
  ASSERT_EQ(lm.GetLoopCounters(), expected);
}

TEST_F(LoopManagerTest, testUpdateLidUsesTheLoopStack) {
  auto lm = dp::LoopManager();

  // without a loop, update_lid marks the metadata as "no loop active"
  ASSERT_EQ(UnpackLidMetadataGetLoopId(lm.UpdateLid(0x1234)), 0xFF);

  lm.CreateNewLoop(1, 42, 3);
  lm.IterateLoop(1);
  lm.IterateLoop(1);

  const LID lid = lm.UpdateLid(0x1234);

  ASSERT_EQ(lid, lm.GetStack().UpdateLid(0x1234));
  ASSERT_EQ(UnpackLidMetadataGetLoopId(lid), 42);
  ASSERT_EQ(UnpackLidMetadataGetLoopIteration0(lid), 2);
  ASSERT_EQ(lid & 0xFFFFFFFF, 0x1234);
}

TEST_F(LoopManagerTest, testCleanFunctionExitStopsAtAForeignLevel) {
  auto lm = dp::LoopManager();

  const auto &table = lm.GetStack();

  // a loop of one function, a loop of the function it calls, and another loop of the first one
  lm.CreateNewLoop(1, 2, 3);
  lm.CreateNewLoop(2, 5, 6);
  lm.CreateNewLoop(1, 8, 9);

  // only the entries on top that belong to the level are unwound, so the level 1 entry below the
  // level 2 one stays behind
  lm.CleanFunctionExit(1, 20);
  ASSERT_EQ(table.size(), 2);
  ASSERT_EQ(table.Top().loop_id, 5);

  // and asking again does not reach it either
  lm.CleanFunctionExit(1, 21);
  ASSERT_EQ(table.size(), 2);

  lm.CleanFunctionExit(2, 22);
  ASSERT_EQ(table.size(), 1);
  ASSERT_EQ(table.Top().loop_id, 2);

  lm.CleanFunctionExit(1, 23);
  ASSERT_TRUE(lm.empty());
}
