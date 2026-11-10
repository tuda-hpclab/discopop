---
layout: default
title: Build options
parent: Setup
nav_order: 2
---

# Build options

The C++ parts of DiscoPoP (the LLVM pass and the runtime library of the profiler, the hotspot detection) are configured with CMake options. This page lists them and explains how to pass them to the different kinds of builds.

1. TOC
{:toc}

## Options for the pip build

`pip install ./profiler` (and `make`, and the installation from PyPI) builds the profiler with scikit-build-core. Options are passed with `--config-settings`, separated by `;`:

```bash
venv/bin/python -m pip install ./profiler --config-settings="cmake.args=-DDP_HYBRID_PROFILING=0;-DLLVM_DIST_PATH=/path/to/llvm"
```

The same works for `./hotspot_detection` (options of the profiler have no effect there). The settings are applied to the CMake configuration of that package only (verified with `-DDP_RTLIB_VERBOSE=0;-DDP_NUM_WORKERS=2`, which end up in the CMake cache of the build).
Install the profiler without `-e`, see [Installation](./discopop.md#manual-installation).

{: .note }
`make` and the installation of `discopop` from PyPI build the profiler with the default options. To use other options, install the profiler afterwards with the command above.

## CMake options

Pass the options as `-D<NAME>=<value>` to `cmake`, or as shown above to `pip`.

### LLVM and compiler

| Option | Default | Description |
|---|---|---|
| `USE_LLVM_VERSION` | empty | Major version of LLVM to use. If neither this nor `LLVM_DIST_PATH` is set, the first LLVM installation found among versions 22, 21, 20 and 19 is used. |
| `LLVM_DIST_PATH` | empty | Base directory of an LLVM installation to use (CMake looks for `lib/cmake/llvm` below it). Takes precedence over `USE_LLVM_VERSION`. |
| `CMAKE_C_COMPILER`, `CMAKE_CXX_COMPILER` | newest `clang-22` ... `clang-19`, then `clang` | Compilers used to build the profiler. |

### Profiling

These options are compiled into the profiler and affect all programs instrumented with it. Rebuild and reinstall the profiler after changing them.

| Option | Default | Description |
|---|---|---|
| `DP_NUM_WORKERS` | not set (the runtime uses 4) | Number of worker threads of the runtime library that analyze the memory accesses during profiling. `0` disables the worker threads. Can be changed per program without rebuilding via `NUM_WORKERS` in [`dp.conf`](./environment_variables.md#runtime-settings-dpconf). |
| `DP_HYBRID_PROFILING` | `1` | Hybrid profiling: the static analysis of the LLVM pass omits instrumentation that is not needed. `0` instruments everything and slows down the profiling. |
| `DP_BRANCH_TRACKING` | `0` | Adds instrumentation that counts the taken branches (used by the optimizer). Slows down the profiling. |
| `DP_PTHREAD_COMPATIBILITY_MODE` | `0` | `1` serializes the calls to the runtime functions. Set it if the profiled application uses Pthreads. Slows down the profiling. |

### Development and debugging

| Option | Default | Description |
|---|---|---|
| `DP_RTLIB_VERBOSE` | `0` | `1` makes the runtime library print debugging output during profiling. |
| `DP_DEBUG` | `0` | `1` builds the debug output that the runtime prints for every memory access, function entry and exit and loop iteration when `DP_DEBUG` is set in `dp.conf`. Without it, the check costs the profiling about 2%. |
| `DP_INTERNAL_TIMER` | `0` | `1` measures the time spent in the functions of the runtime library. Slows down the profiling. |
| `DP_BUILD_UNITTESTS` | `0` | `1` builds the C++ unit tests and the benchmarks (targets `DiscoPoP_UT`, `DiscoPoP_Pass_UT`, `DiscoPoP_BM`) and the benchmark variants of the runtime. |
| `DP_SANITIZERS` | empty | Value for `-fsanitize=`, e.g. `address,undefined` or `thread`. Instruments the runtime library and everything linking it (the unit tests). The LLVM pass is not sanitized. `thread` cannot be combined with `address`, `leak` or `memory`. |
| `CMAKE_EXPORT_COMPILE_COMMANDS` | `ON` | The root `CMakeLists.txt` writes `compile_commands.json` into the build directory. `OFF` turns it off. |

### Root project only

These options only affect a configuration of the root `CMakeLists.txt` (not the pip build):

| Option | Default | Description |
|---|---|---|
| `USE_VENV` | empty | Existing virtual environment to use for the Python part of the configuration. If empty, CMake creates `venv` in the source directory. |

{: .note }
The root `CMakeLists.txt` is meant for development (unit tests, benchmarks, code navigation). It is not the way to install DiscoPoP: the profiler that `discopop_cxx` uses is the one installed by pip, not the one built in a CMake build directory. The target `python_modules` of the root project is not documented on purpose: it installs the PyPI packages and replaces the links `~/.local/bin/discopop_*`.

## Developer builds

For the C++ unit tests and the benchmarks, configure a separate build directory:

```bash
cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1
cmake --build build_tests --target DiscoPoP_UT DiscoPoP_Pass_UT -j "$(nproc)"
build_tests/test/unit_tests/DiscoPoP_UT
build_tests/test/pass_unit_tests/DiscoPoP_Pass_UT
```

Further helpers (sanitizer runs, leak check, coverage, checks of all runtime option combinations) are listed in [How to contribute](../How_to_contribute.md#developer-utilities).

### Code navigation in editors

Editors that use [clangd](https://clangd.llvm.org) need the compiler flags of every source file to resolve the LLVM headers. CMake writes them to `compile_commands.json` in the build directory. clangd finds `build/compile_commands.json` on its own. For a build directory with another name, link its database into the source directory once (the link is ignored by git):

```bash
ln -s build_tests/compile_commands.json .
```

Configure again after adding a source file, so that it is listed. The checked-in `.clangd` removes a GCC-only flag that clang rejects. The database lists the default configuration: code disabled by a `-DDP_...` option is not indexed, and a profiler installed with `pip install ./profiler` is built without such a database.
