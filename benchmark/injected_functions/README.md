<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# Injected callback benchmark

Measures what each callback the DiscoPoP LLVM pass injects costs, and splits that cost in two:
the call the pass adds, and what the runtime does inside it.

| binary                        | linked against               | measures         |
| ----------------------------- | ---------------------------- | ---------------- |
| `DiscoPoP_BM_Callbacks_Empty` | `DiscoPoP_RT_EmptyCallbacks` | the call alone   |
| `DiscoPoP_BM_Callbacks`       | `DiscoPoP_RT`                | the call and the body |

Both are built from [`benchmark_injected_functions.cpp`](benchmark_injected_functions.cpp) and run
the same benchmarks under the same names. `DiscoPoP_RT_EmptyCallbacks` is the runtime library built
with `DP_BENCHMARK_EMPTY_CALLBACKS`, where `callback_body_enabled()` is a compile time `false` and
every callback compiles down to its return (see
[`profiler/rtlib/callback_scope.hpp`](../../profiler/rtlib/callback_scope.hpp)). The body of a
callback therefore costs the difference between the two binaries -- and the loop that drives the
measurement, being the same code on both sides, drops out of that difference.

For the same question asked about whole programs rather than single calls -- how much of a
profiled run's time goes into which callback -- see `--callback-breakdown` in
[`benchmark/pass_overhead`](../pass_overhead). It uses the same switch, with
`DP_BENCHMARK_ONLY_CALLBACK` to turn the bodies back on one at a time.

## Running it

```bash
venv/bin/python3 benchmark/injected_functions/run_callback_benchmark.py
```

The driver configures and builds both binaries, runs them and prints the comparison:

```
callback                           call only   call+body        body   body share
--------------------------------------------------------------------------------
__dp_read                             1.63 ns     16.69 ns     15.06 ns         90%
__dp_write                            2.04 ns     22.35 ns     20.31 ns         91%
...
```

Useful options:

- `--no-build` when the binaries are already built
- `--filter <regex>` to run a single callback while iterating
- `--repetitions <n>` and `--min-time <seconds>` to trade accuracy for wall clock time
- `--json-out` / `--markdown-out` for machine readable results and for the CI job summary

The two binaries can also be run directly, in which case they take the usual Google Benchmark
options. They need `DOT_DISCOPOP` to point at a directory holding a `profiler/` subdirectory: the
runtime opens its result files from `__dp_init`, which runs before `main`, so the benchmark cannot
arrange that for itself and says so on stderr when the directory is missing. Nothing here reads
those results; the driver supplies an empty directory of its own.

## What is measured, and what is not

**One benchmark per callback, with two exceptions.** `__dp_func_entry` / `__dp_func_exit` and
`__dp_loop_entry` / `__dp_loop_exit` are measured as pairs, because the two halves of each bracket
undo each other: measuring an entry on its own would push the runtime's function stack or loop
stack a few hundred million entries deep over the course of a benchmark, and would report the cost
of that growth rather than the cost of the callback. Their rows are marked `(2 calls)`.

**The runtime is up.** The benchmark brings up the real runtime, with its worker threads, its
shadow memory and its queues, and lets the callbacks record what they normally record. For the
memory access callbacks this includes the back pressure from the queue when the workers cannot
keep up, which is part of what an instrumented program pays.

**The inputs rotate through a fixed pool.** Line ids, addresses, variables, loop ids and basic
block indices come from pools of a few dozen to a few thousand entries. One constant value would
measure a hash table of size one; an ever increasing value would measure a hash table growing for
the whole benchmark. Neither is what a program does.

**The call state graph is empty.** No module here was compiled by the pass, so no call state
transitions are registered. The callbacks that consult them -- `__dp_call`, `__dp_func_exit`,
`__dp_loop_entry`, `__dp_loop_exit`, `__dp_loop_incr` -- do the lookup and find nothing, which is
the path a real program takes wherever the pass could not resolve a call, but not the path it takes
where it could. `__dp_call` is additionally driven as a library call, the case in which no
instrumented function exit will follow.

**A body can measure as free, and even as slightly negative.** `__dp_alloca`, `__dp_new` and
`__dp_delete` have no body in the default configuration: two of them are behind
`DP_MEMORY_REGION_DEALIASING` and the third is commented out. What is left is the difference
between two measurements of the same empty call, which is the noise floor -- a few tenths of a
nanosecond, in either direction.

**Not benchmarked at all:** `__dp_init`, `__dp_finalize`, `__dp_loop_output`,
`__dp_taken_branch_counter_output` and `__dp_add_bb_deps`. They run once per program or once per
module rather than once per event, so a per call number would say nothing about them. What they
cost is part of what [`benchmark/pass_overhead`](../pass_overhead) measures.

## Adding a callback

Add a `void benchmark_<name>(benchmark::State &)` to `benchmark_injected_functions.cpp` and
register it with `BENCHMARK(benchmark_<name>)->Name("__dp_<name>")`. The name is what the driver
joins the two runs on, so it has to be the same in both -- which it is, since the file is compiled
twice. Keep the runtime's bookkeeping bounded: either the callback is state neutral over a fixed
input pool, or its counterpart is called in the same iteration.
