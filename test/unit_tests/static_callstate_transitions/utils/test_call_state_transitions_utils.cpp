#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <thread>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/static_callstate_transitions/utils.hpp"

// The callpath state tracking (static_callstate_transitions/utils.hpp) operates on the global
// __dp::current_callpath_state and __dp::call_state_graph. Each test builds a small, deterministic
// state graph and installs it into those globals before running:
//
//   state 1: main (function entry id 100, root entry state of main)
//     --10--> 2 (call instruction node) --0--> 3: callee (function entry id 200)
//     --30--> 4: main_loopstate0 --31--> 5: main_loopstate1
//   state 3 --40--> 6: callee_loopstate0
//   state 7: root entry state of function 300 (no caller in its translation unit)
//   state 1 --50--> 8 (call instruction node of a call into a function without instrumentation,
//     "library") --0--> 9: function node without entry id
//
// Constructing the graph from a directory without profiler output reports the missing input
// files on stderr; that output is expected here.
class CallStateTransitionsUtilsTest : public ::testing::Test {
protected:
  std::unique_ptr<CallStateGraph> graph;

  void SetUp() override {
    setenv("DOT_DISCOPOP_PROFILER", "/tmp/discopop_ut_nonexistent_dir", 1);

    graph = std::make_unique<CallStateGraph>();
    graph->register_function_entry_state(100, 1);
    graph->register_transition(1, 10, 2);
    graph->register_transition(2, 0, 3);
    graph->register_state_function(3, 200);
    graph->register_transition(1, 30, 4);
    graph->register_transition(4, 31, 5);
    graph->register_transition(3, 40, 6);
    graph->register_function_entry_state(300, 7);
    graph->register_transition(1, 50, 8);
    graph->register_transition(8, 0, 9);

    __dp::call_state_graph = graph.get();
    __dp::reset_callstate_tracking(graph->get_or_register_node(1));
  }

  void TearDown() override {
    __dp::reset_callstate_tracking(nullptr);
    __dp::call_state_graph = nullptr;
  }

  int32_t state() { return __dp::current_callpath_state->get_id(); }
};

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateFollowsExistingTransition) {
  __dp::update_callstate(30);
  EXPECT_EQ(state(), 4);
}

TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateIgnoresUnknownTrigger) {
  __dp::update_callstate(999);
  EXPECT_EQ(state(), 1);
}

TEST_F(CallStateTransitionsUtilsTest, testCallAloneDoesNotChangeTheState) {
  __dp::register_call_for_callstate(10);
  EXPECT_EQ(state(), 1);
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
}

TEST_F(CallStateTransitionsUtilsTest, testEnteringTheCalledFunctionFollowsTheCallAndTheFallthrough) {
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  EXPECT_EQ(state(), 3);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  EXPECT_EQ(__dp::callstate_frame_count(), 1u);
}

TEST_F(CallStateTransitionsUtilsTest, testLeavingAFunctionRestoresTheCallersState) {
  __dp::update_callstate(30);
  __dp::update_callstate(31);
  __dp::register_call_for_callstate(10);
  // the call leaves from main_loopstate1, which has no transition for it: the callee's own root
  // entry state does not exist either, so the state is frozen
  __dp::enter_function_for_callstate(200);
  __dp::update_callstate(40);
  __dp::leave_function_for_callstate();
  EXPECT_EQ(state(), 5);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
}

TEST_F(CallStateTransitionsUtilsTest, testLoopTransitionsInsideTheCalleeAreUndoneOnReturn) {
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  __dp::update_callstate(40);
  EXPECT_EQ(state(), 6);
  // a return from inside the loop, without its loop exit
  __dp::leave_function_for_callstate();
  EXPECT_EQ(state(), 1);
}

// P3: a call into code without instrumentation (e.g. an indirect call of a library function)
// never enters an instrumented function, so it must neither change nor freeze the state
TEST_F(CallStateTransitionsUtilsTest, testCallIntoUninstrumentedCodeKeepsTransitionsEnabled) {
  __dp::register_call_for_callstate(77); // indirect call, no static transition
  // the callee returns without __dp_func_entry / __dp_func_exit
  __dp::update_callstate(30);
  EXPECT_EQ(state(), 4);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  // a later call still enters its callee's state
  __dp::update_callstate(31);
  __dp::register_call_for_callstate(999);
  __dp::leave_function_for_callstate(); // no frame: ignored
  EXPECT_EQ(state(), 5);
}

TEST_F(CallStateTransitionsUtilsTest, testUninstrumentedCalleeCallingBackDoesNotUseTheCallsTransition) {
  // main calls a library function (call 50 -> state 9 without entry id), which calls back into the
  // instrumented function 200: the transition of call 50 does not lead into function 200
  __dp::register_call_for_callstate(50);
  __dp::enter_function_for_callstate(200);
  EXPECT_NE(state(), 9);
  EXPECT_EQ(state(), 1);
  EXPECT_TRUE(__dp::callstate_transitions_frozen());
  __dp::leave_function_for_callstate();
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
}

// P2: a function entered without a matching call transition (call from another translation unit,
// constructor alias, virtual call) switches to its root entry state
TEST_F(CallStateTransitionsUtilsTest, testEnteringWithoutTransitionSwitchesToTheRootEntryState) {
  __dp::update_callstate(30);
  __dp::register_call_for_callstate(77);
  __dp::enter_function_for_callstate(300);
  EXPECT_EQ(state(), 7);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  __dp::leave_function_for_callstate();
  EXPECT_EQ(state(), 4);
}

TEST_F(CallStateTransitionsUtilsTest, testFunctionEnteredWithoutCallSwitchesToTheRootEntryState) {
  // e.g. called by library code, without a preceding __dp_call
  __dp::enter_function_for_callstate(300);
  EXPECT_EQ(state(), 7);
}

TEST_F(CallStateTransitionsUtilsTest, testFrozenStateDisablesLoopAndCallTransitions) {
  __dp::register_call_for_callstate(77);
  __dp::enter_function_for_callstate(555); // unknown function: frozen in main's state
  EXPECT_TRUE(__dp::callstate_transitions_frozen());
  __dp::update_callstate(30); // main's loop id must not move the state while in the unknown function
  EXPECT_EQ(state(), 1);
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200); // relative transitions are disabled while frozen
  EXPECT_EQ(state(), 1);
  __dp::leave_function_for_callstate();
  // root entry states remain reachable while frozen
  __dp::enter_function_for_callstate(300);
  EXPECT_EQ(state(), 7);
  __dp::leave_function_for_callstate();
  __dp::leave_function_for_callstate();
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  EXPECT_EQ(state(), 1);
  __dp::update_callstate(30);
  EXPECT_EQ(state(), 4);
}

TEST_F(CallStateTransitionsUtilsTest, testPendingCallIsConsumedByTheFirstEntry) {
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  __dp::leave_function_for_callstate();
  // no new call: a second entry (e.g. a callback) does not reuse call 10
  __dp::enter_function_for_callstate(200);
  EXPECT_EQ(state(), 1);
  EXPECT_TRUE(__dp::callstate_transitions_frozen());
}

TEST_F(CallStateTransitionsUtilsTest, testRecursionThroughTheRootEntryState) {
  __dp::enter_function_for_callstate(100); // main
  EXPECT_EQ(state(), 1);
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  __dp::enter_function_for_callstate(300);
  __dp::enter_function_for_callstate(300);
  EXPECT_EQ(__dp::callstate_frame_count(), 4u);
  __dp::leave_function_for_callstate();
  __dp::leave_function_for_callstate();
  EXPECT_EQ(state(), 3);
  __dp::leave_function_for_callstate();
  __dp::leave_function_for_callstate();
  EXPECT_EQ(state(), 1);
}

TEST_F(CallStateTransitionsUtilsTest, testOtherThreadsDoNotChangeTheState) {
  std::thread other([]() {
    __dp::register_call_for_callstate(10);
    __dp::enter_function_for_callstate(300);
    __dp::update_callstate(30);
    __dp::leave_function_for_callstate();
  });
  other.join();
  EXPECT_EQ(state(), 1);
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
}

TEST_F(CallStateTransitionsUtilsTest, testPendingCallIsPerThread) {
  __dp::register_call_for_callstate(10);
  std::thread other([]() { __dp::register_call_for_callstate(50); });
  other.join();
  __dp::enter_function_for_callstate(200);
  EXPECT_EQ(state(), 3);
}

// an exception thrown in function 300 (entered from callee 200) is caught in main (100): the exits
// of 300 and 200 never run, the landing pad of main restores main's state at its call
TEST_F(CallStateTransitionsUtilsTest, testLandingPadDiscardsTheStatesOfUnwoundFunctions) {
  __dp::enter_function_for_callstate(100);
  __dp::update_callstate(30);
  EXPECT_EQ(state(), 4);
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200); // frozen: no transition from state 4
  __dp::enter_function_for_callstate(300);
  EXPECT_EQ(state(), 7);
  __dp::resume_function_for_callstate(100);
  EXPECT_EQ(state(), 4);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
  EXPECT_EQ(__dp::callstate_frame_count(), 1u);
  __dp::update_callstate(31);
  EXPECT_EQ(state(), 5);
}

TEST_F(CallStateTransitionsUtilsTest, testLandingPadOfTheCurrentFunctionKeepsTheState) {
  __dp::enter_function_for_callstate(100);
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  __dp::update_callstate(40);
  // a cleanup landing pad in function 200 itself (e.g. a destructor call while unwinding)
  __dp::resume_function_for_callstate(200);
  EXPECT_EQ(state(), 6);
  EXPECT_EQ(__dp::callstate_frame_count(), 2u);
}

TEST_F(CallStateTransitionsUtilsTest, testLandingPadOfAnUnknownFunctionChangesNothing) {
  __dp::enter_function_for_callstate(300);
  __dp::resume_function_for_callstate(555);
  EXPECT_EQ(state(), 7);
  EXPECT_EQ(__dp::callstate_frame_count(), 1u);
}

// A transition triggered by instruction id 0 is a fall-through: reaching a state that has one means
// passing straight through it. Both a loop transition and a call resolve it, so neither ever reports
// the intermediate state.
TEST_F(CallStateTransitionsUtilsTest, testAFallThroughTransitionIsTakenImmediately) {
  graph->register_transition(2, 0, 4);

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
}

TEST_F(CallStateTransitionsUtilsTest, testACallTakesTheFallThroughAsWell) {
  // call instruction 10 leads to the call instruction node 2, whose fall-through enters the callee
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 3);
  EXPECT_EQ(__dp::callstate_frame_count(), 1u);
}

// only one fall-through is resolved per step, not a chain of them
TEST_F(CallStateTransitionsUtilsTest, testOnlyOneFallThroughIsResolvedPerStep) {
  graph->register_transition(2, 0, 4);
  graph->register_transition(4, 0, 5);

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
}

// entering a function whose state is unknown disables transitioning until it is left, and
// update_callstate respects that just as the call-related functions do
TEST_F(CallStateTransitionsUtilsTest, testUpdateCallstateDoesNothingWhileDisabled) {
  __dp::register_call_for_callstate(999);
  __dp::enter_function_for_callstate(555);
  ASSERT_TRUE(__dp::callstate_transitions_frozen());

  __dp::update_callstate(10);

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
}

// leaving a function restores the state of its caller, whichever state the callee ended in
TEST_F(CallStateTransitionsUtilsTest, testLeavingTheCalleeRestoresTheStateOfTheCall) {
  __dp::register_call_for_callstate(10);
  __dp::enter_function_for_callstate(200);
  __dp::update_callstate(40);
  ASSERT_EQ(__dp::current_callpath_state->get_id(), 6);

  __dp::leave_function_for_callstate();

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
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
    __dp::reset_callstate_tracking(nullptr);
  }

  void TearDown() override {
    __dp::call_state_graph = nullptr;
    __dp::reset_callstate_tracking(nullptr);
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

// the tracking starts outside of any entered function, with transitions enabled
TEST_F(InitializeCurrentCallpathStateTest, testTheTrackingStartsWithoutFramesAndEnabled) {
  write_initial_state("7\n");

  __dp::initialize_current_callpath_state();

  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
}

// the pass appends to the file instead of replacing it, so a rebuilt target leaves several ids
// behind and the one written last is the one that counts
TEST_F(InitializeCurrentCallpathStateTest, testTheLastIdInTheFileWins) {
  write_initial_state("3\n7\n");

  __dp::initialize_current_callpath_state();

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 7);
}

// A missing or empty file is the normal outcome for a target whose call path tree holds no "main",
// because the pass writes the id only when it finds one. The id used to be read uninitialized in
// that case -- g++ -Wmaybe-uninitialized points straight at it. The fallback reports itself on
// stderr; that output is expected here.
TEST_F(InitializeCurrentCallpathStateTest, testAMissingFileLeavesTheInitialStateDefined) {
  __dp::initialize_current_callpath_state();

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 0);
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);
  EXPECT_FALSE(__dp::callstate_transitions_frozen());
}

TEST_F(InitializeCurrentCallpathStateTest, testAnEmptyFileLeavesTheInitialStateDefined) {
  write_initial_state("");

  __dp::initialize_current_callpath_state();

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 0);
}

// a state without transitions is a state the call path never leaves
TEST_F(InitializeCurrentCallpathStateTest, testTheFallbackStateSimplyDoesNotMove) {
  __dp::initialize_current_callpath_state();

  __dp::update_callstate(10);

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 0);
}

// unwind_function_stack() calls __dp_func_exit until the function stack level has passed zero, so a
// target can leave more functions than it entered. Leaving without a frame keeps the state.
TEST_F(CallStateTransitionsUtilsTest, testLeavingMoreFunctionsThanWereEnteredKeepsTheState) {
  __dp::leave_function_for_callstate();
  __dp::leave_function_for_callstate();

  EXPECT_EQ(__dp::current_callpath_state->get_id(), 1);
  EXPECT_EQ(__dp::callstate_frame_count(), 0u);

  __dp::update_callstate(30);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 4);
}

// the same for the initial state: a line that is not a number is skipped, not thrown over
TEST_F(InitializeCurrentCallpathStateTest, testALineThatIsNotANumberIsSkipped) {
  write_initial_state("not a state id\n7\n");

  ASSERT_NO_THROW(__dp::initialize_current_callpath_state());

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 7);
}

TEST_F(InitializeCurrentCallpathStateTest, testAFileWithNothingUsableFallsBackToTheDefinedState) {
  write_initial_state("not a state id\n");

  ASSERT_NO_THROW(__dp::initialize_current_callpath_state());

  ASSERT_NE(__dp::current_callpath_state, nullptr);
  EXPECT_EQ(__dp::current_callpath_state->get_id(), 0);
}
