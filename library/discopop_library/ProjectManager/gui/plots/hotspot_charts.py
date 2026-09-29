# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Chart renderers for the Hotspot Detection tab, driven by :class:`HotspotRegion`s.

Three chart types, each answering a different question:

* :func:`render_quadrant`    -- *why* is a region YES/MAYBE/NO? Average runtime
  against input sensitivity, with the analyzer's own mean thresholds drawn as
  crosshairs, so the classification and its margins are visible.
* :func:`render_top_bars`    -- *where does the time go?* The hottest regions by
  average runtime.
* :func:`render_run_profile` -- *how does one region react to the input?* Its
  runtime across the accumulated runs.

Encoding: **colour = hotness** (reusing the status colours from :mod:`mode_style`,
which are reserved for state and never used as a series colour) and **marker
shape = region kind** (loop vs. function). Configuration colours are deliberately
not used here -- a region is not owned by one configuration; it is measured by all
of them.

Only the ``render_*`` functions touch a figure; the pure helpers next to them are
matplotlib-free and unit-tested.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from discopop_library.ProjectManager.gui.plots import demangle, interaction, mode_style
from discopop_library.ProjectManager.gui.plots.hotspot_data import (
    HOTNESS_MAYBE,
    HOTNESS_NO,
    HOTNESS_YES,
    KIND_FUNCTION,
    KIND_LOOP,
    HotspotRegion,
    quadrant_thresholds,
    ratio_is_degenerate,
)

# Hotness -> colour. Reuses the reserved status palette: a hot region is a state,
# not a series. NO deliberately uses the neutral reference grey so the eye is
# drawn to the regions that matter.
HOTNESS_COLORS: Dict[str, str] = {
    HOTNESS_YES: mode_style.STATUS_COLORS["valid"],
    HOTNESS_MAYBE: mode_style.STATUS_COLORS["invalid"],
    HOTNESS_NO: mode_style.REFERENCE_COLOR,
}

# Region kind -> marker, mirroring mode_style.MODE_MARKERS' role for modes.
KIND_MARKERS: Dict[str, str] = {
    KIND_LOOP: "o",
    KIND_FUNCTION: "^",
}

# Bar-count choices offered by the top-N chart's control strip.
TOP_N_CHOICES = ("10", "20", "50")
DEFAULT_TOP_N = 20

_NO_DATA = "No hotspot measurements yet"
_SINGLE_RUN_NOTE = (
    "Only one run profiled: min == max, so every ratio is 0.5 and the\n"
    "vertical axis carries no information. Measure another configuration\n"
    "(a differing input) to make input sensitivity meaningful."
)


def hotness_color(hotness: str) -> str:
    """Colour for a hotness value; unknown values fall back to the neutral grey."""
    return HOTNESS_COLORS.get(hotness, mode_style.REFERENCE_COLOR)


def kind_marker(kind: str) -> str:
    """Marker code for a region kind (circle for unknown kinds)."""
    return KIND_MARKERS.get(kind, "o")


def top_regions(regions: Sequence[HotspotRegion], count: int) -> List[HotspotRegion]:
    """The ``count`` regions with the highest average runtime, hottest first."""
    ordered = sorted(regions, key=lambda region: region.avg, reverse=True)
    return ordered[: max(1, count)]


def region_display_name(region: HotspotRegion) -> str:
    """A region's readable name: demangled for functions, the location for loops."""
    if not region.key.name:
        return region.key.location
    return demangle.demangle(region.key.name)


def format_region_tooltip(region: HotspotRegion) -> str:
    """Multi-line hover text for a region."""
    lines = [
        f"{region.key.kind}: {region_display_name(region)}",
        f"Location: {region.key.location}",
        f"Hotness: {region.hotness}",
        f"Average: {region.avg:.6f}s",
        f"Share: {region.share * 100:.1f}%",
        f"Min / max: {region.minimum:.6f}s / {region.maximum:.6f}s",
        f"Ratio: {region.ratio:.3f}",
        f"Runs: {len(region.runtimes)}",
    ]
    return "\n".join(lines)


def _hotness_kind_legends(ax: Any, hotnesses: Sequence[str], kinds: Sequence[str], outside: bool = False) -> None:
    """Colour (hotness) and marker (kind) keys for a chart.

    ``outside`` puts them in a horizontal strip below the axes instead of into the
    upper-left / lower-right corners. The quadrant chart needs that: its corners
    carry the quadrant names, which an in-axes legend would cover.
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    hotness_handles = [Patch(facecolor=hotness_color(h), label=h) for h in hotnesses]
    kind_handles = [
        Line2D([], [], marker=kind_marker(k), color="0.35", linestyle="None", label=k.title()) for k in kinds
    ]
    if outside:
        # Figure-level "outside" locations are the ones constrained layout reserves
        # space for, so the strip cannot be clipped by the canvas edge.
        figure = ax.get_figure()
        if hotness_handles:
            first = figure.legend(
                handles=hotness_handles,
                title="hotness",
                loc="outside lower left",
                ncols=len(hotness_handles),
                fontsize=mode_style.LEGEND_SIZE,
            )
            mode_style.style_legend(first)
        if kind_handles:
            second = figure.legend(
                handles=kind_handles,
                title="kind",
                loc="outside lower right",
                ncols=len(kind_handles),
                fontsize=mode_style.LEGEND_SIZE,
            )
            mode_style.style_legend(second)
        return
    if hotness_handles:
        first = ax.legend(handles=hotness_handles, title="hotness", loc="upper left", fontsize=mode_style.LEGEND_SIZE)
        mode_style.style_legend(first)
        ax.add_artist(first)
    if kind_handles:
        second = ax.legend(handles=kind_handles, title="kind", loc="lower right", fontsize=mode_style.LEGEND_SIZE)
        mode_style.style_legend(second)


def render_quadrant(
    figure: Any,
    regions: Sequence[HotspotRegion],
    on_select: Optional[Callable[[HotspotRegion], None]] = None,
) -> None:
    """Average runtime (log) vs. input-sensitivity ratio, with the classifier drawn.

    The crosshairs are the very thresholds ``discopop_hotspot_analyzer`` compares
    against (``mean(avg)`` and ``mean(ratio)``), so a point's quadrant matches the
    hotness label it was given, and a region sitting just inside a boundary is
    visibly marginal rather than looking definitive.
    """
    figure.clear()
    ax = figure.add_subplot(111)

    # A log x axis cannot show non-positive averages; the analyzer already drops
    # regions that never ran, but guard so one zero cannot blank the chart.
    plotted = [region for region in regions if region.avg > 0]
    if not plotted:
        interaction.empty_message(ax, _NO_DATA)
        return

    mean_avg, mean_ratio = quadrant_thresholds(plotted)
    degenerate = ratio_is_degenerate(plotted)

    groups: Dict[str, List[HotspotRegion]] = {}
    for region in plotted:
        groups.setdefault(f"{region.hotness}|{region.key.kind}", []).append(region)

    for group_key, members in groups.items():
        hotness, kind = group_key.split("|", 1)
        collection = ax.scatter(
            [region.avg for region in members],
            [region.ratio for region in members],
            marker=kind_marker(kind),
            color=hotness_color(hotness),
            edgecolors="white",
            linewidths=0.6,
            s=mode_style.SCATTER_SIZE,
            zorder=3,
        )
        interaction.attach(collection, members)

    ax.set_xscale("log")
    ax.axvline(mean_avg, color=mode_style.REFERENCE_COLOR, linestyle="--", linewidth=1.3, zorder=2)
    ax.axhline(mean_ratio, color=mode_style.REFERENCE_COLOR, linestyle="--", linewidth=1.3, zorder=2)

    ax.set_xlabel("Average runtime (s, log scale)")
    ax.set_ylabel("Input sensitivity ratio")

    if degenerate:
        # Do not dress a single run up as a two-dimensional result.
        ax.text(
            0.5,
            0.02,
            _SINGLE_RUN_NOTE,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            color=mode_style.STATUS_COLORS["invalid"],
            fontsize=mode_style.ANNOTATION_SIZE,
        )
    else:
        # Name the quadrants the classifier implies, in the figure's corners.
        for x_pos, y_pos, label, align_x, align_y in (
            (0.99, 0.97, HOTNESS_YES, "right", "top"),
            (0.01, 0.97, HOTNESS_MAYBE, "left", "top"),
            (0.99, 0.03, HOTNESS_MAYBE, "right", "bottom"),
            (0.01, 0.03, HOTNESS_NO, "left", "bottom"),
        ):
            ax.text(
                x_pos,
                y_pos,
                label,
                transform=ax.transAxes,
                ha=align_x,
                va=align_y,
                color=mode_style.REFERENCE_COLOR,
                fontsize=mode_style.ANNOTATION_SIZE,
            )

    hotnesses = [h for h in (HOTNESS_YES, HOTNESS_MAYBE, HOTNESS_NO) if any(r.hotness == h for r in plotted)]
    kinds = sorted({region.key.kind for region in plotted})
    _hotness_kind_legends(ax, hotnesses, kinds, outside=True)
    mode_style.style_axes(ax)
    interaction.setup_interaction(figure, format_region_tooltip, on_select)


def render_top_bars(
    figure: Any,
    regions: Sequence[HotspotRegion],
    top_n: int = DEFAULT_TOP_N,
    on_select: Optional[Callable[[HotspotRegion], None]] = None,
) -> None:
    """Horizontal bars of the hottest regions by average runtime, coloured by hotness."""
    figure.clear()
    ax = figure.add_subplot(111)

    if not regions:
        interaction.empty_message(ax, _NO_DATA)
        return

    selected = top_regions(regions, top_n)
    # Hottest at the top: barh grows upwards, so plot in reverse order.
    selected = list(reversed(selected))

    positions = list(range(len(selected)))
    bars = ax.barh(
        positions,
        [region.avg for region in selected],
        color=[hotness_color(region.hotness) for region in selected],
        height=0.72,
    )
    for bar, region in zip(bars, selected):
        interaction.attach(bar, region)

    ax.set_yticks(positions)
    ax.set_yticklabels([region.key.location for region in selected])
    ax.set_xlabel("Average runtime (s)")

    # Value + hotness at the end of each bar; the axis alone makes small bars
    # unreadable, and the hotness is the reason the bar is interesting.
    span = max((region.avg for region in selected), default=0.0)
    for position, region in zip(positions, selected):
        ax.text(
            region.avg + span * 0.01,
            position,
            f"{region.avg:.3f}s  {region.hotness}",
            va="center",
            ha="left",
            fontsize=mode_style.ANNOTATION_SIZE,
            color="0.25",
        )
    ax.set_xlim(right=span * 1.28 if span > 0 else 1.0)

    hotnesses = [h for h in (HOTNESS_YES, HOTNESS_MAYBE, HOTNESS_NO) if any(r.hotness == h for r in selected)]
    _hotness_kind_legends(ax, hotnesses, [])
    mode_style.style_axes(ax)
    interaction.setup_interaction(figure, format_region_tooltip, on_select)


def render_run_profile(
    figure: Any,
    region: Optional[HotspotRegion],
    on_select: Optional[Callable[[HotspotRegion], None]] = None,
) -> None:
    """One region's runtime across the accumulated runs.

    This is the direct view of what ``ratio`` summarises: a region whose runtime
    climbs with input size is a parallelization candidate, one that stays flat is
    fixed overhead.
    """
    figure.clear()
    ax = figure.add_subplot(111)

    if region is None:
        interaction.empty_message(ax, "Select a code region to see its profile")
        return
    if not region.runtimes:
        interaction.empty_message(ax, f"No per-run data recorded for {region.key.location}")
        return

    indices = list(range(len(region.runtimes)))
    (line,) = ax.plot(
        indices,
        region.runtimes,
        marker=kind_marker(region.key.kind),
        markersize=mode_style.LINE_MARKER_SIZE,
        linewidth=2.0,
        color=hotness_color(region.hotness),
    )
    interaction.attach(line, region)

    if len(region.runtimes) > 1:
        ax.axhline(region.minimum, color=mode_style.REFERENCE_COLOR, linestyle=":", linewidth=1.1)
        ax.axhline(region.maximum, color=mode_style.REFERENCE_COLOR, linestyle=":", linewidth=1.1)

    ax.set_xlabel("Measurement run")
    ax.set_ylabel("Runtime (s)")
    ax.set_xticks(indices)
    ax.set_ylim(bottom=0)
    ax.set_title(
        f"{region_display_name(region)}  ({region.key.location})",
        fontsize=mode_style.LEGEND_TITLE_SIZE,
    )

    summary = f"min {region.minimum:.6f}s   max {region.maximum:.6f}s   ratio {region.ratio:.3f}   {region.hotness}"
    if len(region.runtimes) < 2:
        summary += "\nsingle run: ratio is fixed at 0.5 and carries no information"
    ax.text(
        0.5,
        0.02,
        summary,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        color=mode_style.REFERENCE_COLOR,
        fontsize=mode_style.ANNOTATION_SIZE,
    )

    mode_style.style_axes(ax)
    interaction.setup_interaction(figure, format_region_tooltip, on_select)
