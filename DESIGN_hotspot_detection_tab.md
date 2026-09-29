<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Hotspot Detection Tab — Design & Implementation Plan

Status: implemented.

Adds a **Hotspot Detection** tab to the DiscoPoP Project Manager GUI
(`library/discopop_library/ProjectManager/gui`), positioned left of *Pattern
Detection*. It replaces the *Use for Hotspot Detection* button on the Execute
tab, which is removed in the process.

The tab does three things:

1. **Run measurements** — instrument the project once, then execute a selected
   run configuration to append one measurement run.
2. **Show the accumulated runs** — which configuration produced which run, when,
   how long it took, whether it succeeded.
3. **Present the analysis** — `Hotspots.json` in four interpretable views, in a
   notebook modelled on the Report tab.

---

## 0. Background: how the hotspot data actually works

These properties of the existing tooling drive every design decision below and
were verified against the sources.

**The analyzer needs several runs with *differing inputs*.**
`discopop_hotspot_analyzer` classifies each code region by two criteria
(`hotspot_analyzer.py:270-287`): `avg >= mean(avg)` (`topAvr`) and
`ratio >= mean(ratio)` (`topRatio`), where
`ratio = 1/((min/max)+1)` over the region's runtimes across all accumulated
runs. Hotness is `YES` when both hold, `NO` when neither, `MAYBE` otherwise.

With a **single** run `min == max`, so every `ratio` is exactly `0.5`,
`mean(ratio)` is `0.5`, `ratio >= mean(ratio)` holds for all regions, and
hotness degenerates to `avg >= mean(avg)`. Repeating the *same* input is worse
than one run: `min` and `max` then differ only by measurement noise, so
`topRatio` splits regions arbitrarily and manufactures `MAYBE` classifications.
**Varying the input across runs is what makes `ratio` meaningful**, and in the
ProjectManager model the input lives in each configuration's `execute.sh` — so
accumulating runs across configurations is the intended workflow.

**The region-id table is append-only, and ids carry across compiles.**
`HotspotDetection.cpp` opens all of its outputs with `std::ios_base::app`:
`cs_id.txt` (`:513`, `:722`), `FileMapping.txt` (`:253`) and `temp.txt`
(`:785`). On startup the pass *resumes* numbering from `temp.txt`
(`:369`, `UID = std::stoi(lastid)`), and `rtlib.c:147-160` sizes its output by
counting the lines of `cs_id.txt`, emitting a row for every id from 1 to that
count.

Consequently, **compiling into a non-empty `private/` directory corrupts the
analysis**: the second compile numbers its regions `N+1…2N`, leaves the stale
`1…N` rows in `cs_id.txt`, and the new binary writes `0.0` for every old id.
Because the analyzer joins purely by id, each region ends up with a real
measurement from the run where it existed and `0.0` from the run where it did
not. `calMin` picks up the `0.0`, `roundMin` rewrites it to `1e-6`, so
`ratio ≈ 1.0` for *every* region and `topRatio` becomes universally true; the
YES/MAYBE distinction stops carrying information, and `calAvr` deflates every
average by the runs the region was absent from.

This is not conditional on editing sources — the removed *Use for Hotspot
Detection* button reproduced it on a second click. `mcp_server/tools/gather_data.py:133`
avoids it by `shutil.rmtree`-ing `.discopop/hotspot_detection` before
instrumenting; the documented CLI flow avoids it by compiling once and
re-executing many times.

**Therefore raw ids are never used to combine runs.** But this is a property of
the *id space*, not of the measurements: `RegionKey` (path, line, kind, name) is
build-independent, so the same source region is recognisable across builds. Since
a meaningful `ratio` requires several configurations — and configurations
generally differ in their `compile.sh` — the tab must combine builds, and does so
by renumbering every accumulated run into one canonical id space before analysis
(§1c). Discarding runs on recompile would defeat the tab's purpose.

**`fid` is resolvable but is not a stable key.** `addFileName`
(`HotspotDetection.cpp:248`), which would write malformed lines, is dead code —
`getFileID` writes valid `id\tpath` entries itself (`:281`, `:288`), so
`.discopop/FileMapping.txt` is loadable via
`PathManagement.load_file_mapping` even on an hd-only build. But the file is
appended and ids depend on compile order, so regions are keyed by resolved
**path** rather than `fid`.

**`execution_results.json` cannot serve as the run log.** `execute_configuration`
deduplicates by `(applied_suggestions, thread_count, label)`
(`configurations/execution.py:213-221`), so repeated hd runs of one
configuration overwrite each other. A separate sidecar log is required.

---

## 1. Decisions

| Aspect | Decision |
|---|---|
| Tab position | `Editor · Execute · Report · **Hotspot Detection** · Pattern Detection · Autotuning` |
| Tab gating | Always enabled — it produces the data, so gating it would deadlock. Unmet prerequisites disable the run button with an inline reason. |
| Launch scope | The configuration selected in the left panel; repeat count (default **1**). |
| Compile policy | Compile **only when needed**; otherwise execute only and append a run. |
| Re-instrumenting with runs present | Runs are **kept and combined** across builds (§1c). `private/` is never wiped, so the pass appends fresh ids and the runtime picks the next free result index; nothing the old runs refer to is touched. |
| Clearing | Only ever explicit: the `Clear Measurements` button (confirm dialog). No automatic wipe, on any path. |
| Result views | Four, in a Report-style notebook: permanent tabs plus a `＋` menu adding closable chart tabs. |
| Selection | Per-tab, exactly as `report_panel.py`; each results tab owns a Selection Details bar. |
| Run log | `.discopop/hotspot_detection/measurement_runs.json`, regions stored by resolved key. |

### 1a. When a compile is required

* no instrumented build yet (`private/cs_id.txt` absent), or
* project sources are newer than `cs_id.txt`, or
* the selected configuration's resolved `compile.sh` differs from the one
  recorded for the current build, or
* the user presses `Re-instrument`.

A compile no longer costs anything: the accumulated runs survive it (§1c).

### 1b. The region fingerprint

The sidecar records `region_fingerprint`: a stable hash over the sorted resolved
region keys parsed from `cs_id.txt` at instrumentation time. It no longer gates
anything — combining runs is safe by construction — but a mismatch against the
current `cs_id.txt` still indicates the region set changed under the accumulated
runs. Paired with a source-mtime change that means line numbers may no longer
denote the same code, which the Status panel warns about while leaving the
decision (keep accumulating, or `Clear Measurements`) to the user.

### 1c. Combining runs across instrumented builds

Ids from two builds are incomparable, so `_invoke_hotspot_analyzer` never points
the analyzer at `private/`. Instead:

1. every run's measurements are resolved to `RegionKey`s and stored that way in
   the sidecar as soon as the run completes (external runs — Execute tab, CLI,
   MCP server — are resolved from their raw file at analysis time);
2. `write_merged_analysis_input` renumbers the union of those keys from 1 into
   `hotspot_detection/merged/`, writing a canonical `cs_id.txt` (with real `fid`s,
   inverted from `FileMapping.txt`, so the explorer's `HostpotLoader` still
   resolves regions) plus one contiguous `hotspot_result_<i>.txt` per run;
3. the analyzer runs over that directory (`--input-dir merged`).

The load-bearing detail is that a region **absent** from a run is *omitted* from
that run's file rather than written as `0.0`. `calAvr`/`calMin`/`calMax` iterate
`runtimes`, so omission means "not measured in this run" — which is what averts
exactly the §0 corruption, where a zero from a build the region did not belong to
drags `minVal` to `1e-6` and pins `ratio` at ~1.0. Correspondingly the analyzer
seeds its region list from `cs_id.txt` rather than from run 0, so a region missing
from the first run is not dropped.

`Hotspots.json` is therefore expressed in the *canonical* id space, and the
Regions tab resolves it against `merged/cs_id.txt` — not `private/cs_id.txt`,
whose ids mean something else.

### 1d. Accepted limitations

* **Repetitions only narrow measurement noise.** The spinner defaults to 1 and
  carries a caption saying so; varying the input across configurations is what
  produces signal. Kept because repeated runs of an unstable benchmark do
  legitimately tighten `min`/`max`.
* **Function names are displayed demangled, but keyed mangled.** `cs_id.txt`
  records `Function::getName()`, i.e. the mangled symbol for C++. That is the
  right basis for a region key (stable, unambiguous) but unreadable in a table,
  so `plots/demangle.py` runs it through `llvm-cxxfilt` / `c++filt` for display
  only — batched per refresh and cached, with the mangled name shown as-is when
  no demangler is installed.
* **`LOOP` region keys are `(path, line)`.** Loops have no name in `cs_id.txt`,
  so an edit that shifts a loop's line changes its key. This is strictly more
  stable than raw ids (which shift when any region anywhere is added or
  removed), and the fingerprint guard catches the case regardless.
* **hd runs still land in `execution_results.json`** with an empty label, so
  repeated runs of one configuration overwrite each other there and the Report
  tab shows a single `hd` row per configuration. This matches the removed
  button's behaviour and keeps the Report table uncluttered; the authoritative
  per-run record is the sidecar.
* **Timeouts are taken from the Execute tab's fields**, as
  `_prepare_inplace_run` already does. Noted in a caption rather than
  duplicated as new inputs.

---

## 2. Step 1 — Remove the old button

* `gui/mixins/execute_panel.py` — drop `prepare_hotspot_detection_button`, its
  tooltip and `on_prepare_hotspot_detection`.
* `gui/mixins/execution.py` — drop `_prepare_hotspot_detection`,
  `HOTSPOT_ANALYZER`, `_hotspot_analysis_process` and its `_stop_execution`
  branch; the two `prepare_hotspot_detection_button.config(...)` calls in
  `_run_execution` and `_prepare_inplace_run`; and the now-unused `post_step`
  parameter of `_prepare_inplace_run` (hotspot detection was its only user, so
  `_prepare_pattern_detection` is left with a single straight path).
  `_run_hotspot_analyzer` moves to the new mixin.
* `gui/mixins/mixin_base.py` — drop the `prepare_hotspot_detection_button`
  attribute and the `_prepare_hotspot_detection` stub.

`hd` remains among the Execute tab's mode checkboxes; that path is orthogonal
and runs produced through it appear as `(external)` in the Runs overview.

---

## 2a. Shared extractions

Two pieces were pulled out of existing code rather than duplicated, since the
Report tab and this tab need identical behaviour:

* `gui/plots/interaction.py` — the hover-tooltip and click-to-select hit-testing
  formerly private to `report_charts.py`, now generic over the attached payload
  and working in **display (pixel) space**. Data-space distances mixed axis units
  and broke on a log-scaled axis, which the quadrant chart requires.
* `gui/detail_bar.py` — the "Selection Details" side bar formerly built inline in
  `report_panel.py`, now a `DetailBar` widget with an optional action-button area
  (used here for "Show in VSCode").

## 3. Step 2 — `gui/plots/hotspot_data.py` (pure, Tk-free)

Mirrors `plots/data.py`: no Tk, no matplotlib, unit-testable headless.

```python
@dataclass(frozen=True)
class RegionKey:                 # stable identity across compiles
    path: str; line: int; kind: str; name: str      # kind: LOOP | FUNCTION

@dataclass
class HotspotRegion:
    key: RegionKey; csid: int
    runtimes: List[float]
    avg: float; minimum: float; maximum: float
    ratio: float; hotness: str                      # YES | MAYBE | NO
    share: float                                    # avg / sum(avg)

@dataclass
class MeasurementRun:
    index: int
    config: Optional[str]                           # None => external
    timestamp: Optional[str]
    time: Optional[float]; code: Optional[int]
    regions: Dict[str, float]                       # serialized key -> runtime
```

Functions:

* `parse_cs_id(text) -> Dict[int, Tuple[str, int, int, str]]` — `(kind, line, fid, name)`,
  handling both the 4-field `loop` and 5-field `func` line formats.
* `resolve_keys(cs_id, file_mapping) -> Dict[int, RegionKey]`.
* `parse_hotspot_result(text) -> Dict[int, float]`.
* `parse_hotspots_json(data, keys) -> List[HotspotRegion]`, deriving `share`.
* `quadrant_thresholds(regions) -> Tuple[float, float]` — reproduces the
  analyzer's `mean(avg)` / `mean(ratio)` so the chart crosshairs agree with the
  labels exactly.
* `region_fingerprint(keys) -> str`.
* `load_runs` / `save_runs` for the sidecar, synthesizing `(external)` entries
  from `hotspot_result_*.txt` mtimes for indices absent from it.

`RegionKey` serializes as `path:line:KIND[:name]`.

### Sidecar schema

```json
{
  "region_fingerprint": "sha1:…",
  "instrumented_at": "2026-07-31T10:01:44",
  "compile_script": "/…/configs/compile.sh",
  "runs": [
    {"run": 0, "config": "small_input", "ts": "2026-07-31T10:02:11",
     "time": 3.4, "code": 0,
     "regions": {"lulesh.cc:1284:LOOP": 4.812,
                 "lulesh.cc:2140:FUNCTION:CalcHourglass": 2.004}}
  ]
}
```

Written by the GUI only; ignored by every other tool. `Clear Measurements`
deletes `.discopop/hotspot_detection/` including this file.
`.discopop/FileMapping.txt` is **not** deleted — it is shared with the `dp` flow.

The index of a newly created run is determined by diffing the set of
`hotspot_result_*.txt` files before and after execution (`rtlib` picks the first
free index itself).

---

## 4. Step 3 — `gui/plots/hotspot_charts.py`

Same shape as `report_charts.py`: `render_*(figure, regions, …, on_select=…)`,
reusing `mode_style.style_axes` / `style_legend`, `_setup_hover_tooltips` and the
`_find_record_at_event` click-routing pattern.

* `render_quadrant` — log-x average runtime vs `ratio`, crosshairs at
  `quadrant_thresholds`, quadrants annotated (`YES` / `MAYBE` / `NO`), marker
  shape from `kind`, colour from hotness. Makes the classifier visible: users see
  *why* a region is `MAYBE` and how close it sits to a boundary.
* `render_top_bars` — horizontal bars, top *N* by average runtime
  (*N* ∈ {10, 20, 50}), coloured by hotness, labelled `path:line`.
* `render_run_profile` — one region's runtime across run indices, with
  `min`/`max`/`ratio` annotated; the region comes from a combobox in the tab's
  control strip, defaulting to the hottest.

Hotness reuses the existing `STATUS_COLORS` semantics (`YES` → green,
`MAYBE` → orange, `NO` → `REFERENCE_COLOR`) so hotness never collides with the
`CONFIG_PALETTE` used for configurations elsewhere.

When only one run is accumulated, the quadrant chart annotates that the `ratio`
axis is inactive rather than presenting a degenerate single column as signal.

---

## 5. Step 4 — `gui/mixins/hotspot_panel.py`

A sub-notebook, flat and Report-shaped:

```
Measurement │ Runs │ Regions │ «closable chart tabs» │ ＋
```

**Measurement** — left: selected-configuration label, repeat count with the
noise caption, `Run Measurement` / `Stop` / `Re-run Analysis` /
`Re-instrument`, a red `Clear Measurements`, and a status block
(`Instrumented build: current | stale | none`, `Accumulated runs: N`,
YES/MAYBE/NO counts). Right: the shared output console via
`create_styled_output_console`.

The worker thread reuses `execute_configuration` exactly as
`_prepare_inplace_run` does, streaming output through `self.after(0, …)`. The
analyzer stays a **subprocess** — it `chdir`s into the profiling directory and
never restores the working directory, and the project's GUI convention is to
subprocess tools carrying C extensions.

**Runs** — Treeview of `MeasurementRun`s: index, configuration, timestamp,
elapsed time, status, region count.

**Regions** — the sortable table (hotness pill, kind, `path:line`, average,
share of total, min/max, `ratio`), filters for hotness and kind, its own
Selection Details bar, and a *Show in VSCode* action reusing the URI approach
from `explorer_integration._open_in_vscode`.

**`＋`** — menu of the three chart types; closable tabs with `✕`, each with its
own detail bar. Lifted from `report_panel._add_report_plot`,
`_build_detail_bar`, `_on_report_tab_changed` and `_close_report_plot`.

`Stop` terminates the compile, execute and analyzer subprocesses through handles
owned by this mixin.

---

## 6. Step 5 — Wiring

* `gui/ConfigManagerApp.py` — add `HotspotPanelMixin` to the bases, insert the
  frame before the Pattern Detection frame, store `hotspot_tab_index`, call
  `_build_hotspot_panel`.
* `_refresh_config_list` / `_on_config_selected` also refresh the hotspot
  configuration label and button states.
* `_update_pattern_detection_ui` additionally refreshes the hotspot results,
  since the analyzer's output feeds the Autotuning tab's hotspot types.
* `gui/mixins/mixin_base.py` — new attributes plus `_build_hotspot_panel`,
  `_update_hotspot_ui` and `_refresh_hotspot_results` stubs.

---

## 7. Step 6 — Verification

* `venv/bin/python -m pytest library/discopop_library/ProjectManager/gui/plots`
  — new `test_hotspot_data.py` and `test_hotspot_charts.py` alongside the four
  existing test modules. Cases: both `cs_id.txt` line formats; `fid` → path
  resolution; the degenerate single-run case (all ratios exactly `0.5`);
  `quadrant_thresholds` agreeing with the hotness labels the analyzer wrote;
  fingerprint stability and mismatch; external-run synthesis from mtimes.
* `venv/bin/python -m mypy --config-file=mypy.ini -p discopop_library`
* `venv/bin/python -m black -l 120 --check .`
* `scripts/dev/run_ci_locally.sh`

End-to-end results (a two-loop program whose `heavy()` scales with the input
argument and whose `light()` does not, measured through two configurations):

| Check | Result |
|---|---|
| First measurement | compiles (`build=none`), 1 run recorded |
| Second measurement, other configuration | **compile skipped** (`build=current`), run appended |
| `ratio` after two differing inputs | `heavy()` 0.86 vs `light()` 0.63 — not degenerate; YES/NO assigned accordingly |
| Run log | both runs attributed to their configuration, region keys resolved and demangled |
| Editing a source | `build=stale`, warning names the 2 runs that a re-instrumentation would discard |
| Re-instrumenting | old runs discarded, fresh accumulation of 1, single-run warning shown |
| Tampering with `cs_id.txt` | `build=mismatch` — the fingerprint guard catches it exactly |
| `Clear Measurements` | `hotspot_detection/` removed, `FileMapping.txt` preserved, buttons re-gated |

---

## 8. Out of scope

* ~~Changing `discopop_hotspot_analyzer` to join runs on resolved region keys
  instead of ids.~~ **Done since.** `RegionKey` and the merging helpers moved to
  `discopop_hotspot_analyzer.region_keys` (`plots/hotspot_data.py` re-exports
  them), and the analyzer performs the same renumbering itself for its default
  `--input-dir private` — so a project compiled more than once is analyzed
  correctly however its runs were produced (CLI, MCP server, benchmark harness),
  not only via this tab. `Hotspots.json` keeps its shape, so the autotuner
  (`HostpotLoader/hostpot_loader.py`) and the optimizer are unaffected. The tab
  itself is unchanged: it still renders `merged/` and passes `--input-dir
  merged`, which the analyzer takes at face value.
* Measuring several configurations from a single click. The tab operates on the
  selected configuration; accumulating across inputs is *select, click, repeat*.

---

## 9. Follow-up — hotspot hint in the Pattern Detection tab

Since hotspot results are optional but valuable, the Pattern Detection tab warns
when there are none: the explorer loads `hotspot_detection/Hotspots.json` and,
where it exists, restricts `calculateFunctionMetadata` to the hot functions, so
its absence means analysing everything.

* `hotspot_data.hotspots_available_for_explorer(dot_dp)` decides this the way
  `HostpotLoader` does — file present *and* holding at least one `YES`/`MAYBE`
  entry, since the loader is configured with `get_NO=False` and an all-`NO` file
  therefore restricts nothing.
* `explorer_integration._build_hotspot_hint` builds a "Hotspot Information"
  block (warning line, explanation, `Go to Hotspot Detection` button) above the
  Settings frame. It lives in a permanently packed, otherwise empty container so
  showing and hiding it never reorders the frames below.
* `_update_hotspot_hint` is called from `_update_pattern_detection_ui` and from
  `_refresh_hotspot_results`, so running or clearing a measurement flips the hint
  immediately. The latter call happens before the Pattern Detection panel is
  built (the hotspot tab is created first), which the `None` check covers.

Known limitation, not addressed here: `HostpotLoader` is invoked with
`dot_discopop_path=os.getcwd()` rather than the explorer's `--path`. The
subprocess run sets `cwd` to the `.discopop` directory and is therefore correct,
but the in-process run used for `Show graph visualization` inherits the GUI's
working directory and so may not find the hotspots the hint promises.
