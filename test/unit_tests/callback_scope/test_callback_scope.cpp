#include <gtest/gtest.h>

#include "../../../profiler/rtlib/callback_scope.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

using namespace __dp;

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

  dp_scope.unlock();
  dp_scope.relock();

  ++callbacks_that_did_their_work;
}

// The third shape: a callback that neither takes the lock nor is traced or timed, and therefore
// asks the same two questions without a scope.
void instrumented_callback_without_a_scope() {
  DP_CALLBACK_GUARD(LOOP_INCR);

  ++callbacks_that_did_their_work;
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
  }

  void TearDown() override { runtime_state = previous_state; }

private:
  RuntimeState previous_state = RuntimeState::NotInitialized;
};

TEST_F(CallbackScopeTest, testProfilingIsNotActiveBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::NotInitialized;

  EXPECT_FALSE(profiling_active());
}

TEST_F(CallbackScopeTest, testProfilingIsActiveWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::Running;

  EXPECT_TRUE(profiling_active());
}

TEST_F(CallbackScopeTest, testProfilingIsNotActiveAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::Terminated;

  EXPECT_FALSE(profiling_active());
}

TEST_F(CallbackScopeTest, testTheScopeLetsACallbackThroughWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::Running;

  const auto scope = CallbackScope(TimerRegion::READ, CallbackId::READ, "test");

  EXPECT_TRUE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::NotInitialized;

  const auto scope = CallbackScope(TimerRegion::READ, CallbackId::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::Terminated;

  const auto scope = CallbackScope(TimerRegion::READ, CallbackId::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

// the decision is made when the scope is entered, so a callback that is already running finishes
// even if the runtime terminates underneath it
TEST_F(CallbackScopeTest, testTheDecisionIsTakenOnceAndDoesNotChangeAfterwards) {
  runtime_state = RuntimeState::Running;
  const auto scope = CallbackScope(TimerRegion::READ, CallbackId::READ, "test");

  runtime_state = RuntimeState::Terminated;

  EXPECT_TRUE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testACallbackDoesItsWorkWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::Running;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testACallbackReturnsWithoutWorkBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::NotInitialized;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

// the case the state exists for: the instrumented destructors of the target's globals
TEST_F(CallbackScopeTest, testACallbackReturnsWithoutWorkAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::Terminated;

  instrumented_callback();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

TEST_F(CallbackScopeTest, testACallbackMayReleaseAndTakeTheLockAgain) {
  runtime_state = RuntimeState::Running;

  instrumented_callback_releasing_the_lock();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

// releasing what was never taken is what a callback that returns early would do
TEST_F(CallbackScopeTest, testReleasingTheLockOfAStoppedCallbackIsHarmless) {
  runtime_state = RuntimeState::Terminated;
  auto scope = CallbackScope(TimerRegion::READ, CallbackId::READ, "test");

  scope.unlock();
  scope.relock();

  EXPECT_FALSE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testACallbackWithoutAScopeDoesItsWorkWhileTheRuntimeRuns) {
  runtime_state = RuntimeState::Running;

  instrumented_callback_without_a_scope();

  EXPECT_EQ(callbacks_that_did_their_work, 1);
}

TEST_F(CallbackScopeTest, testACallbackWithoutAScopeReturnsWithoutWorkAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::Terminated;

  instrumented_callback_without_a_scope();

  EXPECT_EQ(callbacks_that_did_their_work, 0);
}

// The benchmark builds leave callback bodies out to measure what the calls cost on their own, and
// switch exactly one back on to measure what that body adds. Which of the three a runtime library
// is compiled as is a build option, so what is checked here is the shipped build: the one every
// other test in this binary, and every profiled program, depends on.
TEST_F(CallbackScopeTest, testEveryCallbackBodyIsEnabledInTheShippedBuild) {
  for (const auto callback : all_callbacks) {
    EXPECT_TRUE(callback_body_enabled(callback)) << "callback id " << static_cast<int>(callback);
  }
}

// It has to fold away, not be asked at runtime: a body that is only skipped over still costs the
// branch that skips it, and the measurement would report that branch as the cost of the body.
TEST_F(CallbackScopeTest, testWhetherABodyIsEnabledIsDecidedAtCompileTime) {
  static_assert(callback_body_enabled(CallbackId::READ), "the shipped build runs every body");
  static_assert(callback_body_enabled(CallbackId::LOOP_INCR), "the shipped build runs every body");

  SUCCEED();
}

// A timed section is the non-callback variant: no state check and no lock, used for the
// individual output steps of __dp_finalize, which run with the lock already held.
TEST_F(CallbackScopeTest, testATimedSectionDoesNotDependOnTheRuntimeState) {
  runtime_state = RuntimeState::Terminated;

  DP_TIMED_SECTION(OUTPUT_LOOPS, "outputLoops");

  SUCCEED();
}
