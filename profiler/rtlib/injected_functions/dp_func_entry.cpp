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

#include "../DPTypes.hpp"

#include "../runtimeFunctions.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include "../../share/include/debug_print.hpp"
#include "../../share/include/timer.hpp"

#include "../static_callstate_transitions/utils.hpp"

#ifdef __linux__
#include <linux/limits.h>
#endif

#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_func_entry(LID lid, int32_t isStart) {
  if (targetTerminated) {
    // prevent deleting generated results after the main function has been
    // exited. This might happen, e.g., if a destructor of a global struct is
    // called after exiting the main function.
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_func_entry");
#endif

  if (!dpInited) {
    // This part should be executed only once.
    readRuntimeInfo();
    timers = new Timers();
    statistics_profiling_start_time = std::chrono::high_resolution_clock::now();
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::FUNC_ENTRY);
#endif
    function_manager = new FunctionManager();
    loop_manager = new LoopManager();
    memory_manager = new MemoryManager();
    //
#if DP_CALLTREE_PROFILING
//    call_tree = new CallTree();
// metadata_queue = new MetaDataQueue(6); // TODO: add Worker argument
//    dependency_metadata_results_mtx = new std::mutex();
//    dependency_metadata_results = new std::unordered_set<DependencyMetadata>();
#endif

    mainThread_AccessInfoBuffer = firstAccessQueueChunkBuffer.get_prepared_chunk(FIRST_ACCESS_QUEUE_SIZES);

    out = new ofstream();

    // hybrid analysis
    allDeps = new depMap();
    outPutDeps = new stringDepMap();
    bbList = new ReportedBBSet();
    // End HA

    memory_manager->allocate_dummy_region();

#ifdef __linux__
    // try to get an output file name w.r.t. the target application
    // if it is not available, fall back to "Output.txt"
    char *selfPath = new char[PATH_MAX];
    if (selfPath != nullptr) {
      if (readlink("/proc/self/exe", selfPath, PATH_MAX - 1) == -1) {
        delete[] selfPath;
        selfPath = nullptr;
        out->open("Output.txt", ios::out);
      }
      // out->open(string(selfPath) + "_dep.txt", ios::out);  # results in the
      // old <prog>_dep.txt
      //  prepare environment variables
      char const *tmp = getenv("DOT_DISCOPOP");
      if (tmp == NULL) {
        // DOT_DISCOPOP needs to be initialized
        setenv("DOT_DISCOPOP", ".discopop", 1);
      }
      std::string tmp_str(getenv("DOT_DISCOPOP"));
      setenv("DOT_DISCOPOP_PROFILER", (tmp_str + "/profiler").data(), 1);
      std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
      tmp2 += "/dynamic_dependencies.txt";

      out->open(tmp2.data(), ios::out);

      // Static callPath tracing
      call_state_graph = new CallStateGraph();
      initialize_current_callpath_state();
    }
#else
    // Non-Linux: replicate the env-var + output-file + call-state setup from
    // the Linux path above, but without /proc/self/exe (POSIX only).
    {
      char const *tmp = getenv("DOT_DISCOPOP");
      if (tmp == NULL) {
        setenv("DOT_DISCOPOP", ".discopop", 1);
      }
      std::string tmp_str(getenv("DOT_DISCOPOP"));
      setenv("DOT_DISCOPOP_PROFILER", (tmp_str + "/profiler").data(), 1);
      std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
      tmp2 += "/dynamic_dependencies.txt";
      out->open(tmp2.data(), ios::out);

      call_state_graph = new CallStateGraph();
      initialize_current_callpath_state();
    }
#endif
    assert(out->is_open() && "Cannot open a file to output dependences.\n");

    if (DP_DEBUG) {
      cout << "DP initialized at LID " << std::dec << dputil::decodeLID(lid) << endl;
    }
    dpInited = true;
    if (NUM_WORKERS > 0) {
      initParallelization();
    } else {
      initSingleThreadedExecution();
    }
  } else if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "Entering function LID " << std::dec << dputil::decodeLID(lid);
      cout << " but target program has returned from main(). Destructors?" << endl;
    }
  } else {
    function_manager->register_function_start(lid);
  }

#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::FUNC_ENTRY);
#endif

#if DP_STACK_ACCESS_DETECTION
  memory_manager->enter_new_function();
  memory_manager->enterScope("function", lid);
#endif

#ifdef DP_CALLTREE_PROFILING
  call_tree.enter_function(lid);
#endif

  if (isStart)
    *out << "START " << dputil::decodeLID(lid) << endl;

  // Reset last call tracker
  function_manager->log_call(0);
}
}

} // namespace __dp
