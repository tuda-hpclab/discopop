<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# DiscoPoP MCP Server

A Model Context Protocol (MCP) server that exposes DiscoPoP functionality to Claude, enabling Claude to drive the full instrumentation pipeline and query static and dynamic data dependencies.

## Overview

The DiscoPoP MCP Server bridges the gap between Claude and DiscoPoP's profiling and analysis tools. It allows Claude to:

- Instrument a project, run profiling, detect parallel patterns, and retrieve OpenMP patches
- Query static and dynamic data dependencies for arbitrary code regions to support code understanding, refactoring, and correctness checks
- Report the data a function and its callees were observed to read and write outside of it (side effects)
- Retrieve profiling information from executed instrumented code
- List and discover available profiling data and execution configurations

## Features

- **Standalone CLI executable** - Run independently via command line
- **Local deployment** - Uses stdio for direct Claude integration
- **Persistent daemon mode** - Optional long-running server that keeps analysis data in memory between calls
- **Opt-in daemon** - Start `discopop_mcp_server --daemon` yourself; the server connects to it on the first tool call
- **Transparent fallback** - Falls back to inline execution when no daemon is available
- **Comprehensive logging** - View all incoming calls and outgoing responses
- **Type-safe** - Full type hints throughout
- **Extensible** - Easy to add new tools and capabilities

## Installation

### Option 1: Install from source (Recommended for development)

```bash
cd mcp_server
pip install -e ".[dev]"
```

### Option 2: Install as standalone package

```bash
pip install .
```

### Option 3: Direct script usage

```bash
python mcp_server/server.py --debug
```

## Quick Start

### Run the server

```bash
discopop_mcp_server --debug
```

This starts the server in stdio mode, which is used by Claude. The `--debug` flag enables verbose logging.

## Usage Examples

### From the command line

```bash
# Default mode — proxy that routes to daemon if available, otherwise runs inline
discopop_mcp_server

# With debug logging
discopop_mcp_server --debug

# Persistent daemon — keeps analysis data in memory between calls
discopop_mcp_server --daemon

# Daemon on a custom port (default: 7777)
discopop_mcp_server --daemon --daemon-port 8888
```

### Integration with Claude Code

Use the built-in setup flag for easy integration:

```bash
discopop_mcp_server --setup claude_code
```

This automatically configures Claude Code to use the server, handling virtual environment detection, configuration directory creation, and path resolution.

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for more options or [CLAUDE_INTEGRATION.md](CLAUDE_INTEGRATION.md) for detailed setup instructions.

## Available Tools

This section documents the tools around build and execution configuration. The server exposes further tools for running the pipeline and querying its results; call `tools/list`, or see `mcp_server/tools/`, for the complete set.

### `set_compile_script`

Writes a build script for a project. Must use `$CC` / `$CXX` and `$CFLAGS` / `$CXXFLAGS` instead of hard-coded compiler names, since the same script is reused for sequential, instrumented, hotspot-detection and parallel builds — only the settings file differs.

**Parameters:**
- `project_path` (string, required): Path to the target project
- `script_body` (string, required): Bash script body; a `#!/bin/bash` shebang is prepended if absent
- `config_name` (string, optional): Write a per-configuration override instead of the shared script
- `purpose` (string, optional): `execute` (default) writes `compile.sh`; `validate` writes `compile_validate.sh`, a separate build for `validate.sh`

A `compile_validate.sh` is only relevant when the configuration also has a `validate.sh`; the response reports which configurations it is `used_by` and which it is `ignored_for`. See the [project manager documentation](https://tuda-hpclab.github.io/discopop/Tools/Project_manager/) for the full resolution order.

**Example:**
```json
{
  "project_path": "/home/user/my_project",
  "script_body": "$CXX $CXXFLAGS main.cpp -o myapp\n",
  "purpose": "validate"
}
```

### `create_execution_configuration`

Creates a named execution configuration — a subdirectory under `.discopop/project/configs/` describing how to run the compiled binary.

**Parameters:**
- `project_path` (string, required): Path to the target project
- `config_name` (string, required): Name of the configuration; also the subdirectory name
- `script_body` (string, required): Body of `execute.sh`, the timed run
- `validate_script_body` (string, optional): Body of `validate.sh`, an untimed output check run after a successful `execute.sh`; the run counts as correct only if both exit `0`

A configuration that needs its own build, or a separate build for `validate.sh`, gets it from `set_compile_script` with `config_name` (and `purpose: "validate"`) once the configuration exists. Calling the tool again with the same `config_name` overwrites `execute.sh`, and `validate.sh` if given; `delete_execution_configuration` removes a configuration, keeping its recorded execution results and any analysis results gathered with it.

**Example:**
```json
{
  "project_path": "/home/user/my_project",
  "config_name": "small_input",
  "script_body": "./myapp --input data/small.txt > out.txt\n",
  "validate_script_body": "diff out.txt reference.txt\n"
}
```

### `get_configurations`

Retrieves the build scripts and execution configurations defined for a target project, reading `<project_path>/.discopop/project/configs/`.

**Parameters:**
- `project_path` (string, required): Path to the target project

**Returns:** the shared `compile_script` and `validation_compile_script`, the `seq` / `dp` settings, and one entry per configuration with its `execute_script`, `compile_script_override`, `validate_script` and `validation_compile_script`. Each script is `null` when the corresponding file does not exist; an empty configuration list together with a null `compile_script` means the project has not been initialized yet.

**Example:**
```json
{
  "project_path": "./my_project"
}
```

### `get_execution_results`

Shows the recorded runs of a project's scripts, to find out why something failed: a build or profiling step of `gather_data`, a candidate that `run_auto_tuning` rejected, or a run started from the GUI or the command line.

**Parameters:**
- `project_path` (string, required): Path to the target project
- `config_name` (string, optional): Only the runs of this configuration
- `script` (string, optional): Only the runs of this script, e.g. `execute.sh` or `compile.sh`
- `failed_only` (boolean, optional): Only runs with a non-zero return code, a timeout, or suggestions that could not be applied
- `include_output` (boolean, optional): Add the last 2000 characters of each run's stdout and stderr

Reads `<project_path>/.discopop/project/execution_results.json` and returns it grouped by configuration, script and settings file, with one compact entry per run (`code`, `time`, `time_source`, `thread_count`, `applied_suggestions`; further fields only when they carry information). Program output is left out unless `include_output` is set: a full log can be hundreds of kilobytes.

**Example:**
```json
{
  "project_path": "./my_project",
  "failed_only": true,
  "include_output": true
}
```

### `get_data_dependencies`

Returns data dependencies (RAW, WAR, WAW) that cross or lie within a specified code region. Results contain both statically and dynamically identified dependencies — dynamic profiling correctly captures aliasing and other cases that pure static analysis cannot resolve.

Dependencies are grouped by direction:
- `incoming` — source outside the region, sink inside
- `outgoing` — source inside the region, sink outside
- `intra_region` — both source and sink within the region

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `file_path` (string, required): Absolute path to the source file
- `start_line` (integer, required): First line of the code region (inclusive)
- `end_line` (integer, required): Last line of the code region (inclusive)
- `dep_types` (array of `"RAW"`, `"WAR"`, `"WAW"`, optional): Dependency types to return (default: all)
- `directions` (array of `"incoming"`, `"outgoing"`, `"intra_region"`, optional): Directions to return (default: all)
- `var_name` (string, optional): Restrict results to a specific variable; automatically excludes incoming dependencies (aliasing safety, reported as `incoming_excluded_due_to_var_name_filter`)

Each entry carries `dep_type`, `var_name`, `source` and `sink`. An end in the queried `file_path` is given as its bare line number, an end in another file as `{"file", "line"}`.

At most 200 dependencies are returned, ordered by direction (incoming, outgoing, intra_region), then sink and source line, so a cut result is reproducible. `num_dependencies` is always the full count; a cut result adds `truncated: true`, `num_dependencies_by_direction` and a `next_step` naming the ways to narrow the query (smaller line range, `var_name`, `dep_types`, `directions`).

This tool is cheap to call repeatedly — `DetectionResult` and `FileMapping` are cached in memory after the first load. Requires `gather_data` to have been run first.

### `get_side_effects`

Returns the data a function was observed to read and write outside of itself during profiling, including through the functions it calls: globals (also static locals and static data members), memory reached through its pointer, reference, array or class-type parameters (a struct, smart pointer or iterator passed by value may point into the caller's memory), and other memory that outlives the call. It answers whether a call is pure, safe to run concurrently, to reorder or to memoize, during code review and refactoring as well as for parallelization. Results are only valid for the profiled inputs.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `function` (string, required): Name with or without signature (`scale`, `scale(double*, int)`, `ns::Cls::scale`), or the mangled name
- `file_path` (string, optional), `line` (integer, optional): Source file (absolute or relative to `project_path`) and any line inside the definition, to pick one of several functions of that name
- `access` (`"read"` or `"write"`, optional): Only reads or only writes; entries of unknown access are kept with either
- `kinds` (array of `"global"`, `"parameter"`, `"other"`, optional): Default all
- `var_name` (string, optional): Only entries for this name (also matched against `member_of` and `outside_names`, with or without the `GEPRESULT_` prefix), with up to 50 sites each
- `include_callees` (boolean, optional): Default `true`; `false` keeps only the accesses made by the function itself

**Returns:**
- `function`: display name, file and line range of the resolved function
- `coverage`: `executed`; `partial` (some calls of it or of its callees could not be followed: recursion, deep call chains, function pointers; or `unmapped_records` > 0); `untracked` (executed, but no call could be attributed to it); `not_executed` (only statically found global references are listed). Anything but `executed` means that an absent effect is unknown, and comes with a `next_step`
- `pure_on_observed_inputs` (`true`/`false`/`null`), `performs_file_io`, `unprofiled_calls` (called functions without a definition in the project, whose accesses are not observed; at most 20, `num_unprofiled_calls` is the total; matched by the called declaration, so a project's `Logger::write` does not hide POSIX `write`), `unmapped_records` (recorded accesses in the function or anything it calls that could not be attributed to a calling context; if > 0, `coverage` is at most `partial`)
- `summary`: `num_effects`, `by_access`, `by_kind`, `num_contributing_callees` and `contributing_callees` (at most 20) over every entry matching the filters
- `writes`, `reads` and, when present, `unknown_access` (statically found global references whose access could not be derived). One entry per name, kind and access with `kind`, `source` (`observed`, or `static`: referenced in the code, not observed), `through_pointer`, `member_of` (for a struct member), `num_sites`, up to 3 `sites` (50 with `var_name`) and `outside_names` (other source names of the same data, e.g. the caller's argument; never linker names or the function's own name). A site is `{"line", "via"}`, where `via` is the call chain from the function to the function containing the access (`null` for the function itself; consecutive recursive calls are collapsed to `"f(int) x5"`), plus `file` for a site in another file. Names are those at the access: a `parameter` effect found through a callee has the parameter name of the function named by the last `via` element (`wrapper(int* q)` calling `write_through_param(int* p)` reports `p`; the caller's name for the data, e.g. its argument, goes to `outside_names`)
- `notes`: always says that the effects were observed on the profiled inputs only; further notes explain e.g. unattributed accesses, missing source-level facts or unprofiled calls

At most 100 entries are returned, ranked writes before reads; global, parameter, other; the function's own accesses before those of callees, shallower callees first; observed before static; then by name. A cut result has `truncated: true` and a `next_step` naming the filters. An ambiguous name returns `status: "ambiguous"` with the `candidates` (name, file, lines).

The tool reads `.discopop/explorer/side_effects.json.gz`, which `discopop_explorer` writes during `gather_data`; it never loads the PET. It refuses, with a `next_step` to run `gather_data` (again), when that file is missing, unreadable or of another format version, stale (`profiler/dynamic_dependencies.txt` changed since it was written), or written by an older explorer run with `--ignore-dependency-states`. The explorer writes no export when it runs with `--ignore-dependency-states` (and removes an earlier one), so the data is then reported as missing. Semantics and limits: `DESIGN_get_side_effects.md`.

### `explain_parallelization`

Explains why DiscoPoP did or did not suggest a parallelization for the code at given lines. Returns every code region pattern detection considered that overlaps them, innermost first, with its outcome:
- `accepted` — with the ids of the resulting suggestions (as strings, for `get_parallelization_patches`)
- `rejected` — with the reasons, e.g. the data dependency between iterations that prevents it (type, variable, source and sink lines, and whether profiling or the static analysis found it), or too few observed iterations
- `not_reported` — passed the checks, but its pattern type was not part of the result

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `file_path` (string, required): Absolute path to the source file
- `start_line` (integer, required): Line to explain, or the first line of a range
- `end_line` (integer, optional): Last line of the range (default: `start_line`)

It reads `.discopop/explorer/pattern_decisions.json`, which `discopop_explorer` writes next to `patterns.json` (`--pattern-decisions`). The file is format-versioned and not tied to a detector, so further pattern detectors can record their decisions in it; see `discopop_explorer/classes/patterns/PatternDecisions.py`.

### `get_hotspots`

Lists the code regions (loops and functions) where the program spends its time, from the hotspot detection that `gather_data(hotspot_config_names=[...])` runs. Each region has a hotness: `YES` — above-average runtime that also grows with the input more than average; `MAYBE` — only one of the two; `NO` — neither. Regions come hottest class first, then by their longest measured runtime, with one inclusive runtime per hotspot profiling run and demangled function names. A `warning` says when only one input size was profiled, since growth with the input cannot be judged then.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `hotness` (array of `YES`/`MAYBE`/`NO`, optional): Default `["YES", "MAYBE"]`
- `region_type` (`loop` or `function`, optional): Default both
- `file_path` (string, optional): Only regions in this source file
- `limit` (integer, optional): Default 20; `truncated: true` when more matched

### `get_project_status`

Answers in one cheap, read-only call where a project stands in the DiscoPoP workflow and which call comes next, so an agent starting or resuming work does not have to probe several tools.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root

**Returns** (fields that do not apply are left out):
- `initialized`, `compile_script_configured`, `configurations` (names of the runnable configurations)
- `pipeline`: one entry per step — `hotspot_detection`, `instrumentation`, `profiling`, `pattern_detection`, `patch_generation` — with the time it last ran (`at`) and `stale` when a source file is newer, the same test `gather_data` uses to decide what to re-run; `{"done": false}` for a step that has not run
- `suggestions` (number of suggestions the pattern detection produced; one suggestion can patch several files), `hotspot_results`, `applied_suggestions`
- `auto_tuning`: the last tuning run's `config`, whether it was `complete`, its selected `suggestion_ids`, `speedup` and `thread_count`, and `stale` when it predates the current pattern detection
- `note` when the sources were last changed by applying or rolling back suggestions: that marks the steps stale, but the analysis still describes the un-patched sources
- `next_step`: the setup step still missing, `gather_data` when there is no or only stale analysis, `run_auto_tuning` when suggestions exist but have not been tuned, `manage_patches` to apply a tuning selection, and so on

### `run_auto_tuning`

Runs the [empirical autotuner](../docs/tools/Autotuner.md) and returns the combination of suggestions it selected, so the choice of patches is measured rather than guessed. The tuner compiles, executes and validates candidate combinations in throwaway copies of the project and keeps the fastest one that still produces a valid result.

By default the tool leaves the sources as it found them and only reports the selection, which `manage_patches(action="apply", ...)` then persists. Pass `apply=true` to have the selected combination applied in the same call — the shortest route from profiling data to parallelized code.

Patches that are already applied are cleared before the search (the tuner has to measure an un-patched project) and restored afterwards, unless `apply=true` replaces them with the new selection. Nothing has to be cleared by hand.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `config_name` (string, required): Execution configuration to tune (a directory under `.discopop/project/configs/`)
- `apply` (boolean, optional): Apply the selected combination once the search is done, default `false`. The result then carries `applied` with the ids that reached the code; undo them with `manage_patches(action="rollback", ...)`. With `suggestion_ids`, the given selection is applied whenever its `outcome` is `valid`, even if it is slower than the un-patched project; an `invalid`, `failed` or `not_applied` one never is.
- `suggestion_ids` (array of strings or integers, optional): Measure exactly this selection instead of running a search (see below). The ids are the `pattern_id` values of `get_parallelization_patches`. Cannot be combined with `algorithm`.
- `algorithm` (string, optional): Search algorithm: `independent`, `linear`, `evolutionary`, `greedy`, `coordinate_descent` or `hotspot_guided`. Omit it and the tool picks `hotspot_guided` (hotspot-guided region descent) when hotspot detection results are available, and `greedy` (greedy forward search) otherwise; the choice and its reason come back as `algorithm` / `algorithm_selection`. Pass a value only to override that; an explicit `hotspot_guided` without hotspot results is refused rather than silently replaced. The names stand for the tuner's `-A` values 0, 1, 3, 4, 5 and 6, which are still accepted. See `docs/tools/Autotuner.md` for details.
- `timeout_seconds` (integer, optional): Wall clock bound for the whole search, default `3600`

**Preconditions:** `gather_data` must have been run. Running `gather_data` with `hotspot_config_names` set is what makes the hotspot-guided search available.

**Example:**
```json
{
  "project_path": "/abs/path/to/my_project",
  "config_name": "tiny",
  "timeout_seconds": 1800
}
```

**Example response:**
```json
{
  "status": "success",
  "algorithm": "hotspot_guided",
  "algorithm_selection": "hotspot-guided region descent, chosen because hotspot results are available",
  "suggestion_ids": ["7", "12"],
  "speedup": 2.31,
  "efficiency": 0.58,
  "runtime": 4.12,
  "baseline_runtime": 9.52,
  "evaluated_configurations": 14,
  "applied": false,
  "message": "Pass suggestion_ids to manage_patches(action='apply', suggestion_ids=[...]) to persist this selection, or call run_auto_tuning again with apply=true. ..."
}
```

This is a measurement run: one compilation plus one execution of the project per candidate. When `timeout_seconds` expires the search is stopped and the best combination measured so far is still returned, with `"status": "timeout"` and `"partial": true`.

#### Measuring a given selection

With `suggestion_ids`, no search runs: the tool measures the un-patched project and exactly the given selection (the tuner's `-s <ids> --skip-removal-pass`, which also skips the tuner's refinement of the selection), and reports that one measurement. Unknown ids, malformed ids and a combination with `algorithm` are rejected before anything is cleared, compiled or run. Applied patches are cleared and restored, project copies cleaned up and cancellation handled as for a search. The tuner's result files in `.discopop/auto_tuner/` and its statistics graph (`.discopop/dp_autotuner_statistics.dot/.svg`) are restored afterwards, so the result of the last search, which the GUI and `discopop_project_manager --apply-suggestions auto` apply and `get_project_status` reports, is not replaced by the measurement.

The result carries `"mode": "selection"` and, instead of the search's statistics:
- `outcome`: `valid` (built, ran and passed the validation), `invalid` (ran, but the result failed the validation, i.e. `validate.sh` or the exit code), `failed` (the build or execution failed, including an execution stopped after twice the un-patched project's wall clock time) or `not_applied` (a patch could not be applied, listed in `not_applied`; nothing was measured)
- `status`: `success` for a `valid` outcome, `rejected` otherwise
- `result_valid`: whether the output passed the validation; `null` when it was never checked
- `runtime` and `baseline_runtime` (seconds), `speedup` over the un-patched project and `efficiency` — `speedup` only for a `valid` outcome, since a program that crashes or computes the wrong result is fast for the wrong reason
- `return_code` of the selection's run, and a `diagnosis_hint` pointing to `get_execution_results` when it was rejected

```json
{
  "status": "success",
  "mode": "selection",
  "suggestion_ids": ["3", "5"],
  "outcome": "valid",
  "result_valid": true,
  "return_code": 0,
  "runtime": 4.0,
  "baseline_runtime": 10.0,
  "speedup": 2.5,
  "efficiency": 0.625,
  "thread_count": 4,
  "applied": false
}
```

A timeout before the selection's measurement is complete is an error; a timeout afterwards (while the tuner re-runs its best configuration) keeps the measurement.

## Logging Output

The server logs all incoming and outgoing communication:

```
2026-05-19 10:30:00 - discopop-mcp - INFO - Starting DiscoPoP MCP Server (stdio mode)
2026-05-19 10:30:05 - discopop-mcp - INFO - → Incoming call: get_configurations
2026-05-19 10:30:05 - discopop-mcp - DEBUG - Arguments: {"project_path": "./my_project"}
2026-05-19 10:30:05 - discopop-mcp - INFO - ← Outgoing response: get_configurations
```

Enable `--debug` for full argument/response logging.

## Testing

The unit tests are colocated with the source as `test_*.py` files. From the repository root:

```bash
venv/bin/python -m pytest mcp_server
```

## Guidelines for LLM Agents

> **LLM agents must not inspect `.discopop` directories directly** (e.g. via file reads, directory listings, or shell commands). All DiscoPoP data must be accessed exclusively through the `discopop_mcp_server` tool calls.

Reading raw files from `.discopop` is wasteful and unreliable: the directory contains large binary files, intermediate artefacts, and serialised objects that are expensive to parse and consume a significant number of tokens. The MCP tools return pre-processed, structured summaries that contain exactly the information needed — at a fraction of the token cost.

If a piece of information appears to be missing from the available tools, the correct response is to use the tool that produces it (e.g. run `gather_data` before calling `get_parallelization_patches` or `get_data_dependencies`) rather than reading the underlying files directly.

### The route to parallelized code

`gather_data` → `run_auto_tuning` → `manage_patches(action="apply", ...)`, or `gather_data` → `run_auto_tuning(apply=true)`.

**Do not decide which patches to apply by reading them.** Which combination is fastest is what `run_auto_tuning` measures; picking from the diffs by hand discards the one thing DiscoPoP can establish and a reader cannot, and a combination that looks sensible is regularly slower than the sequential program (fork/join overhead on short loops) or invalid. Read patches to *understand* a suggestion, not to choose between them — `get_parallelization_patches(detail="summary")` is enough for the former.

Run the tuner **before** applying anything. It needs an un-patched project, and while it clears and restores an existing selection on its own, a source file that was also edited by hand can no longer be un-patched automatically.

### The project is left buildable

`gather_data`'s instrumentation steps compile **in place** (`execute_inplace=True`, unlike the ProjectManager flow, which works in a sibling copy) — the profiling output has to land in this project's `.discopop`. A compile script that configures a build directory therefore leaves it pinned to `discopop_cc`/`discopop_cxx`, and an ordinary `make` in it afterwards yields an instrumented binary: orders of magnitude slower than the program, and prone to aborting outright with an allocation or heap error once the code is also multithreaded.

Nothing announces that state, so anyone who then builds and runs the program to check their own work measures DiscoPoP's instrumentation instead and reads the crash as a bug in their code. In one recorded benchmark run an agent lost six minutes to three such executions — each hitting its own shell timeout — and then discarded a working OpenMP parallelization because of them.

So `gather_data` rebuilds the project plainly (`par_settings.json`, falling back to `seq_settings.json`) before it returns, on **every** exit path including its own failures — a failed instrumentation is exactly when the build is left half-instrumented. The outcome is reported as `steps.build_restore`; it is best effort, and a failed rebuild is a warning rather than a failed pipeline, since the data the tool exists to produce is already on disk by then. A call that skipped every instrumentation step (results already current) rebuilds nothing: the build it finds is the one the previous call restored.

### Limiting the exposed tools

`--tools analysis` leaves out the project setup tools (`initialize_discopop_directory`, `set_compile_script`, `create_execution_configuration`, `delete_execution_configuration`), which are neither listed nor callable in that mode. Use it when pointing an agent at a project that is already configured: it removes their tool definitions from the agent's context, and rules out an `initialize_discopop_directory(reset=true)` that would delete the analysis results and the recorded runs of the project the agent was pointed at (its configurations are kept).

## Daemon Mode

By default, Claude Code starts a fresh `discopop_mcp_server` process for each session. Data loaded during the session (such as the `DetectionResult` produced by `gather_data`) is cached only for that session and discarded when it ends.

**Daemon mode** (`--daemon`) solves this by running a single long-lived server process that keeps its internal state alive across multiple tool calls and across multiple Claude sessions.

### How it works

When Claude Code runs `discopop_mcp_server` (the default, no flags), the process acts as a **proxy**. No daemon connection is attempted at startup — the check is deferred until the first actual tool call, so idle sessions consume no extra resources.

On the **first tool call**:

1. The proxy checks whether a daemon is already listening on `localhost:7777`.
2. If one is found, the proxy opens a **single persistent connection** to it and forwards all subsequent tool calls through that connection for the lifetime of the Claude session.
3. If none is found, or the connection fails, every tool call **runs inline** in the proxy process — the stateless behaviour — so the server is fully functional without a daemon.

The proxy never starts a daemon on its own.

### Running the daemon

Start the daemon in a terminal of your choice before starting the MCP client:

```bash
discopop_mcp_server --daemon
```

The terminal window stays open showing daemon logs. Press `Ctrl+C` to stop it.

Use `--daemon-port` to run on a non-default port (both the daemon and the proxy must use the same value):

```bash
# Terminal 1 — daemon
discopop_mcp_server --daemon --daemon-port 8888

# Claude Code config — proxy pointing at the same port
discopop_mcp_server --daemon-port 8888
```

### Comparison

|                          | `discopop_mcp_server` (default) | `discopop_mcp_server --daemon` |
|--------------------------|--------------------------------|-------------------------------|
| Who runs it              | Claude Code (automatic)        | You, manually                 |
| Lifetime                 | One Claude session             | Until `Ctrl+C`                |
| Daemon check timing      | First tool call                | N/A                           |
| State between tool calls | None                           | Kept alive in `ToolContext`   |
| `DetectionResult` cache  | Not applicable                 | Loaded once, reused across calls |
| Fallback if unavailable  | Inline execution               | N/A                           |

### What is cached

The daemon's `ToolContext` maintains three caches:

- **`DetectionResult`** — loaded from `.discopop/explorer/detection_result_dump.json` using `jsonpickle` on the first call that needs it (`get_data_dependencies`). Subsequent calls skip the deserialization step entirely.
- **`FileMapping`** — loaded from `.discopop/FileMapping.txt` on the first call to `get_data_dependencies`. Maps numeric file IDs to absolute source file paths.

- **Side effect index** — built from `.discopop/explorer/side_effects.json.gz` on the first call to `get_side_effects`, keyed by the file's modification time and size; the staleness test against `profiler/dynamic_dependencies.txt` runs on every call.

All caches are keyed by `project_path` and automatically invalidated when the underlying file's modification time changes (i.e., after `gather_data` runs again).

## Architecture

### Transport

The default (`discopop_mcp_server`) uses **stdio** for communication with Claude Code. The daemon (`--daemon`) uses **SSE over HTTP** (Starlette + uvicorn on `localhost:7777`). The proxy bridges between the two: it presents a stdio interface to Claude Code and forwards calls to the daemon over SSE.

### Tool Handler Flow

1. Claude calls a tool via stdio
2. Proxy checks whether a daemon session is open
   - If yes: forwards the call to the daemon over SSE
   - If no: executes the tool inline
3. The tool handler runs in a worker thread, so the server stays responsive while a long tool (`gather_data`, `run_auto_tuning`) runs. Tool calls still run one at a time: handlers change the working directory and share their caches
4. If the client sent a `progressToken`, the server sends MCP progress notifications: one per pipeline step of `gather_data`, the number of measured candidates for `run_auto_tuning`, and a heartbeat every 15 seconds during long steps. Through the daemon, the proxy relays them
5. If the client cancels a call (`notifications/cancelled`), the processes the tool started — compile and execute scripts, `discopop_explorer`, the autotuner — are stopped with their children, and the tool cleans up as after a timeout: `gather_data` still rebuilds the project without instrumentation, `run_auto_tuning` removes its project copies and restores the patches it cleared. The next call starts once that cleanup is done
6. Server logs the incoming call and outgoing response
7. Response returned to Claude

## Shipping to Users

### Method 1: PyPI Package (Recommended)

1. Update version in `pyproject.toml`
2. Build: `python -m build`
3. Publish: `python -m twine upload dist/*`
4. Users install: `pip install discopop_mcp_server`

### Method 2: Source Distribution

Include in your DiscoPoP repository:
```bash
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

### Method 3: Bundled Binary

Use PyInstaller to create standalone executables:
```bash
pip install pyinstaller
pyinstaller --onefile mcp_server/server.py --name discopop_mcp_server
```

## Development

### Adding New Tools

1. Define tool schema in `_register_tools()`:
```python
Tool(
    name="your_tool",
    description="...",
    inputSchema={...}
)
```

2. Add handler method:
```python
def _handle_your_tool(self, arguments: dict[str, Any]) -> list[TextContent]:
    self._log_call("your_tool", arguments)
    # Implementation here
    self._log_response("your_tool", result)
    return [TextContent(type="text", text=json.dumps(result))]
```

3. Register in tool call handler:
```python
elif name == "your_tool":
    return self._handle_your_tool(arguments)
```

### Type Checking

```bash
mypy mcp_server/server.py
```

## Troubleshooting

### Claude setup issues
- Automatically configure Claude Code:
  ```bash
  discopop_mcp_server --setup claude_code
  ```
- Verify the setup with:
  ```bash
  discopop_mcp_server --verify claude_code
  ```
- See [CLAUDE_INTEGRATION.md](CLAUDE_INTEGRATION.md) for detailed troubleshooting

### Server won't start
- Check Python version (requires 3.10+)
- Verify MCP package is installed: `pip show mcp`
- Run with `--debug` for detailed error messages

### Claude can't connect
- Verify server is running: `discopop_mcp_server --debug`
- Check claude configuration points to correct command
- Ensure stdio mode is being used (default)
- Check setup status:
  ```bash
  discopop_mcp_server --status
  ```

### Missing dependencies
```bash
# Install all dependencies
pip install -e ".[dev,sse]"
```

## License

This software is part of DiscoPoP and is licensed under the 3-Clause BSD License. See the LICENSE file in the package base directory for details.

## Support

For issues, questions, or contributions:
- Email: discopop@lists.parallel.informatik.tu-darmstadt.de
- Website: https://www.discopop.tu-darmstadt.de/
- Repository: https://github.com/tuda-hpclab/discopop
