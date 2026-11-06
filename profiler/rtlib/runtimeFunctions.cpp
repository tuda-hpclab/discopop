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

#include "runtimeFunctions.hpp"

#include <unistd.h>

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "debug_print.hpp"
#include "lid_utils.hpp"
#include "memory/PerfectShadow.hpp"
#include "memory/ShadowMemory.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "timer.hpp"

namespace dp {

void ReadRuntimeInfo() {
#ifdef DP_RTLIB_VERBOSE
  std::cout << "enter readRuntimeInfo\n";
#endif

  std::ifstream conf(dputil::GetExeDir() + "/dp.conf");
  std::string line;
  if (conf.is_open()) {
    auto func = [](char c) { return (c == ' '); };
    std::vector<std::string>* substrings = nullptr;
    while (std::getline(conf, line)) {
      substrings = dputil::Split(line, '=');
      if (substrings->size() == 2) {
        std::string variable = (*substrings)[0];
        std::string value = (*substrings)[1];
        variable.erase(std::remove_if(variable.begin(), variable.end(), func), variable.end());
        value.erase(std::remove_if(value.begin(), value.end(), func), value.end());

        std::int32_t int_value = std::atoi(value.c_str());
        if (variable.compare("CLEANUP_WORKERS") == 0) {
          // 0 is a valid value: the consumer of the second access queue frees everything itself
          cleanup_workers = std::max(int_value, 0);
        } else if (int_value > 0) {
          if (variable.compare("DP_DEBUG") == 0) {
            dp_debug = true;
          } else if (variable.compare("SIG_ELEM_BIT") == 0) {
            sig_elem_bit = int_value;
          } else if (variable.compare("SIG_NUM_ELEM") == 0) {
            sig_num_elem = int_value;
          } else if (variable.compare("SIG_NUM_HASH") == 0) {
            sig_num_hash = int_value;
          } else if (variable.compare("NUM_WORKERS") == 0) {
            num_workers = int_value;
          } else if (variable.compare("FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER") == 0) {
            first_access_queue_chunks_per_worker = int_value;
          } else if (variable.compare("SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER") == 0) {
            second_access_queue_elements_per_worker = int_value;
          } else if (variable.compare("USE_PERFECT") == 0) {
            use_perfect = int_value != 0;
          }
        }
      }
      substrings->clear();
      delete substrings;
    }
  }
  if (dp_debug) {
    std::cout << "sig_elem_bit = " << sig_elem_bit << "\n";
    std::cout << "sig_num_elem = " << sig_num_elem << "\n";
    std::cout << "sig_num_hash = " << sig_num_hash << "\n";
    std::cout << "num_workers  = " << num_workers << "\n";
    std::cout << "faq_chunks_per_worker   = " << first_access_queue_chunks_per_worker << "\n";
    std::cout << "saq_elements_per_worker = " << second_access_queue_elements_per_worker << "\n";
    std::cout << "cleanup_workers         = " << cleanup_workers << "\n";
    sleep(2);
  }

#ifdef DP_RTLIB_VERBOSE
  std::cout << "exit readRuntimeInfo\n";
#endif
}

void InitParallelization() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("initParallelization");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kInitParallelization);
#endif

  // initialize global variables
  workers = new pthread_t[num_workers];

  // Initialize count of accesses
  num_accesses = new std::uint64_t[num_workers]();

  // bound the memory held by the access queues
  first_access_queue.SetMaxSize(static_cast<std::size_t>(first_access_queue_chunks_per_worker) * num_workers);
  second_access_queue.SetMaxSize(static_cast<std::size_t>(second_access_queue_elements_per_worker) * num_workers);

  // initialize and set thread detached attribute
  finalize_parallelization_called = false;  // mostly for unit-tests.
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_JOINABLE);

  // create worker threads to process the firstAccessQueue
  for (std::int64_t i = 0; i < num_workers; ++i) {
    pthread_create(&workers[i], &attr, ProcessFirstAccessQueue, reinterpret_cast<void*>(i));
  }

  // create worker thread to process the secondAccessQueue
  second_access_queue_worker_thread = new pthread_t();
  pthread_create(second_access_queue_worker_thread, &attr, ProcessSecondAccessQueue,
                 reinterpret_cast<void*>(static_cast<std::intptr_t>(num_workers)));

  // create the threads that free what the consumer is done with
  garbage_queue.Reopen();
  garbage_queue.SetMaxPending(static_cast<std::size_t>(kCleanupQueueElementsPerCleanupWorker) *
                              static_cast<std::size_t>(cleanup_workers));
  cleanup_worker_threads = new pthread_t[cleanup_workers > 0 ? cleanup_workers : 1];
  for (std::int32_t i = 0; i < cleanup_workers; ++i) {
    pthread_create(&cleanup_worker_threads[i], &attr, ProcessGarbageQueue, reinterpret_cast<void*>(i));
  }

  pthread_attr_destroy(&attr);
}

void InitSingleThreadedExecution() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("initSingleThreadedExecution");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kAnalyzeDeps);
#endif

  if (use_perfect) {
    single_threaded_execution_smem = new PerfectShadow2();
  } else {
    single_threaded_execution_smem = new ShadowMemory(sig_elem_bit, sig_num_elem, sig_num_hash);
  }

  my_map = new DepMap();
}

void MergeDeps() {
  all_deps_lock.lock();
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kMergeDeps);
#endif

  for (auto& dep : *my_map) {
    // if a lid occurs the first time, operator[] adds its set to the global hash table;
    // otherwise the set that is already there is extended.
    DepSet& global_deps = (*all_deps)[dep.first];
    for (auto& d : dep.second) {
      global_deps.insert(d);
    }
  }
  all_deps_lock.unlock();
  my_map->clear();
}

void FinalizeParallelization() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("finalizeParallelization");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kFinalizeParallelization);
#endif

  if (dp_debug) {
    std::cout << "BEGIN: finalize parallelization... \n";
  }

  // push last state of the mainThread_AccessInfoBuffer to the global FirstAccessQueue
  first_access_queue.Push(main_thread_access_info_buffer);
  main_thread_access_info_buffer = first_access_queue_chunk_buffer.GetPreparedChunk(kFirstAccessQueueChunkSize);

  // fake signaling: just notify the workers that no more addresses will be
  // collected
  finalize_parallelization_called = true;

  // wait for worker threads
  for (int i = 0; i < num_workers; ++i) {
    pthread_join(workers[i], nullptr);
  }
  pthread_join(*second_access_queue_worker_thread, nullptr);
  // the consumer is the only producer of garbage: once it is gone, the cleanup workers finish what is pending
  garbage_queue.Close();
  for (std::int32_t i = 0; i < cleanup_workers; ++i) {
    pthread_join(cleanup_worker_threads[i], nullptr);
  }

  // delete allocated memory
  delete[] cleanup_worker_threads;
  cleanup_worker_threads = nullptr;
  delete[] workers;
  delete second_access_queue_worker_thread;
  delete[] num_accesses;
  num_accesses = nullptr;

  if (dp_debug) {
    std::cout << "END: finalize parallelization... \n";
  }
}

void FinalizeSingleThreadedExecution() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("finalizeSingleThreadedExecution");
#endif

  if (dp_debug) {
    std::cout << "BEGIN: finalize Single Threaded Execution... \n";
  }

  delete single_threaded_execution_smem;
  single_threaded_execution_smem = nullptr;
  MergeDeps();
  delete my_map;
  my_map = nullptr;

  if (dp_debug) {
    std::cout << "END: finalize Single Threaded Execution... \n";
  }
}

}  // namespace dp
