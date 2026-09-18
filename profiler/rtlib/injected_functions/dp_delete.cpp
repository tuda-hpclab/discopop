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

void __dp_delete(LID lid, ADDR startAddr) {
  DP_CALLBACK_SCOPE(DELETE);

  // DO NOT DELETE MEMORY REGIONS AS THEY ARE STILL REQUIRED FOR LOGGING

  // TODO more efficient implementation

  // find memory region to be deleted
  /*        for(tuple<LID, string, int64_t, int64_t, int64_t, int64_t> entry :
     allocatedMemoryRegions){ if(get<2>(entry) == startAddr){
                  // delete memory region
                  cout << "delete/free: " << decodeLID(lid) << ", " <<
     get<1>(entry) << ", " << std::hex << startAddr << "\n";
                  allocatedMemoryRegions.remove(entry);
                  return;
              }
          }
          cout << "__dp_delete: Could not find base addr: " << std::hex <<
     startAddr << "\n";
  */
}
}

} // namespace __dp
