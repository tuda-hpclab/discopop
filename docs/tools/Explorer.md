---
layout: default
title: Explorer
parent: Tools
nav_order: 2
---

# DiscoPoP explorer
## Executable
`discopop_explorer`

## Purpose
Analyze the [output of the instrumentation and profiling stage](../data/Profiling_and_instrumentation_output.md) in order to identify opportunities for parallelism in the sequential target code ([parallel patterns](../data/Parallel_patterns.md)).
As part of the analysis, the [program execution graph](../data/Program_execution_graph.md) is created.

## Required input
- [Filemapping](../data/Filemapping.md)
- [Profiling and instrumentation output](../data/Profiling_and_instrumentation_output.md)

## Output
Identified [parallel patterns](../data/Parallel_patterns.md) are stored in a file named `.discopop/explorer/patterns.json` by default. This information can be imported by various other tools in the framework.

Which code regions the pattern detection considered, which patterns it found for them and why it rejected the others (e.g. the data dependency that prevents a parallelization) is stored in `.discopop/explorer/pattern_decisions.json`. `--pattern-decisions <path>` writes it elsewhere; `--pattern-decisions` without a value disables the recording.

## Note
For a more detailed description of the available run-time arguments, please refer to the help string of the respective tool.
```
discopop_explorer --help
```

## Background
Please note that like many scientific applications which work on arrays or matrices, the suggestions do not change if we change the input size. Thus, it is possible to analyze the program with small inputs, obtain the parallelization suggestions and execute the parallelized version with larger inputs. However, this is a recommendation merely and it being applicable or not depends highly on the code.

Furthermore, we need to mention that DiscoPoP has an optimistic approach towards parallelization and thus programmers require to validate the final suggestions.
