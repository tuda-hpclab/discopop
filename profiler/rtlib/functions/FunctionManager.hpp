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

#include <cstddef>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <set>
#include <unordered_map>
#include <utility>
#include <vector>

#include "DPTypes.hpp"
#include "lid_utils.hpp"

namespace dp {

// For function merging
// 1) when two BGN func are identical

// a call site: its location, and the instruction id of the call (0 if unknown, e.g. a function
// entered without a logged call)
using CallSite = std::pair<LID, std::int32_t>;

struct CallSiteHash {
  std::size_t operator()(const CallSite& site) const noexcept {
    return std::hash<LID>()(site.first) ^ (std::hash<std::int32_t>()(site.second) << 1);
  }
};

using BGNFuncList = std::unordered_map<CallSite, std::set<LID>, CallSiteHash>;

// 2) when two END func are identical

using ENDFuncList = std::set<LID>;

class FunctionManager {
 public:
  FunctionManager() {}

  ~FunctionManager() {}

  // current_lid: the location of the call site; instruction_id: the instruction id of the call,
  // which identifies the call for the callpath states (0 if unknown)
  void LogCall(const LID current_lid, const std::int32_t instruction_id = 0) {
    last_call_or_invoke_ = current_lid;
    last_call_instruction_ = instruction_id;
  }

  void ResetCall(const LID current_lid) {
    last_call_or_invoke_ = 0;
    last_call_instruction_ = 0;
    last_processed_line_ = current_lid;
  }

  void IncreaseStackLevel() { ++func_stack_level_; }

  void DecreaseStackLevel() { --func_stack_level_; }

  void RegisterFunctionEnd(const LID current_lid) {
    // a function returns very often, but from few locations: most returns are recorded already
    LID& seen = seen_function_ends_[SeenSlot(current_lid)];
    if (seen == current_lid) {
      return;
    }
    seen = current_lid;
    end_funcs_.insert(current_lid);
  }

  std::int32_t GetCurrentStackLevel() const { return func_stack_level_; }

  void RegisterFunctionStart(const LID current_lid) {
    // Process ordinary function call/invoke.

    if (last_call_or_invoke_ == 0) {
      last_call_or_invoke_ = last_processed_line_;
      last_call_instruction_ = 0;
    }
    ++func_stack_level_;

#ifdef DP_DEBUG  // runs for every event, so only built with the build option DP_DEBUG
    if (dp_debug) {
      std::cout << "Entering function LID " << std::dec << dputil::DecodeLid(current_lid) << std::endl;
      std::cout << "Function stack level = " << std::dec << func_stack_level_ << std::endl;
    }
#endif

    // a function is entered very often, but from few call sites: most entries are recorded already
    SeenFunctionBegin& seen =
        seen_function_begins_[SeenSlot(current_lid ^ (last_call_or_invoke_ * 31) ^ last_call_instruction_)];
    if (seen.entry == current_lid && seen.call_site == last_call_or_invoke_ &&
        seen.call_instruction == last_call_instruction_) {
      return;
    }
    seen = SeenFunctionBegin{last_call_or_invoke_, current_lid, last_call_instruction_};
    begin_funcs_[CallSite{last_call_or_invoke_, last_call_instruction_}].insert(current_lid);
  }

  void OutputFunctions(std::ostream& stream) const {
    // "<call site> BGN func <entry> [<call instruction id>]": the instruction id is omitted when
    // no call was logged, e.g. for a function called back from code without instrumentation
    for (const auto& func_begin : begin_funcs_) {
      for (auto fb : func_begin.second) {
        stream << dputil::DecodeLid(func_begin.first.first) << " BGN func ";
        stream << dputil::DecodeLid(fb);
        if (func_begin.first.second != 0) {
          stream << " " << func_begin.first.second;
        }
        stream << std::endl;
      }
    }

    for (auto fe : end_funcs_) {
      stream << dputil::DecodeLid(fe) << " END func" << std::endl;
    }
  }

 private:
  // Caches of recently recorded function entries and returns, which spare most of them the lookups in begin_funcs_
  // and end_funcs_: direct mapped, a slot holds the latest entry resp. return whose hash maps to it.
  static constexpr std::size_t kSeenSlots = 4096;
  static constexpr LID kNoLid = std::numeric_limits<LID>::min();  // no location is encoded like this
  struct SeenFunctionBegin {
    LID call_site = kNoLid;
    LID entry = kNoLid;
    std::int32_t call_instruction = 0;
  };

  static std::size_t SeenSlot(const LID key) {
    std::uint64_t h = static_cast<std::uint64_t>(key) * 0x9E3779B97F4A7C15ULL;
    h ^= h >> 32;
    return static_cast<std::size_t>(h) & (kSeenSlots - 1);
  }

  BGNFuncList begin_funcs_;  // function entries
  ENDFuncList end_funcs_;    // function returns
  std::vector<SeenFunctionBegin> seen_function_begins_ = std::vector<SeenFunctionBegin>(kSeenSlots);
  std::vector<LID> seen_function_ends_ = std::vector<LID>(kSeenSlots, kNoLid);

  LID last_call_or_invoke_ = 0;
  std::int32_t last_call_instruction_ = 0;
  LID last_processed_line_ = 0;
  std::int32_t func_stack_level_ = 0;
};

}  // namespace dp
