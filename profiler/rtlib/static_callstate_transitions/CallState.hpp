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
#include <cstdint>
#include <iostream>
#include <unordered_map>

class CallState {
private:
  std::int32_t id;
  std::unordered_map<int32_t, CallState *> transitions;
  CallState *implicit_return_transition_target = nullptr;
  // instruction id of the __dp_func_entry call of the function this state lies in, if the state
  // is the entry state of a function instance (see callpath_function_entries.txt), else 0
  std::int32_t function_entry_id = 0;
  // The two triggers below are looked up under a fixed id on paths that run per call and per
  // function exit, so they are kept as a pointer next to the map and resolved where the transition
  // is registered. A hash lookup that always asks the same question does not belong in a callback.
  CallState *fallthrough_transition_target = nullptr;
  CallState *return_transition_target = nullptr;

public:
  // Instruction id '0' does not name an instruction: a transition registered under it is taken
  // immediately after the state has been entered.
  static constexpr std::int32_t kFallthroughTrigger = 0;
  // The dummy instruction id that stands for leaving a function.
  static constexpr std::int32_t kReturnTrigger = 1;

  CallState(int32_t id_arg) : id(id_arg) {}
  void register_transition(int32_t trigger_instruction, CallState *target_state);
  void register_implicit_return_transition(CallState *target_state);
  int32_t get_id() const;
  CallState *get_transition_target(int32_t trigger_instruction) const;
  CallState *get_implicit_return_transition_target() const;
  void set_function_entry_id(int32_t function_entry_id_arg) { function_entry_id = function_entry_id_arg; }
  int32_t get_function_entry_id() const { return function_entry_id; }
  // The target of this state's own fall-through transition, or nullptr if it has none.
  CallState *get_fallthrough_transition_target() const;
  // Where leaving a function from this state leads: the transition registered under
  // kReturnTrigger if there is one, the implicit return target otherwise, nullptr if neither
  // exists.
  CallState *get_return_transition_target() const;
};
