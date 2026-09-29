<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# DiscoPoP Results Visualization — Design & Implementation Plan

Status: design approved; PR 1 in progress.

This document describes the plan for adding proper visual presentation of
execution and autotuning results to the DiscoPoP Project Manager GUI
(`library/discopop_library/ProjectManager/gui`).

Two outcomes:

- **A. Report tab** — a notebook with a permanent *Table* tab plus on-demand,
  closable plot tabs (Pareto trade-off scatter, thread-scaling lines, best-of
  bars), all driven by the existing `execution_results.json`.
- **B. Autotuning tab** — a sub-notebook (*Live Plot* default + *Console*) that
  shows an auto-refreshing search plot, fed by a structured progress channel the
  autotuner emits on stdout and persists to `auto_tuner/progress.jsonl`.

Shared encoding language across both: **colour = configuration, marker shape =
execution mode (`setting`: seq/par/dp/hd), fill/marker = validity
(valid/invalid/failed)**.

Interactive HTML mockups (design reference, not shipped) demonstrated both tabs.

---

## 0. Principles & scope

- **No new dependencies.** matplotlib is already a dependency (`reports/*.py`) and
  already embedded in Tk via `FigureCanvasTkAgg` (explorer visualizer). All charts
  are matplotlib-in-Tk.
- **Reuse existing data.** The Report tab reads the existing
  `execution_results.json`. Autotuning adds one small emit path.
- The autotuner's reference is `par_settings.json`, so its speedups are **vs.
  full-parallel**, not sequential — labelled as such in the UI.

---

## 1. Backend — autotuning progress channel (PR 1, CLI-testable, no GUI)

### 1a. New module `EmpiricalAutotuning/output/progress.py`

- `ProgressReporter`: emits one event per step. Each event is (a) printed to
  **stdout** prefixed with `@@AT_PROGRESS ` (the live channel the GUI already
  streams) and (b) appended to **`auto_tuner/progress.jsonl`** (persistence).
- `ProgressList(list)`: a drop-in `debug_stats` container whose `append(...)`
  additionally emits a `measurement` event via the active reporter. This gives
  every step-based algorithm (greedy, coordinate descent, linear, measure-only,
  single) progress emission with **zero changes to those files**.
- `set_active_reporter()` / `get_active_reporter()`: a process-global handle so
  the evolutionary algorithm (which measures via `fitness_cache`, not
  `debug_stats`) can emit without signature churn. Safe no-op when unset (tests).

### 1b. Event schema (one JSON object per line)

| `event`       | fields |
|---------------|--------|
| `baseline`    | `runtime, valid, thread_count` |
| `measurement` | `index, suggestions[], runtime, return_code, valid, tsan, speedup, generation?` |
| `generation`  | `generation, max_fitness, avg_fitness, threshold, evaluated` (evolutionary only) |
| `result`      | `suggestions[], speedup, efficiency, runtime, valid_count, invalid_count, failed_count, evaluated, optimization_time_s` |

`speedup = reference_runtime / runtime` is included in each `measurement` so the
GUI never needs the baseline. The GUI derives greedy/coordinate accept-vs-reject
itself as "valid and speedup improves the running best" — so no `accepted` field
is needed.

### 1c. Emit sites

- `Autotuner.run`: create reporter + `ProgressList` debug_stats; `baseline(...)`
  after the reference executes; `result(...)` after `results.json`; dump full
  `debug_stats` to `auto_tuner/measurements.json`; `close()` at the end.
- Step-based algorithms: **no change** (covered by `ProgressList.append`).
- `evolutionary_combination.py`: emit `measurement(..., generation=g)` per newly
  executed individual in `__calculate_fitness`; emit `generation(...)` wherever
  the time series is updated in `perform_evolutionary_search` (alongside the
  existing plotille CLI plot, which is retained).

### 1d. `debug_stats -> measurements.json` dump

Full `debug_stats` written to `auto_tuner/measurements.json` at the end of the
run, so the plot can be re-shown after a run without re-running.

### 1e. Verification

Run the `example/` autotuner from the CLI; confirm `@@AT_PROGRESS` lines on
stdout and well-formed `progress.jsonl` / `measurements.json`. Unit test for
`ProgressReporter` serialization (pure, Tk-free).

---

## 2. GUI shared plotting utilities (PR 2)

New package `ProjectManager/gui/plots/`:

- `mode_style.py` — single source of encoding truth: config→colour, mode→marker +
  dash, status→colour + fill.
- `embedding.py` — create `Figure` + `FigureCanvasTkAgg` + `NavigationToolbar2Tk`
  in a Tk frame; `redraw(fig)` reusing the `<Configure>`-synthesize trick from
  `explorer_integration._redraw_embedded_canvases`.
- `data.py` — pure functions (unit-testable): parse `execution_results.json` into
  records; compute Pareto frontier; best-so-far series.

---

## 3. Autotuning tab — sub-notebook + live plot (PR 3)

`gui/mixins/autotuning_panel.py` (+ `gui/plots/autotuning_chart.py`):

- Right panel becomes a `ttk.Notebook`: **📈 Live Plot** (default; summary tiles +
  embedded canvas) and **🖥 Console** (existing output console).
- `_invoke_autotuner` parses `@@AT_PROGRESS` lines out of stdout, routes them to a
  progress accumulator on the Tk main thread (`self.after(0, ...)`), and redraws
  the canvas per event. Human log lines still go to the console; the tagged lines
  do not.
- Renderer adapts per algorithm (evolutionary max/avg/threshold; greedy/coordinate
  best-so-far + accept/reject markers; measure-only cloud).
- On tab open with no active run, load `auto_tuner/progress.jsonl` (or
  `measurements.json`) and render the last run.

---

## 4. Report tab — plot notebook (PR 4)

`gui/mixins/report_panel.py` (+ `gui/plots/report_charts.py`):

- Keep the action-button row. Replace the single `report_tree` with a
  `ttk.Notebook`: permanent **Table** tab + a trailing **＋** tab (menu of chart
  types → appends a plot tab) + per-tab **✕** close.
- Chart types: Pareto scatter (primary), thread-scaling lines, best-of bars.
- Enhanced table: `config → setting → threads` rows, validity pills, best-row
  highlight, inline speedup bar, suggestion-ID → suggestion browser.

---

## 5. Cross-cutting

- App is a light ttk theme; matplotlib figures use a fixed light style keyed off
  `widgets.py` tokens.
- All canvas mutations on the Tk main thread via `after(0, ...)`. The autotuner
  stays a subprocess (uses tqdm/plotille C-extensions).
- `mypy --config-file=mypy.ini` on touched packages; `black -l 120`.

---

## 6. PR sequence

| PR | Content |
|----|---------|
| 1  | Backend progress channel + `measurements.json` dump (this doc's §1) |
| 2  | `gui/plots/` shared utils + unit tests |
| 3  | Autotuning sub-notebook + live plot |
| 4  | Report plot notebook + enhanced table |
| 5  | (later) distribution chart polish; greedy waterfall (Tier 4) |

## 7. Risks / out of scope

- Search-tree visualization (node-link of explored configs) needs the algorithms
  to populate `StatisticsGraph` (currently root-only) — out of scope.
- Evolutionary individuals are measured serially in the main process (the `Pool`
  is compile-only), so a single reporter index gives correct measurement order.
