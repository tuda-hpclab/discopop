---
layout: default
title: Empirical autotuner
parent: Tools
nav_order: 9
---

# Empirical autotuner
## Executable
`discopop_auto_tuner`

## Purpose
Identify the best configuration of parallel code which is achievable by applying a combination of the parallelization suggestions found by the [DiscoPoP Explorer](Explorer.md). Internally, the [DiscoPoP patch applicator](Patch_applicator.md) is used to create different parallel codes, which will be compiled, executed, and evaluated based on the observed execution time and result validity.

## Search algorithms
The search algorithm is selected with `-A/--algorithm`. Note that the default, `-A 0`, does **not** combine suggestions: it measures every suggestion on its own.

| `-A` | Algorithm | Notes |
|------|-----------|-------|
| `0`  | No combination (measure only) | Default. Measures each suggestion individually. |
| `1`  | Linear combination | Accumulates suggestions that keep the result valid; does not require a speedup. |
| `3`  | Evolutionary combination | Genetic search. Uses randomness, so results are not reproducible. |
| `4`  | Greedy forward search | One pass over all suggestions, `O(N)` evaluations. |
| `5`  | Coordinate descent | Repeated bit-flip passes until no pass improves the runtime. |
| `6`  | Hotspot-guided region descent | Deterministic. Requires hotspot detection results. |

### Hotspot-guided region descent (`-A 6`)
This algorithm spends its measurements on the code regions that dominate the measured runtime, and makes every decision from sorted data so that two runs on a machine with stable timings produce the same sequence of measured configurations.

- Require hotspot detection results. Without `Hotspots.json` the algorithm stops with a message instead of falling back to treating every suggestion as a hotspot.
- Collect the hot loops of the requested `--hotspot-types` and the suggestions that parallelize them. Loops whose longest measured run is below `--hs-min-share` of the hottest loop's are dropped, so a cold loop never costs a compile-and-execute cycle.
- Rank the remaining regions by hotspot class (`YES`, then `MAYBE`, then `NO`) and, within a class, by their longest measured run. The class already combines both quantities of interest: the hotspot detection derives it from the region's average runtime *and* its scaling behaviour across the profiled input sizes. The longest run is preferred over the average because it describes the largest-input regime, which is where parallel speedup matters.
- Arrange the regions into a nesting forest and try the outermost region of each nest first. Hotspot runtimes are inclusive, so a hot loop and the loops nested inside it report nearly the same time; accepting the outer one therefore skips its whole subtree, which avoids nested parallel regions and the measurements they would cost. Only if the outer region does not pay off does the search descend one level.
- Accept a suggestion only if the code stays valid *and* the runtime improves by more than `--noise-threshold`. Every configuration is measured at most once and remembered, so measurement noise below the threshold cannot flip a decision.
- Finally, re-check whether any accepted suggestion can be removed again -- a suggestion accepted early was judged against a smaller configuration than the final one. Disable this pass with `--skip-removal-pass`.

`--max-measurements` caps the number of compile-and-execute cycles. Note that a search stopped by that cap, by the internal time limit or by `CTRL+C` is no longer reproducible, and the tuner says so in its log.

For meaningful scaling information the hotspot detection should be run for at least two input sizes. With a single run the scaling ratio is constant, the hotspot classification degenerates to a single threshold on the average runtime, and the ranking reduces to plain descending runtime order. The tuner warns when it detects this.

## Measuring a given selection
`-s/--suggestions <ids>` skips the search and measures the comma separated suggestions as one configuration, compared to the reference. By default, the tuner then refines the selection: it measures it again with hotspot instrumentation and drops the suggestions that slow their code region down. Add `--skip-removal-pass` to measure exactly the given selection and nothing else.

## Compile-only runs
`--compile-only` builds every candidate and executes none of them, so a run answers "does this configuration compile?" instead of "how fast is it?". Nothing is measured, so no candidate is ranked, no speedup is reported and `results.json` is not written -- a configuration that was only ever compiled must never be named as the tuner's selection. The outcome is written to `compile_results.json` instead, which states separately whether the *reference* configuration built: when it did not, no candidate's failure says anything about its own patches.

This is what [patch repair](Patch_repair.md) uses to find the suggestions whose patches do not build, and to verify a repair, without paying a full program run per check.

## Measurement noise
Every comparison the search makes rests on a single program execution, so noise on the machine can decide which candidate looks faster. `--execution-repetitions N` (`-xr N`) runs each candidate `N` times and ranks it by the median of the measured times; the individual measurements are logged with the result, so a decision taken by a margin smaller than the spread between them is visible as such.

**The default here is 1**, unlike the project manager's 3. The tuner is the expensive place to repeat: it performs one program execution per candidate, so the count multiplies the runtime of a whole search.

Two cheaper measures come first:

- `--noise-threshold` already requires a suggestion to improve the runtime by a given margin (`-A 6`, 2% by default) before it is accepted, which is what keeps noise out of the *decisions*.
- Repeating the **final** measurements instead — `discopop_project_manager --execution-repetitions`, which is on by default — gives a stable reported runtime at no cost to the search. The two options are separate for exactly this reason.

Raising the tuner's own count is worth it when the machine's noise is large enough to decide the search's comparisons, i.e. comparable to `--noise-threshold`. See [Repeated measurements](Project_manager.md#repeated-measurements) for what is recorded.

## Required input
- `Parallel patterns` in the form of a `JSON` file, created by the [Explorer](Explorer.md)
- `Prepared patch files` created by the [DiscoPoP patch generator](Patch_generator.md) (the Explorer creates them already)
- An `execution configuration` created by the [project manager](Project_manager.md), which provides the `compile.sh` and `execute.sh` scripts used to compile and execute the created parallel code. Its optional `validate.sh` validates the results, and its optional `compile_validate.sh` builds the code that `validate.sh` runs whenever validation requires a different build than the timed execution. The tuner uses the `dp` and `hd` settings of the project, so run the configuration in these modes at least once.
- `Detected hotspots` (`.discopop/hotspot_detection/Hotspots.json`), created by the [Hotspot detection](Hotspot_detection.md). They are only required for `-A 6`; for the other algorithms, all suggestions count as `yes` if no hotspot information exists.

The tool reads the `.discopop` directory it is started in; use `--dot-dp-path` to give another one. The project must not have patches applied.

## Output
The tuner does not modify your sources and, by default, keeps no code copy. Results are written to `.discopop/auto_tuner/`:

| File | Content |
|---|---|
| `results.json` | Per configuration: `applied_suggestions`, `speedup`, `efficiency`, `time` (and `not_applied_count` if patches could not be applied) of the best combination. Not written with `--compile-only`. |
| `measurements.json`, `progress.jsonl` | All measured combinations and the progress events (used by the [GUI](GUI.md)'s live plot) |
| `compile_results.json` | With `--compile-only`: whether each configuration compiles |

Further files are `.discopop/measurements.csv` and `.discopop/dp_autotuner_statistics.dot` / `.svg`. On the console, the tuner prints `@@AT_PROGRESS` event lines and a summary with the selected suggestions, the speedup, the parallel efficiency and the optimization time. The summary names the copy of the project that contains the best configuration; this copy only exists if you pass `--skip-cleanup`, otherwise it is deleted when the tuner exits.

To use the result, apply the selected suggestions with the [patch applicator](Patch_applicator.md) (`discopop_patch_applicator -a <ids>`), or let the project manager apply them in its project copy (`discopop_project_manager -x <configuration>:par -a auto`).

## Options

| Option | Default | Description |
|---|---|---|
| `--dot-dp-path PATH` | current directory | Path to the `.discopop` directory |
| `-c`, `--config NAME` | `tiny` | Execution configuration to use |
| `-A`, `--algorithm N` | `0` | Search algorithm: `0`, `1`, `3`, `4`, `5`, `6` (see above) |
| `-s`, `--suggestions IDS` | | Skip the search; measure these comma separated suggestions as one configuration |
| `--search-space IDS` | all suggestions | Restrict the search to these suggestion ids (explicit ids, ranges are not expanded). Ignored with `-s`. With `-A 0`, a listed id the hotspot loader could not classify is measured as well. |
| `-t`, `--threads N` | CPU count / 2 | `OMP_NUM_THREADS` of the measurements |
| `-ht`, `--hotspot-types TYPES` | `yes,no,maybe` | Hotspot classes to consider (`yes`, `no`, `maybe`) |
| `-xr`, `--execution-repetitions N` | `1` | Runs per candidate; the median ranks it |
| `-etr`, `--execution-time-regex [RE]` | per configuration | Rank candidates by the time the program reports; see [Measured runtime](Project_manager.md#measured-runtime) |
| `--noise-threshold F` | `0.02` | `-A 6`: relative improvement a suggestion needs to be accepted |
| `--hs-min-share F` | `0.01` | `-A 6`: ignore hot loops below this fraction of the hottest loop's runtime |
| `--max-measurements N` | `0` (no limit) | `-A 6`: stop after N compile-and-execute cycles |
| `--skip-removal-pass` | off | `-A 6`: skip the final removal pass; with `-s`: measure exactly the given selection |
| `--compile-only` | off | Build every candidate, execute none |
| `--skip-cleanup` | off | Keep the created code variants (may need much disk space) |
| `--sanitize` | off | Run ThreadSanitizer if `DP_COMPILE_SANITIZE.sh` and `DP_EXECUTE_SANITIZE.sh` are provided |
| `-p`, `--plot` | off | Allow interactive plots |
| `--log LEVEL` | `WARNING` | Log level |
| `--write-log` | off | Write a log file |

## Limitations
Due to the empirical nature of the optimization approach described above, varying sets of input data might yield differing selected configurations.
For this reason it is important, that the used input data (typically specified in `execute.sh`) is representative for a production run of the software and large enough to allow for beneficial parallelizations.

## Invocation from the GUI
The *Autotuning* tab of the [GUI](GUI.md) runs the tuner and shows a live plot of the measurements.

## Note
For the available run-time arguments, see the table above or the help string of the tool.
```text
discopop_auto_tuner --help
```
