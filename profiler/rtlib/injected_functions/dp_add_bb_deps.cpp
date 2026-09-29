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

#include <boost/algorithm/string.hpp>
#include <cstdint>
#include <iostream>
#include <regex>
#include <string>
#include <unordered_set>
#include <vector>

namespace __dp {

// The dependencies of the instructions whose profiling was omitted, as handed
// over by the instrumented modules. Every module registers the string covering
// its own functions; a module which does not define main has no __dp_finalize
// call to attach the handover to, so registration happens from a module
// constructor and thus long before the reported basic blocks are known. The
// strings are therefore only parsed once the program terminates, see
// process_registered_bb_deps.
//
// Wrapped in a function so the vector is constructed on first use: the
// registering constructors run in an order this translation unit cannot
// influence.
static std::vector<const char *> &registered_bb_dep_strings() {
  static std::vector<const char *> strings;
  return strings;
}

// merges the dependencies of every registered string whose basic block was
// actually executed into the collected dependencies. Must run after the target
// has terminated (bbList complete) and before the dependencies are written out.
void process_registered_bb_deps() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = make_debug_print("process_registered_bb_deps");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::ADD_BB_DEPS);
#endif

  if (bbList == nullptr || outPutDeps == nullptr) {
    return;
  }

  std::regex r1("[^=]+"), r2("[^,]+"), r4("(INIT|(R|W)A(R|W)).*");
  std::regex r3("[0-9]+"); // use instructionID based regex, instead of old r3("[0-9]+:[0-9]+") for lineID
  std::smatch res1, res2, res3;

  for (const char *depStringPtr : registered_bb_dep_strings()) {
    if (depStringPtr == nullptr) {
      continue;
    }
    std::string depString(depStringPtr);

    std::vector<std::string> strs;
    boost::split(strs, depString, boost::is_any_of("/"));

    for (const std::string &substring : strs) {
      if (!regex_search(substring, res1, r1)) {
        // skip invalid entry
        continue;
      }
      std::string cond(res1[0]);

      if (cond.length() == 0) {
        // skip invalid entry
        continue;
      }
      if (bbList->find(stoi(cond)) == bbList->end()) {
        continue;
      }
      std::string line(res1.suffix());
      line.erase(0, 1);
      while (regex_search(line, res2, r2)) {
        std::string s(res2[0]);
        regex_search(s, res3, r3);
        std::string k(res3[0]);
        regex_search(s, res3, r4);
        std::string v(res3[0]);
        if (outPutDeps->count(k) == 0) {
          std::unordered_set<std::string> depSet;
          (*outPutDeps)[k] = depSet;
        }
        (*outPutDeps)[k].insert(v);
        line = res2.suffix();
      }
    }
  }
}

/******* Instrumentation function *******/
extern "C" {
// hybrid analysis
//
// Called once per instrumented module, from a module constructor. Only records
// the string: at that point the profiling infrastructure is not initialized yet
// and no basic block has been reported, so nothing could be decided here. The
// string is a constant in the module's own image and thus outlives the program.
// Deliberately takes no lock: this runs during static initialization, where
// locking a global mutex would depend on that mutex already being constructed,
// and where the program is still single-threaded anyway.
void __dp_add_bb_deps(char *depStringPtr) {
  if (depStringPtr == nullptr) {
    return;
  }
  registered_bb_dep_strings().push_back(depStringPtr);
}
// End HA
}

} // namespace __dp
