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

#include "runtimeFunctionsGlobals.hpp"

#include "Immortal.hpp"
#include "hybrid_analysis/bb_deps.hpp"
#include "runtimeFunctions.hpp"

bool USE_PERFECT = true;

// Shadow memory parameters
std::int32_t SIG_ELEM_BIT = 56;
std::int32_t SIG_NUM_ELEM = 270000;
std::int32_t SIG_NUM_HASH = 2;

std::uint64_t *numAccesses = nullptr;

namespace __dp {

namespace {
// The backing storage of the globals whose lifetime the runtime manages itself, see
// Immortal.hpp for why they must not be destroyed along with the target's own globals.
ImmortalStorage<std::unordered_map<char *, long>> cuec_storage;
ImmortalStorage<std::vector<uint32_t>> calls_without_executed_transitions_storage;
ImmortalStorage<FirstAccessQueue> firstAccessQueue_storage;
ImmortalStorage<SecondAccessQueue> secondAccessQueue_storage;
ImmortalStorage<FirstAccessQueueChunkBuffer> firstAccessQueueChunkBuffer_storage;

bool immortal_globals_constructed = false;
} // namespace

bool DP_DEBUG = false; // debug flag

Timers *timers = nullptr;

std::mutex pthread_compatibility_mutex;

FunctionManager *function_manager = nullptr;
LoopManager *loop_manager = nullptr;
MemoryManager *memory_manager = nullptr;

#if DP_CALLTREE_PROFILING
CallTree call_tree;
std::mutex dependency_metadata_results_mtx;
std::unordered_set<DependencyMetadata> dependency_metadata_results;
thread_local std::unordered_set<DependencyMetadata> local_dependency_metadata_results;
#endif

// hybrid analysis
ReportedBBSet *bbList = nullptr;
stringDepMap *outPutDeps = nullptr;
// end hybrid analysis

std::unordered_map<char *, long> &cuec = cuec_storage.value;

RuntimeState runtime_state = RuntimeState::NotInitialized;

// Runtime merging structures
depMap *allDeps = nullptr;

std::ofstream *out = nullptr;

/******* BEGIN: parallelization section *******/
std::mutex allDepsLock;
pthread_t *workers = nullptr; // worker threads
volatile bool finalizeParallelizationCalled =
    false; // signals to worker threads that no further data access will be registered in the first queue
FirstAccessQueueChunk *mainThread_AccessInfoBuffer = nullptr;
FirstAccessQueue &firstAccessQueue = firstAccessQueue_storage.value;
SecondAccessQueue &secondAccessQueue = secondAccessQueue_storage.value;
pthread_t *secondAccessQueue_worker_thread = nullptr;
FirstAccessQueueChunkBuffer &firstAccessQueueChunkBuffer = firstAccessQueueChunkBuffer_storage.value;

#define XSTR(x) STR(x)
#define STR(x) #x
#ifdef DP_NUM_WORKERS
int32_t NUM_WORKERS = DP_NUM_WORKERS;
#else
int32_t NUM_WORKERS = 4; // default number of worker threads (multiple workers
                         // can potentially lead to non-deterministic results)
#endif

AbstractShadow *singleThreadedExecutionSMem = nullptr; // used if NUM_WORKERS==0

thread_local depMap *myMap = nullptr;

CallState *current_callpath_state = 0;
std::vector<uint32_t> &calls_without_executed_transitions = calls_without_executed_transitions_storage.value;
CallStateGraph *call_state_graph;

// statistics
std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

// Constructs the globals above. Called from __dp_init, before anything reads them, and
// idempotent so that a second entry point can call it too.
void construct_immortal_globals() {
  if (immortal_globals_constructed) {
    return;
  }
  cuec_storage.construct();
  calls_without_executed_transitions_storage.construct();
  firstAccessQueue_storage.construct(FIRST_ACCESS_QUEUE_SIZES);
  secondAccessQueue_storage.construct(SECOND_ACCESS_QUEUE_SIZES);
  firstAccessQueueChunkBuffer_storage.construct(10);
  immortal_globals_constructed = true;
}

// Destroys them again, at the end of __dp_finalize. Every callback returns early once the
// runtime state is Terminated, so nothing reaches these objects afterwards.
void destroy_immortal_globals() {
  release_registered_bb_deps();
  if (!immortal_globals_constructed) {
    return;
  }
  firstAccessQueueChunkBuffer_storage.destroy();
  secondAccessQueue_storage.destroy();
  firstAccessQueue_storage.destroy();
  calls_without_executed_transitions_storage.destroy();
  cuec_storage.destroy();
  immortal_globals_constructed = false;
}

/******* END: parallelization section *******/

} // namespace __dp
