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
- Retrieve profiling information from executed instrumented code
- List and discover available profiling data and execution configurations

## Features

- **Standalone CLI executable** - Run independently via command line
- **Local deployment** - Uses stdio for direct Claude integration
- **Persistent daemon mode** - Optional long-running server that keeps analysis data in memory between calls
- **Automatic daemon launch** - Spawns a daemon terminal on the first tool call when none is running
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

### 1. `set_compile_script`

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

### 2. `create_execution_configuration`

Creates a named execution configuration — a subdirectory under `.discopop/project/configs/` describing how to run the compiled binary.

**Parameters:**
- `project_path` (string, required): Path to the target project
- `config_name` (string, required): Name of the configuration; also the subdirectory name
- `script_body` (string, required): Body of `execute.sh`, the timed run
- `compile_script_body` (string, optional): Body of a per-configuration `compile.sh` override
- `validate_script_body` (string, optional): Body of `validate.sh`, an untimed output check run after a successful `execute.sh`; the run counts as correct only if both exit `0`
- `validation_compile_script_body` (string, optional): Body of a per-configuration `compile_validate.sh`; requires a `validate.sh`, and is rejected without one

**Example:**
```json
{
  "project_path": "/home/user/my_project",
  "config_name": "small_input",
  "script_body": "./myapp --input data/small.txt > out.txt\n",
  "validate_script_body": "diff out.txt reference.txt\n"
}
```

### 3. `get_configurations`

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

### 4. `get_execution_results`

Retrieves execution results from prior program executions.

**Parameters:**
- `project_path` (string, required): Path to the target project

Reads `<project_path>/.discopop/project/execution_results.json`.

**Example:**
```json
{
  "project_path": "./my_project"
}
```

### 5. `get_data_dependencies`

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
- `include_raw` / `include_war` / `include_waw` (boolean, optional): Filter by dependency type (default: all true)
- `include_incoming` / `include_outgoing` / `include_intra_region` (boolean, optional): Filter by direction (default: all true)
- `var_name` (string, optional): Restrict results to a specific variable; automatically excludes incoming dependencies (aliasing safety)

This tool is cheap to call repeatedly — `DetectionResult` and `FileMapping` are cached in memory after the first load. Requires `gather_data` to have been run first.

### 6. `run_auto_tuning`

Runs the [empirical autotuner](../docs/tools/Autotuner.md) and returns the combination of suggestions it selected, so the choice of patches is measured rather than guessed. The tuner compiles, executes and validates candidate combinations in throwaway copies of the project and keeps the fastest one that still produces a valid result.

By default the tool leaves the sources as it found them and only reports the selection, which `manage_patches(action="apply", ...)` then persists. Pass `apply=true` to have the selected combination applied in the same call — the shortest route from profiling data to parallelized code.

Patches that are already applied are cleared before the search (the tuner has to measure an un-patched project) and restored afterwards, unless `apply=true` replaces them with the new selection. Nothing has to be cleared by hand.

**Parameters:**
- `project_path` (string, required): Absolute path to the project root
- `config_name` (string, required): Execution configuration to tune (a directory under `.discopop/project/configs/`)
- `apply` (boolean, optional): Apply the selected combination once the search is done, default `false`. The result then carries `applied` with the ids that reached the code; undo them with `manage_patches(action="rollback", ...)`.
- `algorithm` (integer, optional): Search algorithm. Omit it and the tool picks `6` (hotspot-guided region descent) when hotspot detection results are available, and `4` (greedy forward search) otherwise; the choice and its reason come back as `algorithm` / `algorithm_selection`. Pass a value only to override that; an explicit `6` without hotspot results is refused rather than silently replaced. See `docs/tools/Autotuner.md` for the full list.
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
  "algorithm": 6,
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

Run the test suite:

```bash
python -m unittest discover -s mcp_server -p "test_*.py" -v
```

Or with pytest:

```bash
pytest mcp_server/test_server.py -v
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

`--tools analysis` leaves out the three project setup tools (`initialize_discopop_directory`, `set_compile_script`, `create_execution_configuration`), which are neither listed nor callable in that mode. Use it when pointing an agent at a project that is already configured: it removes roughly a third of the tool definitions from the agent's context, and rules out an `initialize_discopop_directory(reset=true)` that would delete the configurations the agent was pointed at.

## Daemon Mode

By default, Claude Code spawns a fresh `discopop_mcp_server` process for each session. This is stateless — every tool call starts from scratch and any data loaded during the session (such as the `DetectionResult` produced by `run_pattern_detection`) is discarded when the session ends.

**Daemon mode** (`--daemon`) solves this by running a single long-lived server process that keeps its internal state alive across multiple tool calls and across multiple Claude sessions.

### How it works

When Claude Code runs `discopop_mcp_server` (the default, no flags), the process acts as a **proxy**. No daemon connection is attempted at startup — the check is deferred until the first actual tool call, so idle sessions consume no extra resources.

On the **first tool call**:

1. The proxy checks whether a daemon is already listening on `localhost:7777`.
2. If no daemon is found, it attempts to **automatically spawn one** in a new terminal window using the first available terminal emulator (`gnome-terminal`, `xterm`, `konsole`, `alacritty`, `kitty`, and others).
3. Once a daemon is reachable, the proxy opens a **single persistent connection** to it and forwards all subsequent tool calls through that connection for the lifetime of the Claude session.
4. If the daemon cannot be reached (no graphical display, spawn timeout, or connection error), every tool call **falls back to inline execution** — the old stateless behaviour — so the server remains fully functional without a daemon.

### Running the daemon manually

You can start the daemon yourself instead of relying on auto-spawn:

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
| Who runs it              | Claude Code (automatic)        | You, manually (or auto-spawned on first tool call) |
| Lifetime                 | One Claude session             | Until `Ctrl+C`                |
| Daemon check timing      | First tool call                | N/A                           |
| State between tool calls | None                           | Kept alive in `ToolContext`   |
| `DetectionResult` cache  | Not applicable                 | Loaded once, reused across calls |
| Fallback if unavailable  | Inline execution               | N/A                           |

### What is cached

The daemon's `ToolContext` maintains two caches:

- **`DetectionResult`** — loaded from `.discopop/explorer/detection_result_dump.json` using `jsonpickle` on the first call that needs it (e.g. `get_data_dependencies`, `get_parallelization_patches`). Subsequent calls skip the deserialization step entirely.
- **`FileMapping`** — loaded from `.discopop/FileMapping.txt` on the first call to `get_data_dependencies`. Maps numeric file IDs to absolute source file paths.

Both caches are keyed by `project_path` and automatically invalidated when the underlying file's modification time changes (i.e., after `gather_data` runs again).

## Architecture

### Transport

The default (`discopop_mcp_server`) uses **stdio** for communication with Claude Code. The daemon (`--daemon`) uses **SSE over HTTP** (Starlette + uvicorn on `localhost:7777`). The proxy bridges between the two: it presents a stdio interface to Claude Code and forwards calls to the daemon over SSE.

### Tool Handler Flow

1. Claude calls a tool via stdio
2. Proxy checks whether a daemon session is open
   - If yes: forwards the call to the daemon over SSE
   - If no: executes the tool inline
3. Server logs the incoming call and outgoing response
4. Response returned to Claude

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
- Check Python version (requires 3.8+)
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
