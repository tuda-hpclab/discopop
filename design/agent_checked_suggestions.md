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
* the patch generator writes the plain do-all patch for each of them, **marked as
  incorrect** and stored where no existing tool looks;
* a new tool, `discopop_suggestion_check`, built like
  [patch repair](patch_repair.md), hands each one to an agent, which either
  rejects it or changes the patch so the parallel version is correct, and states
  the assumption this rests on;
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
| An unsure suggestion is not a suggestion. | Its patch is the plain do-all, known to be incorrect without a change. It never appears where tools look for suggestions (§3). |
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
| **blocker** | One such dependency: type, variable, memory region, source and sink line, origin (dynamic or static), element access. |

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
| `explorer/unsure_suggestions_dump.json` | the same suggestions as jsonpickled `DoAllInfo` / `ReductionInfo`, for the autotuner opt-in (§6) |
| `patch_generator_unsure/<id>/<file_id>.patch` | the plain patches, written by the patch generator (§4.4) |
| `suggestion_check/` | the check tool's artifacts, its results and the approved patches (§5.6) |

**Pattern ids** come from the same allocator as the safe ones, but are allocated
after all detectors have run (§4.2). The ids of the safe suggestions are therefore
the same with and without unsure suggestions, and an unsure id never collides with
a safe one, so an opted-in consumer can put both into one `PatternStorage`.

---

## 4. Explorer and patch generator

### 4.1 Which loops become unsure suggestions

Off by default; `--unsure-suggestions` turns it on. A loop qualifies when

1. it is a do-all candidate that was rejected, and every reason is
   `loop_carried_dependency` or `unprivatizable_static_dependency`. A loop also
   rejected for an early exit, too few iterations, a missing pattern node or as a
   duplicate does not qualify: an agent cannot change those facts;
2. it has at most `--unsure-max-blockers` distinct blockers (default 4). A loop with
   many dependencies between its iterations is not a near miss;
3. no copy of it was reported as a safe suggestion.

The hotspot filter of the explorer (`--hotspot-types`) applies as for every other
pattern. The check tool filters by hotspot type again, like patch repair.

### 4.2 Detection

`identify_simple_doall_and_reduction` already scans all blocking dependencies with
`--all-blocking-dependencies`. With `--unsure-suggestions` it scans all of them
too, independent of the decision log, and keeps for a rejected loop its first copy,
iteration contexts and blockers. After the scan, each qualifying loop is classified
exactly like a safe candidate (`detect_doall_sharing_clauses`, reductions from the
reduction scan), so its plain patch carries the clauses a safe suggestion would
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
          "type": "RAW", "variable": "this1", "memory_region": "...",
          "source_line": "12:184", "sink_line": "12:184", "origin": "dynamic",
          "source_code": "neuron_requests_outgoing.append(...)",
          "sink_code": "neuron_requests_outgoing.append(...)"
        }
      ],
      "read_after_loop": ["..."]
    }
  ]
}
```

* `blockers` are the `DependencyRecord`s of `pattern_decisions.json`, plus the text
  of the source and sink lines, de-duplicated.
* `read_after_loop` lists the blocker variables that are also read after the loop
  with a value written inside it (`last_private` candidates among the blockers). It
  is a measured fact, and decisive for state carried across iterations.
* Lines are `file_id:line`; the check tool resolves them with `FileMapping.txt`.

### 4.4 Patch generator

When `explorer/unsure_suggestions.json` exists, `discopop_patch_generator` also
writes the plain patch of each unsure suggestion to
`patch_generator_unsure/<id>/<file_id>.patch`, with the code generation used for
safe do-all and reduction patterns. The directory is removed and rewritten on
every run, like `patch_generator/`.

---

## 5. `discopop_suggestion_check`

### 5.1 Reused from patch repair

* the agent backends and their configuration (`PatchRepair/llm_backends`,
  `llm_config.py`); the default configuration file is patch repair's, so a
  connection is set up once;
* `patching.py`: dry-run apply, canonicalization against the pristine source,
  pragma guard (the change must keep the loop's `parallel for`);
* the attempt budget (`--prompts`, `--retries`, `--agent-error-retries`,
  `--max-attempts`) and the hotspot filter (`--hotspot-types`, default `yes,maybe`).

### 5.2 What the agent gets

The agent needs to read code beyond the loop: who uses the appended requests, where
the generator is declared, what a called function does. Unlike patch repair it
therefore runs in a **throwaway copy of the project sources**, with permission to
read. Anything it writes lands in the copy and is discarded; the tool checks that
the project itself is unchanged afterwards.

The prompt contains:

* the loop with line numbers, and the plain patch;
* each blocker, in words: "Iteration *i* writes `this1` at
  `CommunicationVector.h:184` (`neuron_requests_outgoing.append(...)`) and a later
  iteration reads it at the same line" — with its origin (measured during
  profiling, or reported by the static analysis);
* for accesses inside called code: the line in the project that made the call;
* which blocker variables are read after the loop;
* the conservative rules (§5.3) and the answer format (§5.4).

It does not contain any proposal of a fix.

### 5.3 Prompt rules

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

One JSON object, extracted with patch repair's tolerant JSON reader:

```json
{
  "verdict": "approved | rejected | unsure",
  "reason": "for rejected / unsure",
  "blockers": [ { "index": 0, "justification": "...", "evidence": ["file:line"] } ],
  "assumption": "for approved",
  "patch": "unified diff against the original source, for approved"
}
```

Gates, cheapest first; a failed gate is fed back as the next turn, like patch repair:

1. the answer parses, and the verdict is one of the three;
2. an approval has a justification for every blocker index and an assumption;
3. the patch applies, canonicalizes and keeps the loop's `parallel for` (patch
   repair's gates).

### 5.5 Review and verification

1. **Review.** A second agent call with a fresh context gets the same facts, the
   approved patch, the justifications and the assumption, under the same rules,
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
    approved/<id>/        the approved, canonical patches
    approved.json         the approved suggestions, for consumers (§6)
```

`results.json` records the modification time and size of
`explorer/unsure_suggestions.json`. When the explorer runs again, earlier results
are stale; tools then ignore `approved.json`, and the GUI says so.

---

## 6. Consumers: opt in only

* **Autotuner:** `--include-agent-approved` reads `suggestion_check/approved.json`
  and `explorer/unsure_suggestions_dump.json`, adds the approved ones to the
  pattern storage under the key `agent_approved` and copies their patches from
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
* **Determinism.** As for patch repair, agent answers are not reproducible;
  `results.json` records backend, model and transcripts.

---

## 9. Implementation order

Each step is reviewable on its own and leaves the tree working.

1. Explorer: `--unsure-suggestions`, `--unsure-max-blockers`, detection (§4.1, §4.2),
   `unsure_suggestions.json` and its dump, unit tests, end-to-end test.
2. Patch generator: `patch_generator_unsure/` (§4.4), tests.
3. Check tool core: arguments, candidate selection, prompt and answer format, gates,
   review, `results.json`, tests with a scripted backend (no model).
4. Autotuner opt-in `--include-agent-approved` and the verification step (§5.5, §6).
5. Remaining consumers: patch applicator, MCP server, GUI suggestion table.
6. GUI stage (§7).
7. Documentation: `docs/tools/Suggestion_check.md`, explorer and patch generator pages.
8. Evaluation on relearn (BarnesHut) with a real model.
