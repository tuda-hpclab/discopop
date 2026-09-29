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

public:
  CallState(int32_t id_arg) : id(id_arg) {}
  void register_transition(int32_t trigger_instruction, CallState *target_state);
  void register_implicit_return_transition(CallState *target_state);
  int32_t get_id();
  CallState *get_transition_target(int32_t trigger_instruction);
  CallState *get_implicit_return_transition_target();
};
