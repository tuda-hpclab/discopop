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

#include "../output_paths.hpp"
#include "../runtimeFunctions.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include "../../share/include/debug_print.hpp"
#include "../../share/include/timer.hpp"

#include "dp_func_exit.hpp"
#include "dp_loop_output.hpp"
#include "dp_taken_branch_counter_output.hpp"

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
  const auto debug_print = make_debug_print("__dp_finalize");
#endif

  {
#ifdef DP_INTERNAL_TIMER
    // This one prints the whole timer report when it is destroyed, so it has to be gone before
    // the Timers instance it points to is released below. Hence the scope around the body.
    const auto timer = Timer(timers, TimerRegion::FINALIZE, true);
#endif

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

    // The iteration counters and the taken branch counters used to be dumped from a call the pass
    // put in front of main's return. That missed every iteration and branch of the global
    // destructors, and was lost entirely when the target left through exit(). Both dumps belong
    // here, where the runtime knows the target is done -- and where the managers they read are
    // still alive.
    __dp_loop_output();
    __dp_taken_branch_counter_output();

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

      auto allocationsFileStream = ofstream(profiler_output_path("memory_regions.txt"), ios::out);
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
    allDeps = nullptr;
    delete outPutDeps;
    outPutDeps = nullptr;
    delete bbList;
    bbList = nullptr;
    // End HA

    delete function_manager;
    function_manager = nullptr;
    delete loop_manager;
    loop_manager = nullptr;
    delete call_state_graph;
    call_state_graph = nullptr;
    // The last reader of the memory manager is output_allocations() just above; the accesses
    // that ask it for a region id are all behind us, and the worker threads that could still
    // have been processing them were joined by finalizeParallelization().
    delete memory_manager;
    memory_manager = nullptr;

#ifdef DP_CALLTREE_PROFILING
    // delete call_tree;
    //  delete metadata_queue;
    //   output metadata to file
    std::cout << "Outputting dependency metadata... " << std::endl;
    std::ifstream ifile;
    std::string line;
    std::ofstream ofile;
    ofile.open(profiler_output_path("dependency_metadata.txt"));
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
    out = nullptr;

    // output elapsed time for profiling
    std::chrono::milliseconds time_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::high_resolution_clock::now() - statistics_profiling_start_time);
    auto stats_file = ofstream(profiler_output_path("statistics/profiling_time.txt"), ios::out);
    stats_file << std::to_string(time_elapsed.count()) << " ms\n";
    stats_file.close();

    dpInited = false;
    targetTerminated = true; // mark the target program has returned from main()

    // last use of the manually managed globals is behind us, and every callback returns early
    // from here on, so they can go
    destroy_immortal_globals();

#ifdef DP_DEBUG
    std::cout << "Program terminated." << std::endl;
#endif
  }

  // Outside the scope above, so the FINALIZE timer has printed its report by now.
  delete timers;
  timers = nullptr;
}
}

} // namespace __dp
