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
extern ReportedBBRecorder *bbList;
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
// number of accesses recorded per chunk of the first access queue
#define FIRST_ACCESS_QUEUE_CHUNK_SIZE 100000
// default limits of the access queues, per worker thread; adjustable via dp.conf
// (FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER, SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER). A queued chunk holds
// FIRST_ACCESS_QUEUE_CHUNK_SIZE accesses (~4 MB), a second queue element up to ~11 MB.
#define DEFAULT_FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER 4
#define DEFAULT_SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER 4

extern FirstAccessQueue firstAccessQueue;
extern SecondAccessQueue secondAccessQueue;
extern pthread_t *secondAccessQueue_worker_thread;
extern FirstAccessQueueChunkBuffer firstAccessQueueChunkBuffer;

extern AbstractShadow *singleThreadedExecutionSMem;

extern int32_t NUM_WORKERS;
extern int32_t FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER;
extern int32_t SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER;

extern thread_local depMap *myMap;

// see static_callstate_transitions/utils.hpp
extern CallState *current_callpath_state;
extern CallStateGraph *call_state_graph;

// statistics
extern std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

} // namespace __dp
