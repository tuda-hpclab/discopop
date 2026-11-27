<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Agent-checked suggestions — Design & Implementation Plan

Status: design agreed, implementation in progress (§9).

DiscoPoP only suggests code whose parallel execution behaves like the sequential
program on the profiled inputs. Some loops miss that standard because of a few
dependencies between their iterations which the *meaning* of the code may make
harmless: a random number generator whose sequence only has to be statistically
equivalent, requests appended to a vector whose order does not matter, a cache.
No analysis of the profile can decide that. An LLM agent reading the code can,
sometimes.

This design adds a second category of suggestions next to the safe ones:

* the explorer emits **unsure suggestions**: loops rejected only because of
  dependencies between their iterations, together with those dependencies, stated
  as facts;
* a new tool, `discopop_suggestion_check`, built like
  [patch repair](patch_repair.md), describes each one to an agent working in a
  throwaway copy of the project. The agent either rejects it, or changes the code
  so that the loop runs in parallel correctly and states the assumption this rests
  on. DiscoPoP computes the patch from the changed copy;
* a suggestion the agent approved stays a **separate, labelled category**. Tools
  use it only on request and always show its assumption.

Motivating case: relearn's `BarnesHutLocationAware.cpp:57`, which the original
code parallelizes with a `critical` section around an append and a `thread_local`
random number generator. Both are blockers for DiscoPoP
(`--all-blocking-dependencies` lists them), and both are judgments about the code's
meaning.

---

## 1. Principles

| Principle | Consequence |
| --- | --- |
| Safe suggestions are unchanged. | Nothing here adds, removes or reorders a safe suggestion, its pattern id or its patch. |
| An unsure suggestion is not a suggestion. | It has no patch: the plain directive would be incorrect. It never appears where tools look for suggestions (§3). |
| The explorer states facts, never remedies. | No `thread_local`, `critical`, `atomic` or similar in its output or in the prompt. The agent decides how, and whether, the code can be parallelized. |
| The assumption comes from the agent. | The explorer does not guess why a dependency could be harmless. The agent names the assumption its change rests on, citing code. |
| The agent is conservative. | Rejection is the default. An approval must justify every blocker; anything left unclear is a rejection (§5.3). |
| Execution can disprove, not prove. | Building and running the approved change is a check, and can be switched off (§5.5). An approval records how far it was verified. |
| Approved stays distinguishable. | An approved suggestion never joins the safe ones. Consumers opt in (§6). |

---

## 2. Terminology and states

| Term | Meaning |
| --- | --- |
| **safe suggestion** | What DiscoPoP reports today: `patterns.json`, `patch_generator/<id>/`. |
| **unsure suggestion** | A loop rejected only for dependencies between its iterations, with at most `--unsure-max-blockers` distinct blockers. |
| **blocker** | The dependencies between iterations with the same type, source line, sink line and origin (dynamic or static): one statement depending on another, or on itself, in an earlier iteration. Its *accesses* are the variables and memory regions involved; a `push_back` alone touches the size, the data pointer and the elements of a vector, which are one problem, not three. |

State of an unsure suggestion, kept by the check tool (§5.6):

```
unverified ──agent──► rejected        (reason; "unsure" is a reason of its own)
     │
     └──agent + reviewer approve──► approved (static)
                                        │ build, if enabled
                                        ├─ fails ──► rejected (build failed)
                                        ▼
                                    approved (built)
                                        │ run + validate, if enabled
                                        ├─ fails ──► rejected (validation failed)
                                        ▼
                                    approved (validated)
```

The verification level (`static`, `built`, `validated`) is part of an approval and
shown wherever the suggestion is shown.

---

## 3. Where unsure suggestions live

Many tools walk *every* list of `PatternStorage` generically (the autotuner's
`restrict_patterns_to_ids`, `get_pattern_ids`, the hotspot loader, the Amdahl
regions, statistics, `services/suggestions.py`) or list every directory below
`patch_generator/` (`Viewer/suggestions_view.py`, `services/patches.py`). A new
key in `patterns` or a new directory below `patch_generator/` would therefore be
picked up as a suggestion. A flag in a pattern would have to be checked by every
one of them, and every tool that forgets the check would apply an incorrect patch.

So unsure suggestions get files of their own, which no existing tool reads:

| File | Content |
| --- | --- |
| `explorer/unsure_suggestions.json` | readable list (§4.3) |
| `suggestion_check/` | the check tool's artifacts, its results and the approved patches (§5.6) |

**Pattern ids** come from the same allocator as the safe ones, but are allocated
after all detectors have run (§4.2). The ids of the safe suggestions are therefore
the same with and without unsure suggestions, and an unsure id never collides with
a safe one, so an opted-in consumer can put both into one `PatternStorage`.

---

## 4. Explorer

### 4.1 Which loops become unsure suggestions

Off by default; `--unsure-suggestions` turns it on. A loop qualifies when

1. it is a do-all candidate that was rejected, and every reason is
   `loop_carried_dependency` or `unprivatizable_static_dependency`. A loop also
   rejected for an early exit, too few iterations, a missing pattern node or as a
   duplicate does not qualify: an agent cannot change those facts;
2. it has at most `--unsure-max-blockers` blockers (default 4). A loop with many
   dependencies between its iterations is not a near miss. relearn's
   BarnesHut:57 has 2 (the append, the random number generator), made of 5
   dependency records;
3. no copy of it was reported as a safe suggestion.

The hotspot filter of the explorer (`--hotspot-types`) applies as for every other
pattern. The check tool filters by hotspot type again, like patch repair.

### 4.2 Detection

`identify_simple_doall_and_reduction` already scans all blocking dependencies with
`--all-blocking-dependencies`. With `--unsure-suggestions` it scans all of them
too, independent of the decision log, and keeps for a rejected loop its first copy,
iteration contexts and blockers. After the scan, each qualifying loop is classified
exactly like a safe candidate (`detect_doall_sharing_clauses`, reductions from the
reduction scan), so its description carries the clauses a safe suggestion would
have.

The detector returns these as data, not as `PatternInfo`: constructing one
allocates a pattern id. `pattern_detection.py` builds the `DoAllInfo` /
`ReductionInfo` objects only after every detector has run, so the safe ids stay
unchanged (§3).

### 4.3 `explorer/unsure_suggestions.json`

```json
{
  "format_version": 1,
  "note": "Not parallelization suggestions: each loop below has dependencies between its iterations, and its patch is incorrect as it is.",
  "suggestions": [
    {
      "pattern_id": 812,
      "type": "do_all",
      "node_id": "4:1022",
      "start_line": "4:57",
      "end_line": "4:86",
      "pragma": "#pragma omp parallel for",
      "first_private": [], "private": [], "last_private": [], "shared": ["..."], "reduction": [],
      "blockers": [
        {
          "type": "RAW", "source_line": "31:184", "sink_line": "31:184", "origin": "dynamic",
          "accesses": [
            { "variable": "*", "memory_region": "..." },
            { "variable": "__i", "memory_region": "..." },
            { "variable": "this1", "memory_region": "..." }
          ]
        }
      ]
    }
  ]
}
```

* `blockers` group the `DependencyRecord`s of `pattern_decisions.json` (§2), sorted,
  so the file is the same for the same profile.
* Lines are `file_id:line`; the check tool resolves them with `FileMapping.txt` and
  adds the text of the lines to the prompt. Variables keep the names of the
  profile, e.g. a mangled global (`_ZL5state`) or a library-internal name (`this1`).
* Whether the data of a blocker is read after the loop is **not** reported. The
  classification only knows it for variables it classifies `lastprivate`, so a
  list of them would be incomplete, and an empty list would read as "not read
  after the loop", a hint toward approval. The agent has to find out from the code.

### 4.4 No patches

Unsure suggestions get no patches. A first version wrote the plain do-all patch of
each one (`patch_generator_unsure/`) and gave it to the agent to change. That was
dropped (§5.2): the plain patch is incorrect by definition, its clauses come from a
classification which ignored the blockers, and agents are better at changing code
than at writing diffs against the right version of a file.

---

## 5. `discopop_suggestion_check`

### 5.1 Reused from patch repair

* the agent backends and their configuration (`PatchRepair/llm_backends`,
  `llm_config.py`); the default configuration file is patch repair's, so a
  connection is set up once;
* the attempt budget (`--prompts`, `--retries`, `--agent-error-retries`) and the
  hotspot filter (`--hotspot-types`, default `yes,maybe`);
* the patch generator's diffing (`get_diffs_from_modified_code`), so an approved
  patch has the same form as a generated one.

### 5.2 The agent works in a copy, DiscoPoP computes the patch

The agent needs to read code beyond the loop (the declaration of the data, who uses
the appended requests, what a called function does) and to change code. It
therefore works in a **workspace: a throwaway copy of the project sources** (the
files git knows of, or the project directory without `.discopop` and `.git`;
without the files the project's fingerprint ignore patterns name, e.g. a build
directory, but always with the source files that have a file id inside the project
root, also those git ignores). Every attempt gets a fresh copy; the follow-up turns of an attempt continue
in it.

* **The agent changes the code itself**, including the OpenMP directive of the
  loop. It writes no diff.
* **DiscoPoP computes the patch** by comparing the copy with the original sources,
  with the patch generator's diffing. Only files with a file id
  (`FileMapping.txt`) may change; anything else is fed back.
  * A changed file of the copy is matched to its file id by its path relative to
    the project root. Both sides are resolved (`realpath`), so a project root
    reached through a symbolic link, or a file mapping recorded under another path
    to the same files, still match. Files with a file id outside the project root
    are not in the copy and cannot be changed.
  * Only the changed content is taken from the copy. It is diffed against the
    original file named in the file mapping, so the patch's headers name the
    project's files, exactly as in a generated patch; the copy's path appears
    nowhere. The temporary file for the diff is written to a scratch directory,
    not next to the original: the check never writes into the project.
* **Tools are restricted on the agent's command line**, not by asking it: read and
  edit, no shell, no web access.
  * `claude`: `--tools Read,Edit,Write,Grep,Glob`, `--restricted` (file tools
    confined to the working directory), `--strict-mcp-config`,
    `--permission-mode acceptEdits`;
  * `opencode`: no `--auto`, permissions `edit: allow`, `bash: deny`,
    `webfetch: deny` (`OPENCODE_CONFIG_CONTENT`). Still to be verified with a real
    run.
* **DiscoPoP's data (MCP).** The agents get DiscoPoP's MCP server, started with
  `--tools readonly --project <project root>`: only tools marked read-only can be
  listed, every call works on the project (the agent never needs its real path,
  file paths are relative to the root), the server never forwards to a daemon of
  the user and writes no log into the project. It reads `<root>/.discopop`; data
  elsewhere means the tools are unavailable. An installed server too old for these
  options is detected (`--help`) and not used; a server the backend reports as
  failed to start is recorded as `failed`. For `claude`, only
  `get_side_effects` and `explain_parallelization` are allowed (`--allowedTools`);
  `--strict-mcp-config` keeps every other MCP server away. `--no-discopop-tools`
  switches it off. The answers are about the profiled runs: evidence, not proof.
* **Reading is checked where it can be.** The prompt requires opening, per blocker,
  the declarations of the data, the called functions and the code after the loop.
  From the reported tool calls the check knows which files were opened: only
  reading (`Read`, `View`) and editing (`Edit`, `MultiEdit`, which need a prior
  read) count, not `Write`, searches, DiscoPoP's MCP tools (they answer about a
  file, they do not show it) or calls the stream reports as failed (`tool_result`
  with `is_error`, opencode's `status: error`). An approval without the files of
  the blockers' lines is sent back, every result records `read_blocker_files`
  (`null` without reported tool calls). That the declaration itself was read cannot
  be checked. A blocker whose line is in no file of the copy (outside the root,
  no file id) fails closed: the suggestion is rejected without asking the agent.
* **Escape check:** the project's own source files are compared with their state
  before every agent call; a change aborts the run.
* The reviewer (§5.5) gets a copy with the changes applied and read-only tools.

The prompt contains a description of the suggestion in the style of the MCP server
(location, the directive DiscoPoP would generate without the blockers, noting that
its data sharing ignores them), each blocker in words, the code of the loop and
around the blockers with line numbers, the rules (§5.3) and the answer format
(§5.4). It does not contain any proposal of a fix.

Each blocker is described as: "RAW dependency: in one iteration, the statement at
`CommunicationVector.h:184` reads data which the statement at
`CommunicationVector.h:184` wrote in an earlier iteration", with the text of the
lines, the data involved and its origin (observed during profiling, or reported by
the static analysis). If a line calls a function, the access may happen inside it.

### 5.3 Prompt rules

**What counts as correct.** The same results as the sequential program in exact
arithmetic, for every input (output, files, returned values, state visible after
the loop). The only differences allowed are rounding differences from
floating-point operations in another order. Lost or duplicated updates, other
random numbers or the same ones in other places, another order of elements or
output, and another choice on ties are different results. Comments are hints about
intent, not facts. "Intent" in a wider sense (e.g. "only the distribution of the
random numbers matters") is deliberately not accepted: it would rest on the agent's
reading of the program's purpose.

**Correctness only.** Profitability is not the agent's question: it is measured
later with production inputs, much larger than the profiled run. The prompts say so
and tell the agent and the reviewer to assume the loop runs long enough, and never
to reject because the body looks small or a correct version needs more work. (Found
on relearn: a rejection "a restructuring the tiny body does not justify".)
Additional dependencies of larger inputs are left to the profiler.

Rounding differences are accepted by default, since they are usually acceptable,
but an approval declares them (§5.4), the reviewer checks the declaration, and
`--reject-rounding` rejects them. Small differences can grow where the results
decide comparisons or branches; the approval states whether they do, and only
`--verify run` with a tolerance can settle it.

* **Rejection is the default.** Approve only if every blocker is justified by code
  you have read. "Probably", "likely" or "usually" is a rejection.
* **Each blocker separately.** For every listed blocker, state why it does not
  make the parallel loop wrong, with file:line evidence. One blocker without a
  justification is a rejection.
* **Facts about the code only.** Do not rely on typical inputs or on code you have
  not read. If the answer depends on what callers do with the result, read them;
  if you cannot, reject.
* **Equal outcomes.** A rejection costs a missed speedup; a wrong approval gives
  wrong results. "Unsure" is a valid answer and is treated as a rejection.
* **State the assumption.** An approval names the property of the program it rests
  on ("the order of the entries of `neuron_requests_outgoing` does not matter,
  because …"), so a user can check it.

### 5.4 Answer format

One JSON object, extracted with patch repair's tolerant JSON reader; the changes are
in the workspace:

```json
{
  "verdict": "approved | rejected | unsure",
  "reason": "for rejected / unsure",
  "blockers": [ { "index": 1, "justification": "...", "evidence": ["file:line"] } ],
  "assumption": "for approved",
  "result_differences": "none | rounding, for approved"
}
```

Gates, cheapest first; a failed gate is fed back as the next turn:

1. the answer parses, and the verdict is one of the three;
2. an approval has a justification with `path:line` evidence of a project file for
   every blocker, an assumption, and declares `result_differences`;
3. only files with a file id changed, and in the changed code the loop's header line
   is directly preceded by a `parallel for` directive (not a comment, not another
   loop);
4. every changed file that holds neither the loop nor a blocker's line is cited in
   the evidence of some justification: changes outside the loop body belong to the
   blocker they resolve (the prompt asks for only what the parallel loop needs, the
   reviewer disagrees with unneeded or unexplained changes).

A rejection needs no evidence and is final, whatever the agent read: when unsure,
the safe side wins.

### 5.4a Prompt templates

The templates (check, review, follow-up) ship in `SuggestionCheck/prompts/`. A
project can replace each one; its version is stored in
`.discopop/project/prompts/suggestion_check/<name>.md` (kept by "Reset Project")
and edited in the GUI under Settings > Suggestion check prompts; `--prompt-dir`
names another directory. Saving the shipped text removes the project's version, so
later changes of the shipped template apply again. `results.json` records per
template whether the project's version was used and a fingerprint of it, so results
stay comparable. The rules of §5.3 then hold only as far as the project's version
keeps them; the gates (§5.4) are enforced either way.

### 5.5 Review and verification

1. **Review.** A second agent call with a fresh context gets the same facts, the
   approved patch, a copy with the changes applied (read-only), the justifications
   and the assumption, under the same rules,
   and answers `agree` or `disagree` with a reason. A disagreement rejects the
   suggestion. `--no-review` switches it off (the approval records that).
2. **Build** (`--verify build|run|none`, default `run`): the approved patch is
   compiled with the configuration's `compile.sh` through
   `discopop_auto_tuner -A 0 --compile-only`, via the opt-in of §6 restricted to
   this one suggestion.
3. **Run and validate** (`--verify run`): the same, without `--compile-only`, so
   `execute.sh` and `validate.sh` run. A program whose output depends on random
   numbers needs a `validate.sh` that tolerates it.

### 5.6 Artifacts under `.discopop/suggestion_check/`

```
suggestion_check/
    results.json          per suggestion: state, verification level, verdict, reason,
                          assumption, justifications, review, attempts, backend, model,
                          and the fingerprint of the explorer output it belongs to
    progress.jsonl        one line per event, for the GUI
    transcripts/<id>/     prompts and answers
    approved/<id>/        the approved patches, computed from the agent's copy
    approved.json         the approved suggestions, for consumers (§6)
```

`results.json` records the modification time and size of
`explorer/unsure_suggestions.json`. When the explorer runs again, earlier results
are stale; tools then ignore `approved.json`, and the GUI says so.

---

## 6. Consumers: opt in only

* **Autotuner:** `--include-agent-approved` reads `suggestion_check/approved.json`
  and `explorer/unsure_suggestions.json`, adds the approved ones to the pattern
  storage under the key `agent_approved` and copies their patches from
  `suggestion_check/approved/<id>/` into each configuration's `patch_generator/`.
  Without the flag, nothing changes. The check tool's verification (§5.5) uses the
  same mechanism, pointed at one candidate.
* **Patch applicator:** `--agent-approved` makes it look up ids it does not find in
  `patch_generator/` in `suggestion_check/approved/`.
* **MCP server:** `get_parallelization_suggestions` lists approved suggestions only
  with `include_agent_approved`, as a separate list with the assumption and the
  verification level.
* **GUI:** the suggestion table shows them only when a filter is switched on, with
  a distinct marker, the assumption and the verification level.
* **Optimizer, parallel region merger:** unchanged; they never see them.

---

## 7. GUI: the Suggestion Check stage

A Qt panel after *Patch Repair* in the workflow sidebar, built like it
(`qt_gui/panels/patch_repair_panel.py`, `services/patch_repair_view.py`,
`services/workflow_status.py`):

* settings: connection / backend / model, prompts and retries with the call-count
  caption, hotspot types, maximum number of suggestions, review on/off, verification
  `none` / `build` / `run`;
* `RunStopButton` starting `python -m discopop_library.SuggestionCheck`, progress
  from `progress.jsonl`;
* result table: suggestion, location, hotness, state, verification level; a detail
  view with the blockers, each justification, the assumption, the review and the
  diff between the plain and the approved patch;
* the stage is locked without `explorer/unsure_suggestions.json`, optional
  otherwise, stale when the explorer ran after the check.

---

## 8. Open points

* **The autotuner's search over approved suggestions.** An approved suggestion
  should probably never be combined with others before it was measured alone. To be
  decided when the opt-in is implemented.
* **Reductions with a blocker.** A loop with a recognized reduction and further
  blockers becomes an unsure `ReductionInfo`. Whether the agent handles those well
  is unknown.
* **Library code in the facts.** The explorer knows the line of the call in project
  code, not the library function the access happened in. If agents struggle with
  `this1` or `__i`, the profiler could record the callee.
* **Reads after the loop.** A measured "the data of this blocker is (not) read
  after the loop" would help the agent with state carried across iterations. It
  needs the dependencies from inside the loop to code after it, per blocker, not
  the classification (§4.3).
* **Determinism.** As for patch repair, agent answers are not reproducible;
  `results.json` records backend, model and transcripts.

---

## 9. Implementation order

Each step is reviewable on its own and leaves the tree working.

1. Explorer: `--unsure-suggestions`, `--unsure-max-blockers`, detection (§4.1, §4.2),
   `unsure_suggestions.json`, unit tests, end-to-end test.
2. ~~Patch generator: `patch_generator_unsure/`~~ (dropped, §4.4).
3. Check tool core: arguments, candidate selection, workspace, prompt and answer
   format, gates, review, `results.json`, tests with a scripted agent (no model).
4. Autotuner opt-in `--include-agent-approved` and the verification step (§5.5, §6).
5. Remaining consumers: patch applicator, MCP server, GUI suggestion table.
6. GUI stage (§7).
7. Documentation: `docs/tools/Suggestion_check.md`, explorer and patch generator pages.
8. Evaluation on relearn (BarnesHut) with a real model.
