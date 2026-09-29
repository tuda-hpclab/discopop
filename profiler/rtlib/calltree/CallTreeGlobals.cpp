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

#include "CallTreeGlobals.hpp"

namespace __dp {

std::atomic<unsigned int> *call_tree_node_count = nullptr; // nodes in use. deactivated by default setting nullptr
std::atomic<unsigned int> *call_tree_total_living_node_count =
    nullptr; // nodes prepared. deactivated by default setting nullptr

bool calltree_thread_stop = false; // stop signal

} // namespace __dp
