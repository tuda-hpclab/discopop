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
#include <string>
#include <vector>

#include "DPTypes.hpp"
#include "memory/AbstractShadow.hpp"
#include "memory/PerfectShadow.hpp"
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

void AnalyzeSingleAccess(dp::AbstractShadow* smem, dp::AccessInfo& access);

// AnalyzeSingleAccess on the persistent shadow of the second access queue's consumer: the slot of the access's address
// holds what the shadow would hold for it, so no lookup is needed.
void AnalyzeAccessOnSlot(ShadowSlot& slot, const AccessInfo& access);

// Run by a first queue worker at the end of its chunk: reorders `entry_accesses` by address (keeping the order of the
// accesses of each address, but not the order across addresses, which the analysis does not depend on) and returns
// one record per address, in the same order, carrying the exit state of the address in `chunk_shadow`. Every address
// of the chunk has an entry access (the first access to an address always is one), so the records cover the chunk.
std::vector<AddressRecord> GroupEntryAccessesByAddress(std::vector<AccessInfo>& entry_accesses,
                                                       const PerfectShadow2& chunk_shadow);

// Run by the consumer of the second access queue per chunk: analyzes the entry accesses of each address against its
// slot in `shadow` and leaves the slot in the exit state of the chunk, with one lookup per address.
void AnalyzeChunkOnSlots(HashMap<std::int64_t, ShadowSlot>& shadow, const std::vector<AccessInfo>& entry_accesses,
                         const std::vector<AddressRecord>& records);

// the dependency analysis of one access on the calling thread, used if NUM_WORKERS==0
void AnalyzeSingleAccessOnMainThread(dp::AccessInfo& access);

void FinalizeParallelization();

void FinalizeSingleThreadedExecution();

}  // namespace dp
