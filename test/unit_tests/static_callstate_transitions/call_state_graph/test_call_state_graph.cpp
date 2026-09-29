#include <gtest/gtest.h>

#include <cstdlib>

#include "../../../../profiler/rtlib/static_callstate_transitions/CallStateGraph.hpp"

// CallStateGraph's constructor reads the files
// "$DOT_DISCOPOP_PROFILER/callpath_state_transitions.txt" and
// ".../callpath_state_return_targets.txt". Pointing it at a directory that
// contains neither yields an empty graph, which these tests then populate and
// query manually. The constructor reports both missing files on stderr; that
// output is expected here.
class CallStateGraphTest : public ::testing::Test {
protected:
  void SetUp() override { setenv("DOT_DISCOPOP_PROFILER", "/tmp/discopop_ut_nonexistent_dir", 1); }
};

TEST_F(CallStateGraphTest, testGetOrRegisterNodeCreatesNewNode) {
  CallStateGraph graph;

  CallState *node = graph.get_or_register_node(1);
  ASSERT_NE(node, nullptr);
  EXPECT_EQ(node->get_id(), 1);
}

TEST_F(CallStateGraphTest, testGetOrRegisterNodeReturnsSameNodeForSameId) {
  CallStateGraph graph;

  CallState *first = graph.get_or_register_node(1);
  CallState *second = graph.get_or_register_node(1);

  EXPECT_EQ(first, second);
}

TEST_F(CallStateGraphTest, testRegisterTransitionWiresUpStates) {
  CallStateGraph graph;

  graph.register_transition(1, 100, 2);

  CallState *source = graph.get_or_register_node(1);
  CallState *target = graph.get_or_register_node(2);

  EXPECT_EQ(source->get_transition_target(100), target);
}

TEST_F(CallStateGraphTest, testRegisterImplicitReturnTransitionWiresUpStates) {
  CallStateGraph graph;

  graph.register_implicit_return_transition(1, 2);

  CallState *source = graph.get_or_register_node(1);
  CallState *target = graph.get_or_register_node(2);

  EXPECT_EQ(source->get_implicit_return_transition_target(), target);
}
