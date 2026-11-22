# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the Hotspot Detection tab shows, as texts and rows, without a toolkit.

The panels (Tk and Qt) only put these into their widgets.
"""

import math
from dataclasses import dataclass
from typing import Any, Callable, Collection, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.project_environment import stale_directories_message
from discopop_library.ProjectManager.plots import hotspot_charts
from discopop_library.ProjectManager.plots.hotspot_data import (
    HOTNESS_MAYBE,
    HOTNESS_NO,
    HOTNESS_ORDER,
    HOTNESS_YES,
    HotspotRegion,
    MeasurementRun,
    hotness_counts,
)
from discopop_library.ProjectManager.services.hotspot_build import (
    BUILD_CURRENT,
    BUILD_MISMATCH,
    BUILD_NONE,
    BUILD_STALE,
)

REGION_COLUMNS: Tuple[Tuple[str, int], ...] = (
    ("Hotness", 90),
    ("Kind", 80),
    ("Location", 200),
    ("Name", 160),
    ("Avg (s)", 95),
    ("Share", 75),
    ("Min (s)", 95),
    ("Max (s)", 95),
    ("Ratio", 70),
    ("Runs", 60),
)

RUN_COLUMNS: Tuple[Tuple[str, int], ...] = (
    ("Run", 55),
    ("Configuration", 170),
    ("Recorded at", 160),
    ("Time (s)", 90),
    ("Status", 90),
    ("Regions", 80),
)

# Column headers of the regions table in the Qt panel: the same columns as REGION_COLUMNS (which name the sort keys),
# with the unit moved into the cells (see format_duration).
REGION_HEADERS: Tuple[str, ...] = (
    "Hotness",
    "Kind",
    "Location",
    "Name",
    "Avg",
    "Share",
    "Min",
    "Max",
    "Ratio",
    "Runs",
)
# the columns holding numbers: shown right-aligned
REGION_NUMERIC_COLUMNS: Tuple[int, ...] = (4, 5, 6, 7, 8, 9)

NO_REGIONS_TEXT = "No measurement yet \u2014 press Run Measurement."
NO_ANALYSIS_TEXT = (
    "Runs are recorded, but there is no analysis yet \u2014 use \u201cRe-run Analysis\u201d in the \u22ef menu."
)
NO_RUNS_TEXT = "No runs recorded yet \u2014 press Run Measurement."

DETAIL_PLACEHOLDER = "Click a code region in a\nchart or the table to see\nits details here."

KIND_FILTER_ALL = "all"

_BUILD_TEXTS = {
    BUILD_CURRENT: "Instrumented build: current",
    BUILD_NONE: "Instrumented build: none (will be compiled)",
    BUILD_STALE: "Instrumented build: this configuration will be instrumented separately",
    BUILD_MISMATCH: "Instrumented build: stale (will be recompiled)",
}


def region_choice_label(region: HotspotRegion) -> str:
    """The entry of a region picker."""
    name = f"  {hotspot_charts.region_display_name(region)}" if region.key.name else ""
    return f"{region.key.location}{name}  ({region.avg:.4f}s, {region.hotness})"


def region_detail_fields(region: HotspotRegion) -> List[Tuple[str, str]]:
    """What the detail bar shows for a selected region."""
    runtimes = ", ".join(f"{value:.6f}" for value in region.runtimes) or "(none recorded)"
    fields = [
        ("Kind", region.key.kind),
        ("Name", hotspot_charts.region_display_name(region) if region.key.name else "(unnamed loop)"),
        ("File", region.key.path),
        ("Line", str(region.key.line)),
        ("Hotness", region.hotness),
        ("Average runtime", f"{region.avg:.6f} s"),
        ("Share of total", f"{region.share * 100:.2f} %"),
        ("Min / max", f"{region.minimum:.6f} s / {region.maximum:.6f} s"),
        ("Ratio", f"{region.ratio:.4f}"),
        ("Runs measured", str(len(region.runtimes))),
        ("Runtime per run", runtimes),
    ]
    if len(region.runtimes) < 2:
        fields.append(("Note", "Only one run: the ratio is fixed at 0.5 and carries no information."))
    return fields


def visible_regions(
    regions: Sequence[HotspotRegion],
    hotness: Optional[Collection[str]] = None,
    kind: str = KIND_FILTER_ALL,
    sort: Optional[Tuple[str, bool]] = None,
) -> List[HotspotRegion]:
    """The regions the table shows: filtered by hotness and kind, sorted by ``sort`` = (column, descending)."""
    shown = list(regions)
    if hotness is not None:
        shown = [region for region in shown if region.hotness in hotness]
    if kind != KIND_FILTER_ALL:
        shown = [region for region in shown if region.key.kind == kind]

    if sort is not None:
        column, descending = sort
        keys: Dict[str, Callable[[HotspotRegion], Any]] = {
            "Hotness": lambda r: (HOTNESS_ORDER.index(r.hotness) if r.hotness in HOTNESS_ORDER else len(HOTNESS_ORDER)),
            "Kind": lambda r: r.key.kind,
            "Location": lambda r: (r.key.path, r.key.line),
            "Name": lambda r: r.key.name.lower(),
            "Avg (s)": lambda r: r.avg,
            "Share": lambda r: r.share,
            "Min (s)": lambda r: r.minimum,
            "Max (s)": lambda r: r.maximum,
            "Ratio": lambda r: r.ratio,
            "Runs": lambda r: len(r.runtimes),
        }
        key_func = keys.get(column)
        if key_func is not None:
            shown.sort(key=key_func, reverse=descending)
    return shown


def next_sort(current: Optional[Tuple[str, bool]], column: str) -> Tuple[str, bool]:
    """The sort after a click on ``column``: descending first, ascending on the second click."""
    return (column, not (current is not None and current[0] == column and current[1]))


def region_row(region: HotspotRegion) -> Tuple[str, ...]:
    """The cells of a row of the regions table, in the order of :data:`REGION_COLUMNS`."""
    return (
        f"● {region.hotness}",
        region.key.kind,
        region.key.location,
        hotspot_charts.region_display_name(region) if region.key.name else "-",
        f"{region.avg:.6f}",
        f"{region.share * 100:.2f} %",
        f"{region.minimum:.6f}",
        f"{region.maximum:.6f}",
        f"{region.ratio:.4f}",
        str(len(region.runtimes)),
    )


def run_failed(run: MeasurementRun) -> bool:
    return run.code not in (None, 0)


def run_row(run: MeasurementRun) -> Tuple[str, ...]:
    """The cells of a row of the runs table, in the order of :data:`RUN_COLUMNS`."""
    if run.code is None:
        status = "—"
    elif run.code == 0:
        status = "✓ ok"
    else:
        status = f"✗ code {run.code}"
    return (
        str(run.index),
        run.config if run.config is not None else "(external)",
        run.timestamp or "—",
        "—" if run.time is None else f"{run.time:.3f}",
        status,
        str(len(run.regions)) if run.regions else "—",
    )


@dataclass(frozen=True)
class MeasurementSummary:
    """The texts of the Status box of the Measurement tab."""

    build_text: str
    build_ok: bool
    runs_text: str
    hotness_text: str
    has_regions: bool
    warnings: List[str]


def measurement_summary(
    build_state: str, build_detail: str, runs: Sequence[MeasurementRun], regions: Sequence[HotspotRegion]
) -> MeasurementSummary:
    external = sum(1 for run in runs if run.is_external)
    suffix = f" ({external} external)" if external else ""
    if regions:
        counts = hotness_counts(regions)
        hotness_text = (
            f"Code regions: {len(regions)}   "
            f"YES {counts[HOTNESS_YES]} / MAYBE {counts[HOTNESS_MAYBE]} / NO {counts[HOTNESS_NO]}"
        )
    else:
        hotness_text = "Code regions: no analysis results yet"

    warnings: List[str] = []
    if build_state == BUILD_MISMATCH and runs:
        warnings.append(
            f"⚠ {build_detail}\n  The {len(runs)} recorded run(s) are kept, but regions that moved are\n"
            "  matched by source line and may no longer line up. Use 'Clear Measurements'\n"
            "  to start over if the sources changed substantially."
        )
    if len(runs) == 1:
        warnings.append(
            "⚠ Only one run accumulated: every ratio is 0.5, so hotness reduces to\n"
            "  'above-average runtime'. Measure another configuration to fix this."
        )
    return MeasurementSummary(
        build_text=_BUILD_TEXTS[build_state],
        build_ok=build_state == BUILD_CURRENT,
        runs_text=f"Accumulated runs: {len(runs)}{suffix}",
        hotness_text=hotness_text,
        has_regions=bool(regions),
        warnings=warnings,
    )


def _significant(value: float, digits: int = 3) -> str:
    """``value`` (> 0) with ``digits`` significant digits, in plain notation."""
    decimals = max(0, digits - 1 - math.floor(math.log10(value)))
    return f"{round(value, decimals):.{decimals}f}"


def format_duration(seconds: Optional[float]) -> str:
    """A time with 3 significant digits and a unit ("609 \u00b5s", "12.3 ms", "1.20 s"); "\u2014" if missing."""
    if seconds is None or math.isnan(seconds) or math.isinf(seconds):
        return "\u2014"
    if seconds <= 0:
        return "0 s"
    if seconds < 1e-3:
        return f"{_significant(seconds * 1e6)} \u00b5s"
    if seconds < 1:
        return f"{_significant(seconds * 1e3)} ms"
    return f"{_significant(seconds)} s"


def region_cells(region: HotspotRegion) -> Tuple[str, ...]:
    """The cells of a row of the Qt regions table (:data:`REGION_HEADERS`): readable times, "\u2014" for missing."""
    return (
        f"\u25cf {region.hotness}",
        region.key.kind,
        region.key.location,
        hotspot_charts.region_display_name(region) if region.key.name else "\u2014",
        format_duration(region.avg),
        f"{region.share * 100:.3g} %",
        format_duration(region.minimum if region.runtimes else None),
        format_duration(region.maximum if region.runtimes else None),
        f"{region.ratio:.3f}",
        str(len(region.runtimes)),
    )


# Levels of a MeasurementStatus; the same strings as the status chip levels of the Qt panels.
LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_IDLE = "idle"


@dataclass(frozen=True)
class MeasurementStatus:
    """The state of the measurements as one short status plus its explanation and a line of facts.

    ``text`` is the short status ("Up to date"), ``detail`` the long explanation (may be empty), ``facts`` a compact
    line such as "Accumulated runs: 1 \u00b7 Code regions: 3 (YES 2 / MAYBE 1 / NO 0)".
    """

    level: str
    text: str
    detail: str
    facts: str


def measurement_status(
    build_state: str, build_detail: str, runs: Sequence[MeasurementRun], regions: Sequence[HotspotRegion]
) -> MeasurementStatus:
    external = sum(1 for run in runs if run.is_external)
    runs_text = f"Accumulated runs: {len(runs)}" + (f" ({external} external)" if external else "")
    if regions:
        counts = hotness_counts(regions)
        regions_text = (
            f"Code regions: {len(regions)} "
            f"(YES {counts[HOTNESS_YES]} / MAYBE {counts[HOTNESS_MAYBE]} / NO {counts[HOTNESS_NO]})"
        )
    else:
        regions_text = "Code regions: no analysis results yet"
    facts = f"{runs_text} \u00b7 {regions_text}"

    one_run = (
        "Only one run accumulated: every ratio is 0.5, so hotness reduces to \u2018above-average runtime\u2019. "
        "Measure another configuration to fix this."
    )
    if build_state == BUILD_MISMATCH:
        detail = build_detail
        if runs:
            detail += (
                f" The {len(runs)} recorded run(s) are kept, but regions that moved are matched by source line and may "
                "no longer line up. Use \u2018Clear Measurements\u2019 to start over if the sources changed "
                "substantially."
            )
        if len(runs) == 1:
            detail += "\n" + one_run
        return MeasurementStatus(LEVEL_WARN, "Build stale \u2014 will be recompiled", detail, facts)
    if len(runs) == 1:
        return MeasurementStatus(LEVEL_WARN, "Only one run", one_run, facts)
    if not runs:
        detail = "" if build_state == BUILD_CURRENT else _BUILD_NOTES[build_state]
        return MeasurementStatus(LEVEL_IDLE, "No measurement yet", detail, facts)
    if build_state == BUILD_CURRENT:
        return MeasurementStatus(LEVEL_OK, "Up to date", "", facts)
    return MeasurementStatus(LEVEL_IDLE, "Will be instrumented", _BUILD_NOTES[build_state], facts)


_BUILD_NOTES = {
    BUILD_NONE: "There is no instrumented build yet; the next measurement compiles it.",
    BUILD_STALE: "This configuration will be instrumented separately; its runs are combined with the others by source "
    "location.",
}


def stale_hotspot_data_message(arguments: ProjectManagerArguments) -> Optional[str]:
    """A warning if the hotspot data was instrumented with other project directories than the stored ones."""
    return stale_directories_message(arguments.dot_dp, "hd", arguments.project_dir)
