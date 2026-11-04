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

#include <cstddef>
#include <cstdint>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "llvm/IR/Module.h"

#include "Structs.hpp"
#include "static_analysis/StaticCallPathTree.hpp"
#include "static_analysis/StaticCalltree.hpp"

// The static call tree of a module and the call path states enumerated from it (the call path state
// transitions the runtime follows), with the files that describe them. None of this depends on the state of
// the pass, so these are functions of their own.
namespace static_callpaths {

// builds a call tree for the given Module on the basis of the statically available information; writes
// loopstate_positions.txt, naming the loops by `loop_id_to_identity`
StaticCalltree BuildStaticCalltree(llvm::Module& m, const std::map<int32_t, LoopIdentity>& loop_id_to_identity);

// std::pair<std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>>, std::unordered_map<int32_t,
// std::unordered_map<int32_t, int32_t>>> enumerate_paths(StaticCalltree& calltree);
StaticCallPathTree* EnumeratePaths(
    StaticCalltree& calltree, std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>* state_transitions,
    std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>* inverse_state_transitions);
// void save_initial_path(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths);
void SaveInitialPath(StaticCallPathTree* call_path_tree_ptr);
// void save_enumerated_paths(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths);
void SaveEnumeratedPaths(StaticCallPathTree* call_path_tree_ptr);
// void save_path_state_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *transitions);
void SavePathStateTransitions(StaticCallPathTree* call_path_tree_ptr);
void SaveStaticCalltreeToDot(StaticCalltree* calltree);
void SaveFunctionEntries(StaticCallPathTree* call_path_tree_ptr);

// void add_function_exit_edges_to_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>&
// state_transitions, std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths,
// std::unordered_map<std::vector<StaticCalltreeNode*>, int32_t, container_hash<std::vector<StaticCalltreeNode*>>>
// path_to_id_map);
// void add_function_exit_edges_to_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>&
// state_transitions, StaticCallPathTree* call_path_tree_ptr);
void AddFunctionExitEdgesToTransitions(StaticCallPathTree* call_path_tree_ptr);

}  // namespace static_callpaths
