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
| `DOT_DISCOPOP` | `.discopop` in the current directory | Directory in which the instrumentation, the runtime and the hotspot detection write their results. The profiling data ends up in the subdirectory `profiler`. When you start an instrumented program by hand from another directory, the directory has to exist and contain `profiler/`. The project manager sets it for every run of a configuration. |
| `DP_PROJECT_ROOT_DIR` | `/` | Root directory of the project to analyze. Only functions defined inside it are instrumented; with the default, all functions including library functions are. Read by the profiler's LLVM pass and by the hotspot detection. The project manager sets it for every run. |
| `DP_WRITE_CALLPATH_DOT` | not set | If set to any value, the static analysis also writes `static_calltree.dot` and `callpath_state_transitions.dot` to `.discopop/profiler`. They visualize the call graph for debugging, are not read by DiscoPoP, and are the largest files of the static analysis for programs with deep call graphs. |
| `DOT_DISCOPOP_PROFILER` | `<DOT_DISCOPOP>/profiler` | Set automatically by the instrumentation from `DOT_DISCOPOP`. Do not set it yourself. |

Example:

```bash
DP_PROJECT_ROOT_DIR=$PWD DOT_DISCOPOP=$PWD/.discopop discopop_cxx example.cpp -o a.out
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
| `BB_REPORT_CACHE_MB` | 50 | Memory allowance in MiB of the caches that spare the hybrid analysis most lookups of reported basic block executions: one table of 512 bytes per callpath state in which a reporting basic block executes (a few MB for LULESH and miniFE). The caches never exceed it: the table pointers of all callpath states (8 bytes each) are taken from it at startup, the tables from the rest. At the limit, states without a table go without one and the runtime prints a note; when their reports pile up (e.g. in another phase of the program), all tables are discarded and taken again by the states reporting next. `0`, or an allowance that cannot hold the table pointers and one table, turns the caches off (the runtime prints a warning), which slows down the profiling. |
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
