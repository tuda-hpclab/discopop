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

#include "Immortal.hpp"
#include "memory/AbstractShadow.hpp"
#include "runtimeFunctionsTypes.hpp"
#include "static_callstate_transitions/CallStateGraph.hpp"
#include "timer.hpp"

extern bool use_perfect;

// Shadow memory parameters
extern std::int32_t sig_elem_bit;
extern std::int32_t sig_num_elem;
extern std::int32_t sig_num_hash;

extern std::uint64_t* num_accesses;

namespace dp {

// DP_DEBUG is declared in DPTypes.hpp, see the note there.

extern Timers* timers;

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

void ConstructManagerGlobals();
void DestroyManagerGlobals();
bool ManagerGlobalsConstructed() noexcept;

// hybrid analysis
extern ReportedBBRecorder* bb_list;
extern StringDepMap* out_put_deps;
// end hybrid analysis

// The globals declared as references below outlive the static destructors of the target
// program: __dp_finalize still uses them after those have run. They are constructed by
// construct_immortal_globals() and destroyed at the end of __dp_finalize; before the runtime
// has been initialized, the referenced objects do not exist yet. See Immortal.hpp.
void ConstructImmortalGlobals();
void DestroyImmortalGlobals();

extern std::unordered_map<char*, int64_t>& cuec;

// What the runtime is currently doing. There are exactly three states and they are reached in
// order: __dp_init moves to Running, __dp_finalize moves to Terminated.
//
// Terminated is not the same as "not initialized". The target's global destructors run after
// __dp_finalize has written the results and released the runtime's resources, and they are
// instrumented like everything else, so their callbacks still arrive -- they have to return
// without touching anything, not start the runtime up again.
enum class RuntimeState {
  kNotInitialized,
  kRunning,
  kTerminated,
};

extern RuntimeState runtime_state;

// The question every instrumented callback asks: may it do its work?
inline bool ProfilingActive() noexcept { return runtime_state == RuntimeState::kRunning; }

// Runtime merging structures
extern DepMap* all_deps;

extern std::ofstream* out;

extern std::mutex all_deps_lock;
extern pthread_t* workers;                                 // worker threads
extern std::atomic<bool> finalize_parallelization_called;  // signals to worker threads that no further data access will
                                                           // be registered in the first queue
extern FirstAccessQueueChunk* main_thread_access_info_buffer;
// number of accesses recorded per chunk of the first access queue
constexpr int kFirstAccessQueueChunkSize = 100000;
// default limits of the access queues, per worker thread; adjustable via dp.conf
// (FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER, SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER). A queued chunk holds
// FIRST_ACCESS_QUEUE_CHUNK_SIZE accesses (~4 MB), a second queue element up to ~11 MB.
constexpr int kDefaultFirstAccessQueueChunksPerWorker = 4;
constexpr int kDefaultSecondAccessQueueElementsPerWorker = 4;

extern FirstAccessQueue& first_access_queue;
extern SecondAccessQueue& second_access_queue;
extern pthread_t* second_access_queue_worker_thread;
extern FirstAccessQueueChunkBuffer& first_access_queue_chunk_buffer;

extern AbstractShadow* single_threaded_execution_smem;

extern int32_t num_workers;
extern int32_t first_access_queue_chunks_per_worker;
extern int32_t second_access_queue_elements_per_worker;
// allowance of the caches in front of the recorded basic block reports in MiB, adjustable via dp.conf
// (BB_REPORT_CACHE_MB, 0 turns the caches off), see ReportedBBRecorder
constexpr int kDefaultBbReportCacheMb = 50;
extern int32_t bb_report_cache_mb;

extern thread_local DepMap* my_map;

// see static_callstate_transitions/utils.hpp
extern CallState* current_callpath_state;
// the id of current_callpath_state (0 without one), read by every access and basic block report; both are set
// together by SetCurrentCallpathState
extern std::uint32_t current_callpath_state_id;
extern CallStateGraph* call_state_graph;

// statistics
extern std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

}  // namespace dp
