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

#include <iostream>
#include <ostream>
#include <vector>

#include "LoopCounter.hpp"
#include "LoopRecord.hpp"
#include "LoopTable.hpp"
#include "lid_utils.hpp"

namespace dp {

class LoopManager {
 public:
  LoopManager() {}

  ~LoopManager() {
    for (auto loop : loops_) {
      delete loop.second;
    }
  }

  void CreateNewLoop(const std::int32_t function_level, const std::int32_t loop_id, const LID begin_line) {
    loop_stack_.Push(LoopTableEntry(function_level, loop_id, 0, begin_line));
    if (loops_.find(begin_line) == loops_.end()) {
      loops_.insert(std::pair<LID, LoopRecord*>(begin_line, new LoopRecord(0, 0, 0)));
    }
    if (dp_debug) {
      std::cout << "(" << std::dec << function_level << ")Loop " << loop_id << " enters." << std::endl;
    }
  }

  bool IsNewLoop(const std::int32_t loop_id) const {
    return loop_stack_.empty() || (loop_stack_.Top().loop_id != loop_id);
  }

  void IterateLoop(const std::int32_t /*function_level*/) {
    loop_stack_.IncrementTopCount();
    if (dp_debug) {
      std::cout << "(" << std::dec << loop_stack_.Top().func_level << ")";
      std::cout << "Loop " << loop_stack_.Top().loop_id << " iterates " << loop_stack_.Top().GetCount() << " times."
                << std::endl;
    }
  }

  void CleanFunctionExit(const std::int32_t function_level, const LID end_line) {
    // Clear up all unfinished loops in the function.
    // This usually happens when using return inside loop.
    while (!loop_stack_.empty() && (loop_stack_.Top().func_level == function_level)) {
      // No way to get the real end line of loop. Use the line where
      // function returns instead.
      const LoopRecords::iterator loop = loops_.find(loop_stack_.Top().begin);
      assert(loop != loops_.end() && "A loop ends without its entry being recorded.");

      if (loop->second->end == 0) {
        loop->second->end = end_line;
      } else {
        // TODO: FIXME: loop end line > return line
      }

      loop->second->total += loop_stack_.Top().GetCount();
      ++loop->second->n_entered;

      loop_stack_.DebugOutput();
      loop_stack_.Pop();
      loop_stack_.DebugOutput();
    }
  }

  LID UpdateLid(LID lid) { return loop_stack_.UpdateLid(lid); }

  void ExitLoop(const LID lid) {
    const LoopRecords::iterator loop = loops_.find(loop_stack_.Top().begin);
    assert(loop != loops_.end() && "A loop ends without its entry being recorded.");
    if (loop->second->end == 0) {
      loop->second->end = lid;
    } else {
      // New loop exit found and it's smaller than before. That means
      // the current exit point can be the break inside the loop.
      // In this case we ignore the current exit point and keep the
      // regular one.
      if (lid < loop->second->end) {
        //    loop->second->end = lid;
      } else if (lid > loop->second->end) {
        // New loop exit found and it's bigger than before. This can
        // happen when the previous exit is a break inside the loop.
        // In this case we update the loop exit to the bigger one.
        loop->second->end = lid;
      }
      // New loop exit found and it's the same as before. Good.
    }

    if (loop->second->max_iteration_count < loop_stack_.Top().GetCount()) {
      loop->second->max_iteration_count = loop_stack_.Top().GetCount();
    }

    loop->second->total += loop_stack_.Top().GetCount();
    ++loop->second->n_entered;

    loop_stack_.DebugOutput();
    loop_stack_.Pop();
    loop_stack_.DebugOutput();
  }

  bool IsSingleExit(const std::int32_t loop_id) { return loop_stack_.IsSingleExit(loop_id); }

  void CorrectFuncLevel(const std::int32_t function_level) { loop_stack_.CorrectFuncLevel(function_level); }

  // -1 when no loop is on the stack. __dp_loop_exit asks for the id in its "ignored single exit"
  // branch, and is_single_exit() takes that branch for an empty stack as well -- reading top()
  // there is a read past the end of the loop stack.
  std::int32_t GetCurrentLoopId() const { return loop_stack_.empty() ? -1 : loop_stack_.Top().loop_id; }

  bool empty() { return loop_stack_.empty(); }

  void Output(std::ostream& stream) {
    for (const auto& loop : loops_) {
      // A loop that was entered and never left contributes no completed iteration: its record is
      // created on entry and every counter is raised on exit, so all of them are still zero --
      // including nEntered, which is what the average is divided by. The assert in
      // unwind_function_stack() that is meant to rule this state out is compiled out of the
      // release build, so the division needs the guard rather than the invariant.
      const std::int32_t entered = loop.second->n_entered;
      const std::int32_t average_iterations = (entered == 0) ? 0 : (loop.second->total / entered);

      stream << dputil::DecodeLid(loop.first) << " BGN loop ";
      stream << loop.second->total << ' ';
      stream << entered << ' ';
      stream << average_iterations << ' ';
      stream << loop.second->max_iteration_count << std::endl;
      stream << dputil::DecodeLid(loop.second->end) << " END loop" << std::endl;
    }
  }

  const LoopTable& GetStack() const { return loop_stack_; }

  const LoopRecords& GetLoops() const { return loops_; }

  bool IsDone() const noexcept { return already_done_; }

  void SetDone() noexcept { already_done_ = true; }

  void IncrLoopCounter(int loop_id) { lc_.IncrLoopCounter(loop_id); }

  const std::vector<unsigned int>& GetLoopCounters() const { return lc_.GetLoopCounters(); }

 private:
  LoopTable loop_stack_;  // loop stack tracking
  LoopRecords loops_;     // loop merging
  LoopCounter lc_;        // loop counter
  // must be initialized: is_done() gates __dp_loop_incr and __dp_loop_output, so reading
  // indeterminate heap memory here silently disables loop counting and, with it, the
  // callstate transitions that distinguish loop iterations in the recorded dependencies.
  bool already_done_ = false;
};

}  // namespace dp
