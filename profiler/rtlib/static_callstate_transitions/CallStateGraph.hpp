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
#include "CallState.hpp"
#include <cstdint>
#include <iostream>
#include <unordered_map>

class CallStateGraph {
private:
  std::unordered_map<std::int32_t, CallState *> node_map;

public:
  CallStateGraph();
  ~CallStateGraph();
  CallState *get_or_register_node(std::int32_t call_state_id);
  void register_transition(std::int32_t source_call_state_id, std::int32_t trigger_instruction,
                           std::int32_t target_call_state_id);
  void register_implicit_return_transition(std::int32_t source_call_state_id, std::int32_t target_call_state_id);
};
