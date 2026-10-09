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
#include "Immortal.hpp"
#include "calltree/CallTree.hpp"
#include "calltree/DependencyMetadata.hpp"
#include "memory/AbstractShadow.hpp"
#include "runtimeFunctionsTypes.hpp"
#include "static_callstate_transitions/CallStateGraph.hpp"

#include <pthread.h>

#include <atomic>
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

// DP_DEBUG is declared in DPTypes.hpp, see the note there.

extern Timers *timers;

extern std::mutex pthread_compatibility_mutex;

// The three managers the callbacks reach through. The storage is the global, rather than a
// pointer to a heap object: reaching one then costs no load of a pointer first, and __dp_read
// and __dp_write ask the function manager to reset the call tracker on every single access.
//
// Their lifetime is unchanged -- construct_manager_globals() runs where __dp_init used to new
// them, destroy_manager_globals() where __dp_finalize used to delete them. Outside that window
// they do not exist, which manager_globals_constructed() answers for the one caller that used
// to compare the pointer against null.
extern ImmortalStorage<FunctionManager> function_manager;
extern ImmortalStorage<LoopManager> loop_manager;
extern ImmortalStorage<MemoryManager> memory_manager;

void construct_manager_globals();
void destroy_manager_globals();
bool manager_globals_constructed() noexcept;

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

// The globals declared as references below outlive the static destructors of the target
// program: __dp_finalize still uses them after those have run. They are constructed by
// construct_immortal_globals() and destroyed at the end of __dp_finalize; before the runtime
// has been initialized, the referenced objects do not exist yet. See Immortal.hpp.
void construct_immortal_globals();
void destroy_immortal_globals();

extern std::unordered_map<char *, long> &cuec;

// What the runtime is currently doing. There are exactly three states and they are reached in
// order: __dp_init moves to Running, __dp_finalize moves to Terminated.
//
// Terminated is not the same as "not initialized". The target's global destructors run after
// __dp_finalize has written the results and released the runtime's resources, and they are
// instrumented like everything else, so their callbacks still arrive -- they have to return
// without touching anything, not start the runtime up again.
enum class RuntimeState {
  NotInitialized,
  Running,
  Terminated,
};

extern RuntimeState runtime_state;

// The question every instrumented callback asks: may it do its work?
inline bool profiling_active() noexcept { return runtime_state == RuntimeState::Running; }

// Runtime merging structures
extern depMap *allDeps;

extern std::ofstream *out;

extern std::mutex allDepsLock;
extern pthread_t *workers;                              // worker threads
extern std::atomic<bool> finalizeParallelizationCalled; // signals to worker threads that no further data access will be
                                                        // registered in the first queue
extern FirstAccessQueueChunk *mainThread_AccessInfoBuffer;
// number of accesses recorded per chunk of the first access queue
#define FIRST_ACCESS_QUEUE_CHUNK_SIZE 100000
// default limits of the access queues, per worker thread; adjustable via dp.conf
// (FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER, SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER). A queued chunk holds
// FIRST_ACCESS_QUEUE_CHUNK_SIZE accesses (~4 MB), a second queue element up to ~11 MB.
#define DEFAULT_FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER 4
#define DEFAULT_SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER 4

extern FirstAccessQueue &firstAccessQueue;
extern SecondAccessQueue &secondAccessQueue;
extern pthread_t *secondAccessQueue_worker_thread;
extern FirstAccessQueueChunkBuffer &firstAccessQueueChunkBuffer;

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
