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

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

#ifdef SKIP_DUP_INSTR
void __dp_write(LID lid, ADDR addr, char *var, ADDR lastaddr, int64_t count) {
#else
void __dp_write(LID lid, ADDR addr, const char *var) {
#endif

  if (!dpInited || targetTerminated) {
    return;
  }

#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::lock_guard<std::mutex> guard(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("__dp_write");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::WRITE);
#endif

  if (targetTerminated) {
    if (DP_DEBUG) {
      cout << "__dp_write() is not executed since target program has returned "
              "from main()."
           << endl;
    }
    return;
  }
  // For tracking function call or invoke
#ifdef SKIP_DUP_INSTR
  if (lastaddr == addr && count >= 2) {
    return;
  }
#endif

  // For tracking function call or invoke
  function_manager->reset_call(lid);

  if (DP_DEBUG) {
    cout << "instStore at encoded LID " << std::dec << dputil::decodeLID(lid) << " and addr " << std::hex << addr
         << endl;
  }

  // TEST
  // check for stack access
#if DP_STACK_ACCESS_DETECTION
  bool is_stack_access = memory_manager->is_stack_access(addr);
#endif
  // !TEST

#if defined DP_NUM_WORKERS && DP_NUM_WORKERS == 0
  AccessInfo current;
#else
  // check if buffer is full. Push it to firstAccessQueue if so, and create a new buffer
  if (mainThread_AccessInfoBuffer->is_full()) {
    // spin-lock to prevent endless queue growth
    while (!firstAccessQueue.can_accept_entries()) {
      usleep(1000);
    }
    firstAccessQueue.push(mainThread_AccessInfoBuffer);
    mainThread_AccessInfoBuffer = firstAccessQueueChunkBuffer.get_prepared_chunk(FIRST_ACCESS_QUEUE_SIZES);
  }
  AccessInfo &current = mainThread_AccessInfoBuffer->get_next_AccessInfo_buffer();

#endif
  current.isRead = false;
  // add current call path state identifier to lid for later retrieval
  current.lid = lid | (((uint64_t)current_callpath_state->get_id()) << 32);
  current.var = var;
#if DP_MEMORY_REGION_DEALIASING
  current.AAvar = getMemoryRegionIdFromAddr(var, addr);
#else
  current.AAvar = (std::int64_t)var;
#endif
  current.addr = addr;

#if DP_CALLTREE_PROFILING
  current.call_tree_node_ptr = std::move(call_tree.get_current_node_ptr());
  current.calculate_dependency_metadata = loop_manager->enable_calculate_dependency_metadata();
#endif

#if defined DP_NUM_WORKERS && DP_NUM_WORKERS == 0
  analyzeSingleAccess(singleThreadedExecutionSMem, current);
#endif
}
}

} // namespace __dp
