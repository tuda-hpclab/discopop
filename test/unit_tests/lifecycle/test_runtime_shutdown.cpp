#include <gtest/gtest.h>

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

#include "../../../profiler/rtlib/hybrid_analysis/bb_deps.hpp"
#include "../../../profiler/rtlib/lifecycle/runtime_shutdown.hpp"
#include "../../../profiler/rtlib/output_paths.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

using namespace __dp;

// The three steps __dp_finalize performs, in order. They run from the .fini_array entry of the
// runtime, after every handler the target registered with __cxa_atexit, and are the only place
// that turns what was profiled into the files the explorer reads. An end-to-end run reaches them
// but cannot observe them in isolation -- and a coverage build cannot even see them, because the
// profile is written before the finalization array is processed.
//
// The runtime is brought up here the way __dp_init does it for a target profiled without worker
// threads, into an output directory of this test's own.
class RuntimeShutdownTest : public ::testing::Test {
protected:
  void SetUp() override {
    previous_state = runtime_state;
    previous_num_workers = NUM_WORKERS;
    previous_out = out;
    previous_all_deps = allDeps;
    previous_output_deps = outPutDeps;
    previous_bb_list = bbList;
    previous_call_state_graph = call_state_graph;
    previous_shadow = singleThreadedExecutionSMem;
    previous_map = myMap;

    const char *const directory = getenv(output_directory_variable);
    had_output_directory = directory != nullptr;
    if (had_output_directory) {
      previous_output_directory = directory;
    }

    char pattern[] = "/tmp/discopop_shutdown_test_XXXXXX";
    ASSERT_NE(::mkdtemp(pattern), nullptr);
    output_directory = pattern;
    ASSERT_EQ(::mkdir((output_directory + "/statistics").c_str(), 0755), 0);
    setenv(output_directory_variable, output_directory.c_str(), 1);

    construct_immortal_globals();

    // no workers, so the accesses are analyzed in the calling thread and merged by the shutdown
    NUM_WORKERS = 0;
    initSingleThreadedExecution();

    // objects in the runtime's own storage rather than pointers, so a fresh set means
    // destroying whatever an earlier test left behind
    destroy_manager_globals();
    construct_manager_globals();
    call_state_graph = new CallStateGraph();

    allDeps = new depMap();
    outPutDeps = new stringDepMap();
    bbList = new ReportedBBRecorder();

    out = new std::ofstream();
    out->open(profiler_output_path("dynamic_dependencies.txt").c_str(), std::ios::out);
    ASSERT_TRUE(out->is_open());

    runtime_state = RuntimeState::Running;
  }

  void TearDown() override {
    // whatever the test under way did not release
    delete out;
    delete allDeps;
    delete outPutDeps;
    delete bbList;
    delete call_state_graph;
    delete singleThreadedExecutionSMem;
    delete myMap;

    // release_runtime() destroys them, and the rest of the suite expects them to exist
    construct_immortal_globals();
    construct_manager_globals();

    out = previous_out;
    allDeps = previous_all_deps;
    outPutDeps = previous_output_deps;
    bbList = previous_bb_list;
    call_state_graph = previous_call_state_graph;
    singleThreadedExecutionSMem = previous_shadow;
    myMap = previous_map;
    runtime_state = previous_state;
    NUM_WORKERS = previous_num_workers;

    remove_output_directory();

    if (had_output_directory) {
      setenv(output_directory_variable, previous_output_directory.c_str(), 1);
    } else {
      unsetenv(output_directory_variable);
    }
  }

  std::string read_output(const std::string &file) const {
    std::ifstream written(output_directory + "/" + file);
    std::stringstream contents;
    contents << written.rdbuf();
    return contents.str();
  }

  bool output_exists(const std::string &file) const {
    struct stat unused = {};
    return ::stat((output_directory + "/" + file).c_str(), &unused) == 0;
  }

  static constexpr const char *output_directory_variable = "DOT_DISCOPOP_PROFILER";

private:
  void remove_output_directory() const {
    for (const char *const file : {"dynamic_dependencies.txt", "loop_meta.txt", "loop_counter_output.txt",
                                   "cu_taken_branch_counter_output.txt", "memory_regions.txt"}) {
      ::remove((output_directory + "/" + file).c_str());
    }
    ::remove((output_directory + "/statistics/profiling_time.txt").c_str());
    ::rmdir((output_directory + "/statistics").c_str());
    ::rmdir(output_directory.c_str());
  }

  std::string output_directory;
  bool had_output_directory = false;
  std::string previous_output_directory;

  RuntimeState previous_state = RuntimeState::NotInitialized;
  std::int32_t previous_num_workers = 0;
  std::ofstream *previous_out = nullptr;
  depMap *previous_all_deps = nullptr;
  stringDepMap *previous_output_deps = nullptr;
  ReportedBBRecorder *previous_bb_list = nullptr;
  CallStateGraph *previous_call_state_graph = nullptr;
  AbstractShadow *previous_shadow = nullptr;
  depMap *previous_map = nullptr;
};

// A target that leaves through exit() is still inside every function it was called from, and each
// of them has to be reported as left before the functions are written out.
TEST_F(RuntimeShutdownTest, testUnwindingReportsAnExitForEveryFunctionStillEntered) {
  function_manager->increase_stack_level();
  function_manager->increase_stack_level();

  unwind_function_stack(0);

  EXPECT_EQ(function_manager->get_current_stack_level(), -1);
}

// A function manager starts at level 0, which is the entry of the outermost function, so even a
// target that announced nothing is left once.
TEST_F(RuntimeShutdownTest, testUnwindingATargetThatEnteredNothingStillPassesTheBase) {
  ASSERT_EQ(function_manager->get_current_stack_level(), 0);

  unwind_function_stack(0);

  EXPECT_EQ(function_manager->get_current_stack_level(), -1);
}

TEST_F(RuntimeShutdownTest, testUnwindingEmptiesTheLoopStack) {
  function_manager->increase_stack_level();

  unwind_function_stack(0);

  EXPECT_TRUE(loop_manager->empty());
}

TEST_F(RuntimeShutdownTest, testTheDependencyFileEndsWithTheEndOfTheProgram) {
  write_results(0);

  EXPECT_NE(read_output("dynamic_dependencies.txt").find("* END program"), std::string::npos);
}

TEST_F(RuntimeShutdownTest, testTheRecordedDependenciesReachTheDependencyFile) {
  (*myMap)[10].insert(Dep(RAW, 7, "x", 3));

  write_results(0);

  EXPECT_NE(read_output("dynamic_dependencies.txt").find("10@0 NOM  RAW 7@0|x(3)"), std::string::npos);
}

// the basic blocks whose instructions the pass omitted are only known to be complete now
TEST_F(RuntimeShutdownTest, testTheStaticallyDeterminedDependenciesReachTheDependencyFile) {
  bbList->record(4, 0, 0);
  registered_bb_dep_strings().push_back("4=10 NOM RAW 7|x(3)");

  write_results(0);

  EXPECT_NE(read_output("dynamic_dependencies.txt").find("10@0 NOM  RAW 7@0|x(3)"), std::string::npos);
}

TEST_F(RuntimeShutdownTest, testTheProfilingTimeIsWritten) {
  write_results(0);

  EXPECT_NE(read_output("statistics/profiling_time.txt").find(" ms"), std::string::npos);
}

TEST_F(RuntimeShutdownTest, testTheAllocationsAreWritten) {
  write_results(0);

  EXPECT_TRUE(output_exists("memory_regions.txt"));
}

TEST_F(RuntimeShutdownTest, testTheLoopCountersAreWritten) {
  write_results(0);

  EXPECT_TRUE(output_exists("loop_counter_output.txt"));
}

// the loop counters are dumped once; a second shutdown must not overwrite them with nothing
TEST_F(RuntimeShutdownTest, testTheLoopCountersAreReportedAsDoneAfterwards) {
  write_results(0);

  EXPECT_TRUE(loop_manager->is_done());
}

// __dp_incr_taken_branch_counter only exists in a pass built with DP_BRANCH_TRACKING, and an
// empty report would claim that every branch went untaken
TEST_F(RuntimeShutdownTest, testNoBranchCountersAreWrittenWhenNoneWereCounted) {
  write_results(0);

  EXPECT_FALSE(output_exists("cu_taken_branch_counter_output.txt"));
}

TEST_F(RuntimeShutdownTest, testTheCountedBranchesAreWritten) {
  char branch[] = "7";
  cuec[branch] = 3;

  write_results(0);

  EXPECT_NE(read_output("cu_taken_branch_counter_output.txt").find(";3"), std::string::npos);
}

TEST_F(RuntimeShutdownTest, testReleasingTheRuntimeDropsEverythingItCreated) {
  release_runtime();

  EXPECT_FALSE(manager_globals_constructed());
  EXPECT_EQ(call_state_graph, nullptr);
  EXPECT_EQ(allDeps, nullptr);
  EXPECT_EQ(outPutDeps, nullptr);
  EXPECT_EQ(bbList, nullptr);
  EXPECT_EQ(out, nullptr);
}

// after this every callback returns without doing anything, which is what the instrumented
// destructors of the target's globals run into
TEST_F(RuntimeShutdownTest, testReleasingTheRuntimeStopsProfiling) {
  release_runtime();

  EXPECT_EQ(runtime_state, RuntimeState::Terminated);
  EXPECT_FALSE(profiling_active());
}

TEST_F(RuntimeShutdownTest, testReleasingTheRuntimeDropsTheRegisteredBasicBlockDependencies) {
  registered_bb_dep_strings().push_back("4=10 NOM RAW 7|x(3)");

  release_runtime();

  EXPECT_TRUE(registered_bb_dep_strings().empty());
}
