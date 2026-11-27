---
layout: default
title: Optimizer
parent: Tools
nav_order: 12
---

# Optimizer
## Executable
`discopop_optimizer`

{: .note }
The optimizer is experimental. It is not part of the [GUI](GUI.md) or [MCP server](MCP_server.md) pipeline; both use the [autotuner](Autotuner.md) to select suggestions.
<!-- UNVERIFIED: on the checkout's example/example.cpp, discopop_optimizer stopped with a KeyError in PETParser while building the optimization graph -->

## Purpose
- Build an optimization graph from the program execution graph and the patterns found by the [explorer](Explorer.md), and evaluate mappings of the patterns to the devices described in a system configuration.
- Identify loop nests that can be collapsed (the `collapse` clause of loops).
- Select a combination of multiple patterns (`-o`: greedy, evolutionary or exhaustive search) so you do not have to choose combinable patterns manually.

## Required input
Run the tool from inside the `.discopop` directory.
- [File mapping](../data/Filemapping.md)
- [Profiling and instrumentation output](../data/Profiling_and_instrumentation_output.md)
- `explorer/patterns.json`, created by the [explorer](Explorer.md)

## Optional input
- Overhead measurements of the target system obtained with the OpenMP microbenchmark suite ([OpenMP-Microbench](https://github.com/discopop-project/OpenMP-Microbench)), passed with `--doall-microbench-file` and `--reduction-microbench-file`. <!-- UNVERIFIED: the link was not checked -->
- A system configuration file (`optimizer/system_configuration.json` by default). The optimizer creates a default one if the file does not exist.

## Output
The optimizer extends the original set of patterns with its results and stores them in `optimizer/patterns.json` (inside `.discopop`), next to the experiment data of the run.

The [patch generator](Patch_generator.md) does not read this file by default. To create patches for it, run:
```bash
discopop_patch_generator -a optimizer/patterns.json
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-v`, `--verbose` | off | Enable verbose output. |
| `-p` | `0` | Program path pruning: `0` none, `1` prune to the paths that cover 80% of the observed decisions per path split, `2` prune to the most likely path. |
| `-o` | `0` | Optimization level: `0` none, `1` greedy, `2` evolutionary, `3` exhaustive. |
| `-opt-2-params <population_size> <generations>` | `50 5` | Parameters of the evolutionary optimization (`-o 2`). |
| `-s`, `--single-suggestions` | off | Generate individual suggestions for device mappings. |
| `--doall-microbench-file` | none | Do-all microbenchmark results. |
| `--reduction-microbench-file` | none | Reduction microbenchmark results. |
| `--system-configuration` | `optimizer/system_configuration.json` | System configuration file. |
| `--pin-function-calls-to-host` | off | Force function calls on the host; prevents offloading of entire functions. |
| `--profiling` | off | Profile the optimizer (writes `optimizer_profile.txt`). |
| `--log` | `WARNING` | Log level. |
| `--write-log` | off | Write a log file. |

Interactive pattern merging:

| Option | Description |
|--------|-------------|
| `-i`, `--interactive` | Start the interactive pattern merge tool. |
| `--interactive-export <ids>` | Merge and export the comma-separated suggestion ids. Requires `-i`. |

Experimental options:

| Option | Description |
|--------|-------------|
| `--allow-nested-parallelism` | Allow nested parallelism suggestions. The cost estimation may be inaccurate. |
| `--check-called-function-for-nested-parallelism` | Extend the nesting check to called functions. Can increase the run time significantly. |
| `--plot` | Plot the internal graph. |
