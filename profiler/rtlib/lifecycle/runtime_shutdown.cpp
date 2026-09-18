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

#include "runtime_shutdown.hpp"

#include "../callback_scope.hpp"
#include "../output_paths.hpp"
#include "../hybrid_analysis/bb_deps.hpp"
#include "../runtimeFunctions.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include "../injected_functions/dp_func_exit.hpp"
#include "../injected_functions/dp_loop_output.hpp"
#include "../injected_functions/dp_taken_branch_counter_output.hpp"

#include <cassert>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>

using namespace std;

namespace __dp {

void unwind_function_stack(LID lid) {
  while (function_manager->get_current_stack_level() >= 0) {
    __dp_func_exit(lid, 1);
  }

  assert(function_manager->get_current_stack_level() == -1 && "Program terminates without clearing function stack!");
  assert(loop_manager->empty() && "Program terminates but loop stack is not empty!");
}

void write_results(LID lid) {
  if (DP_DEBUG) {
    std::cout << "Program terminates at LID " << std::dec << dputil::decodeLID(lid) << ", clearing up" << std::endl;
  }

  if (NUM_WORKERS > 0) {
    finalizeParallelization();
  } else {
    finalizeSingleThreadedExecution();
  }

  {
    DP_TIMED_SECTION(OUTPUT_LOOPS, "outputLoops");
    loop_manager->output(*out);
  }

  // The iteration counters and the taken branch counters used to be dumped from a call the pass
  // put in front of main's return. That missed every iteration and branch of the global
  // destructors, and was lost entirely when the target left through exit(). Both dumps belong
  // here, where the runtime knows the target is done -- and where the managers they read are
  // still alive.
  __dp_loop_output();
  __dp_taken_branch_counter_output();

  {
    DP_TIMED_SECTION(OUTPUT_FUNCS, "outputFunc");
    function_manager->output_functions(*out);
  }

  {
    DP_TIMED_SECTION(OUTPUT_ALLOCATIONS, "outputAllocations");
    auto allocationsFileStream = ofstream(profiler_output_path("memory_regions.txt"), ios::out);
#if DP_MEMORY_REGION_DEALIASING
    memory_manager->output_memory_regions(allocationsFileStream);
#endif
  }

  // hybrid analysis
  // the dependencies of the omitted instructions first: their basic blocks are
  // known to be complete only now that the target has terminated
  process_registered_bb_deps();
  generateStringDepMap();
  // End HA
  outputDeps();

#ifdef DP_CALLTREE_PROFILING
  // delete call_tree;
  //  delete metadata_queue;
  //   output metadata to file
  std::cout << "Outputting dependency metadata... " << std::endl;
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

  const auto time_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::high_resolution_clock::now() - statistics_profiling_start_time);
  auto stats_file = ofstream(profiler_output_path("statistics/profiling_time.txt"), ios::out);
  stats_file << std::to_string(time_elapsed.count()) << " ms\n";
  stats_file.close();
}

void release_runtime() {
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
  // The last reader of the memory manager is the allocation output in write_results(); the
  // accesses that ask it for a region id are all behind us, and the worker threads that could
  // still have been processing them were joined by finalizeParallelization().
  delete memory_manager;
  memory_manager = nullptr;

  delete out;
  out = nullptr;

  runtime_state = RuntimeState::Terminated;

  // last use of the manually managed globals is behind us, and every callback returns early
  // from here on, so they can go
  destroy_immortal_globals();

  if (DP_DEBUG) {
    std::cout << "Program terminated." << std::endl;
  }
}

} // namespace __dp
