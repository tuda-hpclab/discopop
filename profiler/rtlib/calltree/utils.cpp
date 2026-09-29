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

#include "utils.hpp"
#include "../../share/include/timer.hpp"
#include "../runtimeFunctionsGlobals.hpp"
#include <iostream>

namespace __dp {

DependencyMetadata processQueueElement(MetaDataQueueElement &&mdqe) {

#ifdef DP_INTERNAL_TIMER
  const auto calltree_timer = Timer(timers, TimerRegion::PROCESSQUEUEELEMENT);
#endif

  // Keep accessed nodes alive at least until this function is returning
  // Since theo sink_ctn and source_ctn are kept alive until the function returns, we
  // also know, that their ancestors will be kept alive. For this reason, we can use the
  // regular CallTreeNode* in the following and prevent useless reference counter modifications
  // of the shared_ptr.
  shared_ptr<CallTreeNode> buffer_sink_ctn = std::move(mdqe.sink_ctn);
  shared_ptr<CallTreeNode> buffer_source_ctn = std::move(mdqe.source_ctn);

  CallTreeNode *curr_ctn_node_1 = buffer_sink_ctn.get();
  CallTreeNode *curr_ctn_node_2 = buffer_source_ctn.get();

  // collect ancestors of sink_ctn

  hashset<CallTreeNode *> sink_ctn_ancestors;
  hashset<unsigned int> sink_ancestor_loops_and_functions;
  if (curr_ctn_node_1) {
    while (curr_ctn_node_1->get_node_type() != CallTreeNodeType::Root) {
      if (curr_ctn_node_1->get_node_type() == CallTreeNodeType::Loop) {
        // ignore for metadata calculation, but keep for ancestor reporting
        sink_ancestor_loops_and_functions.insert(curr_ctn_node_1->get_loop_or_function_id());
        curr_ctn_node_1 = curr_ctn_node_1->get_parent_ptr_raw(); // duplicate this to prevent jerking reference counters

      } else {
        CallTreeNode *parent_ptr = curr_ctn_node_1->get_parent_ptr_raw();

        // ancestor reporting
        if (curr_ctn_node_1->get_node_type() == CallTreeNodeType::Function) {
          sink_ancestor_loops_and_functions.insert(curr_ctn_node_1->get_loop_or_function_id());
        }

        sink_ctn_ancestors.insert(curr_ctn_node_1);

        curr_ctn_node_1 = parent_ptr;
      }

      if (!curr_ctn_node_1) {
        break;
      }
    }
  }

  // collect ancestors of source_ctn
  hashset<CallTreeNode *> source_ctn_ancestors;
  hashset<unsigned int> source_ancestor_loops_and_functions;
  if (curr_ctn_node_2) {
    while (curr_ctn_node_2->get_node_type() != CallTreeNodeType::Root) {
      if (curr_ctn_node_2->get_node_type() == CallTreeNodeType::Loop) {
        // ignore for metadata calculation, but keep for ancestor reporting
        source_ancestor_loops_and_functions.insert(curr_ctn_node_2->get_loop_or_function_id());
      } else {
        source_ctn_ancestors.insert(curr_ctn_node_2);
        // ancestor reporting
        if (curr_ctn_node_2->get_node_type() == CallTreeNodeType::Function) {
          source_ancestor_loops_and_functions.insert(curr_ctn_node_2->get_loop_or_function_id());
        }
      }

      curr_ctn_node_2 = curr_ctn_node_2->get_parent_ptr_raw();
      if (!curr_ctn_node_2) {
        break;
      }
    }
  }

  // determine common ancestors
  hashset<CallTreeNode *> common_ancestors;
  for (auto &sink_anc : sink_ctn_ancestors) {
    for (auto &source_anc : source_ctn_ancestors) {
      if (sink_anc == source_anc) {
        common_ancestors.insert(sink_anc);
      }
    }
  }

  // determine disjoint ancestors
  hashset<CallTreeNode *> disjoint_sink_ancestors;
  hashset<CallTreeNode *> disjoint_source_ancestors;
  for (auto &sink_anc : sink_ctn_ancestors) {
    bool contained = false;
    for (auto &source_anc : source_ctn_ancestors) {
      if (sink_anc == source_anc) {
        contained = true;
        break;
      }
    }
    if (!contained) {
      disjoint_sink_ancestors.insert(sink_anc);
    }
  }
  for (auto &source_anc : source_ctn_ancestors) {
    bool contained = false;
    for (auto &sink_anc : sink_ctn_ancestors) {
      if (source_anc == sink_anc) {
        contained = true;
        break;
      }
    }
    if (!contained) {
      disjoint_source_ancestors.insert(source_anc);
    }
  }

  // identify intra_call and intra_iteration dependencies
  hashset<unsigned int> intra_call_dependencies;
  hashset<unsigned int> intra_iteration_dependencies;
  for (auto &common_anc : common_ancestors) {
    if (common_anc->get_node_type() == CallTreeNodeType::Function) {
      intra_call_dependencies.insert(common_anc->get_loop_or_function_id());
    } else if (common_anc->get_node_type() == CallTreeNodeType::Iteration) {
      intra_iteration_dependencies.insert(common_anc->get_loop_or_function_id());
    }
  }

  // identify inter_call and inter_iteration dependencies
  hashset<unsigned int> inter_call_dependencies;
  hashset<unsigned int> inter_iteration_dependencies;
  for (auto &disjoint_sink_anc : disjoint_sink_ancestors) {
    for (auto &disjoint_source_anc : disjoint_source_ancestors) {
      // check for inter call dependencies
      if ((disjoint_sink_anc->get_node_type() == CallTreeNodeType::Function) &&
          (disjoint_source_anc->get_node_type() == CallTreeNodeType::Function) &&
          (disjoint_sink_anc->get_loop_or_function_id() == disjoint_source_anc->get_loop_or_function_id())) {
        inter_call_dependencies.insert(disjoint_sink_anc->get_loop_or_function_id());
      }
      // check for inter iteration dependencies
      if ((disjoint_sink_anc->get_node_type() == CallTreeNodeType::Iteration) &&
          (disjoint_source_anc->get_node_type() == CallTreeNodeType::Iteration) &&
          (disjoint_sink_anc->get_parent_ptr_raw() == disjoint_source_anc->get_parent_ptr_raw()) &&
          (disjoint_sink_anc->get_parent_ptr_raw()->get_node_type() == CallTreeNodeType::Loop)) {
        // using get_parent_ptr_raw is unclean but fine here, since disjoint_sink_anc hold a shared_ptr to parent and
        // thus prevents it's deletion. Using the raw pointer prevents count jerking.
        inter_iteration_dependencies.insert(disjoint_sink_anc->get_loop_or_function_id());
      }
    }
  }

  return DependencyMetadata(mdqe, std::move(intra_call_dependencies), std::move(intra_iteration_dependencies),
                            std::move(inter_call_dependencies), std::move(inter_iteration_dependencies),
                            std::move(sink_ancestor_loops_and_functions),
                            std::move(source_ancestor_loops_and_functions));
}

} // namespace __dp
