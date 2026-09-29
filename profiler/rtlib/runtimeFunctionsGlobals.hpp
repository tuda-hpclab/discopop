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

#include "../share/include/timer.hpp"
#include "calltree/CallTree.hpp"
#include "calltree/DependencyMetadata.hpp"
#include "memory/AbstractShadow.hpp"
#include "runtimeFunctionsTypes.hpp"
#include "static_callstate_transitions/CallStateGraph.hpp"

#include <pthread.h>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <list>
#include <mutex>
#include <queue>
#include <stack>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>

extern bool USE_PERFECT;

// Shadow memory parameters
extern std::int32_t SIG_ELEM_BIT;
extern std::int32_t SIG_NUM_ELEM;
extern std::int32_t SIG_NUM_HASH;

extern std::uint64_t *numAccesses;

namespace __dp {

extern bool DP_DEBUG; // debug flag

extern Timers *timers;

extern std::mutex pthread_compatibility_mutex;

extern FunctionManager *function_manager;
extern LoopManager *loop_manager;
extern MemoryManager *memory_manager;

#if DP_CALLTREE_PROFILING
extern CallTree call_tree;
extern std::mutex dependency_metadata_results_mtx;
extern std::unordered_set<DependencyMetadata> dependency_metadata_results;
extern thread_local std::unordered_set<DependencyMetadata> local_dependency_metadata_results;
#endif

// hybrid analysis
extern ReportedBBSet *bbList;
extern stringDepMap *outPutDeps;
// end hybrid analysis

extern std::unordered_map<char *, long> cuec;

extern bool dpInited;         // library initialization flag
extern bool targetTerminated; // whether the target program has returned from main()
// In C++, destructors of global objects can run after main().
// However, when the target program returns from main(), dp
// also frees all the resources. If there are destructors run
// after main(), __dp_func_entry() will be called again, but
// resources are freed, leading to segmentation fault.

// Runtime merging structures
extern depMap *allDeps;

extern std::ofstream *out;

extern std::mutex allDepsLock;
extern pthread_t *workers;                          // worker threads
extern volatile bool finalizeParallelizationCalled; // signals to worker threads that no further data access will be
                                                    // registered in the first queue
extern FirstAccessQueueChunk *mainThread_AccessInfoBuffer;
#define FIRST_ACCESS_QUEUE_SIZES 100000
#define SECOND_ACCESS_QUEUE_SIZES 1000

extern FirstAccessQueue firstAccessQueue;
extern SecondAccessQueue secondAccessQueue;
extern pthread_t *secondAccessQueue_worker_thread;
extern FirstAccessQueueChunkBuffer firstAccessQueueChunkBuffer;

extern AbstractShadow *singleThreadedExecutionSMem;

extern int32_t NUM_WORKERS;

extern thread_local depMap *myMap;

extern CallState *current_callpath_state;
// TODO: keep track of function calls without executed transition to allow recursion and circular calls (not possible in
// the graph due to non-circular states) if a function is left, but the current counter in
// calls_without_executed_transitions is not 0, decrease the counter instead of transitioning the state. disables the
// transitioning
extern std::vector<uint32_t> calls_without_executed_transitions;
extern CallStateGraph *call_state_graph;

// statistics
extern std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

} // namespace __dp
