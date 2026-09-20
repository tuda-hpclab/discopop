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

#include "runtimeFunctionsGlobals.hpp"

#include "../share/include/debug_print.hpp"
#include "../share/include/timer.hpp"

#include <cstddef>
#include <mutex>
#include <optional>

namespace __dp {

// Whether the callbacks the LLVM pass injects carry out their own work at all.
//
// A benchmark build -- and nothing else -- defines DP_BENCHMARK_EMPTY_CALLBACKS. Every callback
// then returns as soon as it has been entered, which separates the two costs of instrumentation
// that are otherwise only ever observed together: what the added calls cost by themselves, and
// what the runtime does inside them. See benchmark/injected_functions.
//
// Deliberately a constant rather than a flag: the body has to be gone from the generated code,
// not skipped over at runtime, or the measurement would include the branch that skips it.
constexpr bool callback_bodies_enabled() noexcept {
#ifdef DP_BENCHMARK_EMPTY_CALLBACKS
  return false;
#else
  return true;
#endif
}

// A region of the runtime that is announced in the verbose build and measured in the timing
// build, and that is neither a callback nor takes a lock. Used for the individual output steps
// of __dp_finalize, which run with the lock already held.
//
// Which of the two members exists depends on DP_RTLIB_VERBOSE and DP_INTERNAL_TIMER. With
// neither, the class is empty and the object is gone after inlining.
template <std::size_t N> class TimedSection {
public:
  explicit TimedSection([[maybe_unused]] TimerRegion region, [[maybe_unused]] const char (&name)[N]) {
#ifdef DP_RTLIB_VERBOSE
    trace.emplace(name);
#endif
#ifdef DP_INTERNAL_TIMER
    timer.emplace(timers, region);
#endif
  }

  TimedSection(const TimedSection &) = delete;
  TimedSection &operator=(const TimedSection &) = delete;

private:
  // Declared trace before timer and therefore destroyed the other way round, so the measurement
  // ends before the region reports that it has been left.
#ifdef DP_RTLIB_VERBOSE
  std::optional<DebugPrint<N>> trace;
#endif
#ifdef DP_INTERNAL_TIMER
  std::optional<Timer> timer;
#endif
};

// Everything an instrumented callback does before its own work: decide whether the runtime is
// running at all, take the pthread compatibility lock, trace the call and time it.
//
// Spelling that out per callback meant twelve lines in front of every one of them, nine of which
// were #ifdef noise; it also meant the three configurations were only ever exercised where
// someone had remembered to repeat the pattern correctly, which is how __dp_finalize came to
// announce itself as __dp_loop_exit and __dp_func_exit came to start its timer twice.
//
// In the default configuration -- none of the three options defined -- what is left is a bool and
// a comparison, which is what the hand written guard compiled to as well.
template <std::size_t N> class CallbackScope {
public:
  CallbackScope([[maybe_unused]] TimerRegion region, [[maybe_unused]] const char (&name)[N])
      : active(callback_bodies_enabled() && profiling_active()) {
    if (!active) {
      // Deliberately before everything else: a callback that is about to return without doing
      // anything must not take the lock, announce itself or produce a timing sample.
      return;
    }
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    lock = std::unique_lock<std::mutex>(pthread_compatibility_mutex);
#endif
#ifdef DP_RTLIB_VERBOSE
    trace.emplace(name);
#endif
#ifdef DP_INTERNAL_TIMER
    timer.emplace(timers, region);
#endif
  }

  CallbackScope(const CallbackScope &) = delete;
  CallbackScope &operator=(const CallbackScope &) = delete;

  // Whether the callback may go on. Callbacks return early when this is false.
  explicit operator bool() const noexcept { return active; }

  // For the callbacks that call back into instrumented code in the middle of their work and
  // therefore have to let go of the lock first. Without DP_PTHREAD_COMPATIBILITY_MODE both are
  // empty. Whatever is still held is released when the scope is destroyed, which the hand
  // written lock()/unlock() pairs did not manage.
  void unlock() {
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    if (lock.owns_lock()) {
      lock.unlock();
    }
#endif
  }

  void relock() {
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
    if (!lock.owns_lock()) {
      lock.lock();
    }
#endif
  }

private:
  // Declared lock, trace, timer and therefore destroyed in the opposite order, so the timer still
  // stops before the lock is released, exactly as the hand written sequence did.
  bool active;
#ifdef DP_PTHREAD_COMPATIBILITY_MODE
  std::unique_lock<std::mutex> lock;
#endif
#ifdef DP_RTLIB_VERBOSE
  std::optional<DebugPrint<N>> trace;
#endif
#ifdef DP_INTERNAL_TIMER
  std::optional<Timer> timer;
#endif
};

} // namespace __dp

// The preamble of an instrumented callback. `region` is the TimerRegion enumerator without its
// scope; the name the verbose build reports comes from __func__, so it cannot drift away from the
// function it belongs to. Declares `dp_scope`, which callbacks that release the lock in the
// middle of their work address by that name.
#define DP_CALLBACK_SCOPE(region)                                                                                      \
  auto dp_scope = ::__dp::CallbackScope(TimerRegion::region, __func__);                                                \
  if (!dp_scope) {                                                                                                     \
    return;                                                                                                            \
  }                                                                                                                    \
  static_cast<void>(dp_scope)

// The preamble of an instrumented callback that neither takes the lock nor is traced or timed,
// and therefore has no CallbackScope to ask. It answers the same two questions: is the runtime
// running, and does this build execute callback bodies at all.
#define DP_CALLBACK_GUARD()                                                                                            \
  if (!::__dp::callback_bodies_enabled() || !::__dp::profiling_active()) {                                             \
    return;                                                                                                            \
  }                                                                                                                    \
  static_cast<void>(0)

// A traced and timed section that is not a callback: no state check, no lock. See TimedSection.
#define DP_TIMED_SECTION(region, name)                                                                                 \
  [[maybe_unused]] const auto dp_section = ::__dp::TimedSection(TimerRegion::region, name)
