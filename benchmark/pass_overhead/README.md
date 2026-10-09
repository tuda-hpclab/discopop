<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# Pass overhead benchmark

Measures what the DiscoPoP LLVM pass (`profiler/DiscoPoP`) costs, by building every program in
[`programs/`](programs) twice and putting the two builds side by side:

| configuration  | how it is built                                                                                     |
| -------------- | --------------------------------------------------------------------------------------------------- |
| `baseline`     | plain `clang++ -g -O0 -fno-discard-value-names -fPIC`                                                 |
| `instrumented` | the same command plus `-fpass-plugin=LLVMDiscoPoP.so` and the `DiscoPoP_RT` runtime library           |

## Where the overhead comes from

`--callback-breakdown` builds every program a further seventeen times, against the benchmark
variants of the runtime library:

| configuration     | links                     | measures                                        |
| ----------------- | ------------------------- | ----------------------------------------------- |
| `calls only`      | `DiscoPoP_RT_EmptyCallbacks` | the calls the pass adds, with no body behind them |
| `only __dp_read`, ... | `DiscoPoP_RT_Only_READ`, ... | those calls plus exactly one callback's body  |

The variants come from `profiler/rtlib/CMakeLists.txt` and are not built by default:

```bash
cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1
cmake --build build_tests --target DiscoPoP_RT_BenchmarkVariants
venv/bin/python3 benchmark/pass_overhead/run_pass_benchmark.py --callback-breakdown
```

With `--callback-breakdown` every instrumented configuration, including `instrumented` itself, is
linked from `--variants-dir` (`build_tests/profiler/rtlib` by default) rather than from the
installed package, so that all of them come out of one build of the runtime.

**The rows do not add up to the last one.** A body that runs while the others do not finds the
runtime's queues and caches in a state it would never find them in during a real profiling run --
in particular, the access queue only saturates, and the main thread only waits for the worker
threads, once enough callbacks are recording at the same time. Read the breakdown as a ranking of
where the cost sits, not as a decomposition of the total.

For the same callbacks measured in isolation and in nanoseconds rather than as whole program
factors, see [`benchmark/injected_functions`](../injected_functions).

That is the same combination [`CXX_wrapper.sh`](../../profiler/scripts/CXX_wrapper.sh) uses, minus
the AST dump — so the difference between the two columns is the pass and its runtime library, and
nothing else.

Three numbers are reported per program:

- **compile time** — how much longer the static analysis and the instrumentation make a build,
- **run time** — the profiling overhead of the instrumented binary,
- **binary size** — the growth caused by the injected calls and the linked runtime library.

This complements the [Google Benchmark micro-benchmarks](..) one level up, which time individual
runtime library data structures rather than the pass as a whole.

## Running it

The profiler has to be installed into the active environment, **without** `-e` (see
[CLAUDE.md](../../CLAUDE.md)), so that `LLVMDiscoPoP.so` and `libDiscoPoP_RT.a` are discoverable:

```bash
venv/bin/pip install ./profiler
venv/bin/python benchmark/pass_overhead/run_pass_benchmark.py
```

Useful options:

```bash
# fewer repetitions while iterating, and a single program
venv/bin/python benchmark/pass_overhead/run_pass_benchmark.py --repetitions 1 --filter matrix

# machine readable results plus a markdown summary
venv/bin/python benchmark/pass_overhead/run_pass_benchmark.py \
    --json-out results.json --markdown-out summary.md

# build artifacts from a CMake build tree instead of the installed package
venv/bin/python benchmark/pass_overhead/run_pass_benchmark.py \
    --plugin build/libi/LLVMDiscoPoP.so --rtlib-dir build/rtlib
```

`--help` lists the rest.

Every program is compiled and executed once as a warm up before the measured repetitions, and the
reported value is the median over those repetitions. Each build gets its own `.discopop` directory
(via `DOT_DISCOPOP`), which is removed before every compilation so that the id counters the pass
maintains do not accumulate across repetitions.

## Exit code

The benchmark fails (exit code 1) when a program does not build or run in either configuration, or
when the instrumented binary no longer reproduces the output of the baseline binary. The runtime
library writes progress messages to stdout, so the outputs are not compared verbatim — instead every
line the baseline printed has to appear in the instrumented output as well.

Timings never fail the run on their own. Pass `--max-compile-factor` / `--max-run-factor` to turn
the geometric mean of the respective factors into a hard limit.

## Adding a program

Drop a self-contained `.cpp` file into [`programs/`](programs). It is picked up automatically. It
has to

- print a deterministic result (a checksum is enough) so the output comparison is meaningful,
- carry a `// BENCHMARK: <one line>` comment, which is used as its description in the report,
- run for a few tens of milliseconds without instrumentation. The instrumented build is one to two
  orders of magnitude slower, so a baseline of 100 ms already means minutes of CI time.

## Interpreting the numbers

Wall clock times depend on the machine, the load on it and the file system cache, and the CI runners
are shared. Treat the factors as trends across runs on the same machine; a single run is not a
reliable absolute measurement, and small differences between two CI runs are noise.
