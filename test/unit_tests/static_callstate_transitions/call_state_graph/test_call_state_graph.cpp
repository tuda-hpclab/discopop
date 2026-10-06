#include <gtest/gtest.h>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>

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

TEST_F(CallStateGraphTest, testFunctionEntryStatesAreUnknownByDefault) {
  CallStateGraph graph;

  EXPECT_EQ(graph.get_function_entry_state(42), nullptr);
  EXPECT_EQ(graph.get_or_register_node(1)->get_function_entry_id(), 0);
}

TEST_F(CallStateGraphTest, testRegisterFunctionEntryState) {
  CallStateGraph graph;

  graph.register_function_entry_state(42, 7);
  graph.register_state_function(8, 43);

  ASSERT_NE(graph.get_function_entry_state(42), nullptr);
  EXPECT_EQ(graph.get_function_entry_state(42)->get_id(), 7);
  EXPECT_EQ(graph.get_or_register_node(7)->get_function_entry_id(), 42);
  EXPECT_EQ(graph.get_or_register_node(8)->get_function_entry_id(), 43);
  EXPECT_EQ(graph.get_function_entry_state(43), nullptr);
}

TEST_F(CallStateGraphTest, testReadsCallpathFunctionEntriesFile) {
  char dir_template[] = "/tmp/discopop_ut_callstate_XXXXXX";
  char *dir = mkdtemp(dir_template);
  ASSERT_NE(dir, nullptr);
  std::string path = std::string(dir) + "/callpath_function_entries.txt";
  {
    std::ofstream file(path);
    file << "# Format: S <state_id> <function_entry_instruction_id> | E <function_entry_instruction_id> "
            "<root_state_id>\n";
    file << "S 5 100\n";
    file << "E 100 5\n";
    file << "S 9 200\n";
    file << "broken line\n";
  }
  setenv("DOT_DISCOPOP_PROFILER", dir, 1);

  CallStateGraph graph;

  ASSERT_NE(graph.get_function_entry_state(100), nullptr);
  EXPECT_EQ(graph.get_function_entry_state(100)->get_id(), 5);
  EXPECT_EQ(graph.get_function_entry_state(200), nullptr);
  EXPECT_EQ(graph.get_or_register_node(9)->get_function_entry_id(), 200);

  std::remove(path.c_str());
  rmdir(dir);
}
