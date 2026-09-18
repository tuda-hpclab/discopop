#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

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

// The constructor reads "callpath_state_transitions.txt" and "callpath_state_return_targets.txt"
// from $DOT_DISCOPOP_PROFILER. The fixture above points it at a directory that holds neither, so
// the parser itself never runs there. These tests write real input and let it parse.
class CallStateGraphParsingTest : public ::testing::Test {
protected:
  std::filesystem::path directory;

  void SetUp() override {
    directory = std::filesystem::temp_directory_path() / "discopop_ut_call_state_graph";
    std::filesystem::remove_all(directory);
    std::filesystem::create_directories(directory);
    setenv("DOT_DISCOPOP_PROFILER", directory.c_str(), 1);
  }

  void TearDown() override { std::filesystem::remove_all(directory); }

  // a file the constructor does not find is reported on stderr and leaves that half of the graph
  // empty, which is what every test not writing it relies on
  void write_input(const std::string &name, const std::string &content) const {
    std::ofstream file(directory / name);
    file << content;
  }
};

TEST_F(CallStateGraphParsingTest, testEveryTransitionInTheFileIsRegistered) {
  write_input("callpath_state_transitions.txt", "1 10 2\n2 20 3\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), graph.get_or_register_node(2));
  EXPECT_EQ(graph.get_or_register_node(2)->get_transition_target(20), graph.get_or_register_node(3));
}

TEST_F(CallStateGraphParsingTest, testCommentsAndEmptyLinesAreSkipped) {
  write_input("callpath_state_transitions.txt", "# the state transitions of the call path\n\n1 10 2\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), graph.get_or_register_node(2));
}

TEST_F(CallStateGraphParsingTest, testALineMissingAFieldIsSkipped) {
  write_input("callpath_state_transitions.txt", "110\n1 10\n2 20 3\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), nullptr);
  EXPECT_EQ(graph.get_or_register_node(2)->get_transition_target(20), graph.get_or_register_node(3));
}

TEST_F(CallStateGraphParsingTest, testTheLastLineNeedsNoNewline) {
  write_input("callpath_state_transitions.txt", "1 10 2");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), graph.get_or_register_node(2));
}

// the returns are stored without the trigger id they are keyed by in the file, so they come back
// only through get_implicit_return_transition_target()
TEST_F(CallStateGraphParsingTest, testTheReturnTargetsAreReadFromTheirOwnFile) {
  write_input("callpath_state_return_targets.txt", "3 1\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(3)->get_implicit_return_transition_target(), graph.get_or_register_node(1));
  EXPECT_EQ(graph.get_or_register_node(3)->get_transition_target(1), nullptr);
}

TEST_F(CallStateGraphParsingTest, testTheReturnTargetsFileSkipsCommentsAndEmptyLinesAsWell) {
  write_input("callpath_state_return_targets.txt", "# the implicit return targets\n\n31\n3 1\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.get_or_register_node(3)->get_implicit_return_transition_target(), graph.get_or_register_node(1));
}

TEST_F(CallStateGraphParsingTest, testBothFilesEndUpInTheSameGraph) {
  write_input("callpath_state_transitions.txt", "1 10 2\n");
  write_input("callpath_state_return_targets.txt", "2 1\n");

  CallStateGraph graph;

  CallState *const entered = graph.get_or_register_node(1)->get_transition_target(10);
  ASSERT_NE(entered, nullptr);
  EXPECT_EQ(entered->get_id(), 2);
  EXPECT_EQ(entered->get_implicit_return_transition_target(), graph.get_or_register_node(1));
}

// The constructor runs from __dp_init, so it must get through its input without throwing. A field
// that is not a number used to escape as std::invalid_argument from stoi and take the instrumented
// program down before it had started.
TEST_F(CallStateGraphParsingTest, testALineWithAFieldThatIsNotANumberIsSkipped) {
  write_input("callpath_state_transitions.txt", "x 10 2\n1 y 2\n1 10 z\n2 20 3\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), nullptr);
    EXPECT_EQ(graph.get_or_register_node(2)->get_transition_target(20), graph.get_or_register_node(3));
  });
}

TEST_F(CallStateGraphParsingTest, testAnIdTooLargeForTheStateTypeIsSkipped) {
  write_input("callpath_state_transitions.txt", "99999999999999999999 10 2\n1 10 2\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.get_or_register_node(1)->get_transition_target(10), graph.get_or_register_node(2));
  });
}

TEST_F(CallStateGraphParsingTest, testTheReturnTargetsFileSurvivesAMalformedLineAsWell) {
  write_input("callpath_state_return_targets.txt", "x 1\n3 y\n3 1\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.get_or_register_node(3)->get_implicit_return_transition_target(), graph.get_or_register_node(1));
  });
}
