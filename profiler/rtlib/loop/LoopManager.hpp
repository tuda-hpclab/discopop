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

#include "LoopCounter.hpp"
#include "LoopRecord.hpp"
#include "LoopTable.hpp"

#include "../DPUtils.hpp"

#include <ostream>

namespace __dp {

class LoopManager {
public:
  LoopManager() {}

  ~LoopManager() {
    for (auto loop : loops) {
      delete loop.second;
    }
  }

  void create_new_loop(const std::int32_t function_level, const std::int32_t loop_id, const LID begin_line) {
#if DP_CALLTREE_PROFILING
    // check if dependency metadata calculation should be disabled due to inheritance
    bool inherited_dep_metadata_calculation = true;
    if (!loopStack.empty()) {
      inherited_dep_metadata_calculation = loopStack.top().get_dependency_metadata_calculation_enabled();
    }

#endif
    loopStack.push(LoopTableEntry(function_level, loop_id, 0, begin_line));
#if DP_CALLTREE_PROFILING
    // set the inherited metadata calculation flag
    loopStack.non_const_top().set_dependency_metadata_calculation_enabled(inherited_dep_metadata_calculation);

#endif
    if (loops.find(begin_line) == loops.end()) {
      loops.insert(pair<LID, LoopRecord *>(begin_line, new LoopRecord(0, 0, 0)));
    }
#ifdef DP_DEBUG
    std::cout << "(" << std::dec << FuncStackLevel << ")Loop " << loop_id << " enters." << std::endl;
#endif
  }

  bool is_new_loop(const std::int32_t loop_id) const {
    return loopStack.empty() || (loopStack.top().loopID != loop_id);
  }

#if DP_CALLTREE_PROFILING
  bool enable_calculate_dependency_metadata() { return loopStack.top().get_dependency_metadata_calculation_enabled(); };
#endif

  void iterate_loop(const std::int32_t function_level) {
    loopStack.increment_top_count();
#if DP_CALLTREE_PROFILING
    if (!(DP_CALLTREE_PROFILING_METADATA_CUTOFF == 0)) {
#if DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY
      loopStack.non_const_top().set_dependency_metadata_calculation_enabled(
          (loopStack.top().get_dependency_metadata_calculation_enabled() &&
           (DP_CALLTREE_PROFILING_METADATA_CUTOFF > loopStack.top().get_count())) ||
          ((rand() % 1000) < DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY));
#else
      // DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY is 0
      loopStack.non_const_top().set_dependency_metadata_calculation_enabled(
          loopStack.top().get_dependency_metadata_calculation_enabled() &&
          (DP_CALLTREE_PROFILING_METADATA_CUTOFF > loopStack.top().get_count()));
#endif
    }
#endif
#ifdef DP_DEBUG
    std::cout << "(" << std::dec << loopStack.top().funcLevel << ")";
    std::cout << "Loop " << loopStack.top().loopID << " iterates " << loopStack.top().count << " times." << std::endl;
#endif
  }

  void clean_function_exit(const std::int32_t function_level, const LID end_line) {
    // Clear up all unfinished loops in the function.
    // This usually happens when using return inside loop.
    while (!loopStack.empty() && (loopStack.top().funcLevel == function_level)) {

      // No way to get the real end line of loop. Use the line where
      // function returns instead.
      LoopRecords::iterator loop = loops.find(loopStack.top().begin);
      assert(loop != loops.end() && "A loop ends without its entry being recorded.");

      if (loop->second->end == 0) {
        loop->second->end = end_line;
      } else {
        // TODO: FIXME: loop end line > return line
      }

      loop->second->total += loopStack.top().get_count();
      ++loop->second->nEntered;

      loopStack.debug_output();
      loopStack.pop();
      loopStack.debug_output();
    }
  }

  LID update_lid(LID lid) { return loopStack.update_lid(lid); }

  void exit_loop(const LID lid) {
    LoopRecords::iterator loop = loops.find(loopStack.top().begin);
    assert(loop != loops.end() && "A loop ends without its entry being recorded.");
    if (loop->second->end == 0) {
      loop->second->end = lid;
    } else {
      // New loop exit found and it's smaller than before. That means
      // the current exit point can be the break inside the loop.
      // In this case we ignore the current exit point and keep the
      // regular one.
      if (lid < loop->second->end) {
        //    loop->second->end = lid;
      }
      // New loop exit found and it's bigger than before. This can
      // happen when the previous exit is a break inside the loop.
      // In this case we update the loop exit to the bigger one.
      else if (lid > loop->second->end) {
        loop->second->end = lid;
      }
      // New loop exit found and it's the same as before. Good.
    }

    if (loop->second->maxIterationCount < loopStack.top().get_count()) {
      loop->second->maxIterationCount = loopStack.top().get_count();
    }

    loop->second->total += loopStack.top().get_count();
    ++loop->second->nEntered;

    loopStack.debug_output();
    loopStack.pop();
    loopStack.debug_output();
  }

  bool is_single_exit(const std::int32_t loop_id) { return loopStack.is_single_exit(loop_id); }

  void correct_func_level(const std::int32_t function_level) { loopStack.correct_func_level(function_level); }

  std::int32_t get_current_loop_id() { return loopStack.top().loopID; }

  bool empty() { return loopStack.empty(); }

  void output(std::ostream &stream) {
    for (const auto &loop : loops) {
      stream << dputil::decodeLID(loop.first) << " BGN loop ";
      stream << loop.second->total << ' ';
      stream << loop.second->nEntered << ' ';
      stream << static_cast<std::int32_t>(loop.second->total / loop.second->nEntered) << ' ';
      stream << loop.second->maxIterationCount << std::endl;
      stream << dputil::decodeLID(loop.second->end) << " END loop" << std::endl;
    }
  }

  const LoopTable &get_stack() const { return loopStack; }

  const LoopRecords &get_loops() const { return loops; }

  bool is_done() const noexcept { return alreadyDone; }

  void set_done() noexcept { alreadyDone = true; }

  void incr_loop_counter(int loop_id) { lc.incr_loop_counter(loop_id); }

  const std::vector<unsigned int> &get_loop_counters() const { return lc.get_loop_counters(); }

private:
  LoopTable loopStack; // loop stack tracking
  LoopRecords loops;   // loop merging
  LoopCounter lc;      // loop counter
  // must be initialized: is_done() gates __dp_loop_incr and __dp_loop_output, so reading
  // indeterminate heap memory here silently disables loop counting and, with it, the
  // callstate transitions that distinguish loop iterations in the recorded dependencies.
  bool alreadyDone = false;
};

} // namespace __dp
