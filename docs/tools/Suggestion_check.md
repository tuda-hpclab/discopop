---
layout: default
title: Suggestion check
parent: Tools
nav_order: 9
---

# Suggestion check
## Executable
`discopop_suggestion_check`

## Purpose
Some loops are almost parallelizable: a few dependencies between their iterations, the *blockers*, keep DiscoPoP from suggesting them. Whether these dependencies matter depends on what the program is meant to do, which no analysis of the profile can decide. Examples are a random number generator whose sequence only has to be statistically equivalent, or requests appended to a list whose order does not matter.

The suggestion check hands such loops to an LLM agent working in a throwaway copy of the project. The agent decides, from the code, whether the loop may run in parallel. If so, it changes the code in its copy, including the loop's OpenMP directive, and names the assumption this rests on; DiscoPoP computes the patch from these changes. It is conservative by design: rejection is the default, and an approval has to justify every blocker with code.

**An approved suggestion is not a DiscoPoP suggestion.** It rests on the agent's judgment, not on measured data. It is stored apart from DiscoPoP's suggestions, together with its assumption, and no other tool uses it unless asked to. The design is described in `design/agent_checked_suggestions.md`.

## Required input
- `explorer/unsure_suggestions.json`, written by `discopop_explorer --unsure-suggestions` (see [Explorer](Explorer.md)).
- `FileMapping.txt`.
- Optionally, `Detected hotspots` (`hotspot_detection/Hotspots.json`), which let cold suggestions be skipped.
- A command line coding agent on `PATH`: [opencode](https://opencode.ai) or [claude](https://claude.com/claude-code). The connection is configured as for [patch repair](Patch_repair.md#choosing-a-model), and the configuration file is shared with it; the GUI edits it under *Settings > LLM connections…* and *Settings > LLM backends…*.

## How it works
**The hotspot filter.** Every check costs agent calls, which a loop that hardly contributes to the runtime is not worth. As in [patch repair](Patch_repair.md#controlling-the-cost), a suggestion is classified `YES`, `MAYBE` or `NO` by the hotspot loops starting within the lines of its pattern (`start_line` to `end_line` as the explorer wrote them; `YES` is matched first, then `NO`, then `MAYBE`), with the rule patch repair applies to DiscoPoP's suggestions. Only the types of `--hotspot-types` (default `yes,maybe`) are checked; the others are skipped, printed (`Skipped N cold suggestion(s), ...`) and listed in `results.json` (`skipped_by_hotspot`, with their type). Without hotspot results every suggestion counts as `YES` and nothing is skipped; with hotspot results, a suggestion no hotspot loop matches is checked (`unknown`), as there is nothing to filter it by. Ids given with `-s` are checked whatever their type. `--max-suggestions` counts the checked suggestions only.

1. **The workspace.** Each attempt gets a fresh copy of the project: the files git knows of, or, outside a git repository, every file outside `.discopop` and `.git`. Files matching the project's fingerprint ignore patterns (`.discopop/project/fingerprint_ignore.json`, e.g. a build directory inside the project) are not copied. Every source file with a file id inside the project root is copied, also one git ignores or an ignore pattern names. The agent reads and changes files only there. Its tools are restricted on its command line: reading and editing files in the copy, no commands, no web access. For `claude` these are `--tools`, `--restricted`, `--strict-mcp-config` and `--permission-mode acceptEdits`; for `opencode`, permissions given in `OPENCODE_CONFIG_CONTENT`, without `--auto` (not yet verified against a real run). After every agent call, the project's own files are compared with their state before the run; if one changed, the run is aborted.
2. **The facts.** The agent gets a description of the suggestion as the MCP server gives it: the location, and the directive DiscoPoP would suggest without the blockers, whose data sharing ignores them. It also gets each blocker in words: which statement depends on which other statement in an earlier iteration, the data involved (as named in the compiled program, so possibly mangled or compiler generated), and whether it was observed during profiling or reported by the static analysis. The loop and the code around every blocker come with line numbers. The prompt states problems only and never proposes a fix. The excerpts are incomplete, so the agent must open, for every blocker, the declarations of the data involved, the functions called on its lines and the code after the loop that uses the data. The check records which files it opened (from the tool calls its backend reports): only reading (`Read`, `View`) and editing (`Edit`, `MultiEdit`, which need the file read before) count; `Write`, searches, DiscoPoP's MCP tools and calls the backend reports as failed do not. An approval without the files holding the blockers' lines is sent back, and every result records `read_blocker_files` (`null` if the backend reports no tool calls). This shows that the files were opened, not that the declarations were read. A suggestion with a blocker whose line is in no file of the copy (outside the project root or without a file id) is rejected without asking the agent, as its reading could not be checked.
   **DiscoPoP's data.** If `discopop_mcp_server` is found (as a command, else as the module `mcp_server.server` of the running Python) and supports `--tools readonly --project`, the agents also get two of its tools: `get_side_effects` (what a function reads and writes, including through its callees) and `explain_parallelization` (why DiscoPoP did or did not parallelize lines, with the dependencies). The server runs with `--tools readonly --project <project root>`, so it changes nothing (it writes no log either), works only on this project and never forwards to a daemon; it reads `<project root>/.discopop`, so if the data of the check is elsewhere (`--dot-dp-path` not the `.discopop` of `--project-root`), the agents work without it. The tools take a `file_path` relative to the project root; for `claude` only these two tools are allowed (`--allowedTools`), with `--strict-mcp-config` as before. The answers describe the profiled runs: evidence, not proof. `--no-discopop-tools` switches this off; `results.json` records it (`discopop_tools`: `on`, `off`, `unavailable`, or `failed` once the backend reported that the server did not start; only `claude` reports this).
3. **The verdict.** The agent answers `approved`, `rejected` or `unsure`. A rejection, and `unsure`, are final. Correct means the same results as the sequential program in exact arithmetic, for every input: the only differences allowed are rounding differences from floating-point operations in another order. Other random numbers, another order of elements or output, lost updates or another choice on ties are different results. An approval must give a justification with `path:line` evidence for every blocker, state its assumption, and declare `result_differences`: `none` (identical results) or `rounding`. Rounding approvals are accepted by default and marked as such; `--reject-rounding` rejects them. The changes in the copy must touch only source files with a file id, and the loop must then be directly preceded by a `parallel for` directive, with its header line unchanged. The agent changes only what the parallel loop needs; a change outside the loop body belongs to the justification of the blocker it resolves, and a changed file that holds neither the loop nor a blocker's line must be cited in some justification's evidence. The reviewer disagrees with changes that are not needed or not explained. Rejections need no evidence: they are always taken as they are. The agent and the reviewer judge correctness only: whether parallelizing pays off is measured later (e.g. by the autotuner) with production inputs, which are much larger than the profiled run, so a small loop body or a larger correct rewrite is no reason to reject. Otherwise the problem is sent back for another turn in the same copy. DiscoPoP computes the patch from the changes: a changed file is matched to the project file of the same relative path (with symbolic links resolved), and its new content is diffed against that file, so the patch names the project's files, never the copy. Source files outside the project root are not part of the copy. The check never writes into the project, not even temporarily.
4. **The review.** A second agent call with a fresh conversation, in a read-only copy with the changes applied, checks the approval under the same rules. If it disagrees, or its answer cannot be read, the suggestion is rejected. `--no-review` switches the review off.
5. **Verification.** Building and running an approved suggestion (`--verify build|run`) is not implemented yet. Approvals are recorded with the verification level `static`.

## Output
In `.discopop/suggestion_check/`:

| File | Content |
|---|---|
| `results.json` | Every checked suggestion: state (`approved`, `rejected`, `failed`), the agent's verdict and reason, the assumption, the justifications, the declared result differences, the review, the verification level, the number of agent calls and its hotspot type (`hotspot_type`: `yes`, `maybe`, `no`, `unknown`). `skipped_by_hotspot` lists the suggestions the last run skipped by the hotspot filter (`pattern_id`, `hotspot_type`). |
| `approved.json` | The approved suggestions with their assumptions and declared result differences, for tools that use them on request. |
| `approved/<id>/<file id>.patch` | The approved patches, computed from the agent's changes. |
| `transcripts/<id>/` | Every prompt and answer; per agent call also the backend's event stream (`*_events.jsonl`) and the tool calls taken from it (`*_tools.txt`: which files the agent read, what it searched for, what it changed). `results.json` counts them per suggestion (`tool_calls`). |
| `progress.jsonl` | One line per event: `skipped_by_hotspot` (if any were skipped), `start`, then `check` and `done` per suggestion, `end` or `aborted`. |

`failed` means that no usable answer was obtained (agent unreachable, or no answer that could be read within the attempt budget). It is not an approval either.

The results belong to one run of the explorer. After the explorer has run again, the next check discards them, since the ids may now name other loops.

## Using approved suggestions
Approvals are used by no other tool by themselves. On request, they are copied to where the other tools look for patches:

```bash
discopop_suggestion_check --publish-approved          # all approvals of the last check
discopop_suggestion_check --publish-approved -s 12,15 # only these
discopop_suggestion_check --withdraw-published        # take them back (all, or those of -s)
```

`--publish-approved` copies the patches of the approved suggestions to `patch_generator/<id>/` and writes a marker, `agent_approved.json`, with the assumption the approval rests on and its declared result differences. The patch applicator, patch repair and the GUI then treat them as suggestions; the autotuner searches them only with `--include-agent-approved`; the GUI labels them *agent-approved*. A directory the patch generator wrote is never replaced, and approvals of an earlier explorer run are not published (check them again). `--withdraw-published` removes only directories with the marker. Neither option checks anything.

In the GUI, the *Suggestion Check* stage runs the check and shows its results; **Use approved suggestions** and **Withdraw** do the same as these options (see [GUI](GUI.md#suggestion-check)).

## Example
```bash
cd .discopop
discopop_explorer --unsure-suggestions
discopop_suggestion_check --backend opencode --model <provider/model>
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--dot-dp-path <path>` | current directory | The `.discopop` directory. |
| `--project-root <path>` | the directory holding `.discopop` | The project the agent gets a copy of. |
| `-s`, `--suggestions <ids>` | all | Comma separated ids of the unsure suggestions to check, whatever their hotspot type. |
| `-ht`, `--hotspot-types <types>` | `yes,maybe` | Hotspot types to check (`yes`, `maybe`, `no`), as for patch repair; the others are skipped. Without hotspot results every suggestion counts as `yes`. |
| `--max-suggestions <n>` | 0 (no limit) | Check at most this many (of those the hotspot filter leaves). |
| `--prompts <n>` | 2 | Independent attempts per suggestion, each with a new conversation and a fresh copy of the project. |
| `--retries <n>` | 2 | Follow-up turns within one attempt for answers that cannot be used. |
| `--agent-error-retries <n>` | 2 | Calls without an answer allowed per suggestion; they do not use up the attempts. |
| `--no-review` | review on | Do not have approvals reviewed. |
| `--reject-rounding` | accepted | Reject approvals whose results may differ by rounding. |
| `--no-discopop-tools` | on, if `discopop_mcp_server` is found | Do not give the agents DiscoPoP's data through the MCP server. |
| `--prompt-dir <path>` | `.discopop/project/prompts/suggestion_check` | The project's own prompt templates (`check.md`, `review.md`, `retry.md`); a template not found there is the shipped one. The GUI edits them under Settings > Suggestion check prompts. `results.json` records per template whether the project's version was used, and a fingerprint of it. |
| `--publish-approved` | | Check nothing; make the approvals (all, or those of `-s`) usable by the other tools (see above). |
| `--withdraw-published` | | Check nothing; remove published approvals again (all, or those of `-s`). |
| `--verify none` | `none` | `build` and `run` are not implemented yet. |
| `--connection`, `--backend`, `--model`, `--llm-config` | | The agent, as for [patch repair](Patch_repair.md). |
| `--agent-timeout <s>` | 600 | Seconds per agent call. |
| `--log`, `--write-log` | `WARNING` | Logging. |
