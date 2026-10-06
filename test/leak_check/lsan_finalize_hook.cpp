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

// Leak check hook for instrumented programs, used by scripts/dev/check_profiler_leaks.sh.
//
// The program is linked with -Wl,--wrap=__dp_finalize, so the call to __dp_finalize that the
// instrumentation inserts before main returns (or the program exits) lands here first. The hook reports
// two LeakSanitizer sections, which test/leak_check/evaluate_leaks.py evaluates separately:
//
// - before_finalize: the target has run completely, but the runtime library has not torn itself down yet.
//   Its worker threads are still alive and everything it keeps by design is reachable from its globals,
//   the workers' thread locals and stacks. A block found unreachable here was lost while the target ran.
// - after_finalize: after the runtime's own teardown (the workers' final merge, finalizeParallelization,
//   the processing of the dependencies and the output). It contains the leaks of before_finalize again,
//   plus whatever the teardown loses.
//
// LSan's own check at exit is disabled (leak_check_at_exit=0), since both sections cover it.
//
// Each section also contains a canary: one block of CANARY_BYTES bytes allocated by
// dp_leak_check_canary() and made unreachable on purpose. The evaluation fails if it does not find it,
// so a change of LSan's report format cannot silently turn the check into a no-op.
//
// For the growth check (reachable memory that grows with the run time, which LSan cannot see), the hook
// prints the sanitizer allocator's live heap, DP_LEAK_CHECK_LIVE_HEAP <section> <bytes>:
// - before_finalize: with DP_LEAK_CHECK_SETTLE=1 (set for the growth runs) only after the worker threads
//   have drained the queued access chunks (the live heap no longer decreases for a second), so the backlog
//   of not yet analyzed chunks, which depends on timing, does not count,
// - after_finalize: right after the teardown,
// and the peak resident set size of the process (DP_LEAK_CHECK_PEAK_RSS_KB, informational).

#include <sanitizer/allocator_interface.h>
#include <sanitizer/lsan_interface.h>

#include <sys/resource.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

extern "C" {

// the wrapped function of the runtime library (see profiler/rtlib/injected_functions/dp_finalize.hpp)
void __real___dp_finalize(std::int64_t lid);

// size of the canary block, recognized by evaluate_leaks.py
static const std::size_t CANARY_BYTES = 7919;
// the canary's address, masked so that it is no pointer LSan could follow
static volatile std::uintptr_t masked_canary = 0;

__attribute__((noinline)) void dp_leak_check_canary() {
  void *canary = std::malloc(CANARY_BYTES);
  std::memset(canary, 0x5a, CANARY_BYTES);
  masked_canary = reinterpret_cast<std::uintptr_t>(canary) ^ 0xa5a5a5a5a5a5a5a5ULL;
}

// overwrite the stack below the caller, so no stale copy of the canary's address keeps it reachable
__attribute__((noinline)) static void clear_stack() {
  volatile char scratch[16384];
  std::memset(const_cast<char *>(scratch), 0, sizeof(scratch));
}

static void report_leaks(const char *section) {
  dp_leak_check_canary();
  clear_stack();
  std::fprintf(stderr, "\nDP_LEAK_CHECK_BEGIN %s\n", section);
  std::fflush(stderr);
  // the report (if any) is printed to stderr by LSan; evaluate_leaks.py parses it
  __lsan_do_recoverable_leak_check();
  std::fflush(stderr);
  std::fprintf(stderr, "DP_LEAK_CHECK_END %s\n", section);
  std::fflush(stderr);
}

// wait until the live heap no longer decreases, i.e. the workers have analyzed the queued chunks
static std::size_t settled_live_heap() {
  using namespace std::chrono;
  const auto deadline = steady_clock::now() + seconds(60);
  std::size_t lowest = __sanitizer_get_current_allocated_bytes();
  auto lowest_since = steady_clock::now();
  while (steady_clock::now() < deadline && steady_clock::now() - lowest_since < milliseconds(1000)) {
    std::this_thread::sleep_for(milliseconds(10));
    const std::size_t now = __sanitizer_get_current_allocated_bytes();
    // a decrease of less than 1 MB does not count as progress of the workers
    if (now + (1 << 20) < lowest) {
      lowest = now;
      lowest_since = steady_clock::now();
    }
  }
  return __sanitizer_get_current_allocated_bytes();
}

static void report_live_heap(const char *section, std::size_t bytes) {
  std::fprintf(stderr, "DP_LEAK_CHECK_LIVE_HEAP %s %zu\n", section, bytes);
  std::fflush(stderr);
}

void __wrap___dp_finalize(std::int64_t lid) {
  // __dp_finalize can be reached more than once (e.g. exit() called after main's own finalize call);
  // the runtime library ignores the later calls, and so does the check
  static bool checked = false;
  if (checked) {
    __real___dp_finalize(lid);
    return;
  }
  checked = true;

  // settling takes a second, so only the growth runs (which compare the live heap) ask for it
  const char *settle = std::getenv("DP_LEAK_CHECK_SETTLE");
  const bool wait_for_workers = settle != nullptr && settle[0] == '1';
  report_live_heap("before_finalize", wait_for_workers ? settled_live_heap() : __sanitizer_get_current_allocated_bytes());
  report_leaks("before_finalize");

  __real___dp_finalize(lid);

  report_live_heap("after_finalize", __sanitizer_get_current_allocated_bytes());
  report_leaks("after_finalize");

  struct rusage usage;
  if (getrusage(RUSAGE_SELF, &usage) == 0) {
    std::fprintf(stderr, "DP_LEAK_CHECK_PEAK_RSS_KB %ld\n", usage.ru_maxrss);
    std::fflush(stderr);
  }
}
}
