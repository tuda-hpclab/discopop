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
- A command line coding agent on `PATH`: [opencode](https://opencode.ai) or [claude](https://claude.com/claude-code). The connection is configured as for [patch repair](Patch_repair.md), and the configuration file is shared with it.

## How it works
1. **The workspace.** Each attempt gets a fresh copy of the project: the files git knows of, or, outside a git repository, every file outside `.discopop` and `.git`. Files matching the project's fingerprint ignore patterns (`.discopop/project/fingerprint_ignore.json`, e.g. a build directory inside the project) are not copied, except for source files with a file id. The agent reads and changes files only there. Its tools are restricted on its command line: reading and editing files in the copy, no commands, no web access. For `claude` these are `--tools`, `--restricted`, `--strict-mcp-config` and `--permission-mode acceptEdits`; for `opencode`, permissions given in `OPENCODE_CONFIG_CONTENT`, without `--auto` (not yet verified against a real run). After every agent call, the project's own files are compared with their state before the run; if one changed, the run is aborted.
2. **The facts.** The agent gets a description of the suggestion as the MCP server gives it: the location, and the directive DiscoPoP would suggest without the blockers, whose data sharing ignores them. It also gets each blocker in words: which statement depends on which other statement in an earlier iteration, the data involved (as named in the compiled program, so possibly mangled or compiler generated), and whether it was observed during profiling or reported by the static analysis. The loop and the code around every blocker come with line numbers. The prompt states problems only and never proposes a fix. The excerpts are incomplete, so the agent must open, for every blocker, the declarations of the data involved, the functions called on its lines and the code after the loop that uses the data. The check records which files it opened (from the tool calls its backend reports): an approval without the files holding the blockers' lines is sent back, and every result records `read_blocker_files` (`null` if the backend reports no tool calls). This shows that the files were opened, not that the declarations were read.
   **DiscoPoP's data.** If `discopop_mcp_server` is found, the agents also get two of its tools: `get_side_effects` (what a function reads and writes, including through its callees) and `explain_parallelization` (why DiscoPoP did or did not parallelize lines, with the dependencies). The server runs with `--tools readonly --project <project>`, so it changes nothing, works only on this project and never forwards to a daemon; for `claude` only these two tools are allowed (`--allowedTools`), with `--strict-mcp-config` as before. The answers describe the profiled runs: evidence, not proof. `--no-discopop-tools` switches this off; `results.json` records it (`discopop_tools`: `on`, `off`, `unavailable`).
3. **The verdict.** The agent answers `approved`, `rejected` or `unsure`. A rejection, and `unsure`, are final. Correct means the same results as the sequential program in exact arithmetic, for every input: the only differences allowed are rounding differences from floating-point operations in another order. Other random numbers, another order of elements or output, lost updates or another choice on ties are different results. An approval must give a justification with `path:line` evidence for every blocker, state its assumption, and declare `result_differences`: `none` (identical results) or `rounding`. Rounding approvals are accepted by default and marked as such; `--reject-rounding` rejects them. The changes in the copy must touch only source files with a file id, and the loop must then be directly preceded by a `parallel for` directive, with its header line unchanged. The agent changes only what the parallel loop needs; a change outside the loop body belongs to the justification of the blocker it resolves, and a changed file that holds neither the loop nor a blocker's line must be cited in some justification's evidence. The reviewer disagrees with changes that are not needed or not explained. Rejections need no evidence: they are always taken as they are. The agent and the reviewer judge correctness only: whether parallelizing pays off is measured later (e.g. by the autotuner) with production inputs, which are much larger than the profiled run, so a small loop body or a larger correct rewrite is no reason to reject. Otherwise the problem is sent back for another turn in the same copy. DiscoPoP computes the patch from the changes: a changed file is matched to the project file of the same relative path (with symbolic links resolved), and its new content is diffed against that file, so the patch names the project's files, never the copy. Source files outside the project root are not part of the copy. The check never writes into the project, not even temporarily.
4. **The review.** A second agent call with a fresh conversation, in a read-only copy with the changes applied, checks the approval under the same rules. If it disagrees, or its answer cannot be read, the suggestion is rejected. `--no-review` switches the review off.
5. **Verification.** Building and running an approved suggestion (`--verify build|run`) is not implemented yet. Approvals are recorded with the verification level `static`.

## Output
In `.discopop/suggestion_check/`:

| File | Content |
|---|---|
| `results.json` | Every checked suggestion: state (`approved`, `rejected`, `failed`), the agent's verdict and reason, the assumption, the justifications, the declared result differences, the review, the verification level and the number of agent calls. |
| `approved.json` | The approved suggestions with their assumptions and declared result differences, for tools that use them on request. |
| `approved/<id>/<file id>.patch` | The approved patches, computed from the agent's changes. |
| `transcripts/<id>/` | Every prompt and answer; per agent call also the backend's event stream (`*_events.jsonl`) and the tool calls taken from it (`*_tools.txt`: which files the agent read, what it searched for, what it changed). `results.json` counts them per suggestion (`tool_calls`). |
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
| `--project-root <path>` | the directory holding `.discopop` | The project the agent gets a copy of. |
| `-s`, `--suggestions <ids>` | all | Comma separated ids of the unsure suggestions to check. |
| `--max-suggestions <n>` | 0 (no limit) | Check at most this many. |
| `--prompts <n>` | 2 | Independent attempts per suggestion, each with a new conversation and a fresh copy of the project. |
| `--retries <n>` | 2 | Follow-up turns within one attempt for answers that cannot be used. |
| `--agent-error-retries <n>` | 2 | Calls without an answer allowed per suggestion; they do not use up the attempts. |
| `--no-review` | review on | Do not have approvals reviewed. |
| `--reject-rounding` | accepted | Reject approvals whose results may differ by rounding. |
| `--no-discopop-tools` | on, if `discopop_mcp_server` is found | Do not give the agents DiscoPoP's data through the MCP server. |
| `--prompt-dir <path>` | `.discopop/project/prompts/suggestion_check` | The project's own prompt templates (`check.md`, `review.md`, `retry.md`); a template not found there is the shipped one. The GUI edits them under Settings > Suggestion check prompts. `results.json` records per template whether the project's version was used, and a fingerprint of it. |
| `--verify none` | `none` | `build` and `run` are not implemented yet. |
| `--connection`, `--backend`, `--model`, `--llm-config` | | The agent, as for [patch repair](Patch_repair.md). |
| `--agent-timeout <s>` | 600 | Seconds per agent call. |
| `--log`, `--write-log` | `WARNING` | Logging. |
