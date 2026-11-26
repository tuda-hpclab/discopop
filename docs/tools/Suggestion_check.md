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

The suggestion check hands such loops to an LLM agent. The agent decides, from the code, whether the loop may run in parallel, and if so changes the patch accordingly and names the assumption this rests on. It is conservative by design: rejection is the default, and an approval has to justify every blocker with code.

**An approved suggestion is not a DiscoPoP suggestion.** It rests on the agent's judgment, not on measured data. It is stored apart from DiscoPoP's suggestions, together with its assumption, and no other tool uses it unless asked to. The design is described in `design/agent_checked_suggestions.md`.

## Required input
- `explorer/unsure_suggestions.json`, written by `discopop_explorer --unsure-suggestions` (see [Explorer](Explorer.md)), and the plain patches in `patch_generator_unsure/`, written by the [patch generator](Patch_generator.md).
- `FileMapping.txt`.
- A command line coding agent on `PATH`: [opencode](https://opencode.ai) or [claude](https://claude.com/claude-code). The connection is configured as for [patch repair](Patch_repair.md), and the configuration file is shared with it.

## How it works
1. **The facts.** For each unsure suggestion the agent gets the loop and the code around every blocker with line numbers, the plain patch, and each blocker in words: which statement depends on which other statement in an earlier iteration, the data involved (as named in the compiled program, so possibly mangled or compiler generated), and whether it was observed during profiling or reported by the static analysis. The prompt states problems only. It never proposes a fix.
2. **The verdict.** The agent answers `approved`, `rejected` or `unsure`. A rejection, and `unsure`, are final. An approval must give a justification with file:line evidence for every blocker, state its assumption, and contain the complete patch as a diff against the original source. An approval that is incomplete, or whose patch does not apply or no longer contains the loop's directive, is sent back for another turn.
3. **The review.** A second agent call with a fresh conversation checks the approval under the same rules. If it disagrees, or its answer cannot be read, the suggestion is rejected. `--no-review` switches the review off.
4. **Verification.** Building and running an approved suggestion (`--verify build|run`) is not implemented yet. Approvals are recorded with the verification level `static`.

The agent currently gets no tools: everything it may use is in the prompt. If it would need code that is not shown, the rules make it answer `unsure`.

## Output
In `.discopop/suggestion_check/`:

| File | Content |
|---|---|
| `results.json` | Every checked suggestion: state (`approved`, `rejected`, `failed`), the agent's verdict and reason, the assumption, the justifications, the review, the verification level and the number of agent calls. |
| `approved.json` | The approved suggestions with their assumptions, for tools that use them on request. |
| `approved/<id>/<file id>.patch` | The approved patches. |
| `transcripts/<id>/` | Every prompt and answer. |
| `progress.jsonl` | One line per event. |

`failed` means that no usable answer was obtained (agent unreachable, or no answer that could be read within the attempt budget). It is not an approval either.

The results belong to one run of the explorer. After the explorer has run again, the next check discards them, since the ids may now name other loops.

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
| `-s`, `--suggestions <ids>` | all | Comma separated ids of the unsure suggestions to check. |
| `--max-suggestions <n>` | 0 (no limit) | Check at most this many. |
| `--prompts <n>` | 2 | Independent attempts per suggestion, each with a new conversation. |
| `--retries <n>` | 2 | Follow-up turns within one attempt for answers that cannot be used. |
| `--agent-error-retries <n>` | 2 | Calls without an answer allowed per suggestion; they do not use up the attempts. |
| `--no-review` | review on | Do not have approvals reviewed. |
| `--verify none` | `none` | `build` and `run` are not implemented yet. |
| `--connection`, `--backend`, `--model`, `--llm-config` | | The agent, as for [patch repair](Patch_repair.md). |
| `--agent-timeout <s>` | 600 | Seconds per agent call. |
| `--log`, `--write-log` | `WARNING` | Logging. |
