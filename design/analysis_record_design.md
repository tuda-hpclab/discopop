<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Design: one analysis record for DiscoPoP's pipeline outputs

Repository: /home/lukas/git/discopop, branch `feature/analysis-record` (already checked out).
Read /home/lukas/git/discopop/CLAUDE.md first (venv, black -l 120, ruff, mypy, pytest commands).

## Problem

Whether the analysis data in `.discopop/` is complete and current is decided today in three
places, by three different rules, all based on file mtimes:

- `mcp_server/tools/gather_data.py` -- each step skips itself when its output is newer than the
  newest source (`ToolContext.newest_source_mtime`, `mcp_server/tools/helpers.py:715`). The hotspot
  step additionally needs the server's own bookkeeping file
  `hotspot_detection/profiled_configurations.json` (`PROFILED_CONFIGURATIONS_FILE`, line 134) to list
  exactly the requested configurations, and the pattern step needs `explorer/patterns.json`'s
  `enabled_patterns` to cover the server's `DETECTED_PATTERNS = ["task", "doall", "reduction"]`.
- `mcp_server/tools/get_project_status.py` -- `_PIPELINE_OUTPUTS` + mtime comparison.
- `library/discopop_library/ProjectManager/services/hotspot_build.py` -- its own source walker
  (`newest_source_mtime`, different suffixes and pruned dirs) for the GUI's hotspot build state.

Consequences: data produced by the ProjectManager CLI (`-x <c>:hd --inplace`,
`discopop_hotspot_analyzer`, `-x <c>:dp --inplace`, `discopop_explorer`) is never accepted by
`gather_data` (no `profiled_configurations.json`; callers pass other pattern sets), and mtimes make
any copy of `.discopop` fragile (`cp` without `-p`, `git checkout` silently invalidate or validate).

## Goal

Whoever produces a step's output (ProjectManager CLI, GUI, MCP server) writes the same record; every
consumer asks one library function whether a step is current. Currentness is decided by a
**content fingerprint of the sources**, not by mtimes.

## New module: `library/discopop_library/AnalysisRecord/`

`__init__.py` re-exports the public API. Implementation in `analysis_record.py`, sources walk in
`sources.py`, colocated pytest tests `test_*.py`.

### Source walk (single definition, replaces both existing walkers)

`source_files(project_root: str) -> List[str]` -- relative POSIX paths, sorted.
- suffixes (case-insensitive): `.c .cc .cpp .cxx .c++ .h .hh .hpp .hxx`
- pruned directories: any name starting with `.` (covers `.git`, `.discopop`, `.discopop_*`, `.venv`),
  `build`, `venv`, `__pycache__`, `node_modules`, `CMakeFiles`, and any directory that contains a
  `CMakeCache.txt` (a CMake build tree under another name)

`SourceFingerprint` (frozen dataclass): `digest: str` ("sha256:<hex>"), `files: Dict[str, str]`
(rel path -> "sha256:<hex>" of the content).
`source_fingerprint(project_root) -> SourceFingerprint`. digest = sha256 over
`"<path>\0<filehash>\n"` for the sorted files. Keep a module-level cache
`{abs_path: (st_mtime_ns, st_size, filehash)}` so repeated calls only re-hash changed files
(mtime is used ONLY as a cache key here, never for a decision).
`changed_files(old: Dict[str,str], new: Dict[str,str]) -> List[str]` (added, removed, modified; sorted).

### Pattern set

`DEFAULT_PATTERNS: Tuple[str, ...] = ("doall", "reduction", "task")` in `analysis_record.py`.
It is the definition of "the full pattern detection" for every DiscoPoP tool.

### Record file

`.discopop/analysis_record.json`, constant `RECORD_FILENAME`. Format:

```json
{
  "format": 1,
  "project_root": "/abs/path/of/project",
  "steps": {
    "<step>": {
      "run_id": "<uuid4 hex, unique per write>",
      "completed_at": "2026-11-03T10:15:00",
      "discopop_version": "x.y.z",
      "sources": {"digest": "sha256:...", "files": {"md.cpp": "sha256:..."}},
      "params": {...},
      "inputs": {"<upstream step>": "<its run_id>"}
    }
  }
}
```

Writes are atomic (temp file in the same dir + `os.replace`). A record that cannot be parsed is
treated as absent (log a warning), never raised. `discopop_version` from
`discopop_library.global_data.version.utils.get_version()` (best effort).

### Steps, their outputs, params and who writes them

| step | outputs that must exist (rel. to `.discopop`) | params | written by |
|---|---|---|---|
| `hotspot_detection` | `hotspot_detection/private/hotspot_result_*.txt` (>=1) | `configs: {config name: compile script}` (script path rel. to project root if inside it) | successful `hd` execution in `execute_configuration` |
| `hotspot_analysis` | `hotspot_detection/Hotspots.json` | `configs: sorted list` (the config names of `hotspot_detection` at analysis time) | `discopop_hotspot_analyzer` (always runs with cwd = the `.discopop` dir; the GUI passes `--input-dir merged`, still cwd = `.discopop`) |
| `dependence_profiling` | `profiler/Data.xml`, `profiler/dynamic_dependencies.txt` | `config: str`, `compile_script: str` | successful `dp` execution in `execute_configuration` |
| `pattern_detection` | `explorer/patterns.json` | `enabled_patterns: sorted list`, `options: dict` (explorer options that change results, e.g. hotspot type filter, ignore-dependency-states; omit defaults) | `discopop_explorer` at the end of a successful run |
| `patch_generation` | `patch_generator/` (dir) | `{}` | `discopop_patch_generator` at the end of a successful run |

Write API: `record_step(dot_discopop: str, step: str, params: dict, project_root: Optional[str] = None) -> None`.
- `project_root` defaults to `dirname(abspath(dot_discopop))` (works for `.discopop_<variant>` copies).
- Every write gets a fresh `run_id` (uuid4). `completed_at` is for display only and never compared
  (one-second resolution; steps of small programs finish within one second).
- Fingerprints the sources at write time; fills `inputs` with the `run_id` of the step's
  upstream steps currently recorded: `hotspot_analysis <- hotspot_detection`,
  `pattern_detection <- dependence_profiling, hotspot_analysis`, `patch_generation <- pattern_detection`.
- `hotspot_detection` accumulates: if a record exists with the same `sources.digest`, the new
  `{config: compile_script}` entry is merged into `configs` and the step gets a new `run_id` (the set
  of runs changed, so a Hotspots.json derived earlier is stale); otherwise `configs`
  is replaced by `{config: compile_script}`. The reset is keyed on the source digest ONLY: benchmarks
  commonly have a per-configuration `compile.sh` (`resolve_compile_script_path` honours
  `configs/<name>/compile.sh`), so `-x tiny:hd,small:hd` builds twice with different scripts and
  must still end as `configs = {tiny: ..., small: ...}` -- otherwise gather_data with
  `hotspot_config_names=[tiny, small]` would re-instrument and delete the hotspot data.
  (The MCP server instruments once and runs every config on that build; the CLI builds per config.
  Both are "one hotspot detection over these configs"; runs from separate builds are combined by
  source location, see `ProjectManager/services/hotspot_session.py`.)
  Provide `record_hotspot_run(dot_discopop, config, compile_script, project_root=None)` for that.
- `clear_record(dot_discopop)` removes the record file (used by resets).
- Recording never raises into the producer: wrap failures in a warning (`logging`), since a
  producer must not fail because the bookkeeping failed.

### Status API

```python
STEPS = ("hotspot_detection", "hotspot_analysis", "dependence_profiling", "pattern_detection", "patch_generation")

@dataclass(frozen=True)
class StepStatus:
    step: str
    state: str              # "missing" | "current" | "stale"
    basis: str              # "fingerprint" | "mtime" (legacy fallback, see below) | "none"
    reason: str             # human readable, e.g. "md.cpp changed since the step ran"
    completed_at: Optional[str]
    params: Dict[str, Any]
    changed_files: List[str]

def analysis_status(dot_discopop: str, project_root: Optional[str] = None) -> Dict[str, StepStatus]
def step_status(dot_discopop: str, step: str, project_root: Optional[str] = None) -> StepStatus
```

Rules, in order, per step:
1. Outputs missing -> `missing` (basis `none`), whatever the record says.
2. Record present for the step:
   - record's `project_root` != current absolute project root -> `stale`, reason
     "produced for another location (<path>)": FileMapping.txt, patches and explorer dumps hold
     absolute paths, so moved data is not usable.
   - `sources.digest` != current digest -> `stale`, `changed_files` filled.
   - any recorded `inputs[upstream]` != that upstream's current `run_id`, or an upstream that
     is itself not `current` -> `stale`, reason names the upstream.
   - else `current`.
3. No record for the step but outputs exist (data from a DiscoPoP predating this record) -> legacy
   fallback, basis `mtime`: `current` iff the newest source mtime (new walker) <= the outputs' mtime
   (same rule gather_data uses today), otherwise `stale`. `params` empty, except
   `pattern_detection` reads `enabled_patterns` from `patterns.json` and `hotspot_detection` reads
   `configs` from a legacy `hotspot_detection/profiled_configurations.json` if present.

Convenience: `covers(status: StepStatus, **required) -> bool`, e.g.
`covers(s, configs=["a","b"])` (set equality against the config names), `covers(s, enabled_patterns=DEFAULT_PATTERNS)`
(superset). Keep this small; callers can also inspect `params` directly.

The fingerprint is computed once per `analysis_status` call and shared across steps.

## Producers (agent B)

- `library/discopop_library/ProjectManager/configurations/execution.py::execute_configuration` (and
  wherever the settings mode `hd`/`dp` is known): after a successful compile+execute in `hd` mode call
  `record_hotspot_run(<the .discopop the data was written to>, config_name, compile_script)`, in `dp`
  mode `record_step(..., "dependence_profiling", {"config": ..., "compile_script": ...})`. Record into
  the `.discopop` of the directory actually executed in (the project copy unless inplace) and with that
  directory as `project_root` -- the copy is deleted afterwards, which is correct (its data is too).
  Verify how the MCP server's gather_data drives instrumentation/profiling: if it calls
  `execute_configuration`, it is covered automatically; if it compiles/executes through another path,
  record there as well (coordinate: gather_data.py belongs to agent C -- report what is needed instead
  of editing it).
- `hotspot_detection/discopop_hotspot_analyzer/hotspot_analyzer.py::run`: after writing Hotspots.json,
  record `hotspot_analysis`. `discopop-hotspot-detection` does not depend on `discopop_library`;
  import it lazily inside a try/except ImportError and skip recording (debug log) if unavailable. Do
  not add a hard dependency.
- `explorer/discopop_explorer/__main__.py`: `--enable-patterns` default becomes
  `",".join(DEFAULT_PATTERNS)` (today "reduction,doall,task" -- same set, single definition).
  At the end of a successful run (`discopop_explorer.py`), record `pattern_detection` with the
  selected pattern types (`pattern_detection.selected_pattern_types`) and the result-changing options.
  The explorer runs with cwd/project_path = the `.discopop` dir.
- `library/discopop_library/PatchGenerator/patch_generator.py::run`: record `patch_generation` at the end.
- Resets must delete the record (`clear_record`): `ProjectManager --reset` and the MCP server's
  `initialize_discopop_directory(reset=true)` (`mcp_server/tools/initialize_discopop_directory.py` --
  that one file of the server is agent B's). Also any other place that deletes
  `profiler/`/`hotspot_detection/`/`explorer/` wholesale outside gather_data -- list what you find.
- Tests for each producer where a unit test is feasible (at least: execution records hd/dp; explorer
  default pattern string equals DEFAULT_PATTERNS).

## Consumers (agent C)

- `mcp_server/tools/gather_data.py`: every skip decision goes through `step_status`/`covers`:
  hotspot step skipped iff `hotspot_detection` current and covers the requested
  `hotspot_config_names` (single-config step: config in configs); analysis iff `hotspot_analysis`
  current; instrumentation+profiling iff `dependence_profiling` current; pattern detection iff
  `pattern_detection` current and covers `DEFAULT_PATTERNS` (replace the server's
  `DETECTED_PATTERNS` by the library constant). Stop writing `profiled_configurations.json`
  (the legacy fallback in the library still reads it). `force` keeps overriding everything.
  Results keep their current shape (`status: skipped`, `reason: results_are_current`, `last_run`);
  add `basis` where cheap.
- `mcp_server/tools/get_project_status.py`: build the pipeline state from `analysis_status`; keep the
  output keys the tests/clients rely on (`at`, `stale`, `next_step`, `sources_modified_at` -- the
  latter may stay mtime-based or become the list of changed files; keep the key, document it), and add
  `changed_files` where stale.
- `mcp_server/tools/helpers.py`: `newest_source_mtime`/`source_mtimes` either delegate to the library
  walker or are removed if unused afterwards.
- `library/discopop_library/ProjectManager/services/hotspot_build.py`: use the library walker instead
  of its own (`SOURCE_SUFFIXES`, `PRUNED_DIRS`, `newest_source_mtime`); the `BUILD_MISMATCH` decision
  uses `step_status(..., "hotspot_detection")` when a record exists, mtime otherwise. Keep the public
  function signatures used by the GUIs.
- Update affected tests (mcp_server/tools/test_*.py, test/end_to_end/mcp_server) and docstrings/tool
  descriptions that mention mtimes.
- Unit tests: consumers honour records (simulated with `record_step`/`record_hotspot_run` + output
  files), legacy fallback still works, copying `.discopop` (with sources) to another directory makes
  it `stale` ("another location").
- The end-to-end proof (written by the integrator after B and C, not by you): in
  `test/end_to_end/mcp_server/`, run the real CLI pipeline on the test program with two
  configurations (`-x a:hd,b:hd --inplace`, `discopop_hotspot_analyzer`, `-x a:dp --inplace`,
  `discopop_explorer`), then call `gather_data` through the MCP client and assert every step is
  `skipped`. Keep that in mind so the test is writable.

## Working rules for implementation agents

- Do not commit. Edit only the files your section assigns you; if you need a change elsewhere,
  report it instead of making it (another agent works in the same tree concurrently).
- Run black -l 120 only on files you changed, ruff, mypy on the packages you changed, and your
  tests (`venv/bin/python -m pytest <your paths>`). Do NOT reinstall the venv
  (`pip install ...`): the integrator does that once. Tests import from the source trees
  (`pythonpath` in pyproject.toml), so unit tests see your changes without reinstalling.
- Report: files changed, design decisions you had to make that the spec did not settle, anything
  you found that contradicts the spec, and test/mypy/ruff/black results verbatim (summarized).

## Out of scope

Sources outside the project root are not fingerprinted (e.g. polybench's shared
`utilities/polybench.c`); the mtime rule had the same gap.

Relative paths in FileMapping.txt / patches; the benchmark harness; explain_parallelization's
patterns-vs-decisions mtime check.
