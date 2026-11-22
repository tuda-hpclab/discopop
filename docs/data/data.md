---
layout: default
title: Data
has_children: true
permalink: /Data
nav_order: 7
---

# Data

All tools of DiscoPoP exchange their data through one directory, `.discopop`. The instrumented program and the tools use the `.discopop` directory of the project (the nearest one from the current directory upwards, created by `discopop_project_manager --init`), or the one at the path in the environment variable `DOT_DISCOPOP` (see [Environment variables](../setup/environment_variables.md)). The pages of this section describe the files in it.

```text
.discopop/
├── FileMapping.txt              file ids -> source file paths
├── line_mapping.json            line shifts caused by applied patches
├── next_free_pattern_id.txt     next free pattern id (written by the explorer)
├── profiler/                    output of the instrumentation and the profiling run
├── explorer/                    output of the explorer
├── patch_generator/<id>/        one directory per suggestion, with its patches
├── patch_applicator/            state of the applied patches
├── hotspot_detection/           hotspot results (optional, read by the explorer)
├── auto_tuner/                  results of the empirical autotuner
└── project/                     configurations and results of the project manager
```

| Path | Content | Described in |
|---|---|---|
| `profiler/` | `Data.xml`, dependencies, loop counters, callpath states, reductions and further files, written by the compiler pass and the runtime library | [Profiling and instrumentation output](Profiling_and_instrumentation_output.md) |
| `FileMapping.txt`, `line_mapping.json` | file ids and line numbers | [File mapping](Filemapping.md) |
| `explorer/` | `patterns.json`, `pattern_decisions.json`, `detection_result_dump.json`, `side_effects.json.gz` | [Explorer output](Explorer_output.md) |
| `patch_generator/`, `patch_applicator/` | patches and the list of applied patches | [Explorer output](Explorer_output.md), [Patch generator](../tools/Patch_generator.md), [Patch applicator](../tools/Patch_applicator.md) |
| `hotspot_detection/` | hotspots | [Hotspot detection](../tools/Hotspot_detection.md) |
| `auto_tuner/` | results of the autotuner | [Empirical autotuner](../tools/Autotuner.md) |
| `project/` | configurations, scripts and execution results | [Project manager](../tools/Project_manager.md) |

The explorer builds the [program execution graph](Program_execution_graph.md) from the profiler output and reports [parallel patterns](Parallel_patterns/Patterns.md).

All tools run from inside `.discopop` or take its path as an argument (`--path`, `--dot-dp-path`).
