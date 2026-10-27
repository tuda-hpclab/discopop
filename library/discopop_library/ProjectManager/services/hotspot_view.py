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

from dataclasses import dataclass
from typing import Any, Callable, Collection, Dict, List, Optional, Sequence, Tuple

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
