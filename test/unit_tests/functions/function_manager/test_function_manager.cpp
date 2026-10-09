#include <gtest/gtest.h>

#include <sstream>

#include "../../../../profiler/rtlib/functions/FunctionManager.hpp"

class FunctionManagerTest : public ::testing::Test {};

TEST_F(FunctionManagerTest, testStackLevelDefaultsToZero) {
  auto fm = __dp::FunctionManager{};
  EXPECT_EQ(fm.get_current_stack_level(), 0);
}

TEST_F(FunctionManagerTest, testIncreaseAndDecreaseStackLevel) {
  auto fm = __dp::FunctionManager{};

  fm.increase_stack_level();
  fm.increase_stack_level();
  EXPECT_EQ(fm.get_current_stack_level(), 2);

  fm.decrease_stack_level();
  EXPECT_EQ(fm.get_current_stack_level(), 1);
}

TEST_F(FunctionManagerTest, testRegisterFunctionStartIncreasesStackLevel) {
  auto fm = __dp::FunctionManager{};

  fm.register_function_start(10);
  EXPECT_EQ(fm.get_current_stack_level(), 1);

  fm.register_function_start(20);
  EXPECT_EQ(fm.get_current_stack_level(), 2);
}

// register_function_start groups the entered function under the LID of the
// call/invoke instruction that most recently triggered it (lastCallOrInvoke),
// falling back to the last processed line if no call was logged.
TEST_F(FunctionManagerTest, testRegisterFunctionStartGroupsByLastCallOrInvoke) {
  auto fm = __dp::FunctionManager{};

  // no call logged yet -> falls back to the (default, 0) last processed line
  fm.register_function_start(100);

  // a logged call becomes the grouping key for the next function start
  fm.log_call(5);
  fm.register_function_start(200);

  // reset_call clears the pending call and records the processed line, which
  // becomes the grouping key for the following, un-logged function start
  fm.reset_call(7);
  fm.register_function_start(300);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(0) + " BGN func " + dputil::decodeLID(100)), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(200)), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(7) + " BGN func " + dputil::decodeLID(300)), std::string::npos);
}

TEST_F(FunctionManagerTest, testRegisterFunctionEndOutput) {
  auto fm = __dp::FunctionManager{};

  fm.register_function_end(42);
  fm.register_function_end(43);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(42) + " END func"), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(43) + " END func"), std::string::npos);
}

// A call site is not cleared by entering a function, so every function entered after one logged
// call is grouped under it -- the branch that adds to an existing entry rather than creating one.
TEST_F(FunctionManagerTest, testSeveralFunctionsAreGroupedUnderTheSameCallSite) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5);
  fm.register_function_start(100);
  fm.register_function_start(200);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100)), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(200)), std::string::npos);
}

// The same entry reached twice is one entry: the LIDs of a call site are kept in a set.
TEST_F(FunctionManagerTest, testTheSameFunctionEntryIsReportedOnce) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5);
  fm.register_function_start(100);
  fm.register_function_start(100);

  std::ostringstream out;
  fm.output_functions(out);

  const auto line = dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100);
  const auto first = out.str().find(line);
  ASSERT_NE(first, std::string::npos);
  EXPECT_EQ(out.str().find(line, first + 1), std::string::npos);
}

// and the same for the returns, which are kept in a set of their own
TEST_F(FunctionManagerTest, testTheSameFunctionEndIsReportedOnce) {
  auto fm = __dp::FunctionManager{};

  fm.register_function_end(42);
  fm.register_function_end(42);

  std::ostringstream out;
  fm.output_functions(out);

  const auto line = dputil::decodeLID(42) + " END func";
  const auto first = out.str().find(line);
  ASSERT_NE(first, std::string::npos);
  EXPECT_EQ(out.str().find(line, first + 1), std::string::npos);
}

// reset_call is what __dp_read/__dp_write/__dp_func_exit call on every access: it drops the pending
// call site, so a function entered later is grouped under the line last seen instead.
TEST_F(FunctionManagerTest, testResetCallDropsThePendingCallSite) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5);
  fm.reset_call(7);
  fm.register_function_start(100);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(7) + " BGN func " + dputil::decodeLID(100)), std::string::npos);
  EXPECT_EQ(output.find(dputil::decodeLID(5) + " BGN func"), std::string::npos);
}

// unwind_function_stack() calls __dp_func_exit until the level has passed zero, and asserts on -1
TEST_F(FunctionManagerTest, testTheStackLevelGoesBelowZero) {
  auto fm = __dp::FunctionManager{};

  fm.decrease_stack_level();

  EXPECT_EQ(fm.get_current_stack_level(), -1);
}

TEST_F(FunctionManagerTest, testAFreshManagerReportsNothing) {
  auto fm = __dp::FunctionManager{};

  std::ostringstream out;
  fm.output_functions(out);

  EXPECT_EQ(out.str(), "");
}

// the two lists are written one after the other, every entry on a line of its own
TEST_F(FunctionManagerTest, testTheOutputIsOneLinePerEntry) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5);
  fm.register_function_start(100);
  fm.register_function_end(200);

  std::ostringstream out;
  fm.output_functions(out);

  EXPECT_EQ(out.str(), dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100) + "\n" + dputil::decodeLID(200) +
                           " END func\n");
}

// __dp_func_exit and unwind_function_stack() only read the level, and writing the results only
// reads the two lists
TEST_F(FunctionManagerTest, testAManagerCanBeReadThroughAConstReference) {
  auto fm = __dp::FunctionManager{};
  fm.log_call(5);
  fm.register_function_start(100);
  fm.register_function_end(200);

  const __dp::FunctionManager &reference = fm;

  EXPECT_EQ(reference.get_current_stack_level(), 1);

  std::ostringstream out;
  reference.output_functions(out);
  EXPECT_NE(out.str().find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100)), std::string::npos);
}

// __dp_call logs the location of the call site and the instruction id of the call. The location
// names the call site, the instruction id follows the entered function as a fifth column, and a
// function entered without a logged call has none.
TEST_F(FunctionManagerTest, testTheCallInstructionIdFollowsTheEntry) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5, 34);
  fm.register_function_start(100);
  fm.reset_call(7);
  fm.register_function_start(200);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100) + " 34\n"), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(7) + " BGN func " + dputil::decodeLID(200) + "\n"), std::string::npos);
}

// one call site, two calls on it: they are told apart by their instruction ids
TEST_F(FunctionManagerTest, testTwoCallsOnOneLineAreKeptApart) {
  auto fm = __dp::FunctionManager{};

  fm.log_call(5, 34);
  fm.register_function_start(100);
  fm.log_call(5, 35);
  fm.register_function_start(200);

  std::ostringstream out;
  fm.output_functions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(100) + " 34\n"), std::string::npos);
  EXPECT_NE(output.find(dputil::decodeLID(5) + " BGN func " + dputil::decodeLID(200) + " 35\n"), std::string::npos);
}
