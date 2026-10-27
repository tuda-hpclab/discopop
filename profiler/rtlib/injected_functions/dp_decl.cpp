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

#include "dp_decl.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

#include "DPTypes.hpp"
#include "callback_scope.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"

namespace dp {

/******* Instrumentation function *******/
extern "C" {

#ifdef SKIP_DUP_INSTR
void __dp_decl(LID lid, ADDR addr, const char* var, ADDR lastaddr, std::int64_t count) {
#else
void __dp_decl(LID lid, ADDR addr, const char* var) {
#endif

  DP_CALLBACK_SCOPE(DECL);

#ifdef SKIP_DUP_INSTR
  if (lastaddr == addr && count >= 2) {
    return;
  }
#endif

  function_manager->ResetCall(lid);

  if (dp_debug) {
    std::cout << "instStore at encoded LID " << std::dec << dputil::DecodeLid(lid) << " and addr " << std::hex << addr
              << std::endl;
  }

#if defined DP_NUM_WORKERS && DP_NUM_WORKERS == 0
  AccessInfo current;
#else
  // check if buffer is full. Push it to firstAccessQueue if so, and create a new buffer
  if (main_thread_access_info_buffer->IsFull()) {
    // spin-lock to prevent endless queue growth
    while (!first_access_queue.CanAcceptEntries()) {
      usleep(1000);
    }
    first_access_queue.Push(main_thread_access_info_buffer);
    main_thread_access_info_buffer = first_access_queue_chunk_buffer.GetPreparedChunk(kFirstAccessQueueChunkSize);
  }
  AccessInfo& current = main_thread_access_info_buffer->GetNextAccessInfoBuffer();
#endif
  current.is_read = false;
  // add current call path state identifier to lid for later retrieval
  current.lid = lid | (static_cast<std::uint64_t>(current_callpath_state->GetId()) << 32);
  current.var = var;
  current.aa_var = reinterpret_cast<std::int64_t>(var);
  current.addr = addr;
  current.skip = true;

#if defined DP_NUM_WORKERS && DP_NUM_WORKERS == 0
  AnalyzeSingleAccessOnMainThread(current);
#endif
}
}

}  // namespace dp
