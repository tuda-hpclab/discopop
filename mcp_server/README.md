<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# DiscoPoP MCP Server

A Model Context Protocol (MCP) server that exposes DiscoPoP functionality to MCP clients such as Claude Code and OpenCode, enabling an LLM agent to drive the full instrumentation pipeline and query the results of the analysis.

## Overview

The DiscoPoP MCP Server bridges the gap between an LLM agent and DiscoPoP's profiling and analysis tools. It allows the agent to:

- Instrument a project, run profiling, detect parallel patterns, and list the suggestions (OpenMP pragmas), ranked by the hotspots
- Show where the program spends its time, and why a region was or was not suggested for parallelization
- Report the data a function and its callees were observed to read and write outside of it (side effects), to support code understanding, refactoring, and correctness checks
- List and discover available execution configurations

DiscoPoP only analyses: the agent edits the source code itself.

## Features

- **Standalone CLI executable** - Run independently via command line
- **Local deployment** - Uses stdio for direct integration with MCP clients (Claude Code, OpenCode, ...)
- **Persistent daemon mode** - Optional long-running server that keeps analysis data in memory between calls
- **Opt-in daemon** - Start `discopop_mcp_server --daemon` yourself; the server connects to it on the first tool call
- **Transparent fallback** - Falls back to inline execution when no daemon is available
- **Comprehensive logging** - View all incoming calls and outgoing responses
- **Type-safe** - Full type hints throughout
- **Extensible** - Easy to add new tools and capabilities

## Prerequisites

- Python 3.11 or newer.
- DiscoPoP installed in the **same environment** as the server. The tools call `discopop_cxx`, `discopop_explorer` and `discopop_auto_tuner`, which come with the other DiscoPoP packages; see the [installation page](https://tuda-hpclab.github.io/discopop/setup/discopop/).
- A build script that uses `$CC`/`$CXX` and `$CFLAGS`/`$CXXFLAGS`, and a small but representative program input.

## Installation

The server is part of `pip install discopop`. From a checkout, install it together with the other packages (all paths in one command, profiler and hotspot detection not editable):

```bash
python3 -m venv venv
venv/bin/python -m pip install . ./profiler ./explorer ./library ./GUI ./hotspot_detection ./mcp_server
```

Check the command:

```bash
discopop_mcp_server --help
```

From a checkout, `python -m mcp_server.server` (started in the repository root) runs the server code of the checkout. `python mcp_server/server.py` also works when the package is installed. The optional `dev` extra (`pip install "./mcp_server[dev]"`) adds the test dependencies.

## Register the server with an agent

```bash
discopop_mcp_server --setup claude_code   # Claude Code: writes ~/.claude.json
discopop_mcp_server --setup opencode      # OpenCode: writes ~/.config/opencode/opencode.jsonc
discopop_mcp_server --setup-all           # every supported agent that is installed
discopop_mcp_server --verify claude_code  # check the entry of an agent
discopop_mcp_server --status              # show the setup status of all agents
```

- If a virtual environment is active, the entry points to the `discopop_mcp_server` of that environment.
- `--full-path` writes the full path of the executable found in `PATH` instead of the bare command name.
- `--debug` adds `--debug` to the entry, `-v/--verbose` prints details during the setup.
- Restart the agent afterwards.

Manual entry for Claude Code in `~/.claude.json` (or `claude mcp add discopop_mcp_server -- discopop_mcp_server`):

```json
{
  "mcpServers": {
    "discopop_mcp_server": { "command": "/path/to/venv/bin/discopop_mcp_server" }
  }
}
```

Entry for OpenCode in `~/.config/opencode/opencode.jsonc`:

```json
{
  "mcp": {
    "discopop_mcp_server": { "type": "local", "command": ["/path/to/venv/bin/discopop_mcp_server"] }
  }
}
```

Other MCP clients that start servers over stdio need an equivalent entry (not tested).

## Usage

```bash
# Default mode: stdio server, a proxy that routes to a daemon if one is available, otherwise runs inline
discopop_mcp_server

# With debug logging
discopop_mcp_server --debug

# Persistent daemon (default port 7777)
discopop_mcp_server --daemon --daemon-port 8888
```

Once registered, ask the agent, for example: "Profile this project and parallelize the hot loops", "Why was the loop in lines 40-80 of src/compute.cpp not parallelized?" or "Which data does `scale` read and write?".

## Available Tools

The server offers 12 tools. In workflow order: `initialize_discopop_directory`, `set_compile_script`, `create_execution_configuration` (once per project; `delete_execution_configuration` and `get_configurations` manage them), `get_project_status`, `gather_data`, `get_hotspots`, `get_parallelization_suggestions`, `explain_parallelization`, `get_side_effects` and `run_configuration`. The setup tools are hidden by `--tools analysis`.

DiscoPoP only reads the sources: it never modifies them. The agent applies the suggestions itself, by editing the code.

The tools that answer questions about the analysis return a short **text**, not a data structure: one line per hotspot, suggestion or effect, most significant first. Where a list is cut, its last line says how much was left out, and a `limit` parameter lists more. Paths are shown relative to the project. The setup, configuration and pipeline tools return JSON. A successful result holds just the facts of the call plus, where there is a sensible follow-up, a `next_step` hint; it carries neither a `status` nor the `project_path` the caller sent. Errors are returned as `{"status": "error", "message": ..., "next_step": ...}`, and the server marks them as errors (`isError`); `status` appears nowhere else at the top level (the entries of `gather_data`'s `steps` carry their own `status`).

### `initialize_discopop_directory`

Sets up `.discopop/project/configs/` with `seq_settings.json`, `dp_settings.json`, `hd_settings.json`, `par_settings.json` and a placeholder `compile.sh`. The first call for every project. An initialized project is left unchanged.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `reset` (boolean, optional): Delete all analysis artefacts under `.discopop/` (profiler output, explorer results, patches, hotspot data, execution results) and keep `.discopop/project/`. Default `false`
- `base_cc`, `base_cxx` (string, optional): Compilers of the plain builds. Defaults `clang`, `clang++`
- `cflags`, `cxxflags` (string, optional): Initial flags shared by all build modes

### `delete_execution_configuration`

Deletes a named configuration (its directory under `.discopop/project/configs/` with `execute.sh`, `validate.sh` and per-configuration compile scripts). Analysis results gathered with it and its recorded runs are kept. Cannot be undone.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `config_name` (string, required): Name of the configuration

### `set_compile_script`

Writes a build script for a project. Must use `$CC` / `$CXX` and `$CFLAGS` / `$CXXFLAGS` instead of hard-coded compiler names, since the same script is reused for sequential, instrumented, hotspot-detection and parallel builds — only the settings file differs.

**Parameters:**
- `project_path` (string, required): Path to the target project
- `script_body` (string, required): Bash script body; a `#!/bin/bash` shebang is prepended if absent
- `config_name` (string, optional): Write a per-configuration override instead of the shared script
- `purpose` (string, optional): `execute` (default) writes `compile.sh`; `validate` writes `compile_validate.sh`, a separate build for `validate.sh`

A `compile_validate.sh` is only relevant when the configuration also has a `validate.sh`; the response reports which configurations it is `used_by` and which it is `ignored_for`. See the [project manager documentation](https://tuda-hpclab.github.io/discopop/tools/Project_manager/) for the full resolution order.

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

### `get_project_status`

Answers in one cheap, read-only call where a project stands in the DiscoPoP workflow and which call comes next, so an agent starting or resuming work does not have to probe several tools.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root

**Returns** (fields that do not apply are left out):
- `initialized`, `compile_script_configured`, `configurations` (names of the runnable configurations)
- `pipeline`: one entry per step — `hotspot_detection`, `instrumentation`, `profiling`, `pattern_detection`, `patch_generation` — with the time it last ran (`at`) and `stale` when a source file is newer, the same test `gather_data` uses to decide what to re-run; `{"done": false}` for a step that has not run. Generated sources of a build (CMake build trees, `.git`) are not sources
- `suggestions`: the number of suggestions the pattern detection produced
- `next_step`: the setup step still missing, `gather_data` when there is no or only stale analysis, `get_parallelization_suggestions` when suggestions exist, and so on

### `gather_data`

Runs the complete data collection pipeline and detects patterns: hotspot detection (compile with hotspot instrumentation, run once per configuration in `hotspot_config_names`, classify regions as YES/MAYBE/NO), then instrumentation, profiling with `config_name`, and `discopop_explorer`. The suggestions are ranked by the hotspots, so a failing hotspot step fails the call and stops the pipeline; the error names the step (`steps.hotspot_instrumentation`, `steps.hotspot_profiling` or `steps.hotspot_analysis`) and carries the end of its error output. A step is skipped when its outputs are newer than the sources. A step that succeeded lists the warnings of its build or run under `warnings` (at most 5, then the number of the rest); a step that failed carries the end of its error output under `stderr`. Afterwards the project is rebuilt without instrumentation (see below).

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `config_name` (string, required): Execution configuration used for compilation and profiling
- `hotspot_config_names` (array of strings, optional): Configurations for the hotspot profiling runs; two with different input sizes classify best, since growth with the input can only be judged then. Default: `[config_name]`, a single run
- `timeout_seconds` (integer, optional): Timeout of each step. Default `3600`
- `force` (boolean, optional): Re-run all steps. Default `false`

### `get_hotspots`

Lists the loops and functions where the program spends its time, as measured by the hotspot detection of `gather_data`, longest running first. A *Hotspot* has an above-average runtime that also grows with the input more than average; a *Potential Hotspot* only one of the two. Each line gives the longest measured runtime (inclusive of what the region calls) and its share of the program's. `main` is left out, as it always takes all of the runtime.

```
5 hotspots and 2 potential hotspots, longest running first:
Hotspot Function md.cpp:261 compute (4.05 s, 100% of runtime)
Hotspot Loop md.cpp:275 (4.05 s, 100% of runtime)
...
3 hotspots and 2 potential hotspots not shown (limit=2); pass a larger limit to see them.
```

With a single profiled input size, growth with the input cannot be judged and the classification reflects the runtime alone; the answer says so.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `limit` (integer, optional): Maximum number of hotspots to list. Default `10`

### `get_parallelization_suggestions`

Lists the suggestions of `gather_data`, hottest first: the code region (its kind, file and lines), its measured runtime and share of the program's (`Hotspot`, `Potential Hotspot`, or neither), the pattern type, and the change to make, e.g. the OpenMP pragma with its data-sharing clauses to put directly above the region. Suggestions on the same code are marked as nested in, or an alternative to, each other.

```
13 parallelization suggestions, hottest first:
Suggestion 5: Hotspot Loop md.cpp:275-317 (4.05 s, 100% of runtime): reduction, #pragma omp parallel for firstprivate(PI2,nd,np,rij) private(d,d2,i,j) shared(f,pos,vel) reduction(+:ke,pe)
Suggestion 7: Potential Hotspot Loop md.cpp:304-307 (0.96 s, 24% of runtime): doall, #pragma omp parallel for firstprivate(d,d2,f,k,nd,rij); nested in suggestion 5
...
3 more suggestions not shown (limit=10); pass a larger limit or file_path to see them.
```

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `file_path` (string, optional): Only list suggestions for this source file (absolute, or relative to the project)
- `limit` (integer, optional): Maximum number of suggestions to list. Default `10`

### `explain_parallelization`

Explains why DiscoPoP did or did not suggest a parallelization for the code at the given lines: one paragraph per code region that pattern detection considered and that overlaps them, innermost first, with either the suggestion for it or the reasons it was rejected. A dependency is worded as `RAW dependency to md.cpp:306 via elements of variable f from md.cpp:306 prevents parallelization (observed during profiling).`, from the first location to the second, between iterations. Lines no region covers were not considered at all, e.g. because they were never executed during profiling, and the answer says so.

```
md.cpp:305 lies in 3 code regions, innermost first:
Loop md.cpp:304-307: suggestion 7 (doall).
Loop md.cpp:285-309: not parallelizable.
- RAW dependency to md.cpp:306 via elements of variable f from md.cpp:306 prevents parallelization (observed during profiling).
Loop md.cpp:275-317: suggestion 5 (reduction).
```

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `file_path` (string, required): The source file (absolute, or relative to the project)
- `start_line` (integer, required): The line to explain, or the first line of a range
- `end_line` (integer, optional): The last line of the range. Default `start_line`

At most 5 regions and 5 reasons per region are explained; the text says how many were left out.

### `get_side_effects`

Describes the data a C/C++ function was observed to read and write outside of itself during profiling, including through the functions it calls: globals (also static locals and static members), memory reached through its pointer, reference, array or class-type parameters, and other memory that outlives the call. Use it to judge whether a call is pure, safe to run concurrently, to reorder or to memoize, e.g. during a review or a refactoring. The answer holds for the profiled inputs only.

```
dist(int, double*, double*, double*) (md.cpp:328-371)
Not pure: it writes dr.
Writes:
- dr (parameter, through pointer), also called rij: line 366
Reads:
- dr (parameter, through pointer): line 367
- r1 (parameter, through pointer), also called pos: line 366
Valid for the profiled inputs only.
```

The first line names the function and where it is defined, the second says whether it is pure on the profiled inputs (it writes nothing and reads only its own parameters or constants), not pure (and why), or undecided. Then the writes and reads, most significant first (writes before reads; globals, parameters, other memory; its own accesses before those of callees), each with the lines of the accesses and, for an access in a called function, the call chain (`via a > b`). A name is the one at the access; the caller's name for the same data follows as `also called`, with its file (`pos (in util.h)`) when that differs from the function's. Data the code names but profiling did not observe is marked `referenced in the code, not observed`. `Caveat` lines say what profiling cannot see: a function that was never executed, calls that could not be followed (recursion, function pointers, deep call chains), or library code. Absent effects are then unknown, not absent.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `function` (string, required): Function name, with or without signature (`scale`, `scale(double*, int)`, `ns::Cls::scale`), or its mangled name
- `file_path` (string, optional), `line` (integer, optional): The definition, to disambiguate. An ambiguous name is answered with the list of candidates
- `limit` (integer, optional): Maximum number of effects to list. Default `20`

### `run_configuration`

Builds the project as it is now, without instrumentation, and runs an execution configuration: to check that the changes of the agent compile and give the same result, and to measure how long the program takes, e.g. with different thread counts. It uses the project's compile script with `par_settings.json` (`seq_settings.json` as the fallback) and the configuration's `execute.sh`, with `OMP_NUM_THREADS` set to `threads`. The sources are never modified. The runs are recorded in `.discopop/project/execution_results.json`, like those of the project manager and the GUI.

The answer is a text: whether the build and the run succeeded, the time (the median of `repetitions`; the program's own timing output when the configuration extracts one), the result of the configuration's `validate.sh` if it has one (built with its `compile_validate.sh` if that exists), the errors and warnings of the build and of the run, and the end of the program's output. Without a `validate.sh` only the exit code is checked, and the answer says so.

```
Configuration 'medium' with 4 threads: built and ran successfully in 0.99 s (median of 3 runs).
There is no validate.sh, so the output was not checked; only the exit code.
Build warnings (2):
- md.cpp:12:5: warning: unused variable 'x' [-Wunused-variable]
- md.cpp:40:9: warning: ignoring #pragma omp parallel [-Wunknown-pragmas]
Output (the end):
    Elapsed cpu time for main computation:
    ...
```

A failed build lists its errors and does not run the program. A failed run gives the exit code, the errors and what the program wrote to stderr; a timeout is reported as one. Warnings are the lines containing `warning:` (or the OpenMP runtime's `Warning #n:`), at most 5 each, with the number of the rest.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `config_name` (string, required): The execution configuration to run
- `threads` (integer, optional): Number of OpenMP threads. Default: the number of CPUs
- `repetitions` (integer, optional): How often to run it; the median time is reported. Default `1`
- `rebuild` (boolean, optional): Build before running; `false` runs the last build again, e.g. for another thread count. Default `true`
- `timeout_seconds` (integer, optional): Maximum time of the build and of each run. Default `3600`

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

If a piece of information appears to be missing from the available tools, the correct response is to use the tool that produces it (e.g. run `gather_data` before calling `get_parallelization_suggestions` or `get_side_effects`) rather than reading the underlying files directly.

### The route to parallelized code

`run_configuration` (the time of the unmodified program) → `gather_data` → `get_hotspots` / `get_parallelization_suggestions` → edit the source yourself → `run_configuration` again (does it build, give the same results, and run faster?).

DiscoPoP never modifies the sources: the agent applies a suggestion by making the change it shows (for an OpenMP pragma: adding it directly above the code region it names). The suggestions rest on the profiled inputs, so the changed program has to be checked with `run_configuration`: its output compared to the sequential one (a `validate.sh` does this automatically) and its runtime measured, with the thread counts that matter. A combination of suggestions that looks sensible is regularly slower than the sequential program (fork/join overhead on short loops), so parallelize the hotspots first, and measure. `explain_parallelization` tells why a region has no suggestion, e.g. which dependency between iterations prevents it, and whether a restructuring of the code could remove it.

After changing the sources, call `gather_data` again: `get_project_status` marks the analysis as stale, as it no longer describes the code.

### Prepared results

The query tools (`get_hotspots`, `get_parallelization_suggestions`, `explain_parallelization`, `get_side_effects`) only read the results in `.discopop`; none of them starts a profiling run, so they are cheap. Results produced beforehand, by a person running `gather_data`, or `discopop_cxx`, the profiled run and `discopop_explorer` by hand (or by an earlier session), are used as they are: an agent starts with `get_project_status`, finds current results and queries them without any wait. This works without `initialize_discopop_directory` and the configuration tools; `--tools analysis` then offers just the analysis tools. A repeated `gather_data` call is cheap as well: it skips every step whose outputs are current.

The results count as current while no source file is newer than them (modification time). After editing, copying or checking out the sources again, `get_project_status` reports them as stale and `gather_data` re-runs the affected steps. The results hold for the inputs that were profiled.

### The project is left buildable

`gather_data`'s instrumentation steps compile **in place** (`execute_inplace=True`, unlike the ProjectManager flow, which works in a sibling copy) — the profiling output has to land in this project's `.discopop`. A compile script that configures a build directory therefore leaves it pinned to `discopop_cc`/`discopop_cxx`, and an ordinary `make` in it afterwards yields an instrumented binary: orders of magnitude slower than the program, and prone to aborting outright with an allocation or heap error once the code is also multithreaded.

Nothing announces that state, so anyone who then builds and runs the program to check their own work measures DiscoPoP's instrumentation instead and reads the crash as a bug in their code. In one recorded benchmark run an agent lost six minutes to three such executions — each hitting its own shell timeout — and then discarded a working OpenMP parallelization because of them.

So `gather_data` rebuilds the project plainly (`par_settings.json`, falling back to `seq_settings.json`) before it returns, on **every** exit path including its own failures — a failed instrumentation is exactly when the build is left half-instrumented. The outcome is reported as `steps.build_restore`; it is best effort, and a failed rebuild is a warning rather than a failed pipeline, since the data the tool exists to produce is already on disk by then. A call that skipped every instrumentation step (results already current) rebuilds nothing: the build it finds is the one the previous call restored.

### Limiting the exposed tools

`--tools analysis` leaves out the project setup tools (`initialize_discopop_directory`, `set_compile_script`, `create_execution_configuration`, `delete_execution_configuration`), which are neither listed nor callable in that mode. Use it when pointing an agent at a project that is already configured: it removes their tool definitions from the agent's context, and rules out an `initialize_discopop_directory(reset=true)` that would delete the analysis results and the recorded runs of the project the agent was pointed at (its configurations are kept).

## Daemon Mode

By default, the agent starts a fresh `discopop_mcp_server` process for each session. Data loaded during the session (such as the `DetectionResult` produced by `gather_data`) is cached only for that session and discarded when it ends.

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
| Who runs it              | The agent (automatic)          | You, manually                 |
| Lifetime                 | One Claude session             | Until `Ctrl+C`                |
| Daemon check timing      | First tool call                | N/A                           |
| State between tool calls | None                           | Kept alive in `ToolContext`   |
| Side effect index cache  | Not applicable                 | Loaded once, reused across calls |
| Fallback if unavailable  | Inline execution               | N/A                           |

### What is cached

The daemon's `ToolContext` maintains two caches:

- **`FileMapping`** — loaded from `.discopop/FileMapping.txt` on the first call that needs it. Maps numeric file IDs to absolute source file paths.

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
3. The tool handler runs in a worker thread, so the server stays responsive while a long tool (`gather_data`) runs. Tool calls still run one at a time: handlers change the working directory and share their caches
4. If the client sent a `progressToken`, the server sends MCP progress notifications: one per pipeline step of `gather_data`, and a heartbeat every 15 seconds during long steps. Through the daemon, the proxy relays them
5. If the client cancels a call (`notifications/cancelled`), the processes the tool started — compile and execute scripts, `discopop_explorer` — are stopped with their children, and the tool cleans up as after a timeout: `gather_data` still rebuilds the project without instrumentation. The next call starts once that cleanup is done
6. Server logs the incoming call and outgoing response
7. Response returned to Claude

## Development

### Adding New Tools

Every tool is a module in `mcp_server/tools/` that defines a `TOOL` (name, description, input schema) and a `handle(arguments, ctx)` function; look at an existing module such as `get_hotspots.py`.

1. Create `mcp_server/tools/your_tool.py` and a colocated `test_your_tool.py`.
2. Import the module in `mcp_server/server.py` and add it to `_ALL_TOOLS`. Tools that define a project belong into `_SETUP_TOOLS` as well; `TOOL_SETS` builds the `--tools` sets from these lists.
3. Describe it in this file and in `docs/tools/MCP_server.md`.

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
- Check that `discopop_mcp_server` is on the `PATH` of the agent, or re-run the setup with `--full-path`
- Restart the agent after changing its configuration; run `discopop_mcp_server --debug` to see start-up errors

### Server won't start
- Check Python version (requires 3.11+)
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
# Reinstall the server with its dependencies (mcp, termcolor, uvicorn, starlette, discopop-library,
# discopop-explorer); from a checkout, pass all packages in one command, as the server requires the library and
# explorer versions of the checkout
venv/bin/python -m pip install . ./profiler ./explorer ./library ./GUI ./hotspot_detection ./mcp_server
```

## License

This software is part of DiscoPoP and is licensed under the 3-Clause BSD License. See the LICENSE file in the package base directory for details.

## Distribution

Maintainer notes on building and publishing the package are in [DISTRIBUTION.md](DISTRIBUTION.md).

## Support

For issues, questions, or contributions:
- Email: discopop@lists.parallel.informatik.tu-darmstadt.de
- Website: https://www.discopop.tu-darmstadt.de/
- Repository: https://github.com/tuda-hpclab/discopop
