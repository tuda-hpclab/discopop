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
