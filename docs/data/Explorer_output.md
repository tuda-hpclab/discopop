---
layout: default
title: Explorer output
parent: Data
nav_order: 3
---

# Explorer output

The [explorer](../tools/Explorer.md) reads `.discopop/profiler` and writes its results to `.discopop/explorer/`. It removes the directory at the start of a run. Relative paths of the options below refer to the `.discopop` directory the explorer runs in.

```text
.discopop/
├── explorer/
│   ├── patterns.json
│   ├── pattern_decisions.json
│   ├── detection_result_dump.json
│   └── side_effects.json.gz
├── patch_generator/<pattern id>/<n>.patch
├── patch_applicator/applied_suggestions.json
├── line_mapping.json
└── next_free_pattern_id.txt
```

## patterns.json

`explorer/patterns.json` (option `--json`) contains the detected patterns. It has the keys `version`, `patterns` and `enabled_patterns`; `patterns` maps a pattern type to a list of patterns. Only the detectors that ran appear: `do_all`, `reduction` and `task` by default (`--enable-patterns reduction,doall,task`), plus the always present, usually empty lists `optimizer_output` and `merged_pattern`. `enabled_patterns` lists the pattern types the detection was asked for, in the order `reduction`, `doall`, `task`, ... (e.g. `["reduction", "doall", "task"]`); the [MCP server](../tools/MCP_server.md) uses it to find out whether a result has to be detected again.

```json
{
  "version": "CURRENTLY INVALID!",
  "patterns": {
    "optimizer_output": [],
    "merged_pattern": [],
    "do_all": [ { "pattern_id": 0, "node_id": "1:7", "start_line": "1:20", "...": "..." } ],
    "reduction": [ { "pattern_id": 1, "node_id": "1:12", "start_line": "1:24", "...": "..." } ],
    "task": []
  },
  "enabled_patterns": ["reduction", "doall", "task"]
}
```

The `version` field is not maintained at the moment and always contains the text `CURRENTLY INVALID!`. The fields of the patterns are described on the pages [Parallel patterns](Parallel_patterns/Patterns.md), [Do-All](Parallel_patterns/doall.md) and [Reduction](Parallel_patterns/reduction.md). The `task` list holds, per [task group](Parallel_patterns/tasks.md), one entry of `type` `TASK` per task and one of `type` `PARALLELREGION`; the fields `task_dependences` and `after_dependences` (region) and `shared`, `private`, `first_private` (task) describe the data flow of the group and are documented there.

## pattern_decisions.json

`explorer/pattern_decisions.json` (option `--pattern-decisions`; without a value nothing is recorded) lists which regions the detectors examined and what they decided. For the example:

```json
{
 "format_version": 1,
 "detectors": { "doall_reduction": ["doall", "reduction"] },
 "decisions": [
  {
   "detector": "doall_reduction",
   "pattern_types": ["doall", "reduction"],
   "region": { "node_id": "1:7", "file_id": 1, "start_line": 20, "end_line": 22, "kind": "loop" },
   "outcome": "accepted",
   "patterns": [ { "type": "doall", "pattern_id": 0 } ],
   "reasons": []
  }
 ]
}
```

For a rejected region, `outcome` says so and `reasons` explains why.
<!-- UNVERIFIED: exact outcome values and reason texts of rejected regions (not produced by the example) -->

## detection_result_dump.json

`explorer/detection_result_dump.json` (option `--dump-detection-result`) is a jsonpickle dump of the whole detection result, including the program execution graph. It is large and meant for tools that reload the result, not for reading.

## side_effects.json.gz

`explorer/side_effects.json.gz` is a gzip-compressed JSON export of the functions, their parameters and local variables, the dependencies with their callpath contexts, and the calls that were executed. The [MCP server](../tools/MCP_server.md) reads it to answer `get_side_effects`. The file starts with `"format_version": 1`; the explorer writes it with every run and removes a stale file if the export fails.

## Patches

For every pattern the explorer runs the [patch generator](../tools/Patch_generator.md), which writes `patch_generator/<pattern id>/<n>.patch` (a unified diff against the source files named in `FileMapping.txt`):

```diff
@@ -21,6 +21,7 @@
     Arr[i] = i % 13;
   }

+  #pragma omp parallel for firstprivate(N) reduction(+:sum)
   for (int i = 0; i < N; i++) {
     sum += Arr[i];
   }
```

The [patch applicator](../tools/Patch_applicator.md) records the patches it applied in `patch_applicator/applied_suggestions.json`; before the first application the list is empty:

```json
{"applied": []}
```

## next_free_pattern_id.txt

The explorer takes pattern ids from `next_free_pattern_id.txt` (a plain number, protected by `next_free_pattern_id.txt.lock`) in its working directory, which is the `.discopop` directory. After the example run it contains `2`. `line_mapping.json` is described on the [File mapping](Filemapping.md) page.
