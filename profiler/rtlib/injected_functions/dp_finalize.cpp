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

#include "dp_func_exit.hpp"

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

void __dp_finalize(LID lid) {
  if (targetTerminated) {
    return;
  }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.lock();
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_loop_exit");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::FINALIZE, true);
#endif

  if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "__dp_finalize() has been called before. Doing nothing this time "
              "to avoid double free."
           << endl;
    }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    pthread_compatibility_mutex.unlock();
#endif
    return;
  }

  // release mutex so it can be re-aquired in the called __dp_func_exit
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  pthread_compatibility_mutex.unlock();
#endif

  while (function_manager->get_current_stack_level() >= 0) {
    __dp_func_exit(lid, 1);
  }

  // use lock_guard here, since no other mutex-aquiring function is called
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif

  // Returning from main or exit from somewhere, clear up everything.
  assert(function_manager->get_current_stack_level() == -1 && "Program terminates without clearing function stack!");
  assert(loop_manager->empty() && "Program terminates but loop stack is not empty!");

#ifdef DP_DEBUG
  std::cout << "Program terminates at LID " << std::dec << dputil::decodeLID(lid) << ", clearing up" << std::endl;
#endif

  if (NUM_WORKERS > 0) {
    finalizeParallelization();
  } else {
    finalizeSingleThreadedExecution();
  }
  std::cout << "Returned from finalizeParallelization" << std::endl;

  const auto output_loops = []() {
#ifdef DP_RTLIB_VERBOSE
    const auto debug_print = make_debug_print("outputLoops");
#endif
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::OUTPUT_LOOPS);
#endif

    loop_manager->output(*out);
  };
  output_loops();

  const auto output_functions = []() {
#ifdef DP_RTLIB_VERBOSE
    const auto debug_print = make_debug_print("outputFunc");
#endif
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::OUTPUT_FUNCS);
#endif
    function_manager->output_functions(*out);
  };
  output_functions();

  const auto output_allocations = []() {
#ifdef DP_RTLIB_VERBOSE
    const auto debug_print = make_debug_print("outputAllocations");
#endif
#ifdef DP_INTERNAL_TIMER
    const auto timer = Timer(timers, TimerRegion::OUTPUT_ALLOCATIONS);
#endif

    const auto prepare_environment = []() {
      // prepare environment variables
      const char *discopop_env = getenv("DOT_DISCOPOP");
      if (discopop_env == NULL) {

        // DOT_DISCOPOP needs to be initialized
        setenv("DOT_DISCOPOP", ".discopop", 1);
        discopop_env = ".discopop";
      }

      auto discopop_profiler_str = std::string(discopop_env) + "/profiler";
      setenv("DOT_DISCOPOP_PROFILER", discopop_profiler_str.data(), 1);

      return discopop_profiler_str + "/memory_regions.txt";
    };
    const auto path = prepare_environment();

    auto allocationsFileStream = ofstream(path, ios::out);
#if DP_MEMORY_REGION_DEALIASING
    memory_manager->output_memory_regions(allocationsFileStream);
#endif
  };
  output_allocations();

  // hybrid analysis
  // the dependencies of the omitted instructions first: their basic blocks are
  // known to be complete only now that the target has terminated
  process_registered_bb_deps();
  generateStringDepMap();
  // End HA
  outputDeps();

  // hybrid analysis
  delete allDeps;
  delete outPutDeps;
  delete bbList;
  // End HA

  delete function_manager;
  function_manager = nullptr;
  delete loop_manager;
  loop_manager = nullptr;
  delete call_state_graph;
  call_state_graph = nullptr;

#ifdef DP_CALLTREE_PROFILING
  // delete call_tree;
  //  delete metadata_queue;
  //   output metadata to file
  std::cout << "Outputting dependency metadata... " << std::endl;
  std::ifstream ifile;
  std::string line;
  std::ofstream ofile;
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  // output information about the loops
  tmp += "/dependency_metadata.txt";
  ofile.open(tmp.data());
  ofile << "# IAC : intra-call-dependency \n";
  ofile << "# IAI : intra-iteration-dependency \n";
  ofile << "# IEC : inter-call-dependency \n";
  ofile << "# IEI : inter-iteration-dependency \n";
  ofile << "# SINK_ANC : entered functions and loops for sink location \n";
  ofile << "# SOURCE_ANC : entered functions and loops for source location \n";
  ofile << "# Format: <DepType> <sink> <source> <var> <AAvar> <IAC> <IAI> <IEC> <IEI> <SINK_ANC> <SOURCE_ANC>\n";
  for (auto dmd : dependency_metadata_results) {
    ofile << dmd.toString() << "\n";
  }
  ofile.close();
//  delete dependency_metadata_results_mtx;
//  delete dependency_metadata_results;
#endif

  *out << dputil::decodeLID(lid) << " END program" << endl;
  out->flush();
  out->close();

  delete out;

  // output elapsed time for profiling
  std::chrono::milliseconds time_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::high_resolution_clock::now() - statistics_profiling_start_time);
#ifdef __linux__
  // try to get an output file name w.r.t. the target application
  // if it is not available, fall back to "Output.txt"
  char *selfPath = new char[PATH_MAX];
  if (selfPath != nullptr) {
    std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
    tmp2 += "/statistics/profiling_time.txt";
    std::ofstream stats_file;
    stats_file.open(tmp2.data(), ios::out);
    stats_file << std::to_string(time_elapsed.count()) << " ms\n";
    stats_file.flush();
    stats_file.close();
  }
#endif

  dpInited = false;
  targetTerminated = true; // mark the target program has returned from main()

#ifdef DP_DEBUG
  std::cout << "Program terminated." << std::endl;
#endif
}
}

} // namespace __dp
