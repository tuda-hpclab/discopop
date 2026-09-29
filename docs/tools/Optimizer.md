---
layout: default
title: Optimizer
parent: Tools
nav_order: 6
---

# DiscoPoP optimizer
## Executable
`discopop_optimizer`

## Purpose
- Propose a mapping of the parallel patterns identified by the [DiscoPoP explorer](../tools/Explorer.md) to various devices available to the system.
- Identify and report optimizations for the identified patterns (e.g. adding a `collapse(3)` clause to parallel loops).
- Create a beneficial combination of potentially multiple patterns to achieve a improved speedup and remove the need to manually select combinable patterns.

## Required input
- [Filemapping](../data/Filemapping.md)
- [Profiling and instrumentation output](../data/Profiling_and_instrumentation_output.md)
- Parallel patterns created by [DiscoPoP explorer](../tools/Explorer.md)

## Optional input
- System information and overhead measurements obtained via the [OpenMP Microbenchmark suite](https://github.com/discopop-project/OpenMP-Microbench)

## Output
Identified optimizations and combinations are stored by extending the original set of [parallel patterns](../data/Parallel_patterns.md). The updated set is stored in a file named `.discopop/optimizer/patterns.json` by default. Similar to the original set of patterns, these can be imported by various other tools in the framework.

## Note
For a more detailed description of the available run-time arguments, please refer to the help string of the respective tool.
```
discopop_optimizer --help
```
