#include <gtest/gtest.h>

#include <cstdlib>
#include <memory>

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
