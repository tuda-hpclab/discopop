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

#include <algorithm>

namespace {

bool TriggerBefore(const std::pair<std::int32_t, CallState*>& transition, std::int32_t trigger_instruction) {
  return transition.first < trigger_instruction;
}

}  // namespace

void CallState::RegisterTransition(std::int32_t trigger_instruction, CallState* target_state) {
  const auto pos = std::lower_bound(transitions_.begin(), transitions_.end(), trigger_instruction, TriggerBefore);
  if (pos != transitions_.end() && pos->first == trigger_instruction) {
    pos->second = target_state;
  } else {
    transitions_.insert(pos, {trigger_instruction, target_state});
  }
  if (trigger_instruction == kFallthroughTrigger) {
    fallthrough_transition_target_ = target_state;
  } else if (trigger_instruction == kReturnTrigger) {
    return_transition_target_ = target_state;
  }
}

void CallState::RegisterImplicitReturnTransition(CallState* target_state) {
  implicit_return_transition_target_ = target_state;
  // A transition registered under the return trigger wins, whichever of the two arrives first:
  // that is the order update_callstate_from_func_exit asked the two questions in.
  const auto pos = std::lower_bound(transitions_.begin(), transitions_.end(), kReturnTrigger, TriggerBefore);
  if (pos == transitions_.end() || pos->first != kReturnTrigger) {
    return_transition_target_ = target_state;
  }
}

int32_t CallState::GetId() const { return id_; }

CallState* CallState::GetTransitionTarget(int32_t trigger_instruction) const {
  const auto pos = std::lower_bound(transitions_.begin(), transitions_.end(), trigger_instruction, TriggerBefore);
  if (pos == transitions_.end() || pos->first != trigger_instruction) {
    return nullptr;
  }
  return pos->second;
}

CallState* CallState::GetImplicitReturnTransitionTarget() const { return implicit_return_transition_target_; }

CallState* CallState::GetFallthroughTransitionTarget() const { return fallthrough_transition_target_; }

CallState* CallState::GetReturnTransitionTarget() const { return return_transition_target_; }
