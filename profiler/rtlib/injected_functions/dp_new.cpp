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

#include "../runtimeFunctionsGlobals.hpp"

#include "../callback_scope.hpp"

#include <cstdint>
#include <iostream>
#include <mutex>
#include <set>
#include <string>

using namespace std;

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_new(LID lid, ADDR startAddr, ADDR endAddr, int64_t numBytes) {
  DP_CALLBACK_SCOPE(NEW);

#if DP_MEMORY_REGION_DEALIASING
  // calculate endAddr of memory region
  endAddr = startAddr + numBytes;

  // -1 indicates 'on heap'
  std::string allocID = memory_manager->allocate_memory(lid, startAddr, endAddr, numBytes, -1);

  if (DP_DEBUG) {
    cout << "new/malloc: " << dputil::decodeLID(lid) << ", " << allocID << ", " << std::hex << startAddr << " - "
         << std::hex << endAddr;
    printf(" NumBytes: %lld\n", numBytes);
  }
#endif
}
}

} // namespace __dp
