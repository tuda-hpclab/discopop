#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/static_callstate_transitions/CallState.hpp"

class CallStateTest : public ::testing::Test {};

TEST_F(CallStateTest, testGetId) {
  CallState state(42);
  EXPECT_EQ(state.get_id(), 42);
}

TEST_F(CallStateTest, testGetTransitionTargetWithoutRegisteredTransition) {
  CallState state(1);
  EXPECT_EQ(state.get_transition_target(99), nullptr);
}

TEST_F(CallStateTest, testRegisterAndGetTransitionTarget) {
  CallState source(1);
  CallState target(2);

  source.register_transition(10, &target);

  EXPECT_EQ(source.get_transition_target(10), &target);
  EXPECT_EQ(source.get_transition_target(11), nullptr);
}

TEST_F(CallStateTest, testRegisterTransitionOverwritesExistingTrigger) {
  CallState source(1);
  CallState target_a(2);
  CallState target_b(3);

  source.register_transition(10, &target_a);
  source.register_transition(10, &target_b);

  EXPECT_EQ(source.get_transition_target(10), &target_b);
}

TEST_F(CallStateTest, testGetImplicitReturnTransitionTargetWithoutRegisteredTransition) {
  CallState state(1);
  EXPECT_EQ(state.get_implicit_return_transition_target(), nullptr);
}

TEST_F(CallStateTest, testRegisterAndGetImplicitReturnTransitionTarget) {
  CallState source(1);
  CallState target(2);

  source.register_implicit_return_transition(&target);

  EXPECT_EQ(source.get_implicit_return_transition_target(), &target);
}

// Returns are stored without the dummy "return" trigger id 1 they used to be keyed by, so
// registering one must not make it observable as a regular transition (and vice versa).
TEST_F(CallStateTest, testImplicitReturnTransitionIsSeparateFromRegularTransitions) {
  CallState source(1);
  CallState return_target(2);
  CallState regular_target(3);

  source.register_implicit_return_transition(&return_target);
  source.register_transition(1, &regular_target);

  EXPECT_EQ(source.get_implicit_return_transition_target(), &return_target);
  EXPECT_EQ(source.get_transition_target(1), &regular_target);
}

// utils.cpp only ever reads a state it has reached, so none of that has to go through a mutable
// reference
TEST_F(CallStateTest, testAStateCanBeReadThroughAConstReference) {
  CallState source(1);
  CallState target(2);
  CallState return_target(3);
  source.register_transition(10, &target);
  source.register_implicit_return_transition(&return_target);

  const CallState &reference = source;

  EXPECT_EQ(reference.get_id(), 1);
  EXPECT_EQ(reference.get_transition_target(10), &target);
  EXPECT_EQ(reference.get_transition_target(11), nullptr);
  EXPECT_EQ(reference.get_implicit_return_transition_target(), &return_target);
}

// looking a trigger up must not add it: the transitions of a state are what the input file listed
TEST_F(CallStateTest, testLookingUpAnUnknownTriggerDoesNotAddIt) {
  CallState source(1);
  CallState target(2);
  source.register_transition(10, &target);

  ASSERT_EQ(source.get_transition_target(11), nullptr);

  EXPECT_EQ(source.get_transition_target(10), &target);
  EXPECT_EQ(source.get_transition_target(11), nullptr);
}
