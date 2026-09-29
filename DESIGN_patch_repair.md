<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Patch Repair — Design & Implementation Plan

Status: implemented, and verified end to end against a real model
(`opencode` / `HPC_Lab/Qwen/Qwen3-Coder-30B-A3B-Instruct`) on the `example/`
project. The sections below are the design as built; §3.6 and §4 in particular
record what that first real run changed about it.

Adds `discopop_patch_repair`: a tool that finds the parallelization suggestions
whose generated patch does not compile, asks a configurable LLM agent to fix the
patch, verifies the fix, and writes the repaired patch back into
`patch_generator/<id>/<file_id>.patch`. Suggestions that compile, and
suggestions whose repair does not succeed within the configured budget, are left
untouched.

The tool is reachable from the CLI and from a new **Patch Repair** tab in the
Project Manager GUI, between *Pattern Detection* and *Autotuning*.

---

## 0. Background: what the existing tooling already gives us

Every design decision below rests on these properties, which were verified
against the sources.

**Patches live in a flat, id-addressed layout.**
`from_json_patterns.py:104-115` writes one directory per suggestion,
`patch_generator/<pattern_id>/<file_id>.patch`, each file a plain `diff -Naru`
of the original source against the modified source
(`PatchGenerator/diffs.py:88-99`). There is no index file to keep in sync —
overwriting a `.patch` file in place is the complete write operation.

**Patches are applied by `patch(1)`, not by `git apply`.**
`PatchApplicator/apply.py:84-100` runs `patch <target_file> <patch_file>` with
the target named explicitly. The `---`/`+++` headers are therefore decorative:
only the hunks matter, and `patch`'s usual offset tolerance applies. This is
what makes an agent-authored diff workable at all (§3.3).

**The autotuner already compiles each suggestion in isolation.**
`-A 0` (`optimization/measure_only.py:57-83`) iterates the candidate
suggestions, and for each one copies the project, applies *that one*
suggestion, and builds it. `--search-space <id>` prunes the pattern storage to a
single id before the algorithm runs (`Autotuner.py:154-157`,
`utils.restrict_patterns_to_ids`), so `-A 0 --search-space <id>` is exactly a
"compile suggestion `<id>` alone" invocation.

**Compiler stderr survives the project copy.**
`CodeConfiguration.compile_only` builds its `ProjectManagerArguments` with
`project_root=arguments.project_path` — the *original* project root, not the
copy. `_store_execution_result` therefore writes into the original
`.discopop/project/execution_results.json`
(`ProjectManagerArguments.py:64-66`, `execution.py:306-355`), keyed as

```
<config> -> <compile script> -> par_settings.json -> [ { ... } ]
```

with `requested_suggestions`, `code`, `stdout` and `stderr` per entry, and with
`requested_suggestions` part of the de-duplication key. The tuner deletes its
copies afterwards, but the diagnostics remain. **No `--skip-cleanup` is needed.**

**Hotspot classification is already available per suggestion.**
`get_patterns_by_hotspot_type` (`HostpotLoader/utilities.py:19-70`) buckets every
pattern id into `YES` / `MAYBE` / `NO` from `Hotspots.json`, and falls back to
classifying everything as `YES` when no hotspot information exists. The autotuner
exposes this as `-ht/--hotspot-types`.

---

## 1. Scope and the four decisions taken

| Decision | Choice |
| --- | --- |
| How the agent delivers a fix | It **rewrites the `.patch` file** (emits a corrected unified diff). |
| Which failures are repaired | **Compile errors only.** No execution, no validation, no warnings. |
| How candidates are compiled | By **invoking `discopop_auto_tuner -A 0`**, restricted to one suggestion per invocation via `--search-space`. |
| When a repair is accepted | It **applies cleanly, recompiles, and still carries the original patch's OpenMP directives.** |

Two consequences of "agent rewrites the patch" shape the rest of the design:

* No sandbox has to be handed to the agent. The agent is a pure
  text-in/text-out step: it never touches the project. Everything it needs —
  original source, patched source, patch, diagnostics — goes into the prompt.
* Diff syntax becomes the dominant failure mode. §3.4 and §3.6 exist to take
  that burden off the model rather than spending retries on it.

**Cost control (hotspots).** When hotspot information is available, suggestions
classified `NO` are skipped by default: they contribute negligibly to runtime, so
repairing them spends agent tokens and build time on code that will never be
part of a worthwhile parallelization. The dial is `--hotspot-types`, default
`yes,maybe`, and it is passed through to every autotuner invocation as `-ht`.
Where no hotspot information exists, everything is `YES` and nothing is skipped.

---

## 2. New code

```
library/discopop_library/PatchRepair/
    __init__.py
    __main__.py                  CLI entry point: discopop_patch_repair
    PatchRepairArguments.py      dataclass (GeneralArguments subclass) + validation
    repair.py                    orchestration: the per-suggestion state machine
    candidates.py                which suggestions to consider (hotspot filter)
    compilation.py               autotuner invocation + execution_results.json reader
    diagnostics.py               parse compiler errors, map them back to file ids
    patchset.py                  a suggestion's patch files handled as one unit
    patching.py                  dry-run apply, canonicalization, pragma guard
    prompts.py                   prompt ladder + rendering
    results.py                   results.json / progress.jsonl writers
    backends/
        __init__.py
        base.py                  AgentBackend protocol
        opencode.py
        claude.py
        registry.py              name -> backend, config file loading
    test_patching.py             pytest, colocated per repo convention
    test_patchset.py
    test_compilation.py
    test_diagnostics.py
    test_prompts.py
```

Touched elsewhere:

* `library/discopop_library/FolderStructure/setup.py` — add `setup_patch_repair`.
* `library/pyproject.toml` — add the `discopop_patch_repair` console script.
* `library/discopop_library/EmpiricalAutotuning/` — one new flag, §3.2.
* `library/discopop_library/ProjectManager/gui/` — the new tab, §5.
* `docs/tools/Patch_repair.md` + a link from `docs/tools/tools.md`.

---

## 3. The repair pipeline

### 3.1 Candidate selection

1. Load `explorer/detection_result_dump.json` and `Hotspots.json` (via
   `HostpotLoader`, exactly as the autotuner does).
2. `get_patterns_by_hotspot_type` → keep the ids whose bucket is in
   `--hotspot-types` (default `yes,maybe`).
3. Intersect with the directories actually present under `patch_generator/`:
   a suggestion with no generated patch has nothing to repair.
4. Apply `--suggestions <ids>` if given, which overrides steps 2–3 for explicit runs.

The result is an ordered candidate list; hot suggestions first
(`YES` before `MAYBE`) so a `--max-repairs` budget is spent where it pays.

### 3.2 Detecting the failures

Two passes, because they have very different costs:

**Discovery pass (once).** One `discopop_auto_tuner -A 0 -ht <types>` run over
the whole candidate set. `measure_only` already compiles every suggestion
individually, so a single invocation yields every per-suggestion compile result.
`--search-space` is passed only when `--suggestions` restricted the set.

**Verification pass (per repair attempt).** One
`discopop_auto_tuner -A 0 --search-space <id> -ht <types>` invocation, which
compiles exactly that one suggestion.

Both passes read their answer from `.discopop/project/execution_results.json`:
the entry under the compile script whose `requested_suggestions == [id]`, with
`code != 0` meaning "failed to build" and `stderr` carrying the diagnostics.
`compilation.py` snapshots the file's mtime/content before the invocation so a
stale entry from an earlier run can never be mistaken for this run's result.

> **One change to the autotuner is required here.** `Autotuner.run` always
> executes the reference configuration first, and `-A 0` executes every
> candidate that builds. Per-suggestion invocation would therefore cost one full
> program run per invocation plus one per successful build — for `N` suggestions
> and `R` retries that is O(N·R) program executions, which dwarfs everything else.
>
> Proposal: add `--compile-only` to `discopop_auto_tuner`. It threads a flag
> into `AutotunerArguments` that makes `CodeConfiguration.execute` return after
> `compile_only()` and makes the baseline skip its run as well. This is ~20 lines,
> touches no search algorithm, and is independently useful ("does my suggestion
> set still build?"). `discopop_patch_repair` always passes it.
>
> Without the flag the tool still works, just far more slowly; §7 keeps it as a
> separate, first commit so it can be reviewed on its own.

### 3.3 The patch set is the unit of work

A suggestion is *not* one patch. `patch_generator/<id>/` holds one
`<file_id>.patch` per source file the suggestion touches, and multi-file
suggestions are expected to become common. The applicator already treats them as
one indivisible unit: `apply.py:71-150` walks the directory, stops at the first
patch that `patch(1)` rejects, and rolls the already-applied ones back. A
half-applied suggestion is never a state the rest of DiscoPoP has to reason
about, and the repair tool must not introduce one.

`patchset.py` therefore makes the *set* the object everything else operates on:

```python
@dataclass
class PatchSet:
    suggestion_id: int
    entries: Dict[int, PatchEntry]   # file_id -> patch text + target path

    def targets(self) -> Dict[int, Path]         # via FileMapping.txt
    def with_replacements(self, new: Dict[int, str]) -> "PatchSet"
    def render_for_prompt(self, ...) -> str
```

Three consequences run through the rest of the design:

* **The agent may rewrite a subset.** It emits a block per `file_id` it changes
  and omits the rest; `with_replacements` merges those over the originals. A
  patch that was already fine is never regenerated — that saves tokens and, more
  importantly, removes the chance of corrupting a working patch while fixing an
  unrelated one.
* **Every gate in §3.6 runs over the whole set**, against one temp copy of the
  project rather than one temp file, because the compiler only ever judges the
  set.
* **Write-back is all-or-nothing** (§3.7).

**Mapping diagnostics back to file ids.** Compiler messages name paths inside the
project copy the tuner has since deleted, so `diagnostics.py` parses
`path:line:col: error: ...` and resolves each path against `FileMapping.txt` by
longest matching path suffix rather than by string equality. The result — which
`file_id`s the errors actually implicate — drives prompt budgeting below. An
unresolvable path is kept in the diagnostics text but implicates no file.

Suffix matching is not defensive over-engineering: `compile.sh` runs with the
project copy as its working directory, so a project that compiles
`$CXX example.cpp` gets diagnostics reading `example.cpp:24:69: error: ...` —
relative to a directory that no longer exists — while a project building through
CMake gets absolute paths into the copy. Both forms have to resolve to the same
`file_id`.

### 3.4 Prompt construction

One conversation per suggestion, covering the whole patch set: a compiler error
in one file is regularly caused by the patch to another, so splitting the set
into per-file conversations would hide the cause from the agent.

`prompts.py` assembles the prompt from a template plus:

* **Identity** — suggestion id, pattern type, and the file list with each
  `file_id`, its path, and whether the diagnostics implicate it.
* **The original source**, in *every* rung including `minimal`. It is not
  optional context: the answer is a diff *against* it, and a model shown only the
  patch and the error has no way to write one that applies.
* **The patch set to fix** — every `<file_id>.patch`, verbatim, in labelled
  blocks.
* **Source context**, line-numbered with absolute line numbers, for the region
  each patch touches plus `--context-lines` (default 60) around it — both the
  original and the patched rendering. The patched rendering is produced locally
  by applying the set to a temp copy of the project; it is what makes the
  compiler's line numbers resolvable at all, since they are in post-patch
  coordinates and the tuner's build tree is already gone.
* **The compiler diagnostics**, truncated to `--max-error-chars` (default 8000)
  keeping the first errors, which are the causal ones.
* **The output contract** — corrected diffs and nothing else, one delimited
  block per file that needs changing:

  ```
  ===BEGIN PATCH <file_id>===
  <unified diff>
  ===END PATCH <file_id>===
  ```

  with the rules stated explicitly: emit a block **only** for files that need to
  change, keep the parallelization, do not delete the `#pragma omp` directives,
  prefer adding clauses (`private`, `firstprivate`, `reduction`, `shared`) over
  restructuring, and change nothing outside the region the original patch
  touched.

**Prompt budgeting.** A multi-file suggestion can easily outgrow a sensible
prompt, so the content above is tiered by whether `diagnostics.py` implicated a
file. Under a `--max-prompt-chars` cap the material is dropped in a fixed,
documented order: source context for files the diagnostics do not implicate
first, then `--context-lines` is halved (repeatedly), then the diagnostics
themselves are truncated further. The patch set itself is never dropped — a file
whose patch is missing from the prompt cannot be reasoned about, and the agent
would have to guess.

Templates live as files under `PatchRepair/prompts/` so they can be edited
without touching code; `--prompt-dir` points at an alternative set.

### 3.5 The attempt budget: `--prompts` and `--retries`

These are two nested dials, and the distinction is deliberate:

* `--prompts N` (default 2) — **independent attempts with a fresh context.**
  Attempt *k* uses template *k* from the prompt ladder, cycling if `N` exceeds
  the number of templates. The ladder goes from terse to increasingly explicit:

  1. `minimal` — patch + diagnostics only.
  2. `context` — adds original/patched source windows and the declarations of
     every identifier named in the diagnostics.
  3. `guided` — adds the pattern's own metadata from `patterns.json` (shared,
     private and reduction variables as DiscoPoP inferred them), which is
     usually exactly the information a missing-clause error needs.

* `--retries M` (default 2) — **follow-up turns inside one attempt.** The
  failure from the previous turn (a `patch` rejection, or the new compiler
  errors) is appended to the same conversation and the agent tries again.

Upper bound per suggestion: `N × (1 + M)` agent invocations, further capped by
`--max-attempts` (default 6) and, for the whole run, by `--max-repairs` and
`--time-limit`. The budget is spent per *suggestion*, not per file: one
conversation covers the whole patch set (§3.3), so a five-file suggestion costs
the same number of agent calls as a one-file suggestion — only its prompts are
larger. A suggestion stops early the moment a candidate set is accepted.

### 3.6 Validating a candidate patch set

A candidate set goes through six gates, cheapest first, each one against a fresh
temp copy of the project. Every failure produces a message that is fed back as
the next turn's input.

1. **Extraction.** Pull each `===BEGIN PATCH <file_id>===` block; fall back to a
   single ```` ```diff ```` fence when exactly one file is in the set. An
   unknown `file_id`, a duplicate block, or no block at all → rejected with that
   reason. The extracted blocks are merged over the originals
   (`PatchSet.with_replacements`), so untouched files keep their existing patch.
2. **Dry-run apply of the whole set.** `patch --batch --dry-run` for every entry,
   in the applicator's own order, against one temp copy. Rejected hunks are the
   single most common agent error and this gate costs milliseconds instead of a
   compile. `patch`'s own output ("Hunk #1 FAILED at 120") goes straight back to
   the agent, labelled with the file it came from. **If any entry fails, the
   whole set is rejected** — a partially applicable set is exactly the state the
   applicator refuses to produce.

   `--batch` is load-bearing: on a reversed or already-applied patch `patch`
   turns interactive ("Assume -R? [n]", "Apply anyway? [n]"), and with no
   terminal attached it reads EOF, skips the hunk and exits non-zero. That looks
   exactly like a rejected patch, so without `--batch` a *correct* answer is
   reported to the agent as a bad diff. Observed against a real model.

2a. **Delta interpretation (fallback).** When the set does not apply to the
   pristine code, it is tried once more *on top of the original patch*, and the
   result re-derived against the pristine file. This is not a nicety: it is the
   single most common way a model gets this task wrong, and it was the first
   thing a real model did. What the model is shown is the broken *patched* code
   and the compiler's complaint about it, so it answers with a diff that edits
   that — removing the directive line the patch added and adding a corrected one.
   A patch has to be a diff against the file where that line does not exist yet,
   so `patch` rejects it. The intent is unambiguous and recoverable, and
   recovering it is worth far more than spending a retry re-explaining the
   distinction. Only if that fails too is the answer genuinely wrong, and the
   rejection then carries an explicit reminder about which file the diff is
   against.
3. **Real apply.** Apply the set to the temp copy for real, in the same order.
4. **Canonicalization, per file.** Re-diff each modified file against its
   pristine original with `diff -Naru`, reusing
   `PatchGenerator.diffs.get_diffs_from_modified_code`. The stored patches are
   therefore always byte-identical in form to what `discopop_patch_generator`
   emits, with correct hunk headers and each file's own line terminators
   (`diffs.detect_line_terminator` / `apply_line_terminator`), regardless of how
   sloppy the agent's line counts were. Only `patch`'s fuzz tolerance has to
   carry the agent, not exactness. A file whose canonical diff comes back empty
   is dropped from the set: the agent's edit was a no-op.
5. **Pragma guard, per file.** Extract the OpenMP directives from the added
   (`^+`) lines of the original patch and of the canonicalized candidate,
   normalising whitespace and stripping clauses. Every directive kind present in
   a file's original patch must still be present in that file's candidate.
   Clause changes are allowed — they are the expected fix; directive deletion is
   not, because it turns the suggestion into a silent no-op that builds green.
   Applied per file rather than across the set, so a pragma cannot be "preserved"
   by having moved into a different translation unit. Failure is reported as
   `the parallelization was removed from <path>`.
6. **Recompile.** Verification pass of §3.2 — one autotuner invocation for the
   suggestion, since the applicator applies the whole directory anyway. Non-zero
   → feed the new diagnostics back, re-running `diagnostics.py` so the next turn
   is budgeted against the *new* set of implicated files.

Accepted only when all six pass.

### 3.7 Writing back

Write-back is all-or-nothing over the suggestion's directory, mirroring how the
applicator treats it.

Before the first overwrite of a suggestion, the pristine `patch_generator/<id>/`
directory is copied wholesale to `patch_repair/backups/<id>/` — the whole
directory, not the individual files that happen to change, so a restore always
reproduces a coherent set. The accepted canonical patches are then written into
a staging directory and moved into place only once all of them are written, so
an interruption mid-write cannot leave a set that is half repaired and half
original.

`--dry-run` performs the whole pipeline but writes only into `patch_repair/`,
leaving `patch_generator/` untouched — the intended way to inspect what a backend
would do before letting it near the patches.

`--restore` copies the backups back, so a repair run is always reversible without
re-running `discopop_patch_generator`.

## 4. Backends and LLM configuration

Modelled directly on the benchmark harness' `shared/llm_backends/` +
`shared/llm_config.py` (`/home/lukas/git/new_benchmark_harness`), which already
solved this problem for `opencode` and `claude`. That repository is not a
dependency of DiscoPoP, so the design is mirrored rather than imported, and
simplified where the repair use case is genuinely smaller. Keeping the shapes
and the vocabulary identical means what is learned about one is true of the
other.

```
library/discopop_library/PatchRepair/llm_backends/
    __init__.py     the declarative registry: BACKENDS, get(), fields_of(), resolve_options()
    base.py         FieldSpec, Invocation, run_agent(), binary probes, tolerant JSON
    opencode.py     adapter
    claude.py       adapter
library/discopop_library/PatchRepair/llm_config.py
```

**An adapter module** fills in a fixed contract, documented in `base.py`:
`NAME` / `LABEL` / `DESCRIPTION`, `BINARY_ENV_VAR` / `DEFAULT_BINARY`, `FIELDS`,
`MODELS_ARE_EXHAUSTIVE`, `INSTALL_HINT` / `AUTH_HINT`, the probes
`binary()` / `version()` / `available()` / `list_models()`, and
`build_argv()` / `parse_events()` / `new_session_id()`. Everything that is not
agent-specific — running the process, the timeout, the artifacts, extracting the
answer — lives in `base.py`, so adding a third agent is one module and one line
in the registry.

`FIELDS` is the part that earns its keep twice over: it is a `FieldSpec` list
declaring the settings only that backend understands (label, hint, kind,
choices, default), so **the GUI builds its editor from the registry** instead of
from a hardcoded row per flag, and the CLI can validate them.

**`llm_config.py`** holds two sections in one JSON file, defaulting to
`.discopop/patch_repair/llm_config.json` and overridable with
`--llm-config` or `$DISCOPOP_PATCH_REPAIR_LLM_CONFIG`:

* **connections** — part of the experiment: which model, through which backend,
  with which defaults for `prompts`, `retries` and `agent_timeout`, plus
  `extra_args`, `env` and the backend-specific `backend_options`.
* **backends** — part of the *installation*: where that agent's executable is on
  this machine, and what every connection through it should default to.

They are separate for the reason the harness separates them: a connection is
"ask this model, this way" and survives being copied to another machine, while a
backend section is "here is where that agent lives here" and does not. Settings
resolve most-specific-first — `backend_options`, then the connection's top
level, then the backend defaults, then the field's own default.

**No credentials are ever stored or read.** The agent owns provider
authentication; DiscoPoP never sees an API key.

**The agent runs in an empty throwaway directory, never in the project.** It is
given everything it needs in the prompt and is asked for text, so it has no
reason to touch a file — but a coding agent pointed at a project *will* reach
for its edit tool, and `opencode` scopes itself to (and can write in) the
directory it is run in. This is not hypothetical: an early version passed the
project root as the working directory, and the model duly "fixed" the error by
editing the real `example.cpp` instead of answering with a diff. The edit landed
outside everything the gates check, and the next run then measured a source file
that no longer matched its own patches. Tool errors from an agent that reaches
for a tool anyway are treated as recoverable rather than fatal — it is told, and
usually answers correctly on the next turn — and the prompt tells it up front not
to use tools at all.

**Invocation.** One process per turn. `--retries` continues the same
conversation by session id (`opencode --session`, `claude --resume`), so a
follow-up turn sees its own previous answer rather than starting over —
precisely how the harness drives its repair attempts. `Invocation` records
argv, return code, duration, session id, model, token counts and cost where the
backend reports them, and never raises: a failed call is data the run reports,
not an error that aborts it.

Selection:

```
--connection <name>   a stored connection (its backend, model and defaults)
--backend opencode|claude   ad hoc override
--model <id>                ad hoc override
--agent-timeout <s>         per turn, default 300
--llm-config <path>         alternative configuration file
```

**Where this is smaller than the harness.** The harness' agent edits the
benchmark's sources, so it needs workspace scoping (`--dir`, `--add-dir`), edit
approval and MCP selection. Here the agent is a pure text-in/text-out step: it
is given the patch, the source and the diagnostics, and returns a diff. It is
never given write access to the project, never driven in a tool-use loop, and
its output is only ever interpreted as a diff — which is then re-derived locally
(§3.6 gate 4) before anything is stored. The worst a misbehaving backend can do
is waste the attempt budget. Token and cost accounting is kept, because
`--hotspot-types` exists to control exactly that cost and it should be visible.

## 5. Artifacts under `.discopop/patch_repair/`

`setup_patch_repair(path)` in `FolderStructure/setup.py`, mirroring
`setup_auto_tuner`:

```
patch_repair/
    results.json                       per-suggestion outcome, the tool's result
    progress.jsonl                     structured events, replayable in the GUI
    backends.json                      optional, user-provided
    backups/<id>/<file_id>.patch       pristine patch set, copied once per run
    attempts/<id>/<n>/
        prompt.txt                     what was sent
        response.txt                   what came back, verbatim
        candidate/<file_id>.patch      extracted blocks, pre-canonicalization
        canonical/<file_id>.patch      post-canonicalization, the merged set
        rejection.txt                  which gate failed, and for which file
        compile_stderr.txt             diagnostics of the verification build
```

`results.json` per suggestion: `status` (`ok` — compiled already / `repaired` /
`failed` / `skipped`), `hotspot_type`, `files` (the `file_id`s in the set and
which of them the repair actually changed), `attempts`, `backend`, `model`,
`accepted_attempt`, `first_error` (first line of the original diagnostics),
`duration_s`.

The attempt transcripts are the main debugging surface for prompt work, so they
are written unconditionally, not behind a verbose flag.

**Progress channel.** `progress.jsonl` plus `@@PR_PROGRESS <json>` lines on
stdout, modelled directly on
`EmpiricalAutotuning/output/progress.py` (`PROGRESS_PREFIX`) and consumed with
the existing `plots/data.py:split_progress_events`. Events: `start` (candidate
count), `candidate` (id, hotspot type, compiles yes/no), `attempt` (id, n,
template, gate that failed), `repaired`, `done`. This is what lets the GUI show
live progress without a second IPC mechanism, and lets a finished run be
re-displayed from disk.

---

## 6. GUI: the Patch Repair tab

A new `PatchRepairPanelMixin` in
`library/discopop_library/ProjectManager/gui/mixins/patch_repair_panel.py`,
built as a close sibling of `AutotuningPanelMixin` — same scrollable settings
column on the left, same console/output notebook on the right.

Wiring in `ConfigManagerApp.py`: add the mixin to the base list and insert the
tab construction block between the *Pattern Detection* and *Autotuning* blocks
(`ConfigManagerApp.py:165-175`); `ttk.Notebook.add` order is the tab order, so
the new block simply moves ahead of the autotuning one. The panel's widget
attributes are declared on `ConfigManagerMixinBase` alongside the existing
per-panel blocks.

Left column:

* Configuration (label, follows the selected run config), Threads, Log level —
  same widgets as the Autotuning tab.
* **Hotspot Types** checkboxes, defaulting to YES + MAYBE (NO unchecked), with
  the caption explaining that NO suggestions are skipped to save time and cost.
  Disabled with an explanatory hint when no hotspot results exist.
* **Backend** combo (populated from what is on PATH plus `backends.json`),
  **Model** entry, **Agent timeout**.
* **Prompts** and **Retries** spinboxes, with a live "at most N × (1+M) = X agent
  calls per suggestion" caption — the cost dial made visible.
* **Suggestion scope**: a `SuggestionSelector` (the widget the Autotuning tab
  already uses for its search space) to optionally restrict to explicit ids.
* **Dry run** checkbox.
* Pinned below: **Run Patch Repair** / **Stop**, and a summary line
  (`n candidates · k broken · r repaired`).

Right side, a notebook:

1. **Console** — streamed stdout, `@@PR_PROGRESS` lines stripped out, exactly as
   `_invoke_autotuner` does.
2. **Results** — a `ttk.Treeview`: suggestion id, hotspot type, status, files
   changed / files in set, attempts, first error. Selecting a row fills the diff
   view.
3. **Diff** — original patch beside repaired patch for the selected suggestion,
   plus the attempt transcript, so a repair can be judged before it is trusted.
   A suggestion's patch set can hold several files, so the view carries a file
   selector listing every `file_id` in the set and marking the ones the repair
   changed.

Execution: `subprocess.Popen([sys.executable, "-m",
"discopop_library.PatchRepair", ...], cwd=dot_discopop)` in a daemon thread,
stdout streamed line by line, UI updates marshalled with `self.after(0, ...)`.
In-process execution is not an option here for the same reason it is not for the
explorer and the tuner: the child pulls in C-extension-backed console output and
would corrupt the Tk main loop.

Stop sends `SIGINT`, so the tool can finish the current suggestion, write
`results.json` and exit cleanly rather than leaving a half-written patch.

On completion the tab refreshes the suggestion displays of the Autotuning and
Report tabs — repaired patches change what those show.

Prerequisites gating (matching how the Autotuning tab gates itself): the Run
button stays disabled, with a tooltip, until `patch_generator/` is populated and
a run configuration with a compile script is selected.

---

## 7. Implementation order

Each step is independently reviewable and leaves the tree working.

1. **`--compile-only` for the autotuner** (§3.2), with a unit test that a
   compile-only run records a compile entry and no execute entry.
2. **`PatchRepairArguments`, `candidates.py`, `compilation.py`** — the discovery
   pass, no agent involved. `discopop_patch_repair --dry-run --backend none`
   then already answers "which suggestions do not build, and why", which is a
   useful tool on its own and the natural place to stabilise the
   `execution_results.json` reader.
3. **`patchset.py` + `diagnostics.py`** — the set abstraction, `FileMapping.txt`
   resolution by longest path suffix, and error-to-`file_id` mapping. Tested
   against real clang and gcc diagnostics captured as fixtures, including paths
   pointing into a project copy that no longer exists.
4. **`patching.py`** — extraction, whole-set dry-run apply, canonicalization,
   pragma guard. This is the part with real logic and no I/O to speak of; it gets
   the densest unit tests (`test_patching.py`): CRLF sources, multi-hunk patches,
   a candidate that deletes the pragma, a candidate whose hunk headers are wrong
   but whose content applies with an offset, a multi-file set where the agent
   rewrites only one file, and a multi-file set where one entry is rejected and
   the whole set must therefore be refused.
5. **`backends/` + `prompts.py`** — with a `ScriptedBackend` used by the tests so
   the pipeline is testable end to end without a network or an agent binary, and
   with a prompt-budgeting test that a large multi-file set degrades in the
   documented order and never drops a patch.
6. **`repair.py`** — the state machine tying it together, plus `results.json`,
   `progress.jsonl`, staged all-or-nothing write-back, backups and `--restore`.
7. **CLI entry point and `pyproject.toml`.**
8. **GUI tab.**
9. **`docs/tools/Patch_repair.md`**, linked from `docs/tools/tools.md`, and a
   note in `docs/tools/Autotuner.md` about `--compile-only`.

Per `CLAUDE.md`, each step is checked with
`venv/bin/python -m mypy --config-file=mypy.ini -p discopop_library`,
`venv/bin/python -m black -l 120 --check <changed paths>` (never repo-wide) and
the relevant pytest selection.

---

## 8. Open points

* **Reduction of scope on failure.** When no repair is found, an alternative to
  leaving the patch set alone is to mark the suggestion as unusable so the
  autotuner skips it. Currently out of scope: leaving it alone keeps the tool's
  effect purely additive, and the autotuner already handles a failing build.
* **Determinism.** Agent output is not reproducible, so the same run can yield
  different patches. `results.json` records backend, model and the accepted
  attempt; a `--seed`-style guarantee is not available from either CLI backend.
* **Cross-suggestion breakage.** Every suggestion is compiled alone, so a patch
  set that builds in isolation but conflicts with another suggestion's patch is
  out of this tool's reach by construction. That is the autotuner's domain, and
  the split is deliberate — it keeps the repair signal a single, unambiguous
  compiler diagnostic.

---

## 9. Decisions on record

| Question | Answer |
| --- | --- |
| Fix channel | The agent rewrites the `.patch` files. |
| Failure scope | Compile errors only. |
| Compilation driver | `discopop_auto_tuner -A 0`, one suggestion per invocation via `--search-space`. |
| Acceptance | Applies cleanly, recompiles, and keeps its OpenMP directives. |
| Hotspot filter | `NO` suggestions skipped by default (`--hotspot-types`, default `yes,maybe`). |
| `--prompts` / `--retries` | Separate flags: independent attempts with fresh context, vs. follow-up turns within one attempt. |
| Multi-file suggestions | First-class. The patch set is the unit of work: one conversation, whole-set validation, all-or-nothing write-back. |
| Autotuner change | One new flag, `--compile-only`, landed as its own commit. |
