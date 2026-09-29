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

#include "../DPUtils.hpp"
#include "CallTreeGlobals.hpp"
#include "CallTreeNodeType.hpp"

#include <memory>

namespace __dp {

class CallTreeNode {
public:
  CallTreeNode();
  CallTreeNode(shared_ptr<CallTreeNode> parent_ptr, CallTreeNode *parent_ptr_raw, CallTreeNodeType type,
               unsigned int loop_or_function_id, unsigned int iteration_id);
  ~CallTreeNode();
  bool operator==(const CallTreeNode &other) const;
  shared_ptr<CallTreeNode> get_parent_ptr();
  CallTreeNode *get_parent_ptr_raw(); // must not be used by threads other than the main!
  CallTreeNodeType get_node_type();
  unsigned int get_loop_or_function_id();
  unsigned int get_iteration_id(); // only relevant for iteration type nodes, else always 0
  void set(shared_ptr<CallTreeNode> &&arg_parent_ptr, CallTreeNode *arg_parent_ptr_raw, CallTreeNodeType arg_type,
           unsigned int arg_loop_or_function_id, unsigned int arg_iteration_id);

private:
  CallTreeNodeType type;
  unsigned int loop_or_function_id; // id of the loop or function that is represented by the current node
  unsigned int iteration_id;
  shared_ptr<CallTreeNode> parent_ptr;
  CallTreeNode *parent_ptr_raw; // must not be used by threads other than the main for dereferencing. Using for equality
                                // checks is fine!
  atomic<unsigned int> *node_count_ptr;
};

} // namespace __dp
