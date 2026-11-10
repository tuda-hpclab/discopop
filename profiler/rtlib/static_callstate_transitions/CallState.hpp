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

#pragma once
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <utility>
#include <vector>

class CallState {
 private:
  std::int32_t id_;
  // (trigger instruction, target), sorted by the trigger instruction: a state has few transitions, which a binary
  // search of a contiguous array finds faster than a hash map
  std::vector<std::pair<int32_t, CallState*>> transitions_;
  CallState* implicit_return_transition_target_ = nullptr;
  // instruction id of the __dp_func_entry call of the function this state lies in, if the state
  // is the entry state of a function instance (see callpath_function_entries.txt), else 0
  std::int32_t function_entry_id_ = 0;
  // The two triggers below are looked up under a fixed id on paths that run per call and per
  // function exit, so they are kept as a pointer next to the map and resolved where the transition
  // is registered. A hash lookup that always asks the same question does not belong in a callback.
  CallState* fallthrough_transition_target_ = nullptr;
  CallState* return_transition_target_ = nullptr;

 public:
  // Instruction id '0' does not name an instruction: a transition registered under it is taken
  // immediately after the state has been entered.
  static constexpr std::int32_t kFallthroughTrigger = 0;
  // The dummy instruction id that stands for leaving a function.
  static constexpr std::int32_t kReturnTrigger = 1;

  explicit CallState(int32_t id_arg) : id_(id_arg) {}
  void RegisterTransition(int32_t trigger_instruction, CallState* target_state);
  void RegisterImplicitReturnTransition(CallState* target_state);
  // the getters run in the callbacks, so they are defined here, to be inlined into them
  int32_t GetId() const { return id_; }
  CallState* GetTransitionTarget(int32_t trigger_instruction) const {
    const auto pos = std::lower_bound(transitions_.begin(), transitions_.end(), trigger_instruction, TriggerBefore);
    if (pos == transitions_.end() || pos->first != trigger_instruction) {
      return nullptr;
    }
    return pos->second;
  }
  CallState* GetImplicitReturnTransitionTarget() const { return implicit_return_transition_target_; }
  void SetFunctionEntryId(int32_t function_entry_id_arg) { function_entry_id_ = function_entry_id_arg; }
  int32_t GetFunctionEntryId() const { return function_entry_id_; }
  // The target of this state's own fall-through transition, or nullptr if it has none.
  CallState* GetFallthroughTransitionTarget() const { return fallthrough_transition_target_; }
  // Where leaving a function from this state leads: the transition registered under
  // kReturnTrigger if there is one, the implicit return target otherwise, nullptr if neither
  // exists.
  CallState* GetReturnTransitionTarget() const { return return_transition_target_; }

 private:
  // orders the transitions by their trigger instruction
  static bool TriggerBefore(const std::pair<int32_t, CallState*>& transition, int32_t trigger_instruction) {
    return transition.first < trigger_instruction;
  }
};
