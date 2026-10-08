/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#include "CallState.hpp"

void CallState::register_transition(std::int32_t trigger_instruction, CallState *target_state) {
  transitions[trigger_instruction] = target_state;
  if (trigger_instruction == kFallthroughTrigger) {
    fallthrough_transition_target = target_state;
  } else if (trigger_instruction == kReturnTrigger) {
    return_transition_target = target_state;
  }
}

void CallState::register_implicit_return_transition(CallState *target_state) {
  implicit_return_transition_target = target_state;
  // A transition registered under the return trigger wins, whichever of the two arrives first:
  // that is the order update_callstate_from_func_exit asked the two questions in.
  if (transitions.find(kReturnTrigger) == transitions.end()) {
    return_transition_target = target_state;
  }
}

int32_t CallState::get_id() const { return id; }

CallState *CallState::get_transition_target(int32_t trigger_instruction) const {
  const auto pos = transitions.find(trigger_instruction);
  if (pos == transitions.end()) {
    return nullptr;
  }
  return pos->second;
}

CallState *CallState::get_implicit_return_transition_target() const { return implicit_return_transition_target; }

CallState *CallState::get_fallthrough_transition_target() const { return fallthrough_transition_target; }

CallState *CallState::get_return_transition_target() const { return return_transition_target; }
