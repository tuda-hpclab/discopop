---
layout: default
title: MCP server
parent: Tools
nav_order: 10
---

# MCP server
## Executable
`discopop_mcp_server`

## Purpose
The DiscoPoP MCP server lets an LLM agent (for example Claude Code or OpenCode) drive DiscoPoP through the [Model Context Protocol](https://modelcontextprotocol.io/). The agent can configure a project, profile it, ask where the program spends its time, get ranked parallelization suggestions, learn why a loop was not parallelized and which data a function reads and writes, without reading the large `.discopop` artefacts itself. DiscoPoP only analyses: the agent applies the suggestions by editing the source code. Every answer is based on data dependences measured in an actual execution, so it is reliable and captures aliasing that reading the code misses; judging dependences from the source alone is error-prone, which makes the wait for the profiling run worthwhile.

Use it when you want an agent to parallelize C/C++ code, to check whether code can safely run in parallel, or to find out which data a function or code region reads and writes (for example to check that a refactoring preserves the data flow).

It is not suitable when the project cannot be built and run locally, for other languages than C/C++, or for GPU or distributed-memory parallelism. Profiling an instrumented build takes minutes for small programs and longer for large ones.

## Prerequisites
- DiscoPoP installed in the same Python environment as the server (see [Installation](../setup/discopop.md)). The tools call `discopop_cxx` and `discopop_explorer`.
- A build script that uses `$CC`/`$CXX` and `$CFLAGS`/`$CXXFLAGS` instead of fixed compiler names. The same script is used for plain, instrumented and parallel builds.
- A small but representative program input, because instrumented runs are slow.

## Prepared results
The query tools (`get_hotspots`, `get_parallelization_suggestions`, `explain_parallelization`, `get_side_effects`) only read the results in `.discopop`, so they are cheap: the profiling run is the only expensive step. You can run it beforehand, with `gather_data` or by hand (`discopop_cxx`, the profiled run, `discopop_explorer`), and the agent then starts with `get_project_status`, finds the results and queries them without any wait. This needs no `initialize_discopop_directory` and no configuration; start the server with `--tools analysis` to offer just the analysis tools. A repeated `gather_data` call is cheap too, as it skips every step whose outputs are current.

Results are current while no source file is newer than them (modification time); otherwise `get_project_status` reports them as stale. They hold for the inputs that were profiled.

## Installation
The server is part of `pip install discopop`. Activate the environment and check the command:
```bash
discopop_mcp_server --help
```

## Register the server with an agent
```bash
discopop_mcp_server --setup claude_code   # writes ~/.claude.json
discopop_mcp_server --setup opencode      # writes ~/.config/opencode/opencode.jsonc
discopop_mcp_server --setup-all           # all agents that are installed
discopop_mcp_server --verify claude_code  # check the entry
discopop_mcp_server --status              # show the setup status
```
If a virtual environment is active, the entry points to the server of that environment. `--full-path` writes the full path of the executable found in `PATH` instead, and `--debug` adds `--debug` to the entry.

Other MCP clients that start servers over stdio need an entry like the following (not tested with other clients):
```json
{
  "mcpServers": {
    "discopop_mcp_server": { "command": "/path/to/venv/bin/discopop_mcp_server" }
  }
}
```

## Tools
The server offers 12 tools. In workflow order:

| Tool | Purpose |
|------|---------|
| `initialize_discopop_directory` | Create the `.discopop` structure of a project (once per project). `reset=true` removes the analysis results and keeps the configuration. |
| `set_compile_script` | Write the build script `compile.sh` (shared, or per configuration). |
| `create_execution_configuration` | Create a named configuration with an `execute.sh` (and optional `validate.sh`). |
| `delete_execution_configuration` | Delete a configuration; its recorded results are kept. |
| `get_configurations` | Show the build scripts and configurations of a project. |
| `get_project_status` | Show which steps have run, whether they are stale and which call comes next. |
| `gather_data` | Run the pipeline: hotspot detection (`hotspot_config_names`), instrumentation, profiling and pattern detection. Rebuilds the project plainly afterwards. A failing hotspot step fails the call. The pattern detection covers doall, reduction and task parallelism; results which do not list all three in `enabled_patterns` of `patterns.json` are detected again. |
| `get_hotspots` | List the hotspots, longest running first, with their runtime and share of the program's. |
| `get_parallelization_suggestions` | List the suggestions, hottest first (10 by default, `limit` shows more, `file_path` restricts them to one file), with the pragma to add. Task parallelism is a task group instead (see [Task groups](#task-groups)): it names no pragmas, the agent places them. |
| `explain_parallelization` | Explain in a text why code at given lines was or was not suggested for parallelization, e.g. which dependency prevents it. For lines inside the parallel region of a task group it names the group and points to its suggestion; the task detection does not record why other code is not part of a group, and the answer says so. |
| `get_side_effects` | Describe in a text the data a function reads and writes outside of itself, including its callees. |
| `run_configuration` | Build the project as it is and run a configuration with a given thread count; reports the time, the result of `validate.sh`, and the errors and warnings of the build and the run. |

`--tools analysis` hides the four project setup tools (`initialize_discopop_directory`, `set_compile_script`, `create_execution_configuration`, `delete_execution_configuration`). Use it against a project that is already configured. The default is `--tools all`.

The analysis tools answer in short text, one line per hotspot, suggestion or effect. The setup and pipeline tools answer in JSON that holds the facts of the call and, where useful, a `next_step` hint; an error is `{"status": "error", "message": ..., "next_step": ...}`.

## Task groups
Task parallelism is reported as a task group instead of a pragma, because the task positions of the explorer are not always applicable one to one (see [Tasks](../data/Parallel_patterns/tasks.md) for how groups are detected). A group is listed as one suggestion with the following lines:

- the headline: the enclosing function with its runtime (from the hotspot detection; `no hotspot data` without it),
- `parallel region`: the lines that contain all tasks,
- `task <id>`: the lines of each task and the first line of its code (`(+n lines)` for longer tasks),
- `dependences between the tasks`: `task a -> task b: variable`, with `(anti)` for a write-after-read dependence; `none` if there are none (older results that recorded no dependences list the `in`/`out` clauses of the tasks or say `none recorded`),
- `join`: the line after the region at which the tasks have to be complete, with the variables the code there reads (or overwrites) and the tasks that write them; if nothing later depends on the tasks it says so and notes that what recursive calls write is not tracked,
- `data sharing of task <id>`: the variables the task accesses as `shared`, `firstprivate` and `private`,
- `flag`: where the group looks implausible, e.g. an unknown end line, tasks with the same or overlapping lines, fewer than two tasks, a task that is only a brace or ends in a `return`. The groups are not filtered, so check the flags first.

A task group is `nested in` a suggested loop that contains it, and the loop then says `contains task group`. A loop whose independent iterations call a hotspot function (e.g. recursion in a loop) is a group of one task per iteration (`one task per iteration of the loop at <file>:<line>`, `task body`); its `join` names the line after the loop that reads the results, or, if none is found, tells to wait for the tasks after the loop.

Example, for a function that calls `knapsack` recursively twice (output of `get_parallelization_suggestions` for a profiled run of such a program without hotspot detection):
```text
1 parallelization suggestions, hottest first:
Suggestion 2: Task group in Function knapsack (knapsack.c:13-31; no hotspot data)
  parallel region: knapsack.c:24-26
  task 0: knapsack.c:24-24   knapsack(e + 1, c, n - 1, v, &without, l + 1);
  task 1: knapsack.c:26-26   knapsack(e + 1, c - e->weight, n - 1, v + e->value, &with, l + 1);
  dependences between the tasks: none
  join: no later code depends on the tasks (not tracked: what recursive calls write)
  data sharing of task 0: firstprivate c, e, l, n, v
  data sharing of task 1: firstprivate c, e, l, n, v
Apply a suggestion by making the change it shows (an OpenMP pragma goes directly above the code it names). explain_parallelization tells why code has no suggestion.
A task group says which code may run as tasks, not where to put the pragmas: choose the parallel region, the tasks and a wait before code that uses their results yourself, and check the flags first.
```
Two further groups (the first one with a join; the second one a task per loop iteration inside a do-all loop; the list is shortened and long source lines are cut at comments):
```text
Suggestion 2: Task group in Function h (dep.c:9-13; no hotspot data)
  parallel region: dep.c:11-12
  task 0: dep.c:11-11   a = f(k);
  task 1: dep.c:12-12   b = f(n + 1);
  dependences between the tasks: none
  join: the tasks have to be complete before dep.c:13, which reads a (task 0), reads b (task 1)
  data sharing of task 0: shared a; firstprivate k
  data sharing of task 1: shared b; firstprivate n

Suggestion 5: Loop loop.c:16-18: doall, #pragma omp parallel for firstprivate(n); contains task group 2, 7
Suggestion 7: Task group in Function g (loop.c:13-20; no hotspot data)
  one task per iteration of the loop at loop.c:16 (loop lines 16-17)
  task body 6: loop.c:17-17   store(&res[k], f(n + k));
  join: the tasks have to be complete before loop.c:19, which reads res (task 6)
  data sharing of task 6: shared res; firstprivate n
  nested in suggestion 5
```
The `join` is derived from the data flow, `after_dependences` of `patterns.json`, so it is only as good as the profiled run: a write through a pointer that happens only in a recursive call is not seen.

## Daemon mode
By default, the client starts one server process per session and the cached data is lost when it ends. `discopop_mcp_server --daemon` runs a persistent server that keeps the loaded analysis data (file mapping, side-effect index) between calls and sessions. It listens on `127.0.0.1`, port `7777` by default (`--daemon-port`). The server that the client starts checks for a daemon on its first tool call and forwards the calls to it; without a daemon, it runs the tools itself. It never starts a daemon. Start the daemon yourself before you start the client:
```bash
discopop_mcp_server --daemon --daemon-port 8888   # client entry: discopop_mcp_server --daemon-port 8888
```
Use the same `--daemon-port` for the daemon and for the client entry.

## Rules for agents
- Access DiscoPoP data only through the tools. Never read `.discopop` directories: they contain large binary artefacts, and the tools return compact summaries.
- If data is missing, run the tool that produces it, usually `gather_data`.
- Apply a suggestion by editing the source yourself; DiscoPoP never modifies it. The suggestions rest on the profiled inputs, so check with `run_configuration` that the changed program still gives the same results, and measure its runtime before and after. Call `gather_data` again after changing the sources.
- If the pipeline is in an inconsistent state, call `initialize_discopop_directory(reset=true)`.

## Relation to the project manager and the GUI
The server uses the same project structure as the [project manager](Project_manager.md) and the [GUI](GUI.md): configurations live in `.discopop/project/configs/`, and runs are recorded in `.discopop/project/execution_results.json`. You can create a configuration with the GUI and let an agent use it, or the other way round.

## More information
The [README of the MCP server](https://github.com/tuda-hpclab/discopop/blob/master/mcp_server/README.md) describes the parameters and results of every tool, the progress and cancellation support, and development.
