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
#include <string>
#include <unordered_map>
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

std::uint32_t current_callpath_state_id_for_bb_reports() {
  return current_callpath_state == nullptr ? 0 : (std::uint32_t)current_callpath_state->get_id();
}

namespace {

// One dependency of a handed over dependency string,
// "<sink> NOM <type> <source>|<variable>(<memory region>)", split for adding
// callpath states to its sink and source.
struct HandedOverDep {
  std::string sink;
  std::string type;
  std::string source; // instruction id, or "*" (INIT)
  std::string rest;   // "|<variable>(<memory region>)"
};

// parses "<sink> NOM <type> <source>|<rest>". Returns false for malformed
// entries, which are skipped.
bool parse_handed_over_dep(const std::string &dep, HandedOverDep &parsed) {
  const std::size_t sink_end = dep.find(' ');
  if (sink_end == std::string::npos || sink_end == 0) {
    return false;
  }
  parsed.sink = dep.substr(0, sink_end);
  if (parsed.sink.find_first_not_of("0123456789") != std::string::npos) {
    return false;
  }
  // skip the "NOM" token
  std::size_t type_begin = dep.find(' ', sink_end + 1);
  if (type_begin == std::string::npos) {
    return false;
  }
  ++type_begin;
  const std::size_t type_end = dep.find(' ', type_begin);
  const std::size_t rest_begin = dep.find('|', type_begin);
  if (type_end == std::string::npos || rest_begin == std::string::npos || rest_begin < type_end) {
    return false;
  }
  parsed.type = dep.substr(type_begin, type_end - type_begin);
  if (parsed.type != "RAW" && parsed.type != "WAR" && parsed.type != "WAW" && parsed.type != "INIT") {
    return false;
  }
  parsed.source = dep.substr(type_end + 1, rest_begin - type_end - 1);
  parsed.rest = dep.substr(rest_begin);
  return !parsed.source.empty();
}

// basic block index -> the dependencies handed over under it
std::unordered_map<std::uint32_t, std::vector<HandedOverDep>>
parse_handed_over_dep_strings(const std::vector<const char *> &dep_strings) {
  std::unordered_map<std::uint32_t, std::vector<HandedOverDep>> deps_by_bb;
  for (const char *dep_string_ptr : dep_strings) {
    if (dep_string_ptr == nullptr) {
      continue;
    }
    const std::string dep_string(dep_string_ptr);
    std::vector<std::string> entries;
    boost::split(entries, dep_string, boost::is_any_of("/"));
    for (const std::string &entry : entries) {
      const std::size_t separator = entry.find('=');
      if (separator == std::string::npos || separator == 0 ||
          entry.find_first_not_of("0123456789") != separator) {
        // skip invalid entry
        continue;
      }
      const std::uint32_t bb_index = (std::uint32_t)std::stoul(entry.substr(0, separator));
      const std::string dep_list = entry.substr(separator + 1);
      std::vector<std::string> deps;
      boost::split(deps, dep_list, boost::is_any_of(","));
      std::vector<HandedOverDep> &target = deps_by_bb[bb_index];
      for (const std::string &dep : deps) {
        HandedOverDep parsed;
        if (parse_handed_over_dep(dep, parsed)) {
          target.push_back(std::move(parsed));
        }
      }
    }
  }
  return deps_by_bb;
}

} // namespace

void merge_bb_deps(const std::vector<const char *> &dep_strings, const ReportedBBSet &reported, stringDepMap &out) {
  if (reported.empty()) {
    return;
  }
  const auto deps_by_bb = parse_handed_over_dep_strings(dep_strings);
  for (const ReportedBB &execution : reported) {
    const auto deps = deps_by_bb.find(execution.bb_index);
    if (deps == deps_by_bb.end()) {
      continue;
    }
    const std::string sink_state = "@" + std::to_string(execution.sink_state);
    const std::string source_state = "@" + std::to_string(execution.source_state);
    for (const HandedOverDep &dep : deps->second) {
      std::string source = dep.source == "*" ? dep.source : dep.source + source_state;
      out[dep.sink + sink_state].insert(dep.type + " " + source + dep.rest);
    }
  }
}

// merges the dependencies of every registered string whose basic block was
// actually executed into the collected dependencies, once per distinct pair of
// callpath states the executions were reported with. Must run after the target
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
  merge_bb_deps(registered_bb_dep_strings(), bbList->get_executions(), *outPutDeps);
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
