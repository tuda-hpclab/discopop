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

#include <set>
#include <unordered_map>

namespace __dp {

// For function merging
// 1) when two BGN func are identical

typedef std::unordered_map<LID, std::set<LID>> BGNFuncList;

// 2) when two END func are identical

typedef std::set<LID> ENDFuncList;

class FunctionManager {
public:
  FunctionManager() {}

  ~FunctionManager() {}

  void log_call(const LID current_lid) { lastCallOrInvoke = current_lid; }

  void reset_call(const LID current_lid) {
    lastCallOrInvoke = 0;
    lastProcessedLine = current_lid;
  }

  void increase_stack_level() { ++FuncStackLevel; }

  void decrease_stack_level() { --FuncStackLevel; }

  void register_function_end(const LID current_lid) { endFuncs.insert(current_lid); }

  std::int32_t get_current_stack_level() { return FuncStackLevel; }

  void register_function_start(const LID current_lid) {
    // Process ordinary function call/invoke.

    if (lastCallOrInvoke == 0)
      lastCallOrInvoke = lastProcessedLine;
    ++FuncStackLevel;

#ifdef DP_DEBUG
    std::cout << "Entering function LID " << std::dec << dputil::decodeLID(lid) << std::endl;
    std::cout << "Function stack level = " << std::dec << FuncStackLevel << std::endl;
#endif

    BGNFuncList::iterator func = beginFuncs.find(lastCallOrInvoke);
    if (func == beginFuncs.end()) {
      std::set<LID> tmp{};
      tmp.insert(current_lid);
      beginFuncs.emplace(lastCallOrInvoke, std::move(tmp));
    } else {
      func->second.insert(current_lid);
    }
  }

  void output_functions(std::ostream &stream) {
    for (const auto &func_begin : beginFuncs) {
      for (auto fb : func_begin.second) {
        stream << dputil::decodeLID(func_begin.first) << " BGN func ";
        stream << dputil::decodeLID(fb) << std::endl;
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
  LID lastProcessedLine = 0;
  std::int32_t FuncStackLevel = 0;
};

} // namespace __dp
