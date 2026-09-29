---
layout: default
title: Patch repair
parent: Tools
nav_order: 5
---

# DiscoPoP Patch Repair
## Executable
`discopop_patch_repair`

## Purpose
Find the parallelization suggestions whose generated patch does not compile, ask a configurable LLM agent to fix the patch, verify the fix, and write it back.

A suggestion whose patch does not build is one the [autotuner](Autotuner.md) can only ever record as a failure: it is compiled, it fails, and it is dropped from the search. This tool sits between pattern detection and tuning and tries to turn those into usable suggestions. Suggestions that already compile, and suggestions whose repair does not succeed within the configured budget, are **left exactly as they were**.

## Required input
- `Prepared patch files` created by the [patch generator](Patch_generator.md)
- `Parallel patterns` in the form of a `JSON` file, created by the [Explorer](Explorer.md)
- An `execution configuration` created by the [project manager](Project_manager.md), providing the `compile.sh` used to build the candidate code
- A command line coding agent on `PATH`: [opencode](https://opencode.ai) or [claude](https://claude.com/claude-code). DiscoPoP never handles credentials -- the agent owns provider authentication.
- Optionally, `Detected hotspots`, which let cold suggestions be skipped

## How it works
1. **Discovery.** One `discopop_auto_tuner -A 0 --compile-only` run builds every considered suggestion on its own and reports which of them fail. The compiler's diagnostics are read from `execution_results.json`, which lives in the original project and therefore survives the deletion of the project copy that produced them.
2. **Repair.** Each failing suggestion is handed to the agent together with its patch, the source before and after the patch, and the compiler's output. The agent answers with a corrected patch -- it is never given write access to the project.
3. **Verification.** The answer passes six checks before anything is stored, and the suggestion is rebuilt with the candidate in place. Only a candidate that builds is kept.

If the *reference* configuration does not build -- the project without any suggestion applied -- the run stops immediately. No candidate's failure says anything about its patches in that case.

The tool also refuses to run -- `--restore` included -- while any suggestion is applied to the project sources (see the [patch applicator](Patch_applicator.md)). The applicator rolls a suggestion back with the patch that is on disk at that time, so replacing the patch of an applied suggestion would make it impossible to remove, and every candidate would be built on top of the applied code. Roll back first with `discopop_patch_applicator -C`.

A candidate is written to `patch_generator/<id>/` only for its verification build. Whatever ends that build -- a failure, an error, `Ctrl+C` -- the directory is put back byte for byte unless the candidate built, and under `--dry-run` it is put back in every case.

## The attempt budget
Two nested dials, and the distinction matters:

| Flag | Meaning |
|------|---------|
| `--prompts N` | Independent attempts, each with a **fresh context**, using the next rung of the prompt ladder. A later attempt asks a *better question* rather than the same one again. |
| `--retries M` | Follow-up turns **inside** one attempt. The conversation continues, so the model sees its own previous answer and is told only what was wrong with it. |

At most `N x (1 + M)` agent calls are made per suggestion, further capped by `--max-attempts`. A suggestion stops the moment a candidate is accepted.

### A call that never reaches the model is not an attempt
`N x (1 + M)` bounds how many times a **model** is asked. A call that produces no answer at all -- an unreachable provider, a server error, no response within `--agent-timeout` -- costs no tokens and gives the model no chance, so it does not consume a prompt or a retry. It is repeated in place instead, bounded by its own allowance:

| Flag | Meaning |
|------|---------|
| `--agent-error-retries K` | Extra calls allowed per suggestion when a call produces no answer. Default: 2. |

Without that separation a flaky endpoint spends the whole budget without the model ever seeing the prompt, and the suggestion is then recorded as one a model could not repair. That is not a small distinction: it is the difference between a finding about a model and a finding about an outage, and only one of them is fixed by changing the prompt.

Once the allowance is used up the suggestion is recorded as `agent_unreachable` rather than `failed`, the run's summary counts it separately (`Agent unreachable: N (no answer; not a failed repair)`), and the GUI shows it in its own colour. `results.json` carries `attempts` (every call made) next to `unanswered` (how many of them never reached a model), so a run where the agent misbehaved is visible without reading the transcripts.

The prompt ladder goes from terse to increasingly explicit: the patch and the diagnostics; then the source with line numbers; then DiscoPoP's own findings for the region (its shared, private, firstprivate and reduction variables), which is usually exactly what a missing-clause error needs.

## Controlling the cost
Every repair costs agent tokens and at least one build, so the default is deliberately narrow:

- `--hotspot-types` defaults to `yes,maybe`. A suggestion classified `NO` contributes negligibly to the runtime, so repairing it spends effort on code that will never be worth parallelizing. Where no hotspot information exists every suggestion counts as `YES` and nothing is skipped.
- `-s/--suggestions` restricts the run to explicit ids, overriding the hotspot filter. The compile checks build exactly the considered ids, whatever their hotspot type, including suggestions the hotspot loader could not classify.
- `--max-repairs` stops after a given number of successful repairs.
- `--dry-run` performs the whole pipeline but leaves `patch_generator/` as it found it. Note that a candidate is still *built* to check it, so a patch file is written and put back; the run ends with the file exactly as it started.

## When a repair is accepted
A candidate must pass all of these:

1. **Extraction** -- the answer contains a patch block per file it changes.
2. **Apply** -- the whole patch set applies. A suggestion's patches are indivisible (the [patch applicator](Patch_applicator.md) rolls back a partial application), so one rejected file rejects the set.
3. **Canonicalization** -- the patch is re-derived from the code it produces, with the patch generator's own `diff -Naru`. A stored repaired patch is therefore indistinguishable in form from a generated one, and the model's line numbers only have to be close enough for `patch` to apply.
4. **The parallelization is still there** -- every OpenMP directive the original patch added must still be added. This check is what keeps a green build honest: an agent can always make a compiler error go away by deleting the directive, which compiles and silently turns the suggestion into a no-op. Changing a directive's *clauses* is allowed, and is the expected fix.
5. **It compiles** -- the suggestion is rebuilt with the candidate in place.

## Choosing a model
The agent, the model and their settings are configured in `.discopop/patch_repair/llm_config.json`, in two sections:

- **connections** -- part of the experiment: which model, through which backend, with which defaults for prompts, retries and timeout.
- **backends** -- part of the *installation*: where that agent's executable is on this machine, and what every connection through it should default to.

They are separate because they answer different questions: a connection means the same on any machine, an install path does not. Settings resolve most-specific-first, and **no credentials are stored**.

For a one-off run nothing needs configuring: `--backend` and `--model` override whatever is stored, and with exactly one agent installed even those can be omitted.

```
discopop_patch_repair --backend opencode --model openai/gpt-5.4-mini
```

## Output
Written to `.discopop/patch_repair/`:

| Path | Contents |
|------|----------|
| `results.json` | One record per considered suggestion: status (`ok`, `repaired`, `failed`, `not_applied`, `agent_unreachable`, `skipped`), hotspot type, the files in its patch set and which of them a repair changed, attempts and how many of them went unanswered, backend, model, first error |
| `progress.jsonl` | The structured event stream, so a finished run can be redisplayed without repeating it |
| `backups/<id>/` | The patch set as the generator produced it, copied aside before the first overwrite. `backups/<id>.written` records the digest of the patch set a repair left in place |
| `attempts/<id>/<n>/` | What was sent, what came back, the extracted and canonicalized patches, and which check rejected them |

Repaired patches replace the originals in `patch_generator/<id>/`, all of a suggestion's files or none of them. `--restore` puts the backups back, so a repair run is always reversible without re-running the patch generator. A backup belongs to one generation of patches: when the patch generator has rewritten a suggestion's patches since, the next repair replaces the stale backup, and `--restore` leaves the newer patches alone and drops it.

The attempt transcripts are the main surface for judging a repair, and for working on the prompts; they are written unconditionally.

## Graphical interface
The tool is also available from the **Patch Repair** tab of the [project manager](Project_manager.md) GUI, between *Pattern Detection* and *Autotuning*. The tab shows the outcome per suggestion and the generated and repaired patch side by side, so a repair can be read before it is trusted.

## Limitations
- The answer of a language model is not reproducible: the same run can yield different patches. `results.json` records the backend, the model and the accepted attempt.
- Every suggestion is compiled on its own, so a patch set that builds in isolation but conflicts with another suggestion's patches is out of this tool's reach by construction. That is the [autotuner](Autotuner.md)'s domain.
- Only compilation is repaired. A suggestion that builds but produces a wrong result, or no speedup, is not this tool's concern.

## Note
For a more detailed description of the available run-time arguments, please refer to the help string of the respective tool.
