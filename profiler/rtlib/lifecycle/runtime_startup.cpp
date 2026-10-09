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

#include "runtime_startup.hpp"

#include "../DPTypes.hpp"

#include "../output_paths.hpp"
#include "../runtimeFunctions.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include "../injected_functions/dp_finalize.hpp"

#include "../../share/include/debug_print.hpp"
#include "../../share/include/timer.hpp"

#include "../static_callstate_transitions/utils.hpp"

#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

using namespace std;

namespace __dp {

/******* Runtime startup *******/
extern "C" {

void __dp_init() {
  // Anything but NotInitialized: either the runtime is already up, or it has already written its
  // results and released everything. The latter used to pass this check, because the flag it read
  // was cleared again in __dp_finalize.
  if (runtime_state != RuntimeState::NotInitialized) {
    return;
  }

  // This part should be executed only once.
  // The globals the runtime manages itself have to exist before anything reads them.
  construct_immortal_globals();
  readRuntimeInfo();
  timers = new Timers();
  statistics_profiling_start_time = std::chrono::high_resolution_clock::now();
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::INIT);
#endif
  construct_manager_globals();
  //
#if DP_CALLTREE_PROFILING
//    call_tree = new CallTree();
// metadata_queue = new MetaDataQueue(6); // TODO: add Worker argument
//    dependency_metadata_results_mtx = new std::mutex();
//    dependency_metadata_results = new std::unordered_set<DependencyMetadata>();
#endif

  mainThread_AccessInfoBuffer = firstAccessQueueChunkBuffer.get_prepared_chunk(FIRST_ACCESS_QUEUE_CHUNK_SIZE);

  out = new ofstream();

  // hybrid analysis
  allDeps = new depMap();
  outPutDeps = new stringDepMap();
  bbList = new ReportedBBRecorder();
  // End HA

  memory_manager->allocate_dummy_region();

  // This is the first thing to run in an instrumented program, so it is also where the output
  // directory is pinned down. Everything in the runtime that writes a result file reaches it
  // through profiler_output_path() afterwards, see output_paths.hpp.
  if (getenv("DOT_DISCOPOP") == nullptr) {
    setenv("DOT_DISCOPOP", ".discopop", 1);
  }
  const std::string profiler_directory = std::string(getenv("DOT_DISCOPOP")) + "/profiler";
  setenv("DOT_DISCOPOP_PROFILER", profiler_directory.c_str(), 1);

  out->open(profiler_output_path("dynamic_dependencies.txt").c_str(), ios::out);
  assert(out->is_open() && "Cannot open a file to output dependences.\n");

  // Static callPath tracing
  call_state_graph = new CallStateGraph();
  initialize_current_callpath_state();

  if (DP_DEBUG) {
    cout << "DP initialized." << endl;
  }
  runtime_state = RuntimeState::Running;
  if (NUM_WORKERS > 0) {
    initParallelization();
  } else {
    initSingleThreadedExecution();
  }
}
}

namespace {

// The runtime has to be up before the first instrumented callback, and it has to write its results
// after the last one. Both ends are reached through the ELF initialization and finalization arrays
// rather than from main, because the target's global constructors and destructors are instrumented
// as well and run outside of it.
//
// .init_array is processed in ascending priority order and clang gives the target's own static
// initializers the default priority 65535, so 101 puts the runtime ahead of all of them. The
// matching .fini_array entry is processed after every handler registered with __cxa_atexit, which
// is where the destructors of those objects live -- so __dp_finalize sees the accesses they make.
// Priorities below 101 are reserved for the implementation.
//
// Since no instrumented code calls __dp_init any more, nothing references this translation unit,
// and the linker would drop it from the static runtime archive together with the two entries
// below -- without any diagnostic; the profiled program would simply never start the runtime.
// The link wrappers in profiler/scripts therefore request __dp_init with -u, which is why that
// symbol and these two entries have to stay in the same file.
__attribute__((constructor(101))) void dp_runtime_startup() { __dp_init(); }

__attribute__((destructor(101))) void dp_runtime_shutdown() {
  if (!profiling_active()) {
    // Either nothing was profiled, or __dp_finalize already ran because the target left through a
    // function that does not return to main.
    return;
  }
  // LID 0 decodes to "*": the end of the program no longer has a source location to report, now
  // that this is not a call sitting at the return of main.
  __dp_finalize(0);
}

} // namespace

} // namespace __dp
