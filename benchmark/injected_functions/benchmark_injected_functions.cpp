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

// One benchmark per callback the DiscoPoP LLVM pass injects.
//
// This file is compiled twice and linked against the two builds of the runtime library:
//
//   DiscoPoP_BM_Callbacks         against DiscoPoP_RT              -- call plus body
//   DiscoPoP_BM_Callbacks_Empty   against DiscoPoP_RT_EmptyCallbacks -- call only
//
// The second one is built with DP_BENCHMARK_EMPTY_CALLBACKS, where every callback returns as soon
// as it has been entered (see profiler/rtlib/callback_scope.hpp). Its numbers are therefore what
// an instrumented program pays for the added calls alone; the difference between the two is what
// the runtime does inside them. Both binaries run the same benchmarks under the same names, so the
// driver can subtract them per callback -- which also cancels out the loop bookkeeping around the
// measured call, since that is identical on both sides.
//
// The runtime opens its result files in __dp_init, which runs from an .init_array entry before
// main, so where they land is decided by the environment this process was started with and cannot
// be corrected from inside. run_callback_benchmark.py points DOT_DISCOPOP at a directory of its
// own; started by hand without one, the runtime cannot write the results that nobody reads here
// and says so on stderr. See README.md.
//
// Not benchmarked, because they run once per program or once per module rather than per event:
// __dp_init, __dp_finalize, __dp_loop_output, __dp_taken_branch_counter_output and
// __dp_add_bb_deps. What they cost is a property of the profiled run as a whole and is what
// benchmark/pass_overhead measures.

#include <benchmark/benchmark.h>

#include "../../profiler/rtlib/DPTypes.hpp"
#include "../../profiler/rtlib/callback_scope.hpp"
#include "../../profiler/rtlib/injected_functions/all.hpp"
#include "../../profiler/rtlib/lifecycle/runtime_startup.hpp"
#include "../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace {

// ------------------------------------------------------------------ input ---

// The values the benchmarks rotate through. An instrumented program reaches its callbacks from
// many different lines, with many different addresses, and the runtime keeps a record per distinct
// value -- so feeding one constant would measure a hash table of size one, and feeding an
// ever-increasing value would measure a hash table that grows for the whole benchmark. A fixed
// pool gives the runtime the variety without the growth.
//
// All sizes are powers of two, so the cursor is masked instead of divided and the bookkeeping
// around the measured call stays an increment and an AND. That bookkeeping is the same in both
// builds and therefore drops out of the comparison.
constexpr std::size_t kLineCount = 64;
constexpr std::size_t kAddressCount = 1024;
constexpr std::size_t kVariableCount = 64;
constexpr std::size_t kLoopCount = 16;
constexpr std::size_t kBasicBlockCount = 256;

constexpr std::int32_t kFileId = 1;

// The instruction ids the pass would hand to the call state transitions. No transition is
// registered for them (see the note on the call state in README.md), so they are looked up and
// not found, which is the path a callback takes whenever the pass could not resolve a call.
constexpr std::int32_t kInstructionId = 1;

LID line_ids[kLineCount];
ADDR addresses[kAddressCount];
char variable_names[kVariableCount][16];
char branch_names[kBasicBlockCount][24];

// Addresses the benchmarks report as accessed. A real allocation rather than made up numbers: the
// shadow memory buckets by address, and a block of an instrumented program's own memory is what it
// is designed for.
std::int64_t accessed_memory[kAddressCount];

void fill_input_pools() {
  for (std::size_t i = 0; i < kLineCount; ++i) {
    // what the pass encodes: the file id above the line number, see dputil::decodeLID
    line_ids[i] = (static_cast<LID>(kFileId) << LIDSIZE) | static_cast<LID>(i + 1);
  }
  for (std::size_t i = 0; i < kAddressCount; ++i) {
    addresses[i] = reinterpret_cast<ADDR>(&accessed_memory[i]);
  }
  for (std::size_t i = 0; i < kVariableCount; ++i) {
    std::snprintf(variable_names[i], sizeof(variable_names[i]), "var_%zu", i);
  }
  for (std::size_t i = 0; i < kBasicBlockCount; ++i) {
    std::snprintf(branch_names[i], sizeof(branch_names[i]), "bb_%zu->bb_%zu", i, (i + 1) % kBasicBlockCount);
  }
}

// ------------------------------------------------------------ runtime state ---

// Puts the call state bookkeeping back where __dp_init left it.
//
// __dp_call raises a counter every time it cannot resolve a call, and __dp_func_exit lowers it
// again; while it is raised, the callbacks that would look up a transition return before doing so.
// Without this reset a benchmark would measure whichever of the two paths the benchmark that ran
// before it happened to leave behind, and filtering down to a single benchmark would change the
// result of the ones that remain.
void reset_call_state() {
  __dp::calls_without_executed_transitions.clear();
  __dp::calls_without_executed_transitions.push_back(0);
}

// --------------------------------------------------------------- benchmarks ---

// A cursor over the input pools. Kept in a local so that the compiler can hold it in a register:
// what is measured is the callback, not the walk over the pools.
struct Cursor {
  std::uint64_t position = 0;

  LID line() noexcept { return line_ids[position & (kLineCount - 1)]; }
  ADDR address() noexcept { return addresses[position & (kAddressCount - 1)]; }
  char *variable() noexcept { return variable_names[position & (kVariableCount - 1)]; }
  char *branch() noexcept { return branch_names[position & (kBasicBlockCount - 1)]; }
  std::int32_t loop() noexcept { return static_cast<std::int32_t>(position & (kLoopCount - 1)); }
  std::uint32_t basic_block() noexcept { return static_cast<std::uint32_t>(position & (kBasicBlockCount - 1)); }

  void advance() noexcept { ++position; }
};

void benchmark_read(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
#ifdef SKIP_DUP_INSTR
    __dp::__dp_read(cursor.line(), cursor.address(), cursor.variable(), 0, 0);
#else
    __dp::__dp_read(cursor.line(), cursor.address(), cursor.variable());
#endif
    cursor.advance();
  }
}

void benchmark_write(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
#ifdef SKIP_DUP_INSTR
    __dp::__dp_write(cursor.line(), cursor.address(), cursor.variable(), 0, 0);
#else
    __dp::__dp_write(cursor.line(), cursor.address(), cursor.variable());
#endif
    cursor.advance();
  }
}

void benchmark_decl(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
#ifdef SKIP_DUP_INSTR
    __dp::__dp_decl(cursor.line(), cursor.address(), cursor.variable(), 0, 0);
#else
    __dp::__dp_decl(cursor.line(), cursor.address(), cursor.variable());
#endif
    cursor.advance();
  }
}

void benchmark_alloca(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    const ADDR start = cursor.address();
    __dp::__dp_alloca(cursor.line(), cursor.variable(), start, start + 8, 8, 1);
    cursor.advance();
  }
}

void benchmark_new(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    const ADDR start = cursor.address();
    __dp::__dp_new(cursor.line(), start, start + 8, 8);
    cursor.advance();
  }
}

void benchmark_delete(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    __dp::__dp_delete(cursor.line(), cursor.address());
    cursor.advance();
  }
}

// The call is announced as a library call, which is the case in which the pass has no instrumented
// function exit to pair it with. That skips the call state transition and leaves the function
// manager's record of the last call, which is what the following __dp_read or __dp_write reads.
void benchmark_call(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    __dp::__dp_call(cursor.line(), 1);
    cursor.advance();
  }
}

// Entry and exit in one benchmark, because they are the two halves of one bracket: entry raises
// the function stack level and exit lowers it again, so measuring either on its own would let the
// runtime's idea of the stack run away over millions of iterations. The reported time covers both
// calls.
void benchmark_function_entry_exit(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    const LID line = cursor.line();
    // isStart = 0: the "START" line belongs to main and is written once per program, not per call
    __dp::__dp_func_entry(line, 0);
    __dp::__dp_func_exit(line, 0);
    cursor.advance();
  }
}

// The same bracket for loops: the entry pushes onto the loop stack, the exit pops it. Entering the
// same loop id twice in a row would take the "iterates again" path instead, which is what
// __dp_loop_incr below measures. The reported time covers both calls.
void benchmark_loop_entry_exit(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    const LID line = cursor.line();
    const std::int32_t loop_id = cursor.loop();
    __dp::__dp_loop_entry(line, loop_id, kInstructionId);
    __dp::__dp_loop_exit(line, loop_id, kInstructionId);
    cursor.advance();
  }
}

void benchmark_loop_incr(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    __dp::__dp_loop_incr(cursor.loop(), kInstructionId);
    cursor.advance();
  }
}

void benchmark_report_bb(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    __dp::__dp_report_bb(cursor.basic_block());
    cursor.advance();
  }
}

void benchmark_report_bb_pair(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    // semaphore set: the branch was taken, so the block is recorded
    __dp::__dp_report_bb_pair(1, cursor.basic_block());
    cursor.advance();
  }
}

void benchmark_incr_taken_branch_counter(benchmark::State &state) {
  reset_call_state();
  Cursor cursor;
  for (auto _ : state) {
    // cmp_res == active_on: the branch was taken, so the counter is raised
    __dp::__dp_incr_taken_branch_counter(cursor.branch(), 1, 1);
    cursor.advance();
  }
}

BENCHMARK(benchmark_read)->Name("__dp_read");
BENCHMARK(benchmark_write)->Name("__dp_write");
BENCHMARK(benchmark_decl)->Name("__dp_decl");
BENCHMARK(benchmark_alloca)->Name("__dp_alloca");
BENCHMARK(benchmark_new)->Name("__dp_new");
BENCHMARK(benchmark_delete)->Name("__dp_delete");
BENCHMARK(benchmark_call)->Name("__dp_call");
BENCHMARK(benchmark_function_entry_exit)->Name("__dp_func_entry+__dp_func_exit");
BENCHMARK(benchmark_loop_entry_exit)->Name("__dp_loop_entry+__dp_loop_exit");
BENCHMARK(benchmark_loop_incr)->Name("__dp_loop_incr");
BENCHMARK(benchmark_report_bb)->Name("__dp_report_bb");
BENCHMARK(benchmark_report_bb_pair)->Name("__dp_report_bb_pair");
BENCHMARK(benchmark_incr_taken_branch_counter)->Name("__dp_incr_taken_branch_counter");

// ------------------------------------------------------------------ startup ---

#ifdef DP_BENCHMARK_EMPTY_CALLBACKS
constexpr const char *kCallbackBodies = "disabled";
#else
constexpr const char *kCallbackBodies = "enabled";
#endif

} // namespace

int main(int argc, char **argv) {
  fill_input_pools();

  // Naming __dp_init is what puts the runtime's startup into the link at all. DiscoPoP_RT is a
  // static archive, an object file only enters the link when an undefined symbol pulls it in, and
  // nothing else here references the translation unit that carries both __dp_init and the
  // .init_array entry that calls it. Without this the runtime would never come up and every
  // callback below would return at its first line -- with no diagnostic, and with timings that
  // look like a spectacular speedup. The call itself does nothing: the .init_array entry has
  // already run by now and __dp_init returns immediately when the runtime is up.
  __dp::__dp_init();

  if (!__dp::profiling_active()) {
    std::fprintf(stderr, "ERROR: the DiscoPoP runtime is not running, so the callbacks would measure nothing.\n");
    return 1;
  }

  ::benchmark::Initialize(&argc, argv);
  if (::benchmark::ReportUnrecognizedArguments(argc, argv)) {
    return 1;
  }

  // Read back by the driver to check that it is comparing the two builds and not one of them
  // with itself.
  ::benchmark::AddCustomContext("dp_callback_bodies", kCallbackBodies);

  ::benchmark::RunSpecifiedBenchmarks();
  ::benchmark::Shutdown();

  return 0;
}
