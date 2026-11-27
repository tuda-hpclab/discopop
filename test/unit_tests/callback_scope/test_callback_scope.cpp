#include <gtest/gtest.h>

#include "callback_scope.hpp"
#include "runtimeFunctionsGlobals.hpp"

using namespace dp;

namespace {

int callbacks_that_did_their_work = 0;

// Stands in for an instrumented callback: the preamble every one of them opens with, followed by
// the work it only performs while the runtime is running.
void instrumented_callback() {
  DP_CALLBACK_SCOPE(READ);

  ++callbacks_that_did_their_work;
}

// The other shape: a callback that hands control back to instrumented code in the middle of its
// work and therefore has to let go of the lock first.
void instrumented_callback_releasing_the_lock() {
  DP_CALLBACK_SCOPE(FUNC_EXIT);

  dp_scope.Unlock();
  dp_scope.Relock();

  ++callbacks_that_did_their_work;
}

// The third shape: a callback that neither takes the lock nor is traced or timed, and therefore
// asks the same two questions without a scope.
void instrumented_callback_without_a_scope() {
  DP_CALLBACK_GUARD(LOOP_INCR);

  ++callbacks_that_did_their_work;
}

// A callback that reaches instrumented code: the runtime calling the instrumented copy of a template instantiation
// it shares with the program (see inside_runtime in runtimeFunctionsGlobals.hpp).
void instrumented_callback_reaching_instrumented_code() {
  DP_CALLBACK_SCOPE(LOOP_INCR);

  instrumented_callback();
  instrumented_callback_without_a_scope();
  ++callbacks_that_did_their_work;
}

bool inside_runtime_during_the_callback = false;

void instrumented_callback_recording_inside_runtime() {
  DP_CALLBACK_SCOPE(READ);

  inside_runtime_during_the_callback = inside_runtime;
}

// Every callback the pass injects, so that a CallbackId added without a callback -- or a callback
// switched by an id that belongs to another one -- shows up here rather than as a variant of the
// runtime that measures the wrong thing.
constexpr CallbackId all_callbacks[] = {
    CallbackId::ALLOCA,
    CallbackId::CALL,
    CallbackId::DECL,
    CallbackId::DELETE,
    CallbackId::FUNC_ENTRY,
    CallbackId::FUNC_EXIT,
    CallbackId::INCR_TAKEN_BRANCH_COUNTER,
    CallbackId::LANDING_PAD,
    CallbackId::LOOP_ENTRY,
    CallbackId::LOOP_EXIT,
    CallbackId::LOOP_INCR,
    CallbackId::NEW,
    CallbackId::READ,
    CallbackId::REPORT_BB,
    CallbackId::REPORT_BB_PAIR,
    CallbackId::WRITE,
};

} // namespace

// The preamble of an instrumented callback. There are exactly three runtime states and they are
// reached in order; only the middle one lets a callback do anything. Terminated is not the same
// as NotInitialized: the target's global destructors run after __dp_finalize and are instrumented
// like everything else, so their callbacks still arrive and have to return without touching
// anything rather than start the runtime up again.
class CallbackScopeTest : public ::testing::Test {
protected:
  void SetUp() override {
    previous_state = runtime_state;
    callbacks_that_did_their_work = 0;
    ASSERT_FALSE(inside_runtime);
  }

  void TearDown() override { runtime_state = previous_state; }

private:
  RuntimeState previous_state = RuntimeState::kNotInitialized;
};

TEST_F(CallbackScopeTest, testProfilingIsNotActiveBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::kNotInitialized;

  EXPECT_FALSE(ProfilingActive());
}

TEST_F(CallbackScopeTest, testProfilingIsActiveWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::kRunning;

  EXPECT_TRUE(ProfilingActive());
}

TEST_F(CallbackScopeTest, testProfilingIsNotActiveAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::kTerminated;

  EXPECT_FALSE(ProfilingActive());
}

TEST_F(CallbackScopeTest, testTheScopeLetsACallbackThroughWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::kRunning;

  const auto scope = CallbackScope(TimerRegion::kRead, CallbackId::READ, "test");

  EXPECT_TRUE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::kNotInitialized;

  const auto scope = CallbackScope(TimerRegion::kRead, CallbackId::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::kTerminated;

  const auto scope = CallbackScope(TimerRegion::kRead, CallbackId::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

// the decision is made when the scope is entered, so a callback that is already running finishes
// even if the runtime terminates underneath it
TEST_F(CallbackScopeTest, testTheDecisionIsTakenOnceAndDoesNotChangeAfterwards) {
  runtime_state = RuntimeState::kRunning;
  const auto scope = CallbackScope(TimerRegion::kRead, CallbackId::READ, "test");

  runtime_state = RuntimeState::kTerminated;

  EXPECT_TRUE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testACallbackDoesItsWorkWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::kRunning;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testACallbackReturnsWithoutWorkBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::kNotInitialized;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

// the case the state exists for: the instrumented destructors of the target's globals
TEST_F(CallbackScopeTest, testACallbackReturnsWithoutWorkAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::kTerminated;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

TEST_F(CallbackScopeTest, testACallbackMayReleaseAndTakeTheLockAgain) {
  runtime_state = RuntimeState::kRunning;

  instrumented_callback_releasing_the_lock();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

// releasing what was never taken is what a callback that returns early would do
TEST_F(CallbackScopeTest, testReleasingTheLockOfAStoppedCallbackIsHarmless) {
  runtime_state = RuntimeState::kTerminated;
  auto scope = CallbackScope(TimerRegion::kRead, CallbackId::READ, "test");

  scope.Unlock();
  scope.Relock();

  EXPECT_FALSE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testACallbackWithoutAScopeDoesItsWorkWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::kRunning;

  instrumented_callback_without_a_scope();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testACallbackWithoutAScopeReturnsWithoutWorkAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::kTerminated;

  instrumented_callback_without_a_scope();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

// The benchmark builds leave callback bodies out to measure what the calls cost on their own, and
// switch exactly one back on to measure what that body adds. Which of the three a runtime library
// is compiled as is a build option, so what is checked here is the shipped build: the one every
// other test in this binary, and every profiled program, depends on.
TEST_F(CallbackScopeTest, testEveryCallbackBodyIsEnabledInTheShippedBuild) {
  for (const auto callback : all_callbacks) {
    EXPECT_TRUE(CallbackBodyEnabled(callback)) << "callback id " << static_cast<int>(callback);
  }
}

// It has to fold away, not be asked at runtime: a body that is only skipped over still costs the
// branch that skips it, and the measurement would report that branch as the cost of the body.
TEST_F(CallbackScopeTest, testWhetherABodyIsEnabledIsDecidedAtCompileTime) {
  static_assert(CallbackBodyEnabled(CallbackId::READ), "the shipped build runs every body");
  static_assert(CallbackBodyEnabled(CallbackId::LOOP_INCR), "the shipped build runs every body");

  SUCCEED();
}

// A timed section is the non-callback variant: no state check and no lock, used for the
// individual output steps of __dp_finalize, which run with the lock already held.
TEST_F(CallbackScopeTest, testATimedSectionDoesNotDependOnTheRuntimeState) {
  runtime_state = RuntimeState::kTerminated;

  DP_TIMED_SECTION(kOutputLoops, "outputLoops");

  SUCCEED();
}

// The runtime reaches instrumented code when the program and the runtime share an instrumented template
// instantiation (e.g. std::vector<unsigned>::_M_default_append with libstdc++ as project code): callbacks entered
// from within a callback must return without work, as the runtime's state is in the middle of a change.
TEST_F(CallbackScopeTest, testACallbackEnteredFromWithinACallbackReturnsWithoutWork) {
  runtime_state = RuntimeState::kRunning;

  instrumented_callback_reaching_instrumented_code();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testTheThreadIsInsideTheRuntimeOnlyWhileACallbackRuns) {
  runtime_state = RuntimeState::kRunning;

  instrumented_callback_recording_inside_runtime();

  EXPECT_TRUE(inside_runtime_during_the_callback);
  EXPECT_FALSE(inside_runtime);
}

// a stopped callback must not clear the mark of the callback (or runtime section) it was entered from
TEST_F(CallbackScopeTest, testAStoppedCallbackKeepsTheThreadInsideTheRuntime) {
  runtime_state = RuntimeState::kRunning;
  const RuntimeSection section;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
  EXPECT_TRUE(inside_runtime);
}

// __dp_init, the output of __dp_finalize and the worker threads are runtime without being a callback
TEST_F(CallbackScopeTest, testCallbacksReturnWithoutWorkInARuntimeSection) {
  runtime_state = RuntimeState::kRunning;
  {
    const RuntimeSection section;

    instrumented_callback();
    instrumented_callback_without_a_scope();

    EXPECT_EQ(callbacks_that_did_their_work, 0);
  }

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testANestedRuntimeSectionRestoresTheOuterOne) {
  {
    const RuntimeSection outer;
    { const RuntimeSection inner; }

    EXPECT_TRUE(inside_runtime);
  }

  EXPECT_FALSE(inside_runtime);
}
