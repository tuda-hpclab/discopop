---
layout: default
title: Tasks
parent: Parallel patterns
grand_parent: Data
nav_order: 3
---

# Task parallelism

{: .warning }
Experimental: it is part of the default `--enable-patterns reduction,doall,task`; leave `task` out of the list to switch it off. The detector is incomplete: it suggests where tasks can be created and where they have to be joined, but it does not name the pragmas of the join or place them for you.

The task detector (`new_task_detector.py` in the explorer) works on the task graph that is built on top of the [program execution graph](../Program_execution_graph.md). It reports its results in the `task` list of `.discopop/explorer/patterns.json`. The pattern `*` enables all detectors, including this one; the run can then take much longer than with the default.

## Task groups

A result is a *task group*. It consists of

- one `TaskParallelismInfo` entry of `type` `TASK` per task, and
- one `ParallelRegionInfo` entry of `type` `PARALLELREGION` that contains them (`contains_patterns` lists the pattern ids of its tasks). The region is the entry with a patch (`applicable_pattern` is true for it only): `#pragma omp parallel` and `#pragma omp single` around the tasks.

The tasks of a group share their `task_group` number. A task knows the lines it spans (`region_start_line`, `region_end_line`, relative to the file of the function that contains the group) and the instructions it consists of (`instruction_ids`, see [Data.xml](../Profiling_and_instrumentation_output.md#dataxml)); the lines are derived from the instructions, and lines that only hold a jump (a closing brace, the jump over an `else`) are not counted as part of a task.

### How groups are found

1. The explorer simplifies the task graph and looks for sequences of contexts (for example the statements of a function body) that can be separated into tasks. A group needs at least two valid tasks.
2. A task is dropped if it cannot be the body of an OpenMP task: it does no work (its CUs access no variable and call nothing, e.g. a `return` or the jump over an `else` branch), or it is not a region with a single exit (it ends in a conditional branch whose targets are not part of the task, e.g. the condition of `if (verbose) fprintf(...)`). If fewer than two tasks remain, there is no group.
3. A recursive function is inlined once per recursion level in the task graph, which produces one copy of a group per level. The explorer reports a group once: groups with the same enclosing node, the same line ranges and the same instructions of their tasks are identical.
4. Loop tasks: a do-all loop (see [Do-All](doall.md)) whose body calls a function that is a hotspot is reported as one task per iteration (`TASK` entry with `loop_start_line` set to the line of the loop, in the form `<file id>:<line>`), together with a `PARALLELREGION` entry. The task body is the loop without its header. The tasks are created inside the loop and have to be joined after it. Without hotspot information (`hotspot_detection/Hotspots.json`), every call in the body qualifies; a loop whose body calls nothing is not a task candidate (do-all is reported for it). The data sharing of these tasks is the one of the do-all loop, adapted so that what the code after the loop reads is `shared`.

The detection needs the instruction ids of the profiler (`instructionIDs` and `jumpInstructionIDs` in `Data.xml`); a `Data.xml` from an older profiler is not supported.

### Data flow of a group

For every group the explorer also records how the tasks use data. The fields refer to pattern ids.

| Entry | Field | Content |
|---|---|---|
| `PARALLELREGION` | `task_dependences` | Dependences between the tasks of the group: a list of `{"from_task", "to_task", "variable", "kind"}`. `kind` is `RAW` (the later task reads what the earlier one wrote), `WAR` (the later task writes what the earlier one read) or `WAW` (both write it: an output dependence, which does not prevent the parallelization if the variable is privatized). A group is always a pair of tasks without a data edge between them, so `RAW` and `WAR` between its tasks show up as the join, see `after_dependences`; `WAW` is the dependence that occurs inside a pair. |
| `PARALLELREGION` | `after_dependences` | What the code after the region depends on: a list of `{"task", "variable", "kind", "line", "at_return"}`. The tasks have to be complete before `line` (`<file id>:<line>`, the first line that reads (`RAW`), overwrites (`WAR`) or overwrites what the task wrote (`WAW`) the variable). `at_return` (absent in older results: false) means that the reader is outside of the function, e.g. its caller reads what a task wrote through a pointer parameter or a global: the tasks have to be complete before the function returns, `line` is `null`. `variable` is a name of the scope of the function of the group (a heuristic, it is empty if no such name is known). Writes of callees through pointers are included. For a task that reaches its own function (recursion) the dependences cannot be assigned to a recursion level (the call paths are cut at the recursive call): the code of the function counts as the task's work, which may report a join that is not needed, and no `at_return` entries are made. |
| `TASK` | `shared`, `private`, `first_private` | Data sharing of the variables the task accesses, named as in the source. A variable is `shared` if it is global, written by the task or written by a sibling task, or if it is declared in the task and the code after the group needs it; it is `private` if it is declared in the task and not needed afterwards; otherwise (only read) it is `first_private`. |
| `TASK` | `in_dep`, `out_dep`, `in_out_dep` | The variables of `task_dependences` as the `depend` clauses `in`, `out` and `inout` of the task would list them. |
| `TASK` | `reduction`, `last_private` | `reduction` lists `"<operation>:<name>"` (`?` if the operation is unknown) of variables the task accumulates; they are not listed as `shared`. `last_private` lists variables whose value of the last iteration has to remain; it is a hint on top of `shared` (OpenMP tasks have no lastprivate). |
| `PARALLELREGION` | `loop_start_line`, `loop_end_line` | Set if the tasks are created per iteration of a loop: the first and last line of the loop (`<file id>:<line>`). The region itself covers the task statement; the parallel region of a patch spans the loop. For nested do-all loops with the same statement the innermost loop is reported. |

For a loop task, `after_dependences` is set on the region of the loop, and `task_dependences` is empty.

An example from a small program, in which `h` calls `f` twice (`a = f(k);` on line 11 and `b = f(n + 1);` on line 12) and uses both results on line 13. The first of its two tasks (pattern ids 0 and 1, not applicable on their own) and the region are shown, abbreviated to the fields described here:

```json
{
  "pattern_id": 0, "type": "TASK", "pragma": ["#pragma omp task"],
  "region_start_line": "11", "region_end_line": "11", "task_group": [0],
  "shared": ["a"], "private": [], "first_private": ["k"],
  "in_dep": [], "out_dep": [], "in_out_dep": [],
  "instruction_ids": [50, 51, 52], "loop_start_line": null
}
```
```json
{
  "pattern_id": 2, "type": "PARALLELREGION", "node_id": "1:9",
  "pragma": ["#pragma omp parallel", "#pragma omp single"],
  "region_start_line": "11", "region_end_line": "12",
  "task_group": [0], "contains_patterns": [0, 1],
  "instruction_ids": [50, 51, 52, 53, 54, 55, 56],
  "task_dependences": [],
  "after_dependences": [
    {"task": 0, "variable": "a", "kind": "RAW", "line": "1:13"},
    {"task": 1, "variable": "b", "kind": "RAW", "line": "1:13"}
  ],
  "loop_start_line": null
}
```

The remaining fields of the entries are the common ones of all [patterns](Patterns.md); the `instruction_ids` of the region are those of all its tasks.

The [MCP server](../../tools/MCP_server.md) turns a group into a description (parallel region, task bodies, dependences, join, data sharing) for an agent; see its page for the format.
