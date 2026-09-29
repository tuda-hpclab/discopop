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

#include <cassert>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <ostream>
#include <string>
#include <vector>

/**
 * This type allows type-safe specification of a specific timer
 */
enum class TimerRegion : unsigned int {
  // These are directly inserted calls
  ADD_BB_DEPS = 0,
  ALLOCA,
  CALL,
  DECL,
  DELETE,
  FINALIZE,
  FUNC_ENTRY,
  FUNC_EXIT,
  LOOP_ENTRY,
  LOOP_EXIT,
  NEW,
  READ,
  REPORT_BB,
  REPORT_BB_PAIR,
  WRITE,

  // These are indirectly inserted calls
  ADD_DEP,
  GENERATE_STRING_DEP_MAP,
  OUTPUT_DEPS,
  OUTPUT_LOOPS,
  OUTPUT_FUNCS,
  OUTPUT_ALLOCATIONS,
  READ_RUNTIME_INFO,
  INIT_PARALLELIZATION,
  GET_MEMORY_REGION_ID_FROM_ADDR,
  MERGE_DEPS,
  ANALYZE_DEPS,
  ANALYZE_SINGLE_ACCESS,
  FINALIZE_PARALLELIZATION,
  CLEAR_STACK_ACCESSES,

  // These are statistics regarding stack access detection
  STACK_CHECK_READ_ACCESS,
  STACK_CHECK_WRITE_ACCESS,
  STACK_FOUND_READ_ACCESS,
  STACK_FOUND_WRITE_ACCESS,
  STACK_CHECK_ADDR_IS_OWNED_BY_SCOPE,
  STACK_CHECK_ADDR_IS_OWNED_BY_SCOPE_TRUE,

  // Statistics regarding calltree profiling
  ADD_DEP_CALLTREE_REGISTER_METADATAQUEUEELEMENT,
  METADATAQUEUE_PROCESSQUEUE,
  METADATAQUEUE_PROCESSQUEUEELEMENT,
  METADATAQUEUE_PROCESSQUEUE_FETCH,
  PROCESSQUEUEELEMENT,

  SIZE_DONT_USE,
};

/**
 * This number is used as a shortcut to count the number of values valid for
 * TimerRegion
 */
constexpr std::size_t NUMBER_TIMERS = static_cast<std::size_t>(TimerRegion::SIZE_DONT_USE);

/**
 * This class is used to collect all sorts of different timers (see
 * TimerRegion). It provides an interface to start, stop, and print the timers
 */
class Timers {
  using time_point = std::chrono::high_resolution_clock::time_point;
  using index_type = std::vector<time_point>::size_type;

public:
  Timers() {
    time_start = std::vector<Timers::time_point>{NUMBER_TIMERS};
    time_stop = std::vector<Timers::time_point>{NUMBER_TIMERS};

    number_called = std::vector<std::size_t>(NUMBER_TIMERS, std::size_t(0));
    time_elapsed = std::vector<std::chrono::nanoseconds>{NUMBER_TIMERS};
  }

  /**
   * @brief Starts the respective timer
   * @param timer The timer to start
   */
  void start(const TimerRegion timer) {
    const auto timer_id = get_timer_index(timer);
    number_called[timer_id]++;
    time_start[timer_id] = std::chrono::high_resolution_clock::now();
  }

  /**
   * @brief Stops the respective timer
   * @param timer The timer to stops
   */
  void stop(const TimerRegion timer) {
    const auto timer_id = get_timer_index(timer);
    time_stop[timer_id] = std::chrono::high_resolution_clock::now();
  }

  /**
   * @brief Stops the respective timer and adds the elapsed time
   * @param timer The timer to stops
   */
  void stop_and_add(const TimerRegion timer) {
    stop(timer);
    add_start_stop_diff_to_elapsed(timer);
  }

  /**
   * @brief Adds the difference between the current start and stop time points
   * to the elapsed time
   * @param timer The timer for which to add the difference
   */
  void add_start_stop_diff_to_elapsed(const TimerRegion timer) {
    const auto timer_id = get_timer_index(timer);
    time_elapsed[timer_id] += (time_stop[timer_id] - time_start[timer_id]);
  }

  /**
   * @brief Resets the elapsed time for the timer
   * @param timer The timer for which to reset the elapsed time
   */
  void reset_elapsed(const TimerRegion timer) {
    const auto timer_id = get_timer_index(timer);
    time_elapsed[timer_id] = std::chrono::nanoseconds(0);
  }

  /**
   * @brief Returns the elapsed time for the respective timer
   * @param timer The timer for which to return the elapsed time
   * @return The elapsed time
   */
  [[nodiscard]] std::chrono::nanoseconds get_elapsed(const TimerRegion timer) {
    const auto timer_id = get_timer_index(timer);
    return time_elapsed[timer_id];
  }

  /**
   * @brief Prints a formatted output to the stream
   * @param stream The out stream
   */
  void print(std::ostream &stream) {
    stream << "\n========== DiscoPoP TIMERS: Inserted calls ==========\n";
    print(stream, " Function call                                   : ", TimerRegion::CALL);
    print(stream, " Function entry                                  : ", TimerRegion::FUNC_ENTRY);
    print(stream, " Function exit                                   : ", TimerRegion::FUNC_EXIT);
    stream << '\n';
    print(stream, " Loop entry                                      : ", TimerRegion::LOOP_ENTRY);
    print(stream, " Loop exit                                       : ", TimerRegion::LOOP_EXIT);
    stream << '\n';
    print(stream, " Add basic block dependencies                    : ", TimerRegion::ADD_BB_DEPS);
    print(stream, " Report a basic block                            : ", TimerRegion::REPORT_BB);
    print(stream, " Report a pair of basic blocks                   : ", TimerRegion::REPORT_BB_PAIR);
    stream << '\n';
    print(stream, " New memory on the stack                         : ", TimerRegion::ALLOCA);
    print(stream, " New memory on the heap                          : ", TimerRegion::NEW);
    print(stream, " Delete memory                                   : ", TimerRegion::DELETE);
    stream << '\n';
    print(stream, " Read from memory                                : ", TimerRegion::READ);
    print(stream, " Write to memory                                 : ", TimerRegion::WRITE);
    stream << '\n';
    print(stream, " Decl                                            : ", TimerRegion::DECL);
    print(stream, " Finalize                                        : ", TimerRegion::FINALIZE);
    stream << '\n';

    stream << "\n========== DiscoPoP TIMERS: Indirect calls ==========\n";
    print(stream, " Reading the runtime info                        : ", TimerRegion::READ_RUNTIME_INFO);
    print(stream, " Initializing the parallelization                : ", TimerRegion::INIT_PARALLELIZATION);
    print(stream, " Finalizing the parallelization                  : ", TimerRegion::FINALIZE_PARALLELIZATION);
    stream << '\n';
    print(stream, " Generate the dependency map                     : ", TimerRegion::GENERATE_STRING_DEP_MAP);
    print(stream, " Analyze singe accesses                          : ", TimerRegion::ANALYZE_SINGLE_ACCESS);
    print(stream, "  |- Add a dependency                            : ", TimerRegion::ADD_DEP);
    print(stream, " Merge dendencies                                : ", TimerRegion::MERGE_DEPS);
    print(stream, " Analyze the dependencies (incorrect!)           : ",
          TimerRegion::ANALYZE_DEPS); // Incorrect due to multithreading
    stream << '\n';
    print(stream, " Output the dependencies                         : ", TimerRegion::OUTPUT_DEPS);
    print(stream, " Output the loops                                : ", TimerRegion::OUTPUT_LOOPS);
    print(stream, " Output the functions                            : ", TimerRegion::OUTPUT_FUNCS);
    print(stream, " Output the allocations                          : ", TimerRegion::OUTPUT_ALLOCATIONS);
    stream << '\n';
    print(stream, " Get memory region by id from address            : ", TimerRegion::GET_MEMORY_REGION_ID_FROM_ADDR);
    print(stream, " Clear the stack accesses                        : ", TimerRegion::CLEAR_STACK_ACCESSES);
    stream << '\n';

    stream << "\n========== DiscoPoP TIMERS: stack access detection ==\n";
    stream << " NOTE: times to detect stack access in read and write contained "
              "in \n";
    stream << "       reported times to read and write from / to memory. \n";
    print(stream, " Check for read access to stack                  : ", TimerRegion::STACK_CHECK_READ_ACCESS);
    print(stream, " Check for write access to stack                 : ", TimerRegion::STACK_CHECK_WRITE_ACCESS);
    print(stream, " Found read access to stack                      : ", TimerRegion::STACK_FOUND_READ_ACCESS);
    print(stream, " Found write access to stack                     : ", TimerRegion::STACK_FOUND_WRITE_ACCESS);
    print(stream,
          " Check for addr is owned by scope                : ", TimerRegion::STACK_CHECK_ADDR_IS_OWNED_BY_SCOPE);
    print(stream,
          " Found addr is owned by scope                    : ", TimerRegion::STACK_CHECK_ADDR_IS_OWNED_BY_SCOPE_TRUE);
    stream << "\n";

#if DP_CALLTREE_PROFILING
    stream << "\n========== DiscoPoP TIMERS: calltree profiling ======\n";
    print(stream, " Context: Analyze singe accesses                 : ", TimerRegion::ANALYZE_SINGLE_ACCESS);
    print(stream, "  |- Context: Add a dependency                   : ", TimerRegion::ADD_DEP);
    print(stream, "  |- Register MetaDataQueueElements              : ",
          TimerRegion::ADD_DEP_CALLTREE_REGISTER_METADATAQUEUEELEMENT);
    print(stream, " MetaDataQueue: processQueue                     : ", TimerRegion::METADATAQUEUE_PROCESSQUEUE);
    print(stream, "  |- Fetch MetaDataQueueElement                  : ", TimerRegion::METADATAQUEUE_PROCESSQUEUE_FETCH);
    print(stream,
          "  |- processQueueElement                         : ", TimerRegion::METADATAQUEUE_PROCESSQUEUEELEMENT);
    print(stream, " Stand-alone processQueueElement                 : ", TimerRegion::PROCESSQUEUEELEMENT);
    stream << "\n";
#endif
  }

  /**
   * @brief Returns the current time as a string
   * @return The current time as a string
   */
  [[nodiscard]] std::string wall_clock_time() {
    // The time is printed with 24 interesting characters followed by '\n'
    constexpr auto size_of_date_string = 24;

#if defined(__linux__) || defined(__APPLE__)
    time_t raw_time = 0;
    struct tm time_info;

    // Need some more space for '\n' and other checks
    char char_buff[size_of_date_string + 3];

    time(&raw_time);
    localtime_r(&raw_time, &time_info);
    asctime_r(&time_info, char_buff);

    // Avoid '\n'
    return std::string(char_buff, size_of_date_string);
#else
    time_t raw_time = 0;
    struct tm time_info;

    // Need some more space for '\n' and other checks
    char char_buff[size_of_date_string + 3];

    time(&raw_time);
    localtime_s(&time_info, &raw_time);
    asctime_s(char_buff, &time_info);

    // Avoid '\n'
    return std::string(char_buff, size_of_date_string);
#endif
  }

private:
  /**
   * @brief Casts the value of timer to an index for the vectors
   * @param timer The timer as an enum value
   * @result The timer as an index
   */
  [[nodiscard]] index_type get_timer_index(const TimerRegion timer) noexcept {
    const auto timer_id = static_cast<index_type>(timer);
    return timer_id;
  }

  void print(std::ostream &stream, const char *message, const TimerRegion region) {
    const auto index = get_timer_index(region);

    const auto counted = time_elapsed[index].count();
    const auto seconds = static_cast<double>(counted) * 1e-9;

    const auto called = number_called[index];

    stream << message << std::setw(8) << std::fixed << seconds << "\t(" << called << " times called)\n";
  }

  std::vector<time_point> time_start;
  std::vector<time_point> time_stop;

  std::vector<std::size_t> number_called;
  std::vector<std::chrono::nanoseconds> time_elapsed;
};

class Timer {
public:
  Timer(Timers *timers, TimerRegion region, bool also_print = false)
      : timers(timers), region(region), print(also_print) {
    assert(timers != nullptr && "Timer started but timers is nullptr");
    timers->start(region);
  }

  ~Timer() {
    timers->stop_and_add(region);
    if (print) {
      timers->print(std::cout);
    }
  }

private:
  Timers *timers;
  TimerRegion region;
  bool print;
};
