#include <gtest/gtest.h>

#include <set>
#include <sstream>
#include <string>

#include "functions/FunctionManager.hpp"

class FunctionManagerTest : public ::testing::Test {};

TEST_F(FunctionManagerTest, testStackLevelDefaultsToZero) {
  auto fm = dp::FunctionManager{};
  EXPECT_EQ(fm.GetCurrentStackLevel(), 0);
}

TEST_F(FunctionManagerTest, testIncreaseAndDecreaseStackLevel) {
  auto fm = dp::FunctionManager{};

  fm.IncreaseStackLevel();
  fm.IncreaseStackLevel();
  EXPECT_EQ(fm.GetCurrentStackLevel(), 2);

  fm.DecreaseStackLevel();
  EXPECT_EQ(fm.GetCurrentStackLevel(), 1);
}

TEST_F(FunctionManagerTest, testRegisterFunctionStartIncreasesStackLevel) {
  auto fm = dp::FunctionManager{};

  fm.RegisterFunctionStart(10);
  EXPECT_EQ(fm.GetCurrentStackLevel(), 1);

  fm.RegisterFunctionStart(20);
  EXPECT_EQ(fm.GetCurrentStackLevel(), 2);
}

// register_function_start groups the entered function under the LID of the
// call/invoke instruction that most recently triggered it (lastCallOrInvoke),
// falling back to the last processed line if no call was logged.
TEST_F(FunctionManagerTest, testRegisterFunctionStartGroupsByLastCallOrInvoke) {
  auto fm = dp::FunctionManager{};

  // no call logged yet -> falls back to the (default, 0) last processed line
  fm.RegisterFunctionStart(100);

  // a logged call becomes the grouping key for the next function start
  fm.LogCall(5);
  fm.RegisterFunctionStart(200);

  // reset_call clears the pending call and records the processed line, which
  // becomes the grouping key for the following, un-logged function start
  fm.ResetCall(7);
  fm.RegisterFunctionStart(300);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(0) + " BGN func " + dputil::DecodeLid(100)), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(200)), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(7) + " BGN func " + dputil::DecodeLid(300)), std::string::npos);
}

TEST_F(FunctionManagerTest, testRegisterFunctionEndOutput) {
  auto fm = dp::FunctionManager{};

  fm.RegisterFunctionEnd(42);
  fm.RegisterFunctionEnd(43);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(42) + " END func"), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(43) + " END func"), std::string::npos);
}

// A call site is not cleared by entering a function, so every function entered after one logged
// call is grouped under it -- the branch that adds to an existing entry rather than creating one.
TEST_F(FunctionManagerTest, testSeveralFunctionsAreGroupedUnderTheSameCallSite) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5);
  fm.RegisterFunctionStart(100);
  fm.RegisterFunctionStart(200);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100)), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(200)), std::string::npos);
}

// The same entry reached twice is one entry: the LIDs of a call site are kept in a set.
TEST_F(FunctionManagerTest, testTheSameFunctionEntryIsReportedOnce) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5);
  fm.RegisterFunctionStart(100);
  fm.RegisterFunctionStart(100);

  std::ostringstream out;
  fm.OutputFunctions(out);

  const auto line = dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100);
  const auto first = out.str().find(line);
  ASSERT_NE(first, std::string::npos);
  EXPECT_EQ(out.str().find(line, first + 1), std::string::npos);
}

// and the same for the returns, which are kept in a set of their own
TEST_F(FunctionManagerTest, testTheSameFunctionEndIsReportedOnce) {
  auto fm = dp::FunctionManager{};

  fm.RegisterFunctionEnd(42);
  fm.RegisterFunctionEnd(42);

  std::ostringstream out;
  fm.OutputFunctions(out);

  const auto line = dputil::DecodeLid(42) + " END func";
  const auto first = out.str().find(line);
  ASSERT_NE(first, std::string::npos);
  EXPECT_EQ(out.str().find(line, first + 1), std::string::npos);
}

// The manager keeps a small cache of the entries and returns it recorded recently. Many distinct entries and returns,
// which share the cache's slots, repeated and interleaved, must give the output of each one recorded once.
TEST_F(FunctionManagerTest, testManyRepeatedEntriesAndReturnsGiveTheOutputOfSingleOnes) {
  auto repeated = dp::FunctionManager{};
  auto single = dp::FunctionManager{};
  for (int round = 0; round < 3; ++round) {
    for (LID entry = 1; entry <= 10000; ++entry) {
      repeated.LogCall(entry % 7, static_cast<std::int32_t>(entry % 3));
      repeated.RegisterFunctionStart(entry % 5000);
      repeated.RegisterFunctionEnd(entry % 6000);
      if (round == 0 && entry <= 5000) {
        single.LogCall(entry % 7, static_cast<std::int32_t>(entry % 3));
        single.RegisterFunctionStart(entry % 5000);
        single.RegisterFunctionEnd(entry % 6000);
      }
    }
  }
  for (LID entry = 5001; entry <= 6000; ++entry) {
    single.RegisterFunctionEnd(entry % 6000);
  }
  for (LID entry = 5001; entry <= 10000; ++entry) {
    single.LogCall(entry % 7, static_cast<std::int32_t>(entry % 3));
    single.RegisterFunctionStart(entry % 5000);
  }

  std::ostringstream repeated_out;
  std::ostringstream single_out;
  repeated.OutputFunctions(repeated_out);
  single.OutputFunctions(single_out);
  std::multiset<std::string> repeated_lines;
  std::multiset<std::string> single_lines;
  std::istringstream repeated_in(repeated_out.str());
  std::istringstream single_in(single_out.str());
  for (std::string line; std::getline(repeated_in, line);) {
    repeated_lines.insert(line);
  }
  for (std::string line; std::getline(single_in, line);) {
    single_lines.insert(line);
  }
  EXPECT_EQ(repeated_lines.size(), 10000u + 6000u);
  EXPECT_EQ(repeated_lines, single_lines);
}

// one function entered from more call sites than the cache has slots: each call site is reported
TEST_F(FunctionManagerTest, testAFunctionEnteredFromManyCallSitesIsReportedForEach) {
  auto fm = dp::FunctionManager{};
  for (LID call_site = 1; call_site <= 20000; ++call_site) {
    fm.LogCall(call_site, 1);
    fm.RegisterFunctionStart(77);
    fm.LogCall(call_site, 2);
    fm.RegisterFunctionStart(77);
  }

  std::ostringstream out;
  fm.OutputFunctions(out);
  std::istringstream in(out.str());
  std::set<std::string> lines;
  for (std::string line; std::getline(in, line);) {
    lines.insert(line);
  }
  EXPECT_EQ(lines.size(), 40000u);
}

// reset_call is what __dp_read/__dp_write/__dp_func_exit call on every access: it drops the pending
// call site, so a function entered later is grouped under the line last seen instead.
TEST_F(FunctionManagerTest, testResetCallDropsThePendingCallSite) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5);
  fm.ResetCall(7);
  fm.RegisterFunctionStart(100);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(7) + " BGN func " + dputil::DecodeLid(100)), std::string::npos);
  EXPECT_EQ(output.find(dputil::DecodeLid(5) + " BGN func"), std::string::npos);
}

// unwind_function_stack() calls __dp_func_exit until the level has passed zero, and asserts on -1
TEST_F(FunctionManagerTest, testTheStackLevelGoesBelowZero) {
  auto fm = dp::FunctionManager{};

  fm.DecreaseStackLevel();

  EXPECT_EQ(fm.GetCurrentStackLevel(), -1);
}

TEST_F(FunctionManagerTest, testAFreshManagerReportsNothing) {
  auto fm = dp::FunctionManager{};

  std::ostringstream out;
  fm.OutputFunctions(out);

  EXPECT_EQ(out.str(), "");
}

// the two lists are written one after the other, every entry on a line of its own
TEST_F(FunctionManagerTest, testTheOutputIsOneLinePerEntry) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5);
  fm.RegisterFunctionStart(100);
  fm.RegisterFunctionEnd(200);

  std::ostringstream out;
  fm.OutputFunctions(out);

  EXPECT_EQ(out.str(), dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100) + "\n" + dputil::DecodeLid(200) +
                           " END func\n");
}

// __dp_func_exit and unwind_function_stack() only read the level, and writing the results only
// reads the two lists
TEST_F(FunctionManagerTest, testAManagerCanBeReadThroughAConstReference) {
  auto fm = dp::FunctionManager{};
  fm.LogCall(5);
  fm.RegisterFunctionStart(100);
  fm.RegisterFunctionEnd(200);

  const dp::FunctionManager &reference = fm;

  EXPECT_EQ(reference.GetCurrentStackLevel(), 1);

  std::ostringstream out;
  reference.OutputFunctions(out);
  EXPECT_NE(out.str().find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100)), std::string::npos);
}

// __dp_call logs the location of the call site and the instruction id of the call. The location
// names the call site, the instruction id follows the entered function as a fifth column, and a
// function entered without a logged call has none.
TEST_F(FunctionManagerTest, testTheCallInstructionIdFollowsTheEntry) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5, 34);
  fm.RegisterFunctionStart(100);
  fm.ResetCall(7);
  fm.RegisterFunctionStart(200);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100) + " 34\n"), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(7) + " BGN func " + dputil::DecodeLid(200) + "\n"), std::string::npos);
}

// one call site, two calls on it: they are told apart by their instruction ids
TEST_F(FunctionManagerTest, testTwoCallsOnOneLineAreKeptApart) {
  auto fm = dp::FunctionManager{};

  fm.LogCall(5, 34);
  fm.RegisterFunctionStart(100);
  fm.LogCall(5, 35);
  fm.RegisterFunctionStart(200);

  std::ostringstream out;
  fm.OutputFunctions(out);
  const auto output = out.str();

  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(100) + " 34\n"), std::string::npos);
  EXPECT_NE(output.find(dputil::DecodeLid(5) + " BGN func " + dputil::DecodeLid(200) + " 35\n"), std::string::npos);
}
