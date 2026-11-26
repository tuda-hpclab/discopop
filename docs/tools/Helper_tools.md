---
layout: default
title: Helper tools
parent: Tools
nav_order: 13
---

# Helper tools
These tools are used by other tools or serve special purposes. All except the configuration provider and the dependency comparator run from inside a `.discopop` directory (or take `--dot-dp-path`). All of them are installed with `discopop-library`.

| Tool | Purpose |
|------|---------|
| [`discopop_config_provider`](#config-provider) | Prints information about the local DiscoPoP installation. |
| [`discopop_sanity_checker`](#sanity-checker) | Checks suggestions with ThreadSanitizer. |
| [`discopop_preprocessor`](#preprocessor) | Demangles names in the profiling data. |
| [`discopop_dependency_comparator`](#dependency-comparator) | Compares dependency files against a reference. |
| [`discopop_parallel_region_merger`](#parallel-region-merger) | Merges parallel loops into larger parallel regions. |

## Config provider
Executable: `discopop_config_provider`

Prints a value of the local DiscoPoP installation to `stdout`. Other tools (for example the preprocessor and the patch generator) call it to find the LLVM binaries. The options are mutually exclusive.

| Option | Description |
|--------|-------------|
| `-b`, `--dp-build-dir` | Path to the DiscoPoP build directory. |
| `--llvm-bin-dir` | Path to the LLVM `bin` directory. |
| `-f`, `--full` | The full build configuration. |
| `-v`, `--version` | The version string of the DiscoPoP library. |

```bash
discopop_config_provider --llvm-bin-dir
```
<!-- UNVERIFIED: --version prints the placeholder "CURRENTLY INVALID!" at the time of writing -->

## Sanity checker
Executable: `discopop_sanity_checker`

Applies every selected suggestion on its own in a copy of the project, builds it with ThreadSanitizer and runs it, and reports which suggestions produce data race warnings or invalid results. The results are written to `sanity_checker/` inside `.discopop`.

Required input: the data of the [explorer](Explorer.md), hotspot information (`hotspot_detection/`), and a project root that contains the scripts `DP_COMPILE_SANITIZE.sh` and `DP_EXECUTE_SANITIZE.sh`. The compile script must allow OpenMP pragmas and instrument the code with ThreadSanitizer. The project root is copied several times.

| Option | Default | Description |
|--------|---------|-------------|
| `--project-path` | none | Root path of the project. |
| `--dot-dp-path` | none | Path to the `.discopop` folder. |
| `-sc`, `--suggestion_classes` | `YES` | Hotspot classes of the suggestions to check (`YES`, `NO`, `MAYBE`, comma-separated). |
| `--log` | `WARNING` | Log level. |
| `--write-log` | off | Write a log file. |

## Preprocessor
Executable: `discopop_preprocessor`

Prepares the profiling data. It copies `profiler/` to `raw_profiler/` and demangles the C++ names in `profiler/reduction.txt` with `llvm-cxxfilt`. The other profiling files are not changed. Run it from inside `.discopop`. It has no options besides `--log` and `--write-log`.

```bash
cd .discopop && discopop_preprocessor
```

## Dependency comparator
Executable: `discopop_dependency_comparator`

Compares the dynamic and static dependency files of a test set with a gold standard (reference). It is used to check changes of the profiler.

| Option | Description |
|--------|-------------|
| `-g`, `--gold-standard-dynamic` | Dynamic dependency file for reference. |
| `-gs`, `--gold-standard-static` | Static dependency file for reference. |
| `-t`, `--test-set-dynamic` | Dynamic dependency file under test. |
| `-ts`, `--test-set-static` | Static dependency file under test. |
| `-o`, `--output` | Save the comparison results as JSON to this path. |
| `-v`, `--verbose` | Takes a value: any non-empty value (e.g. `-v 1`) enables verbose output. |

The return code encodes the result: `0` no difference; `1xx` missing dependencies; `x1x` additional non-init dependencies; `xx1` additional init dependencies.

## Parallel region merger
Executable: `discopop_parallel_region_merger`

Detects parallel loops that can be merged into larger OpenMP parallel regions, writes the result to `parallel_region_merger/` (`patterns.json`, `results.json`) and runs the [patch generator](Patch_generator.md) on it. It needs the data of the [explorer](Explorer.md) and a `.discopop/project` directory of the [project manager](Project_manager.md); with `-a auto`, it also needs the results of the [autotuner](Autotuner.md).

| Option | Default | Description |
|--------|---------|-------------|
| `--dot-dp-path` | current directory | Path to the `.discopop` folder. |
| `-a`, `--apply-suggestions` | none | Comma-separated suggestion ids to consider for the merge, or `auto` to use the autotuner's result. |
| `-c`, `--config` | `tiny` | Configuration to load from the autotuning results. Only has an effect with `-a auto`. |
| `-p`, `--plot` | off | Allow interactive plots. |
| `--log` | `WARNING` | Log level. |
| `--write-log` | off | Write a log file. |
