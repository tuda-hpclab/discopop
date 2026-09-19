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

  const auto scope = CallbackScope(TimerRegion::READ, "test");

  EXPECT_TRUE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackBeforeTheRuntimeStarted) {
  runtime_state = RuntimeState::NotInitialized;

  const auto scope = CallbackScope(TimerRegion::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

TEST_F(CallbackScopeTest, testTheScopeStopsACallbackAfterTheRuntimeTerminated) {
  runtime_state = RuntimeState::Terminated;

  const auto scope = CallbackScope(TimerRegion::READ, "test");

  EXPECT_FALSE(static_cast<bool>(scope));
}

// the decision is made when the scope is entered, so a callback that is already running finishes
// even if the runtime terminates underneath it
TEST_F(CallbackScopeTest, testTheDecisionIsTakenOnceAndDoesNotChangeAfterwards) {
  runtime_state = RuntimeState::Running;
  const auto scope = CallbackScope(TimerRegion::READ, "test");

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
  auto scope = CallbackScope(TimerRegion::READ, "test");

  scope.unlock();
  scope.relock();

  EXPECT_FALSE(static_cast<bool>(scope));
}

// A timed section is the non-callback variant: no state check and no lock, used for the
// individual output steps of __dp_finalize, which run with the lock already held.
TEST_F(CallbackScopeTest, testATimedSectionDoesNotDependOnTheRuntimeState) {
  runtime_state = RuntimeState::Terminated;

  DP_TIMED_SECTION(OUTPUT_LOOPS, "outputLoops");

  SUCCEED();
}
