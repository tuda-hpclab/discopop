---
layout: default
title: Parallel patterns
parent: Data
has_children: true
permalink: /Data/Patterns
nav_order: 5
---

# Parallel patterns

The [explorer](../../tools/Explorer.md) searches the [program execution graph](../Program_execution_graph.md) for code that can run in parallel and reports it as parallel patterns. The option `--enable-patterns` selects the detectors (default: `reduction,doall,task`).

| Pattern | Status | Page |
|---|---|---|
| Do-all (`doall`) | detected, default | [Do-All](doall.md) |
| Reduction (`reduction`) | detected, default | [Reduction](reduction.md) |
| Task (`task`) | experimental, only with `--enable-patterns task` | [Tasks](tasks.md) |
| Pipeline (`pipeline`) | not run at the moment | [Pipeline](pipeline.md) |
| Geometric decomposition (`geodec`) | not run at the moment | [Geometric decomposition](geometric_decomposition.md) |
| Simple GPU (`simplegpu`) | not run at the moment | - |

The help text of `--enable-patterns` still lists `pipeline`, `geodec` and `simplegpu`, but the explorer does not call their detectors; the value `*` enables all detectors that are run, including the experimental `task`.

## How patterns are reported

- `.discopop/explorer/patterns.json` contains all patterns, grouped by type (see [Explorer output](../Explorer_output.md)). If you disable the JSON output (`--json` without a value), the explorer prints the patterns as text instead.
- `.discopop/explorer/pattern_decisions.json` records for every examined loop whether a pattern was accepted and why not otherwise.
- For every pattern, the [patch generator](../../tools/Patch_generator.md) writes a patch to `.discopop/patch_generator/<pattern id>/`. You apply patches with the [patch applicator](../../tools/Patch_applicator.md); the patches, not the JSON, are what you use to parallelize the code.

## Shared fields

All patterns in `patterns.json` have these fields:

| Field | Meaning |
|---|---|
| `pattern_id` | unique id (see `next_free_pattern_id.txt`); the name of the patch directory |
| `node_id` | id of the node in `Data.xml` the pattern belongs to; for a loop pattern the entry CU of the loop |
| `start_line`, `end_line` | `<file id>:<line>` of the first and last line of the pattern |
| `applicable_pattern`, `standalone_pattern` | whether the pattern can be applied, and whether it can be applied on its own |
| `pattern_tag` | string that identifies the pattern (type, location, clauses) |
| `affected_cu_ids` | ids of the CUs of the pattern |
| `affected_line_ids` | lines of the pattern (`<file id>:<line>`) |
| `affected_functions` | `<start line>:<function name>` of the surrounding function |
| `average_iteration_count`, `iterations_count`, `entries` | loop counts; `-1` if unknown |
| `workload`, `per_iteration_workload` | estimated workload, `null` if unknown |
| `device_id`, `device_type` | for GPU patterns, `null` otherwise |

Do-all and reduction patterns add `pragma`, the data sharing clauses and `collapse_level`.
