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

#pragma once

#include "../DPTypes.hpp"
#include "../DPUtils.hpp"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <set>
#include <unordered_map>
#include <utility>

namespace __dp {

// For function merging
// 1) when two BGN func are identical

// a call site: its location, and the instruction id of the call (0 if unknown, e.g. a function
// entered without a logged call)
typedef std::pair<LID, std::int32_t> CallSite;

struct CallSiteHash {
  std::size_t operator()(const CallSite &site) const noexcept {
    return std::hash<LID>()(site.first) ^ (std::hash<std::int32_t>()(site.second) << 1);
  }
};

typedef std::unordered_map<CallSite, std::set<LID>, CallSiteHash> BGNFuncList;

// 2) when two END func are identical

typedef std::set<LID> ENDFuncList;

class FunctionManager {
public:
  FunctionManager() {}

  ~FunctionManager() {}

  // current_lid: the location of the call site; instruction_id: the instruction id of the call,
  // which identifies the call for the callpath states (0 if unknown)
  void log_call(const LID current_lid, const std::int32_t instruction_id = 0) {
    lastCallOrInvoke = current_lid;
    lastCallInstruction = instruction_id;
  }

  void reset_call(const LID current_lid) {
    lastCallOrInvoke = 0;
    lastCallInstruction = 0;
    lastProcessedLine = current_lid;
  }

  void increase_stack_level() { ++FuncStackLevel; }

  void decrease_stack_level() { --FuncStackLevel; }

  void register_function_end(const LID current_lid) { endFuncs.insert(current_lid); }

  std::int32_t get_current_stack_level() const { return FuncStackLevel; }

  void register_function_start(const LID current_lid) {
    // Process ordinary function call/invoke.

    if (lastCallOrInvoke == 0) {
      lastCallOrInvoke = lastProcessedLine;
      lastCallInstruction = 0;
    }
    ++FuncStackLevel;

    if (DP_DEBUG) {
      std::cout << "Entering function LID " << std::dec << dputil::decodeLID(current_lid) << std::endl;
      std::cout << "Function stack level = " << std::dec << FuncStackLevel << std::endl;
    }

    beginFuncs[CallSite{lastCallOrInvoke, lastCallInstruction}].insert(current_lid);
  }

  void output_functions(std::ostream &stream) const {
    // "<call site> BGN func <entry> [<call instruction id>]": the instruction id is omitted when
    // no call was logged, e.g. for a function called back from code without instrumentation
    for (const auto &func_begin : beginFuncs) {
      for (auto fb : func_begin.second) {
        stream << dputil::decodeLID(func_begin.first.first) << " BGN func ";
        stream << dputil::decodeLID(fb);
        if (func_begin.first.second != 0) {
          stream << " " << func_begin.first.second;
        }
        stream << std::endl;
      }
    }

    for (auto fe : endFuncs) {
      stream << dputil::decodeLID(fe) << " END func" << std::endl;
    }
  }

private:
  BGNFuncList beginFuncs; // function entries
  ENDFuncList endFuncs;   // function returns

  LID lastCallOrInvoke = 0;
  std::int32_t lastCallInstruction = 0;
  LID lastProcessedLine = 0;
  std::int32_t FuncStackLevel = 0;
};

} // namespace __dp
