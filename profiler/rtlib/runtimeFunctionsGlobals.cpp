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

bool USE_PERFECT = true;

// Shadow memory parameters
std::int32_t SIG_ELEM_BIT = 56;
std::int32_t SIG_NUM_ELEM = 270000;
std::int32_t SIG_NUM_HASH = 2;

std::uint64_t *numAccesses = nullptr;

namespace __dp {

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

std::unordered_map<char *, long> cuec;

bool dpInited = false;         // library initialization flag
bool targetTerminated = false; // whether the target program has returned from main()
// In C++, destructors of global objects can run after main().
// However, when the target program returns from main(), dp
// also frees all the resources. If there are destructors run
// after main(), __dp_func_entry() will be called again, but
// resources are freed, leading to segmentation fault.

// Runtime merging structures
depMap *allDeps = nullptr;

std::ofstream *out = nullptr;

/******* BEGIN: parallelization section *******/
std::mutex allDepsLock;
pthread_t *workers = nullptr; // worker threads
volatile bool finalizeParallelizationCalled =
    false; // signals to worker threads that no further data access will be registered in the first queue
FirstAccessQueueChunk *mainThread_AccessInfoBuffer = nullptr;
FirstAccessQueue firstAccessQueue(FIRST_ACCESS_QUEUE_SIZES);
SecondAccessQueue secondAccessQueue(SECOND_ACCESS_QUEUE_SIZES);
pthread_t *secondAccessQueue_worker_thread = nullptr;
FirstAccessQueueChunkBuffer firstAccessQueueChunkBuffer(10);

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
std::vector<uint32_t> calls_without_executed_transitions;
CallStateGraph *call_state_graph;

// statistics
std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

/******* END: parallelization section *******/

} // namespace __dp
