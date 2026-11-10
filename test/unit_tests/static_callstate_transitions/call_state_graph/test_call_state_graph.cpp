#include <gtest/gtest.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <unistd.h>

#include "static_callstate_transitions/CallStateGraph.hpp"

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

  CallState *node = graph.GetOrRegisterNode(1);
  ASSERT_NE(node, nullptr);
  EXPECT_EQ(node->GetId(), 1);
}

TEST_F(CallStateGraphTest, testGetOrRegisterNodeReturnsSameNodeForSameId) {
  CallStateGraph graph;

  CallState *first = graph.GetOrRegisterNode(1);
  CallState *second = graph.GetOrRegisterNode(1);

  EXPECT_EQ(first, second);
}

TEST_F(CallStateGraphTest, testRegisterTransitionWiresUpStates) {
  CallStateGraph graph;

  graph.RegisterTransition(1, 100, 2);

  CallState *source = graph.GetOrRegisterNode(1);
  CallState *target = graph.GetOrRegisterNode(2);

  EXPECT_EQ(source->GetTransitionTarget(100), target);
}

TEST_F(CallStateGraphTest, testRegisterImplicitReturnTransitionWiresUpStates) {
  CallStateGraph graph;

  graph.RegisterImplicitReturnTransition(1, 2);

  CallState *source = graph.GetOrRegisterNode(1);
  CallState *target = graph.GetOrRegisterNode(2);

  EXPECT_EQ(source->GetImplicitReturnTransitionTarget(), target);
}

TEST_F(CallStateGraphTest, testFunctionEntryStatesAreUnknownByDefault) {
  CallStateGraph graph;

  EXPECT_EQ(graph.GetFunctionEntryState(42), nullptr);
  EXPECT_EQ(graph.GetOrRegisterNode(1)->GetFunctionEntryId(), 0);
}

TEST_F(CallStateGraphTest, testRegisterFunctionEntryState) {
  CallStateGraph graph;

  graph.RegisterFunctionEntryState(42, 7);
  graph.RegisterStateFunction(8, 43);

  ASSERT_NE(graph.GetFunctionEntryState(42), nullptr);
  EXPECT_EQ(graph.GetFunctionEntryState(42)->GetId(), 7);
  EXPECT_EQ(graph.GetOrRegisterNode(7)->GetFunctionEntryId(), 42);
  EXPECT_EQ(graph.GetOrRegisterNode(8)->GetFunctionEntryId(), 43);
  EXPECT_EQ(graph.GetFunctionEntryState(43), nullptr);
}

TEST_F(CallStateGraphTest, testFunctionEntryStatesOfIdsBelowAndAboveTheRegisteredOnes) {
  CallStateGraph graph;

  graph.RegisterFunctionEntryState(5000, 3);
  graph.RegisterFunctionEntryState(10, 4);
  graph.RegisterFunctionEntryState(10, 6);  // the latest registration wins

  EXPECT_EQ(graph.GetFunctionEntryState(5000)->GetId(), 3);
  EXPECT_EQ(graph.GetFunctionEntryState(10)->GetId(), 6);
  EXPECT_EQ(graph.GetFunctionEntryState(11), nullptr);
  EXPECT_EQ(graph.GetFunctionEntryState(5001), nullptr);
  EXPECT_EQ(graph.GetFunctionEntryState(-1), nullptr);
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

  ASSERT_NE(graph.GetFunctionEntryState(100), nullptr);
  EXPECT_EQ(graph.GetFunctionEntryState(100)->GetId(), 5);
  EXPECT_EQ(graph.GetFunctionEntryState(200), nullptr);
  EXPECT_EQ(graph.GetOrRegisterNode(9)->GetFunctionEntryId(), 200);

  std::remove(path.c_str());
  rmdir(dir);
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

  EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), graph.GetOrRegisterNode(2));
  EXPECT_EQ(graph.GetOrRegisterNode(2)->GetTransitionTarget(20), graph.GetOrRegisterNode(3));
}

TEST_F(CallStateGraphParsingTest, testCommentsAndEmptyLinesAreSkipped) {
  write_input("callpath_state_transitions.txt", "# the state transitions of the call path\n\n1 10 2\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), graph.GetOrRegisterNode(2));
}

TEST_F(CallStateGraphParsingTest, testALineMissingAFieldIsSkipped) {
  write_input("callpath_state_transitions.txt", "110\n1 10\n2 20 3\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), nullptr);
  EXPECT_EQ(graph.GetOrRegisterNode(2)->GetTransitionTarget(20), graph.GetOrRegisterNode(3));
}

TEST_F(CallStateGraphParsingTest, testTheLastLineNeedsNoNewline) {
  write_input("callpath_state_transitions.txt", "1 10 2");

  CallStateGraph graph;

  EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), graph.GetOrRegisterNode(2));
}

// the returns are stored without the trigger id they are keyed by in the file, so they come back
// only through get_implicit_return_transition_target()
TEST_F(CallStateGraphParsingTest, testTheReturnTargetsAreReadFromTheirOwnFile) {
  write_input("callpath_state_return_targets.txt", "3 1\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.GetOrRegisterNode(3)->GetImplicitReturnTransitionTarget(), graph.GetOrRegisterNode(1));
  EXPECT_EQ(graph.GetOrRegisterNode(3)->GetTransitionTarget(1), nullptr);
}

TEST_F(CallStateGraphParsingTest, testTheReturnTargetsFileSkipsCommentsAndEmptyLinesAsWell) {
  write_input("callpath_state_return_targets.txt", "# the implicit return targets\n\n31\n3 1\n");

  CallStateGraph graph;

  EXPECT_EQ(graph.GetOrRegisterNode(3)->GetImplicitReturnTransitionTarget(), graph.GetOrRegisterNode(1));
}

TEST_F(CallStateGraphParsingTest, testBothFilesEndUpInTheSameGraph) {
  write_input("callpath_state_transitions.txt", "1 10 2\n");
  write_input("callpath_state_return_targets.txt", "2 1\n");

  CallStateGraph graph;

  CallState *const entered = graph.GetOrRegisterNode(1)->GetTransitionTarget(10);
  ASSERT_NE(entered, nullptr);
  EXPECT_EQ(entered->GetId(), 2);
  EXPECT_EQ(entered->GetImplicitReturnTransitionTarget(), graph.GetOrRegisterNode(1));
}

// The constructor runs from __dp_init, so it must get through its input without throwing. A field
// that is not a number used to escape as std::invalid_argument from stoi and take the instrumented
// program down before it had started.
TEST_F(CallStateGraphParsingTest, testALineWithAFieldThatIsNotANumberIsSkipped) {
  write_input("callpath_state_transitions.txt", "x 10 2\n1 y 2\n1 10 z\n2 20 3\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), nullptr);
    EXPECT_EQ(graph.GetOrRegisterNode(2)->GetTransitionTarget(20), graph.GetOrRegisterNode(3));
  });
}

TEST_F(CallStateGraphParsingTest, testAnIdTooLargeForTheStateTypeIsSkipped) {
  write_input("callpath_state_transitions.txt", "99999999999999999999 10 2\n1 10 2\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.GetOrRegisterNode(1)->GetTransitionTarget(10), graph.GetOrRegisterNode(2));
  });
}

TEST_F(CallStateGraphParsingTest, testTheReturnTargetsFileSurvivesAMalformedLineAsWell) {
  write_input("callpath_state_return_targets.txt", "x 1\n3 y\n3 1\n");

  ASSERT_NO_THROW({
    CallStateGraph graph;

    EXPECT_EQ(graph.GetOrRegisterNode(3)->GetImplicitReturnTransitionTarget(), graph.GetOrRegisterNode(1));
  });
}

// Whatever the runtime prints lands in the output of the program being profiled, between that
// program's own lines. Building and tearing down the graph used to time itself and report the
// result on stdout on every single run.
TEST_F(CallStateGraphParsingTest, testBuildingTheGraphWritesNothingToStandardOutput) {
  write_input("callpath_state_transitions.txt", "1 10 2\n");
  write_input("callpath_state_return_targets.txt", "2 1\n");

  ::testing::internal::CaptureStdout();
  {
    CallStateGraph graph;
  }
  const std::string output = ::testing::internal::GetCapturedStdout();

  EXPECT_EQ(output, "");
}
