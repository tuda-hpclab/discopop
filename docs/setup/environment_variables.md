---
layout: default
title: Environment variables and runtime settings
parent: Setup
nav_order: 3
---

# Environment variables and runtime settings

The tools of DiscoPoP read a few environment variables. The profiling runtime is configured with a settings file instead.

1. TOC
{:toc}

## Instrumentation and profiling

| Variable | Default | Description |
|---|---|---|
| `DOT_DISCOPOP` | the nearest `.discopop` directory | Directory in which the instrumentation, the runtime and the hotspot detection write their results. The profiling data ends up in the subdirectory `profiler`. If it is not set, the compiler wrappers and the pass use the **nearest `.discopop` directory** of the current directory and its parents (of the directory of the source file, for a build outside of the project), like git finds `.git`: create it once in the root of the project (`discopop_project_manager --init` does) and every compiler call of the build, in any subdirectory (a CMake build compiles in many), writes to it. The pass records the directory in the instrumented program, so the program writes its results there when it is started from any directory; a `DOT_DISCOPOP` set when the program starts wins. If there is no `.discopop` in the current directory or above, the default is `.discopop` in the current directory with a warning: set the variable to the **same absolute path** for every compiler call of the build and for the instrumented program, as a build that compiles in several directories would create a `.discopop` in each of them, whose data does not fit together. A `.discopop` below the project that holds no `project` directory (left by such a build) is still the nearest one; the pass warns if a farther one holds the project configuration. An instrumented program that cannot create its results in `<DOT_DISCOPOP>/profiler` stops at its start with an error message and exit code 1. The project manager sets it for every run of a configuration and checks the result, see [Project manager](../tools/Project_manager.md#checks-of-instrumented-builds-and-runs). |
| `DP_PROJECT_ROOT_DIR` | the directory holding the `.discopop` that was found, else `/` | Root directory of the project to analyze: only functions defined in a file below it (or below one of `DP_PROJECT_INCLUDE_DIRS`, and not below one of `DP_PROJECT_EXCLUDE_DIRS`) are instrumented; with `/`, all functions including library functions are. If `DOT_DISCOPOP` is not set and a `.discopop` directory is found, the directory that holds it is the default. Read by the profiler's LLVM pass and by the hotspot detection. Use an absolute path. The project manager sets it to the project root of every run (or the copy of it the run works in); scripts can use it to refer to the project. |
| `DP_PROJECT_INCLUDE_DIRS` | not set | Directories outside of `DP_PROJECT_ROOT_DIR` whose code is project code as well (e.g. a library of the same repository that lies next to the project), separated by `:`, absolute or relative to `DP_PROJECT_ROOT_DIR`, e.g. `../common:/opt/mylib/include`. A path is project code if it lies below `DP_PROJECT_ROOT_DIR` or below one of these directories, and below none of `DP_PROJECT_EXCLUDE_DIRS` (also not below an included directory: `DP_PROJECT_EXCLUDE_DIRS=/opt/mylib/include/generated`). A directory includes everything below it (`/opt/mylib` does not include `/opt/mylib2`), and may be named through a symbolic link or its resolved path. Read by the profiler's LLVM pass, by the hotspot detection and by the AST export of `discopop_cc` / `discopop_cxx`. The project manager sets it from the included directories of the *Project Setup* stage (as absolute paths). |
| `DP_PROJECT_EXCLUDE_DIRS` | not set | Directories inside `DP_PROJECT_ROOT_DIR` (or `DP_PROJECT_INCLUDE_DIRS`) whose code is no project code, separated by `:`, absolute or relative to `DP_PROJECT_ROOT_DIR`, e.g. `build/_deps:third_party`. Their files are neither instrumented nor listed in `FileMapping.txt`, and the AST of the instrumentation leaves out their declarations, which for template libraries fetched into the build directory saves gigabytes per translation unit. A directory excludes everything below it (`build/_deps` does not exclude `build/_deps2`). Both variables may name the project through a symbolic link or its resolved path. Read by the profiler's LLVM pass, by the hotspot detection and by the AST export of `discopop_cc` / `discopop_cxx`. The project manager sets it from the excluded directories of the *Project Setup* stage. |
| `DP_STRIP_OPENMP` | not set | If set to `1`, the compiler wrappers (`discopop_cc`, `discopop_cxx`, the MPI and linker wrappers, and the wrappers of the hotspot detection) remove the OpenMP flags (`-fopenmp`, `-fopenmp=...`, `-fopenmp-simd`, `-Xclang -fopenmp`, `-Xpreprocessor -fopenmp`, `-qopenmp`, `-openmp`, `-lomp`, `-lgomp`, `-liomp5`) from the compiler call, the instrumented compilation and the AST dump alike: the pragmas are ignored and the program is profiled as the sequential code. Without it the flags are kept, the program is profiled with its OpenMP pragmas active, and the first compiler call of a build that contains such a flag prints a warning that names this variable (also recorded in `.discopop/openmp_flags_seen.json`). Code that calls `omp_*` functions needs `#ifdef _OPENMP` guards to link without the OpenMP runtime. The project manager sets it from its setting (`--strip-openmp`, *Project Setup* stage of the GUI) for every instrumented build and ignores a value from the environment or the settings files. |
| `DP_OPENMP_QUIET` | not set | If set to `1`, the wrappers record the OpenMP flags they see but print no warning. Set by the project manager, which words the warning itself (it points at the GUI setting). |
| `DP_WRITE_CALLPATH_DOT` | not set | If set to any value, the static analysis also writes `static_calltree.dot` and `callpath_state_transitions.dot` to `.discopop/profiler`. They visualize the call graph for debugging, are not read by DiscoPoP, and are the largest files of the static analysis for programs with deep call graphs. |
| `DP_CALLPATH_HOTSPOTS` | not set | Path of the `Hotspots.json` of a hotspot detection run. If set, the profiler's LLVM pass folds the call path states of functions that are neither hot nor lead to a hot function into the state of their caller (call path pruning): faster profiling and smaller data. Without it nothing is pruned. The project manager sets it for the instrumented (`dp`) compilation if pruning is activated in the *Project Setup* stage and current hotspot results exist, and removes a value from the environment or the settings file otherwise. |
| `DP_CALLPATH_HOTNESS` | `yes,maybe` | Comma separated hotness classes of `Hotspots.json` that count as hot. Only read with `DP_CALLPATH_HOTSPOTS`. |
| `DP_CALLPATH_SEEDS` | `both` | What makes a function the start of a hot path: `loops` (it contains a hot loop), `functions` (it is hot itself) or `both`. A hot function without calls and loops is no start unless `DP_CALLPATH_KEEP_HOT_LEAVES` is set. Only read with `DP_CALLPATH_HOTSPOTS`. |
| `DP_CALLPATH_HOT_DEPTH` | `2` | Calls whose call path states are kept below a hot function. Only read with `DP_CALLPATH_HOTSPOTS`. |
| `DP_CALLPATH_UNCLASSIFIED` | `keep` | `keep` or `prune`: what happens to functions `Hotspots.json` does not mention. Only read with `DP_CALLPATH_HOTSPOTS`. |
| `DP_BB_REPORT_CACHE_MB` | not set | Memory allowance in MiB of the caches of the basic block reports, for one run; takes precedence over `BB_REPORT_CACHE_MB` in `dp.conf` (see [Runtime settings](#runtime-settings-dpconf)). |
| `DOT_DISCOPOP_PROFILER` | `<DOT_DISCOPOP>/profiler` | Set automatically by the instrumentation from `DOT_DISCOPOP`. Do not set it yourself. |

Example:

```bash
DP_PROJECT_ROOT_DIR=$PWD/ DOT_DISCOPOP=$PWD/.discopop discopop_cxx example.cpp -o a.out
```

A CMake project whose dependencies are fetched into the build directory:

```bash
DP_PROJECT_ROOT_DIR=$PWD/ DP_PROJECT_EXCLUDE_DIRS=dp_build/_deps DOT_DISCOPOP=$PWD/.discopop \
    cmake -B dp_build -DCMAKE_C_COMPILER=discopop_cc -DCMAKE_CXX_COMPILER=discopop_cxx
DP_PROJECT_ROOT_DIR=$PWD/ DP_PROJECT_EXCLUDE_DIRS=dp_build/_deps DOT_DISCOPOP=$PWD/.discopop make -C dp_build -j
```

A project that uses a library of the same repository outside of its directory:

```bash
DP_PROJECT_ROOT_DIR=$PWD/ DP_PROJECT_INCLUDE_DIRS=../common DOT_DISCOPOP=$PWD/.discopop discopop_cxx example.cpp -I../common -o a.out
```

See the [command line walk-through](../examples/walk_through.md) for the complete workflow.

## Patch repair

| Variable | Default | Description |
|---|---|---|
| `DISCOPOP_PATCH_REPAIR_LLM_CONFIG` | `.discopop/patch_repair/llm_config.json` | Path of the LLM connection configuration of the [patch repair](../tools/Patch_repair.md). Overrides the default location for one run; the option `--llm-config` of the tool takes precedence over both. |

## Graphical user interface

`discopop_gui` needs a display. It exits with an error message if neither `DISPLAY` (X11) nor `WAYLAND_DISPLAY` is set. On a machine without a display, use the project manager on the command line instead (`discopop_project_manager --help`). The package `python3-tk` has to be installed, see [Installation](./discopop.md#prerequisites).

## Runtime settings (dp.conf)

The runtime library of the profiler reads the file `dp.conf` from the directory of the instrumented executable when the program starts. Each line has the form `<KEY>=<value>`; spaces are ignored. Keys that are not listed are ignored.

| Key | Default | Description |
|---|---|---|
| `NUM_WORKERS` | 4 (the build default, see [Build options](./build_options.md#profiling)) | Number of worker threads that analyze the memory accesses. |
| `FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER` | 4 | Limit of the first access queue per worker, in chunks of 100000 accesses (about 4 MB each). Lower it to reduce the memory use of the profiler. |
| `SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER` | 4 | Limit of the second access queue per worker, in elements of up to about 11 MB each. |
| `BB_REPORT_CACHE_MB` | 50 | The environment variable `DP_BB_REPORT_CACHE_MB` takes precedence. Memory allowance in MiB of the caches that spare the hybrid analysis most lookups of reported basic block executions: one table of 512 bytes per callpath state in which a reporting basic block executes (a few MB for LULESH and miniFE). The caches never exceed it: the table pointers of all callpath states (8 bytes each) are taken from it at startup, the tables from the rest. At the limit, states without a table go without one and the runtime prints a note; when their reports pile up (e.g. in another phase of the program), all tables are discarded and taken again by the states reporting next. `0`, or an allowance that cannot hold the table pointers and one table, turns the caches off, which slows down the profiling: the runtime prints a warning with the number of callpath states and an estimate of the allowance the caches would need. Large programs (millions of callpath states) need more than the default; whether the speed is worth the memory is up to you. |
| `SIG_ELEM_BIT` | 56 | Signature memory: bits per element. |
| `SIG_NUM_ELEM` | 270000 | Signature memory: number of elements. |
| `SIG_NUM_HASH` | 2 | Signature memory: number of hash functions. |
| `USE_PERFECT` | 1 (enabled) | Perfect instead of signature-based shadow memory. |
| `DP_DEBUG` | off | Any positive value prints the settings at start (followed by a pause of two seconds) and enables debug output of the runtime. The output for every memory access, function entry and exit and loop iteration needs a runtime built with the [build option](./build_options.md#development-and-debugging) `DP_DEBUG`. |

Example `dp.conf` for eight workers:

```text
NUM_WORKERS=8
```

{: .warning }
Values have to be greater than 0, other values are ignored. Consequently `USE_PERFECT=0` has no effect, and neither can the number of workers be set to 0 in `dp.conf`.

{: .note }
The signature settings (`SIG_*`) and `USE_PERFECT` are only evaluated for the shadow memory of the single-threaded execution mode, which is used when the runtime has no worker threads. The worker threads always use the perfect shadow memory.
