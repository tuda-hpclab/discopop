#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/static_callstate_transitions/utils.hpp"

// update_callstate{,_from_call,_from_func_exit} operate on the global
// __dp::current_callpath_state / __dp::calls_without_executed_transitions.
// Each test builds a small, deterministic transition graph
// (1 --10--> 2 --20--> 3) and installs it into those globals before running.
// Constructing the graph from a directory without profiler output reports the
// missing input files on stderr; that output is expected here.
class CallStateTransitionsUtilsTest : public ::testing::Test {
protected:
  std::unique_ptr<CallStateGraph> graph;

  void SetUp() override {
    setenv("DOT_DISCOPOP_PROFILER", "/tmp/discopop_ut_nonexistent_dir", 1);

    graph = std::make_unique<CallStateGraph>();
    graph->register_transition(1, 10, 2);
    graph->register_transition(2, 20, 3);

    __dp::current_callpath_state = graph->get_or_register_node(1);
    __dp::calls_without_executed_transitions.clear();
    __dp::calls_without_executed_transitions.push_back(0);
  }

  void TearDown() override {
    __dp::current_callpath_state = nullptr;
    __dp::calls_without_executed_transitions.clear();
  }
};

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFollowsExistingTransition) {
  __dp::update_callstate(10);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 2);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateIgnoresUnknownTrigger) {
  __dp::update_callstate(999);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFromCallFollowsTransitionAndPushesDepth) {
  __dp::update_callstate_from_call(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 2);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 2u);
  EXPECT_EQ(__dp::calls_without_executed_transitions.back(), 0u);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFromCallWithoutTransitionDisablesTransitioning) {
  __dp::update_callstate_from_call(999);

  // state is unchanged, but further transitions are disabled until the call returns
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 1u);
  EXPECT_EQ(__dp::calls_without_executed_transitions.back(), 1u);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFromFuncExitReversesCall) {
  __dp::update_callstate_from_call(10);
  __dp::update_callstate_from_func_exit(20);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 3);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 1u);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFromFuncExitDecrementsDisabledCounter) {
  __dp::update_callstate_from_call(999);       // no transition -> disables transitioning, counter = 1
  __dp::update_callstate_from_func_exit(10); // decrements the counter instead of transitioning

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
  EXPECT_EQ(__dp::calls_without_executed_transitions.back(), 0u);
}

// A transition triggered by instruction id 0 is a fall-through: reaching a state that has one means
// passing straight through it. Both update functions resolve it, so neither ever reports the
// intermediate state.
TEST_F(CallStateTransitionsUtilsTest, testAFallThroughTransitionIsTakenImmediately) {
  graph->register_transition(2, 0, 4);

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
}

TEST_F(CallStateTransitionsUtilsTest, testACallTakesTheFallThroughAsWell) {
  graph->register_transition(2, 0, 4);

  __dp::update_callstate_from_call(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 2u);
}

// only one fall-through is resolved per step, not a chain of them
TEST_F(CallStateTransitionsUtilsTest, testOnlyOneFallThroughIsResolvedPerStep) {
  graph->register_transition(2, 0, 4);
  graph->register_transition(4, 0, 5);

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
}

// a call whose target state was unknown disables transitioning until it returns, and update_callstate
// respects that just as the two call-related functions do
TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateDoesNothingWhileDisabled) {
  __dp::update_callstate_from_call(999);
  ASSERT_EQ(__dp::calls_without_executed_transitions.back(), 1u);

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
}

// __dp_func_exit always passes the dummy instruction id 1, and the states reached by a return are
// stored apart from the regular transitions -- so leaving a function is this lookup, every time.
TEST_F(CallStateTransitionsUtilsTest, testFuncExitTakesTheImplicitReturnTransition) {
  graph->register_implicit_return_transition(2, 1);
  __dp::update_callstate_from_call(10);
  ASSERT_EQ(__dp::current_callpath_state->get_id(), 2);

  __dp::update_callstate_from_func_exit(1);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 1u);
}

TEST_F(CallStateTransitionsUtilsTest, testTheImplicitReturnIsOnlyUsedForTheDummyInstructionId) {
  graph->register_implicit_return_transition(2, 1);
  __dp::update_callstate_from_call(10);

  __dp::update_callstate_from_func_exit(999);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 2);
  EXPECT_EQ(__dp::calls_without_executed_transitions.size(), 2u);
}

// a regular transition registered under the dummy id is looked up first, so it wins
TEST_F(CallStateTransitionsUtilsTest, testARegularTransitionWinsOverTheImplicitReturn) {
  graph->register_transition(2, 1, 3);
  graph->register_implicit_return_transition(2, 1);
  __dp::update_callstate_from_call(10);

  __dp::update_callstate_from_func_exit(1);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 3);
}

// initialize_current_callpath_state() reads the state the program starts in from
// "initial_stateID.txt" and establishes the base entry of the call depth stack.
class InitializeCurrentCallpathStateTest : public ::testing::Test {
protected:
  std::filesystem::path directory;
  std::unique_ptr<CallStateGraph> graph;

  void SetUp() override {
    directory = std::filesystem::temp_directory_path() / "discopop_ut_initial_state";
    std::filesystem::remove_all(directory);
    std::filesystem::create_directories(directory);
    setenv("DOT_DISCOPOP_PROFILER", directory.c_str(), 1);

    graph = std::make_unique<CallStateGraph>();
    __dp::call_state_graph = graph.get();
    __dp::current_callpath_state = nullptr;
    __dp::calls_without_executed_transitions.clear();
  }

  void TearDown() override {
    __dp::call_state_graph = nullptr;
    __dp::current_callpath_state = nullptr;
    __dp::calls_without_executed_transitions.clear();
    std::filesystem::remove_all(directory);
  }

  void write_initial_state(const std::string &content) const {
    std::ofstream file(directory / "initial_stateID.txt");
    file << content;
  }
};

TEST_F(InitializeCurrentCallpathStateTest, testTheStateFromTheFileBecomesTheCurrentOne) {
  write_initial_state("7\n");

  __dp::initialize_current_callpath_state();

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 7);
  EXPECT_EQ(__dp::current_callpath_state, __dp::call_state_graph->get_or_register_node(7));
}

// the base entry every later push and pop is counted against
TEST_F(InitializeCurrentCallpathStateTest, testTheCallDepthStackStartsWithOneEnabledEntry) {
  write_initial_state("7\n");

  __dp::initialize_current_callpath_state();

  ASSERT_EQ(__dp::calls_without_executed_transitions.size(), 1u);
  EXPECT_EQ(__dp::calls_without_executed_transitions.back(), 0u);
}

// the pass appends to the file instead of replacing it, so a rebuilt target leaves several ids
// behind and the one written last is the one that counts
TEST_F(InitializeCurrentCallpathStateTest, testTheLastIdInTheFileWins) {
  write_initial_state("3\n7\n");

  __dp::initialize_current_callpath_state();

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 7);
}
