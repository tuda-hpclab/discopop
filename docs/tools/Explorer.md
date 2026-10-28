---
layout: default
title: Explorer
parent: Tools
nav_order: 5
---

# Explorer
## Executable
`discopop_explorer`

## Purpose
The explorer analyzes the [output of the instrumentation and profiling stage](../data/Profiling_and_instrumentation_output.md) and identifies opportunities for parallelism in the sequential target code ([parallel patterns](../data/Parallel_patterns/Patterns.md)).
As part of the analysis, it creates the [program execution graph](../data/Program_execution_graph.md).

By default, it detects [do-all loops](../data/Parallel_patterns/doall.md) and [reductions](../data/Parallel_patterns/reduction.md).
When it has found the patterns, it runs the [patch generator](Patch_generator.md), so the patch files of all suggestions exist when the explorer returns.

## Required input
The explorer works on the data of one `.discopop` directory. Run it from inside that directory, or pass the directory with `--path`.
- [File mapping](../data/Filemapping.md) (`FileMapping.txt`)
- [Profiling and instrumentation output](../data/Profiling_and_instrumentation_output.md) (the `profiler` folder: `Data.xml`, `dynamic_dependencies.txt`, `loop_counter_output.txt`, `reduction.txt`)
- Optional: hotspot information (`hotspot_detection/Hotspots.json`, see [Hotspot detection](Hotspot_detection.md)). If it exists, only the code regions classified by `--hotspot-types` are analyzed.

## Output
All paths are relative to the `.discopop` directory. The files are described in [Explorer output](../data/Explorer_output.md).

| Path | Contents |
|------|----------|
| `explorer/patterns.json` | The identified parallel patterns (suggestions). Other tools of the framework import it. |
| `explorer/pattern_decisions.json` | Which code regions the detection considered, which patterns it found for them and why it rejected the others (e.g. the data dependency that prevents a parallelization). |
| `explorer/detection_result_dump.json` | Dump of the complete detection result, including the program execution graph. |
| `explorer/side_effects.json.gz` | Data that functions read and write outside of themselves, as observed during profiling. |
| `patch_generator/<pattern id>/<file id>.patch` | The patches created by the [patch generator](Patch_generator.md). |

`--json`, `--dump-detection-result` and `--pattern-decisions` change the location of the first three files.

## Example
```bash
cd .discopop && discopop_explorer
```

On `example/example.cpp`, this finds two suggestions (a do-all loop and a reduction) and writes the patches to `patch_generator/0/` and `patch_generator/1/`. Apply them with the [patch applicator](Patch_applicator.md).

## Options
Options for the patterns to detect:

| Option | Default | Description |
|--------|---------|-------------|
| `--enable-patterns` | `reduction,doall,task` | Comma-separated list of the pattern types to identify (see below). |
| `--hotspot-types` | `yes,maybe` | Hotspot types whose code regions are analyzed (`yes`, `no`, `maybe`). Only takes effect if `hotspot_detection/Hotspots.json` exists; otherwise, the whole program is analyzed. |
| `--load-existing-doall-and-reduction-patterns` | off | Skip the pattern detection and insert the contents of an existing `patterns.json` into the detection result. |

Options for the input and the output:

| Option | Default | Description |
|--------|---------|-------------|
| `--path` | `./` | The `.discopop` directory to analyze. |
| `--cu-xml` | `profiler/Data.xml` | CU node XML file. |
| `--dep-file` | `profiler/dynamic_dependencies.txt` | Dependency file. |
| `--loop-counter` | `profiler/loop_counter_output.txt` | Loop counter data. |
| `--reduction` | `profiler/reduction.txt` | Reduction variables file. |
| `--fmap` | `FileMapping.txt` | File mapping. |
| `--json [path]` | `explorer/patterns.json` | Location of the patterns file. |
| `--pattern-decisions [path]` | `explorer/pattern_decisions.json` | Location of the file that records the pattern decisions. Without a value, nothing is recorded. |
| `--dump-detection-result [path]` | `explorer/detection_result_dump.json` | Location of the dump of the detection result. Note: the dump contains the program execution graph. |
| `-j`, `--jobs` | unlimited | Number of threads to use. `0` or `1` disable threading. |
| `--log` | `WARNING` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--write-log` | off | Write a log file. |

Further options:

| Option | Default | Description |
|--------|---------|-------------|
| `--dump-pet [path]` | off | Dump the program execution graph to a JSON file (`explorer/pet_dump.json` if no path is given). |
| `--profiling [path]` | off | Write profiling statistics of the explorer itself (`explorer/profiling_stats.txt` if no path is given). |
| `--plugins [name ...]` | none | Plugins to execute. |
| `--dp-build-path` | `build` folder next to the package | Path to the DiscoPoP build folder. <!-- UNVERIFIED: whether this value is still used --> |
| `--visualize` | off | Enable the visualizer. |

### Pattern types
`--enable-patterns` accepts `reduction`, `doall`, `task`, `pipeline`, `geodec` and `simplegpu`.
- `reduction` and `doall` are enabled by default.
- `task` (on by default) runs the experimental [task detector](../data/Parallel_patterns/tasks.md). It is slow and its results are not deterministic.
- `pipeline`, `geodec` and `simplegpu` are listed in the help of the explorer, but the explorer does not run these detectors (see [pipeline](../data/Parallel_patterns/pipeline.md) and [geometric decomposition](../data/Parallel_patterns/geometric_decomposition.md)).

### Experimental and debugging options
These options may change or be removed.

| Option | Default | Description |
|--------|---------|-------------|
| `--microbench-file` | none | Path to a microbenchmark JSON file. |
| `--generate-data-cu-inst <dir>` | none | Generate `Data_CUInst.txt` in the given directory and stop. Requires `--cu-xml`, `--dep-file`, `--loop-counter` and `--reduction`. |
| `--enable-statistics` | off | Calculate and store statistics for the code and the generated suggestions. |
| `--ignore-dependency-states` | off | Ignore the callpath state markers (`@<state_id>`) in the dependency data. The affected dependencies are then reclassified from dynamic to static. The explorer writes no `side_effects.json.gz` in this mode. |
| `--plot-pet [path]` | off | Write the program execution graph as GEXF file (`explorer/pet_plot.gexf` if no path is given). |
| `--plot-task-graph` | off | Plot the task graph interactively. |
| `--plot-context-graph` | off | Plot the context graph interactively. |

## Use from other tools
- The [GUI](GUI.md) runs the explorer in its Pattern Detection tab.
- The [MCP server](MCP_server.md) runs it as part of `gather_data`.
- The [project manager](Project_manager.md) can run it from the command line.

## Background
Like many scientific applications that work on arrays or matrices, the suggestions do not change if the input size changes. It is therefore possible to analyze the program with small inputs, obtain the parallelization suggestions and execute the parallelized version with larger inputs. This is a recommendation only, and whether it applies depends on the code.

DiscoPoP has an optimistic approach towards parallelization. You have to validate the final suggestions.
