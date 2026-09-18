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

#include "DPTypes.hpp"
#include "memory/AbstractShadow.hpp"
#include "runtimeFunctionsTypes.hpp"

#include <string>

namespace __dp {

/******* Helper functions *******/
#if DP_CALLTREE_PROFILING
void addDep(depType type, LID curr, LID depOn, const char *var, std::int64_t AAvar, ADDR addr,
            shared_ptr<CallTreeNode> arg_write_ctn, shared_ptr<CallTreeNode> arg_read_ctn,
            bool calculate_dependency_metadata);
#else
void addDep(depType type, LID curr, LID depOn, char *var, std::int64_t AAvar);
#endif

void outputDeps();

void generateStringDepMap();

void readRuntimeInfo();

void initParallelization();

void initSingleThreadedExecution();

void mergeDeps();

// void *analyzeDeps(void *arg);

void *processFirstAccessQueue(void *arg);

void *processSecondAccessQueue(void *arg);

#if DP_CALLTREE_PROFILING
void analyzeSingleAccess(
    __dp::AbstractShadow *SMem, __dp::AccessInfo &access,
    std::unordered_map<ADDR, std::shared_ptr<CallTreeNode>> *thread_private_write_addr_to_call_tree_node_map,
    std::unordered_map<ADDR, std::shared_ptr<CallTreeNode>> *thread_private_read_addr_to_call_tree_node_map);
#else
void analyzeSingleAccess(__dp::AbstractShadow *SMem, __dp::AccessInfo &access);
#endif

std::string getMemoryRegionIdFromAddr(std::string fallback, ADDR addr);

void finalizeParallelization();

void finalizeSingleThreadedExecution();

#if DP_STACK_ACCESS_DETECTION
void clearStackAccesses(ADDR stack_lower_bound, ADDR stack_upper_bound);
#endif
} // namespace __dp
