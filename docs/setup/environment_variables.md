---
layout: default
title: Environment variables
parent: Setup
nav_order: 1
---

# Environment variables
Environment variables can be used to control the instrumentation and profiling behavior of DiscoPoP.
An overview of the configurable environment variables and their effects can be found below.

## Instrumentation
The following environment variables take effect during the static analysis and instrumentation of the program (see [Example: Step 1](../examples/walk_through.md#step-1-instrument-and-build-the-example-code)).

- `DP_PROJECT_ROOT_DIR`: Specify the path to the root folder of the project to be analyzed. Only functions defined inside this folder will be instrumented. If no value is supplied, all functions including library functions will be instrumented. Default value: `/`. 
- `DP_WRITE_CALLPATH_DOT`: If set to any value, the static analysis additionally writes `static_calltree.dot` and `callpath_state_transitions.dot` to `.discopop/profiler`. Both files are visualizations for debugging purposes and are not read back by DiscoPoP. For programs with deep call graphs they are by far the largest files the static analysis produces, which is why they are not written by default.


## Profiling
The following environment variables take effect during the profiling of the instrumented program (see [Example: Step 2](../examples/walk_through.md#step-2-execute-instrumented-code)).

