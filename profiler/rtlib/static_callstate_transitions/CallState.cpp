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
}

void CallState::register_implicit_return_transition(CallState *target_state) {
  implicit_return_transition_target = target_state;
}

int32_t CallState::get_id() { return id; }

CallState *CallState::get_transition_target(int32_t trigger_instruction) {
  auto pos = transitions.find(trigger_instruction);
  if (pos == transitions.end()) {
    return nullptr;
  }
  return pos->second;
}

CallState *CallState::get_implicit_return_transition_target() { return implicit_return_transition_target; }
