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

#include <string>

#include "DPTypes.hpp"
#include "memory/AbstractShadow.hpp"
#include "runtimeFunctionsTypes.hpp"

namespace dp {

/******* Helper functions *******/
void AddDep(DepType type, LID curr, LID dep_on, const char* var, std::int64_t aa_var, ADDR addr);

void OutputDeps();

void GenerateStringDepMap();

void ReadRuntimeInfo();

void InitParallelization();

void InitSingleThreadedExecution();

void MergeDeps();

// void *analyzeDeps(void *arg);

void* ProcessFirstAccessQueue(void* arg);

void* ProcessSecondAccessQueue(void* arg);

// frees the chunks the consumer of the second access queue retires
void* ProcessGarbageQueue(void* arg);

void AnalyzeSingleAccess(dp::AbstractShadow* smem, dp::AccessInfo& access);

// the dependency analysis of one access on the calling thread, used if NUM_WORKERS==0
void AnalyzeSingleAccessOnMainThread(dp::AccessInfo& access);

void FinalizeParallelization();

void FinalizeSingleThreadedExecution();

}  // namespace dp
