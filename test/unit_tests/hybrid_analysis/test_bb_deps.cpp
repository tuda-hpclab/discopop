#include <gtest/gtest.h>

#include <cstdlib>
#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

#include "../../../profiler/rtlib/injected_functions/dp_add_bb_deps.hpp"
#include "../../../profiler/rtlib/injected_functions/dp_report_bb.hpp"
#include "../../../profiler/rtlib/injected_functions/dp_report_bb_pair.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

// The hybrid analysis hands the dependencies of stack locals over as strings
// "<bb index>=<dep>,<dep>/<bb index>=..." (one per module) and reports the
// executions of the basic blocks holding their sinks. These tests check that
// each reported execution carries the callpath states of both ends, and that
// the merge turns them into records in the notation of the dynamically
// profiled dependencies ("<instruction id>@<callpath state id>").
class HybridAnalysisBBDepsTest : public ::testing::Test {
protected:
  std::unique_ptr<CallStateGraph> graph;
  bool saved_dp_inited = false;
  bool saved_target_terminated = false;
  __dp::ReportedBBRecorder *saved_bb_list = nullptr;
  CallState *saved_state = nullptr;

  void SetUp() override {
    setenv("DOT_DISCOPOP_PROFILER", "/tmp/discopop_ut_nonexistent_dir", 1);
    graph = std::make_unique<CallStateGraph>();

    saved_dp_inited = __dp::dpInited;
    saved_target_terminated = __dp::targetTerminated;
    saved_bb_list = __dp::bbList;
    saved_state = __dp::current_callpath_state;

    __dp::dpInited = true;
    __dp::targetTerminated = false;
    __dp::bbList = new __dp::ReportedBBRecorder();
    enter_state(7);
  }

  void TearDown() override {
    delete __dp::bbList;
    __dp::bbList = saved_bb_list;
    __dp::dpInited = saved_dp_inited;
    __dp::targetTerminated = saved_target_terminated;
    __dp::current_callpath_state = saved_state;
  }

  void enter_state(std::int32_t id) { __dp::current_callpath_state = graph->get_or_register_node(id); }

  static std::unordered_set<std::string> records_of(const __dp::stringDepMap &deps, const std::string &sink) {
    const auto it = deps.find(sink);
    return it == deps.end() ? std::unordered_set<std::string>() : it->second;
  }
};

TEST_F(HybridAnalysisBBDepsTest, testReportBBGivesBothEndsTheCurrentState) {
  __dp::__dp_report_bb(3);

  ASSERT_EQ(__dp::bbList->get_executions().size(), 1u);
  EXPECT_EQ(*__dp::bbList->get_executions().begin(), (__dp::ReportedBB{3, 7, 7}));
}

TEST_F(HybridAnalysisBBDepsTest, testBBStateIsCurrentStatePlusOne) {
  EXPECT_EQ(__dp::__dp_bb_state(), 8u);
  enter_state(0);
  EXPECT_EQ(__dp::__dp_bb_state(), 1u); // state 0 still counts as executed
}

TEST_F(HybridAnalysisBBDepsTest, testBBStateIsZeroWithoutKnownState) {
  __dp::current_callpath_state = nullptr;
  EXPECT_EQ(__dp::__dp_bb_state(), 0u);
  enter_state(7);
  __dp::dpInited = false;
  EXPECT_EQ(__dp::__dp_bb_state(), 0u);
  __dp::dpInited = true;
  __dp::targetTerminated = true;
  EXPECT_EQ(__dp::__dp_bb_state(), 0u);
}

TEST_F(HybridAnalysisBBDepsTest, testReportBBPairIgnoresUnexecutedSource) {
  __dp::__dp_report_bb_pair(0, 4);
  EXPECT_TRUE(__dp::bbList->get_executions().empty());
}

TEST_F(HybridAnalysisBBDepsTest, testReportBBPairTakesSourceStateFromSemaphore) {
  // the source block executes in state 7 (e.g. iteration bucket 0) ...
  const std::int32_t semaphore = (std::int32_t)__dp::__dp_bb_state();
  // ... the sink block in the next iteration (state 8)
  enter_state(8);
  __dp::__dp_report_bb_pair(semaphore, 4);

  ASSERT_EQ(__dp::bbList->get_executions().size(), 1u);
  EXPECT_EQ(*__dp::bbList->get_executions().begin(), (__dp::ReportedBB{4, 7, 8}));
}

TEST_F(HybridAnalysisBBDepsTest, testReportsAreIgnoredOutsideOfTheProfiledRun) {
  __dp::dpInited = false;
  __dp::__dp_report_bb(1);
  __dp::__dp_report_bb_pair(8, 2);
  __dp::dpInited = true;
  __dp::targetTerminated = true;
  __dp::__dp_report_bb(1);
  __dp::__dp_report_bb_pair(8, 2);
  EXPECT_TRUE(__dp::bbList->get_executions().empty());
}

TEST_F(HybridAnalysisBBDepsTest, testRepeatedExecutionsInTheSameStatesAreRecordedOnce) {
  for (int i = 0; i < 5; ++i) {
    __dp::__dp_report_bb(3);
    __dp::__dp_report_bb_pair(8, 4);
  }
  EXPECT_EQ(__dp::bbList->get_executions().size(), 2u);
}

TEST_F(HybridAnalysisBBDepsTest, testRecorderKeepsEveryDistinctExecution) {
  // repeated executions in recurring states, interleaved between basic blocks,
  // and enough distinct ones to make the recorder's table grow several times
  __dp::ReportedBBRecorder recorder;
  __dp::ReportedBBSet expected;
  for (int round = 0; round < 3; ++round) {
    for (std::uint32_t state = 0; state < 3000; ++state) {
      recorder.record(2, state, state + 1);
      recorder.record(5, 9, state % 7);
      if (round == 0) {
        expected.insert(__dp::ReportedBB{2, state, state + 1});
        expected.insert(__dp::ReportedBB{5, 9, state % 7});
      }
    }
  }
  // the pair of states (0, 0) of basic block 0 is an ordinary entry
  recorder.record(0, 0, 0);
  expected.insert(__dp::ReportedBB{0, 0, 0});

  EXPECT_EQ(recorder.size(), expected.size());
  EXPECT_EQ(recorder.get_executions(), expected);
}

TEST_F(HybridAnalysisBBDepsTest, testMergeAddsStatesToSinkAndSource) {
  const std::vector<const char *> strings = {"0=36 NOM RAW 38|s(S2),35 NOM RAW 34|t(S4)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{0, 29, 27}};
  __dp::stringDepMap out;

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(out.size(), 2u);
  EXPECT_EQ(records_of(out, "36@27"), (std::unordered_set<std::string>{"RAW 38@29|s(S2)"}));
  EXPECT_EQ(records_of(out, "35@27"), (std::unordered_set<std::string>{"RAW 34@29|t(S4)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeKeepsInitWithoutSource) {
  const std::vector<const char *> strings = {"5=34 NOM INIT *|t(S4)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{5, 28, 28}};
  __dp::stringDepMap out;

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(records_of(out, "34@28"), (std::unordered_set<std::string>{"INIT *|t(S4)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeEmitsOneRecordPerReportedStatePair) {
  // a loop-carried dependency of a loop with iteration buckets 27, 28, 29
  const std::vector<const char *> strings = {"2=36 NOM RAW 38|s(S2)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{2, 27, 28}, __dp::ReportedBB{2, 28, 29},
                                        __dp::ReportedBB{2, 29, 27}};
  __dp::stringDepMap out;

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(out.size(), 3u);
  EXPECT_EQ(records_of(out, "36@27"), (std::unordered_set<std::string>{"RAW 38@29|s(S2)"}));
  EXPECT_EQ(records_of(out, "36@28"), (std::unordered_set<std::string>{"RAW 38@27|s(S2)"}));
  EXPECT_EQ(records_of(out, "36@29"), (std::unordered_set<std::string>{"RAW 38@28|s(S2)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeSkipsUnreportedBlocksAndCombinesModules) {
  // two modules, numbered consecutively (DP_BBDepCounter.txt)
  const std::vector<const char *> strings = {"0=10 NOM RAW 9|x(S0)/1=11 NOM WAR 10|x(S0)",
                                             "2=20 NOM WAW 20|y(S1)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{1, 3, 3}, __dp::ReportedBB{2, 4, 5}};
  __dp::stringDepMap out;

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(out.size(), 2u);
  EXPECT_TRUE(records_of(out, "10@3").empty());
  EXPECT_EQ(records_of(out, "11@3"), (std::unordered_set<std::string>{"WAR 10@3|x(S0)"}));
  EXPECT_EQ(records_of(out, "20@5"), (std::unordered_set<std::string>{"WAW 20@4|y(S1)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeJoinsExistingRecordsOfTheSameSink) {
  const std::vector<const char *> strings = {"0=36 NOM RAW 20|s(S2)", "1=36 NOM RAW 38|s(S2)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{0, 26, 27}, __dp::ReportedBB{1, 29, 27}};
  __dp::stringDepMap out;
  out["36@27"].insert("RAW 12@27|other(1234)");

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(records_of(out, "36@27"),
            (std::unordered_set<std::string>{"RAW 12@27|other(1234)", "RAW 20@26|s(S2)", "RAW 38@29|s(S2)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeSkipsMalformedEntries) {
  const std::vector<const char *> strings = {nullptr, "x=1 NOM RAW 2|a(S0)/3=garbage,4 NOM RAW 5|b(S1)/=6 NOM RAW 7|c(S2)"};
  const __dp::ReportedBBSet reported = {__dp::ReportedBB{3, 1, 1}};
  __dp::stringDepMap out;

  __dp::merge_bb_deps(strings, reported, out);

  EXPECT_EQ(out.size(), 1u);
  EXPECT_EQ(records_of(out, "4@1"), (std::unordered_set<std::string>{"RAW 5@1|b(S1)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testProcessRegisteredBBDepsUsesReportedExecutions) {
  // what __dp_finalize does: the strings registered by the module constructors
  // are merged with the executions reported during the run
  static const char dep_string[] = "900001=36 NOM RAW 38|s(S2)";
  __dp::__dp_add_bb_deps(const_cast<char *>(dep_string));
  const std::int32_t semaphore = (std::int32_t)__dp::__dp_bb_state();
  enter_state(8);
  __dp::__dp_report_bb_pair(semaphore, 900001);

  __dp::stringDepMap *saved_out = __dp::outPutDeps;
  __dp::outPutDeps = new __dp::stringDepMap();
  __dp::process_registered_bb_deps();
  const auto records = records_of(*__dp::outPutDeps, "36@8");
  delete __dp::outPutDeps;
  __dp::outPutDeps = saved_out;

  EXPECT_EQ(records, (std::unordered_set<std::string>{"RAW 38@7|s(S2)"}));
}
