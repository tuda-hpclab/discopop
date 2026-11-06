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

#include <unordered_map>

#include "Immortal.hpp"
#include "hybrid_analysis/bb_deps.hpp"
#include "runtimeFunctions.hpp"

bool use_perfect = true;

// Shadow memory parameters
std::int32_t sig_elem_bit = 56;
std::int32_t sig_num_elem = 270000;
std::int32_t sig_num_hash = 2;

std::uint64_t* num_accesses = nullptr;

namespace dp {

namespace {
// The backing storage of the globals whose lifetime the runtime manages itself, see
// Immortal.hpp for why they must not be destroyed along with the target's own globals.
ImmortalStorage<std::unordered_map<char*, int64_t>> cuec_storage;
ImmortalStorage<FirstAccessQueue> first_access_queue_storage;
ImmortalStorage<SecondAccessQueue> second_access_queue_storage;
ImmortalStorage<GarbageQueue> garbage_queue_storage;
ImmortalStorage<FirstAccessQueueChunkBuffer> first_access_queue_chunk_buffer_storage;

bool immortal_globals_constructed = false;
bool manager_globals_alive = false;
}  // namespace

bool dp_debug = false;  // debug flag

Timers* timers = nullptr;

std::mutex pthread_compatibility_mutex;

ImmortalStorage<FunctionManager> function_manager;
ImmortalStorage<LoopManager> loop_manager;

// hybrid analysis
ReportedBBRecorder* bb_list = nullptr;
StringDepMap* out_put_deps = nullptr;
// end hybrid analysis

std::unordered_map<char*, int64_t>& cuec = cuec_storage.value;

RuntimeState runtime_state = RuntimeState::kNotInitialized;

// Runtime merging structures
DepMap* all_deps = nullptr;

std::ofstream* out = nullptr;

/******* BEGIN: parallelization section *******/
std::mutex all_deps_lock;
pthread_t* workers = nullptr;  // worker threads
// signals to worker threads that no further data access will be registered in the first queue
std::atomic<bool> finalize_parallelization_called = false;
FirstAccessQueueChunk* main_thread_access_info_buffer = nullptr;
FirstAccessQueue& first_access_queue = first_access_queue_storage.value;
SecondAccessQueue& second_access_queue = second_access_queue_storage.value;
pthread_t* second_access_queue_worker_thread = nullptr;
GarbageQueue& garbage_queue = garbage_queue_storage.value;
pthread_t* cleanup_worker_threads = nullptr;
FirstAccessQueueChunkBuffer& first_access_queue_chunk_buffer = first_access_queue_chunk_buffer_storage.value;

#define XSTR(x) STR(x)
#define STR(x) #x
#ifdef DP_NUM_WORKERS
int32_t num_workers = DP_NUM_WORKERS;
#else
int32_t num_workers = 4;  // default number of worker threads (multiple workers
                          // can potentially lead to non-deterministic results)
#endif

int32_t first_access_queue_chunks_per_worker = kDefaultFirstAccessQueueChunksPerWorker;
int32_t second_access_queue_elements_per_worker = kDefaultSecondAccessQueueElementsPerWorker;
int32_t cleanup_workers = kDefaultCleanupWorkers;

AbstractShadow* single_threaded_execution_smem = nullptr;  // used if NUM_WORKERS==0

thread_local DepMap* my_map = nullptr;

CallState* current_callpath_state = nullptr;
CallStateGraph* call_state_graph;

// statistics
std::chrono::high_resolution_clock::time_point statistics_profiling_start_time;

// The managers, constructed where __dp_init used to new them. Kept apart from the immortal
// globals below because they are created later in the startup sequence and a unit test brings
// them up on its own.
void ConstructManagerGlobals() {
  if (manager_globals_alive) {
    return;
  }
  function_manager.Construct();
  loop_manager.Construct();
  manager_globals_alive = true;
}

// Destroyed in the reverse order, where __dp_finalize used to delete them.
void DestroyManagerGlobals() {
  if (!manager_globals_alive) {
    return;
  }
  loop_manager.Destroy();
  function_manager.Destroy();
  manager_globals_alive = false;
}

bool ManagerGlobalsConstructed() noexcept { return manager_globals_alive; }

// Constructs the globals above. Called from __dp_init, before anything reads them, and
// idempotent so that a second entry point can call it too.
void ConstructImmortalGlobals() {
  if (immortal_globals_constructed) {
    return;
  }
  cuec_storage.Construct();
  // the limits are scaled by NUM_WORKERS in initParallelization
  first_access_queue_storage.Construct(kDefaultFirstAccessQueueChunksPerWorker);
  second_access_queue_storage.Construct(kDefaultSecondAccessQueueElementsPerWorker);
  garbage_queue_storage.Construct(kCleanupQueueElementsPerCleanupWorker);
  first_access_queue_chunk_buffer_storage.Construct(10);
  immortal_globals_constructed = true;
}

// Destroys them again, at the end of __dp_finalize. Every callback returns early once the
// runtime state is Terminated, so nothing reaches these objects afterwards.
void DestroyImmortalGlobals() {
  ReleaseRegisteredBbDeps();
  if (!immortal_globals_constructed) {
    return;
  }
  first_access_queue_chunk_buffer_storage.Destroy();
  garbage_queue_storage.Destroy();
  second_access_queue_storage.Destroy();
  first_access_queue_storage.Destroy();
  cuec_storage.Destroy();
  immortal_globals_constructed = false;
}

/******* END: parallelization section *******/

}  // namespace dp
