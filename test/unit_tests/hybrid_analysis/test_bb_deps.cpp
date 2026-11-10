#include <gtest/gtest.h>

#include <cstdlib>
#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

#include "injected_functions/dp_add_bb_deps.hpp"
#include "injected_functions/dp_report_bb.hpp"
#include "injected_functions/dp_report_bb_pair.hpp"
#include "hybrid_analysis/bb_deps.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "static_callstate_transitions/utils.hpp"

// The hybrid analysis hands the dependencies of stack locals over as strings
// "<bb index>=<dep>,<dep>/<bb index>=..." (one per module) and reports the
// executions of the basic blocks holding their sinks. These tests check that
// each reported execution carries the callpath states of both ends, and that
// the merge turns them into records in the notation of the dynamically
// profiled dependencies ("<instruction id>@<callpath state id>").
class HybridAnalysisBBDepsTest : public ::testing::Test {
protected:
  std::unique_ptr<CallStateGraph> graph;
  dp::RuntimeState saved_runtime_state = dp::RuntimeState::kNotInitialized;
  dp::ReportedBBRecorder *saved_bb_list = nullptr;
  CallState *saved_state = nullptr;

  void SetUp() override {
    setenv("DOT_DISCOPOP_PROFILER", "/tmp/discopop_ut_nonexistent_dir", 1);
    graph = std::make_unique<CallStateGraph>();

    saved_runtime_state = dp::runtime_state;
    saved_bb_list = dp::bb_list;
    saved_state = dp::current_callpath_state;

    dp::runtime_state = dp::RuntimeState::kRunning;
    dp::bb_list = new dp::ReportedBBRecorder();
    enter_state(7);
  }

  void TearDown() override {
    delete dp::bb_list;
    dp::bb_list = saved_bb_list;
    dp::runtime_state = saved_runtime_state;
    dp::SetCurrentCallpathState(saved_state);
  }

  void enter_state(std::int32_t id) { dp::SetCurrentCallpathState(graph->GetOrRegisterNode(id)); }

  static std::unordered_set<std::string> records_of(const dp::StringDepMap &deps, const std::string &sink) {
    const auto it = deps.find(sink);
    return it == deps.end() ? std::unordered_set<std::string>() : it->second;
  }
};

TEST_F(HybridAnalysisBBDepsTest, testReportBBGivesBothEndsTheCurrentState) {
  dp::__dp_report_bb(3);

  ASSERT_EQ(dp::bb_list->GetExecutions().size(), 1u);
  EXPECT_EQ(*dp::bb_list->GetExecutions().begin(), (dp::ReportedBB{3, 7, 7}));
}

TEST_F(HybridAnalysisBBDepsTest, testBBStateIsCurrentStatePlusOne) {
  EXPECT_EQ(dp::__dp_bb_state(), 8u);
  enter_state(0);
  EXPECT_EQ(dp::__dp_bb_state(), 1u); // state 0 still counts as executed
}

TEST_F(HybridAnalysisBBDepsTest, testBBStateIsZeroWithoutKnownState) {
  dp::SetCurrentCallpathState(nullptr);
  EXPECT_EQ(dp::__dp_bb_state(), 0u);
  enter_state(7);
  dp::runtime_state = dp::RuntimeState::kNotInitialized;
  EXPECT_EQ(dp::__dp_bb_state(), 0u);
  dp::runtime_state = dp::RuntimeState::kTerminated;
  EXPECT_EQ(dp::__dp_bb_state(), 0u);
}

TEST_F(HybridAnalysisBBDepsTest, testReportBBPairIgnoresUnexecutedSource) {
  dp::__dp_report_bb_pair(0, 4);
  EXPECT_TRUE(dp::bb_list->GetExecutions().empty());
}

TEST_F(HybridAnalysisBBDepsTest, testReportBBPairTakesSourceStateFromSemaphore) {
  // the source block executes in state 7 (e.g. iteration bucket 0) ...
  const std::int32_t semaphore = (std::int32_t)dp::__dp_bb_state();
  // ... the sink block in the next iteration (state 8)
  enter_state(8);
  dp::__dp_report_bb_pair(semaphore, 4);

  ASSERT_EQ(dp::bb_list->GetExecutions().size(), 1u);
  EXPECT_EQ(*dp::bb_list->GetExecutions().begin(), (dp::ReportedBB{4, 7, 8}));
}

TEST_F(HybridAnalysisBBDepsTest, testReportsAreIgnoredOutsideOfTheProfiledRun) {
  dp::runtime_state = dp::RuntimeState::kNotInitialized;
  dp::__dp_report_bb(1);
  dp::__dp_report_bb_pair(8, 2);
  dp::runtime_state = dp::RuntimeState::kTerminated;
  dp::__dp_report_bb(1);
  dp::__dp_report_bb_pair(8, 2);
  EXPECT_TRUE(dp::bb_list->GetExecutions().empty());
}

TEST_F(HybridAnalysisBBDepsTest, testRepeatedExecutionsInTheSameStatesAreRecordedOnce) {
  for (int i = 0; i < 5; ++i) {
    dp::__dp_report_bb(3);
    dp::__dp_report_bb_pair(8, 4);
  }
  EXPECT_EQ(dp::bb_list->GetExecutions().size(), 2u);
}

TEST_F(HybridAnalysisBBDepsTest, testRecorderKeepsEveryDistinctExecution) {
  // repeated executions in recurring states, interleaved between basic blocks,
  // and enough distinct ones to make the recorder's table grow several times
  dp::ReportedBBRecorder recorder;
  dp::ReportedBBSet expected;
  for (int round = 0; round < 3; ++round) {
    for (std::uint32_t state = 0; state < 3000; ++state) {
      recorder.Record(2, state, state + 1);
      recorder.Record(5, 9, state % 7);
      if (round == 0) {
        expected.insert(dp::ReportedBB{2, state, state + 1});
        expected.insert(dp::ReportedBB{5, 9, state % 7});
      }
    }
  }
  // the pair of states (0, 0) of basic block 0 is an ordinary entry
  recorder.Record(0, 0, 0);
  expected.insert(dp::ReportedBB{0, 0, 0});

  EXPECT_EQ(recorder.size(), expected.size());
  EXPECT_EQ(recorder.GetExecutions(), expected);
}

// The recorder answers repeated reports from a small cache per sink state, indexed by the low bits of the block
// index: blocks sharing a cache entry (indices 64 apart), several source states of one block, many sink states and
// a sink state with a high id must still be recorded exactly once each.
TEST_F(HybridAnalysisBBDepsTest, testRecorderKeepsExecutionsThatShareACacheEntry) {
  dp::ReportedBBRecorder recorder;
  dp::ReportedBBSet expected;
  for (int round = 0; round < 3; ++round) {
    for (std::uint32_t sink = 0; sink < 40; ++sink) {
      const std::uint32_t sink_state = sink == 39 ? 1000000 : sink;
      for (std::uint32_t bb = 0; bb < 4; ++bb) {
        for (std::uint32_t source = 0; source < 3; ++source) {
          const std::uint32_t bb_index = 5 + 64 * bb;
          recorder.Record(bb_index, source + sink_state, sink_state);
          expected.insert(dp::ReportedBB{bb_index, source + sink_state, sink_state});
        }
      }
    }
  }
  recorder.Record(0, 0, 0);
  expected.insert(dp::ReportedBB{0, 0, 0});

  EXPECT_EQ(recorder.size(), expected.size());
  EXPECT_EQ(recorder.GetExecutions(), expected);
}

namespace {
constexpr std::size_t kPointerBytes = sizeof(void *);
constexpr std::size_t kTableBytes = 64 * 8 + 4;  // a table of 64 entries and its owner
}  // namespace

// The caches in front of the recorder's table are bounded by their allowance: without caches, with room for a
// single table and with room for a few tables (at the limit, states go without a table, and the tables are
// discarded when their reports pile up), every distinct execution is still recorded exactly once.
TEST_F(HybridAnalysisBBDepsTest, testRecorderKeepsEveryExecutionWithinASmallCacheAllowance) {
  constexpr std::size_t kStates = 300;
  for (const std::size_t tables : {std::size_t{0}, std::size_t{1}, std::size_t{4}}) {
    const std::size_t cache_bytes = tables == 0 ? 0 : kStates * kPointerBytes + tables * kTableBytes;
    dp::ReportedBBRecorder recorder(cache_bytes, kStates);
    dp::ReportedBBSet expected;
    for (int round = 0; round < 3; ++round) {
      for (std::uint32_t sink_state = 0; sink_state < kStates; sink_state += 7) {
        for (std::uint32_t bb_index = 0; bb_index < 130; bb_index += 3) {
          for (const std::uint32_t source_state : {std::uint32_t{1}, sink_state % 5}) {
            recorder.Record(bb_index, source_state, sink_state);
            expected.insert(dp::ReportedBB{bb_index, source_state, sink_state});
          }
        }
      }
    }
    EXPECT_EQ(recorder.size(), expected.size()) << tables;
    EXPECT_EQ(recorder.GetExecutions(), expected) << tables;
    EXPECT_LE(recorder.CacheBytes(), cache_bytes) << tables;
    if (tables == 0) {
      EXPECT_EQ(recorder.CacheResets(), 0u);
    } else {
      EXPECT_GT(recorder.CacheResets(), 0u) << tables;  // the tables were discarded and taken again
    }
  }
}

// room for one table: a state whose table was discarded must not find the entries of the state that takes it next
TEST_F(HybridAnalysisBBDepsTest, testRecorderForgetsTheCacheOfAStateThatWasDiscarded) {
  dp::ReportedBBRecorder recorder(2 * kPointerBytes + kTableBytes, 2);
  recorder.Record(5, 1, 0);  // state 0 takes the only table
  // state 1 goes without a table until its reports pile up (4 refills of the table), then the table is discarded
  for (std::uint32_t reports = 0; recorder.CacheResets() == 0; ++reports) {
    ASSERT_LT(reports, 10000u) << "the table was never discarded";
    recorder.Record(reports % 64, 3, 1);
  }
  recorder.Record(5, 2, 1);  // state 1 takes the table
  recorder.Record(5, 2, 0);  // new for state 0, although the table holds block 5 with source state 2

  EXPECT_EQ(recorder.GetExecutions().count(dp::ReportedBB{5, 2, 0}), 1u);
  EXPECT_EQ(recorder.GetExecutions().count(dp::ReportedBB{5, 1, 0}), 1u);
  EXPECT_EQ(recorder.GetExecutions().count(dp::ReportedBB{5, 2, 1}), 1u);
}

TEST_F(HybridAnalysisBBDepsTest, testRecorderCachesNeverExceedTheirAllowance) {
  // too small for the table pointers of the states and one table: no caches
  EXPECT_EQ(dp::ReportedBBRecorder(1000 * kPointerBytes + kTableBytes - 1, 1000).CacheBytes(), 0u);
  for (const std::size_t allowance : {std::size_t{1} << 14, std::size_t{1} << 20, std::size_t{50} << 20}) {
    dp::ReportedBBRecorder recorder(allowance, 1000);
    EXPECT_LE(recorder.CacheBytes(), allowance) << allowance;
    for (std::uint32_t sink_state = 0; sink_state < 5000; sink_state += 3) {  // ids above 999 get no cache
      recorder.Record(sink_state % 100, 0, sink_state);
      ASSERT_LE(recorder.CacheBytes(), allowance) << allowance << " " << sink_state;
    }
  }
  EXPECT_LE(dp::ReportedBBRecorder().CacheBytes(), dp::ReportedBBRecorder::kDefaultCacheBytes);
}

// When the caches are off, the warning tells how to turn them on, with an estimate of the allowance they need.
TEST_F(HybridAnalysisBBDepsTest, testTheWarningAboutTurnedOffCachesEstimatesTheirAllowance) {
  // 10M states: 80 MB of table pointers, tables for 625001 states (322.5 MB): 384 MiB
  EXPECT_EQ(dp::ReportedBBRecorder::RecommendedCacheMb(10000000), 384u);
  EXPECT_EQ(dp::ReportedBBRecorder::RecommendedCacheMb(1000), 50u);  // never less than the default
  testing::internal::CaptureStderr();
  dp::ReportedBBRecorder recorder(std::size_t{50} << 20, 10000000);
  const std::string warning = testing::internal::GetCapturedStderr();
  EXPECT_EQ(recorder.CacheBytes(), 0u);
  EXPECT_NE(warning.find("turned off (BB_REPORT_CACHE_MB=50 in dp.conf; the program has 10000000 callpath states, "
                         "the caches need 77 MiB at least)"),
            std::string::npos)
      << warning;
  EXPECT_NE(warning.find("set BB_REPORT_CACHE_MB=384 (MiB, an estimate) in the file dp.conf"), std::string::npos)
      << warning;
}

// A state without a table at the limit does not take one from a state that has one, as long as the reports of the
// states without a table do not pile up.
TEST_F(HybridAnalysisBBDepsTest, testRecorderKeepsTheTablesWhileFewReportsGoWithoutOne) {
  dp::ReportedBBRecorder recorder(3 * kPointerBytes + kTableBytes, 3);
  recorder.Record(1, 0, 0);
  for (std::uint32_t i = 0; i < 64; ++i) {
    recorder.Record(i, 0, 2);  // state 2 goes without a table
  }
  EXPECT_EQ(recorder.CacheResets(), 0u);
}

TEST_F(HybridAnalysisBBDepsTest, testMergeAddsStatesToSinkAndSource) {
  const std::vector<const char *> strings = {"0=36 NOM RAW 38|s(S2),35 NOM RAW 34|t(S4)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{0, 29, 27}};
  dp::StringDepMap out;

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(out.size(), 2u);
  EXPECT_EQ(records_of(out, "36@27"), (std::unordered_set<std::string>{"RAW 38@29|s(S2)"}));
  EXPECT_EQ(records_of(out, "35@27"), (std::unordered_set<std::string>{"RAW 34@29|t(S4)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeKeepsInitWithoutSource) {
  const std::vector<const char *> strings = {"5=34 NOM INIT *|t(S4)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{5, 28, 28}};
  dp::StringDepMap out;

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(records_of(out, "34@28"), (std::unordered_set<std::string>{"INIT *|t(S4)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeEmitsOneRecordPerReportedStatePair) {
  // a loop-carried dependency of a loop with iteration buckets 27, 28, 29
  const std::vector<const char *> strings = {"2=36 NOM RAW 38|s(S2)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{2, 27, 28}, dp::ReportedBB{2, 28, 29},
                                        dp::ReportedBB{2, 29, 27}};
  dp::StringDepMap out;

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(out.size(), 3u);
  EXPECT_EQ(records_of(out, "36@27"), (std::unordered_set<std::string>{"RAW 38@29|s(S2)"}));
  EXPECT_EQ(records_of(out, "36@28"), (std::unordered_set<std::string>{"RAW 38@27|s(S2)"}));
  EXPECT_EQ(records_of(out, "36@29"), (std::unordered_set<std::string>{"RAW 38@28|s(S2)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeSkipsUnreportedBlocksAndCombinesModules) {
  // two modules, numbered consecutively (DP_BBDepCounter.txt)
  const std::vector<const char *> strings = {"0=10 NOM RAW 9|x(S0)/1=11 NOM WAR 10|x(S0)",
                                             "2=20 NOM WAW 20|y(S1)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{1, 3, 3}, dp::ReportedBB{2, 4, 5}};
  dp::StringDepMap out;

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(out.size(), 2u);
  EXPECT_TRUE(records_of(out, "10@3").empty());
  EXPECT_EQ(records_of(out, "11@3"), (std::unordered_set<std::string>{"WAR 10@3|x(S0)"}));
  EXPECT_EQ(records_of(out, "20@5"), (std::unordered_set<std::string>{"WAW 20@4|y(S1)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeJoinsExistingRecordsOfTheSameSink) {
  const std::vector<const char *> strings = {"0=36 NOM RAW 20|s(S2)", "1=36 NOM RAW 38|s(S2)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{0, 26, 27}, dp::ReportedBB{1, 29, 27}};
  dp::StringDepMap out;
  out["36@27"].insert("RAW 12@27|other(1234)");

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(records_of(out, "36@27"),
            (std::unordered_set<std::string>{"RAW 12@27|other(1234)", "RAW 20@26|s(S2)", "RAW 38@29|s(S2)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testMergeSkipsMalformedEntries) {
  const std::vector<const char *> strings = {nullptr, "x=1 NOM RAW 2|a(S0)/3=garbage,4 NOM RAW 5|b(S1)/=6 NOM RAW 7|c(S2)"};
  const dp::ReportedBBSet reported = {dp::ReportedBB{3, 1, 1}};
  dp::StringDepMap out;

  dp::MergeBbDeps(strings, reported, out);

  EXPECT_EQ(out.size(), 1u);
  EXPECT_EQ(records_of(out, "4@1"), (std::unordered_set<std::string>{"RAW 5@1|b(S1)"}));
}

TEST_F(HybridAnalysisBBDepsTest, testProcessRegisteredBBDepsUsesReportedExecutions) {
  // what __dp_finalize does: the strings registered by the module constructors
  // are merged with the executions reported during the run
  static const char dep_string[] = "900001=36 NOM RAW 38|s(S2)";
  dp::__dp_add_bb_deps(const_cast<char *>(dep_string));
  const std::int32_t semaphore = (std::int32_t)dp::__dp_bb_state();
  enter_state(8);
  dp::__dp_report_bb_pair(semaphore, 900001);

  dp::StringDepMap *saved_out = dp::out_put_deps;
  dp::out_put_deps = new dp::StringDepMap();
  dp::ProcessRegisteredBbDeps();
  const auto records = records_of(*dp::out_put_deps, "36@8");
  delete dp::out_put_deps;
  dp::out_put_deps = saved_out;

  EXPECT_EQ(records, (std::unordered_set<std::string>{"RAW 38@7|s(S2)"}));
}
