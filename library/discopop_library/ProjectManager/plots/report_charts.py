# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Chart renderers for the Report tab, driven by :class:`ExecutionRecord`s.

Three chart types share the encoding language from :mod:`mode_style` (colour =
configuration, marker/dash = execution mode, fill = validity).

Records whose parallelization suggestions could not be applied carry no measurement
(the run was skipped instead of executed on the unmodified code), so they are excluded
from every metric here and surfaced as an explicit in-chart warning plus a dedicated
row in the Report table -- never silently dropped, and never plotted as a parallel run
that happened to reach no speedup:

* :func:`render_pareto`  -- trade-off scatter of every measured run;
* :func:`render_scaling` -- scatter of one (config, mode) series per thread count;
* :func:`render_bars`    -- best-of comparison per configuration and mode.

The pure metric/reduction helpers are matplotlib-free and unit-tested; only the
``render_*`` functions touch a figure (passed in by the caller). Record metadata
is stored on each point/line/bar via :mod:`interaction` so hovering shows a
tooltip and clicking can report the record back to the caller (e.g. to fill an
always-visible detail panel).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.plots import interaction, mode_style
from discopop_library.ProjectManager.plots.data import ExecutionRecord, pareto_frontier

# metric key -> (axis label, "more is better")
METRICS: Dict[str, Tuple[str, bool]] = {
    "speedup": ("Speedup ×", True),
    "efficiency": ("Parallel efficiency", True),
    "runtime": ("Runtime (s)", False),
    "threads": ("Threads", True),
}

# Grouped-bar colours are keyed by mode (the within-group series); kept separate
# from the categorical config palette, which encodes colour on the other charts.
MODE_BAR_COLORS: Dict[str, str] = {
    "seq": mode_style.REFERENCE_COLOR,
    "par": mode_style.CONFIG_PALETTE[0],
    "dp": mode_style.CONFIG_PALETTE[2],
    "hd": mode_style.CONFIG_PALETTE[3],
}


def metric_value(record: ExecutionRecord, metric: str) -> Optional[float]:
    if metric == "runtime":
        return record.time
    if metric == "threads":
        return float(record.thread_count)
    if metric == "speedup":
        return record.speedup
    if metric == "efficiency":
        return record.efficiency
    return None


def more_is_better(metric: str) -> bool:
    return METRICS.get(metric, ("", True))[1]


def best_of(records: Sequence[ExecutionRecord], metric: str) -> Dict[Tuple[str, str], ExecutionRecord]:
    """Best *valid* record per (config, mode) by ``metric`` (max, or min for runtime).

    Records without a measurement (suggestions not applied, so the run was skipped)
    are never candidates: they hold no runtime to compare.
    """
    prefer_max = more_is_better(metric)
    best: Dict[Tuple[str, str], ExecutionRecord] = {}
    for record in records:
        if not record.valid or not record.has_measurement:
            continue
        value = metric_value(record, metric)
        if value is None:
            continue
        key = (record.config, record.mode)
        current = best.get(key)
        if current is None:
            best[key] = record
            continue
        current_value = metric_value(current, metric)
        assert current_value is not None
        if (prefer_max and value > current_value) or (not prefer_max and value < current_value):
            best[key] = record
    return best


def record_status_text(record: ExecutionRecord) -> str:
    """The record's status as shown in tooltips, the detail bar and the table."""
    if record.application_failed:
        return "⚠ not applied"
    if record.valid:
        return "✓ valid"
    return "⧗ timeout" if record.timeout else "✗ failed"


def _format_record_tooltip(record: ExecutionRecord) -> str:
    """Format an ExecutionRecord as a multi-line tooltip string."""
    lines = [
        f"Config: {record.config}",
        f"Mode: {record.mode}",
        f"Suggestions: {record.applied_suggestions if record.applied_suggestions else '(none)'}",
        f"Threads: {record.thread_count}",
    ]
    if record.has_measurement:
        lines.append(f"Runtime: {record.time:.3f}s")
    if record.speedup is not None:
        lines.append(f"Speedup: {record.speedup:.3f}×")
    if record.efficiency is not None:
        lines.append(f"Efficiency: {record.efficiency:.3f}")
    if record.amdahl_ceiling is not None:
        lines.append(f"Amdahl ceiling ({record.thread_count} threads): {record.amdahl_ceiling:.3f}×")
        if record.amdahl_limit is not None and math.isfinite(record.amdahl_limit):
            lines.append(f"Amdahl limit (unlimited threads): {record.amdahl_limit:.3f}×")
    lines.append(f"Status: {record_status_text(record)}")
    if record.application_failed:
        lines.append(f"Not applied: {record.failed_suggestions if record.failed_suggestions else '(unknown)'}")
        lines.append("Not executed - the code was unmodified.")
    return "\n".join(lines)


def not_applied_records(records: Sequence[ExecutionRecord]) -> List[ExecutionRecord]:
    """Records that were skipped because their suggestions could not be applied."""
    return [r for r in records if r.application_failed]


def not_applied_note(records: Sequence[ExecutionRecord]) -> Optional[str]:
    """Warning text for charts, or None when every requested patch was applied."""
    skipped = not_applied_records(records)
    if not skipped:
        return None
    ids = sorted({s for r in skipped for s in (r.failed_suggestions or r.requested_suggestions)})
    return (
        "⚠ "
        + str(len(skipped))
        + " run(s) not shown: suggestions could not be applied"
        + (" (" + ", ".join(str(i) for i in ids) + ")" if ids else "")
        + " - see Table"
    )


def _annotate_not_applied(ax: Any, records: Sequence[ExecutionRecord]) -> None:
    """Make skipped runs visible in a chart that cannot plot them."""
    note = not_applied_note(records)
    if note is None:
        return
    ax.text(
        0.99,
        0.01,
        note,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=mode_style.ANNOTATION_SIZE,
        color=mode_style.status_color(mode_style.NOT_APPLIED_STATUS),
    )


def _empty(ax: Any, message: str = "No execution results yet") -> None:
    interaction.empty_message(ax, message)


def _setup_record_interaction(figure: Any, on_select: Optional[Callable[[ExecutionRecord], None]] = None) -> None:
    """Enable hover tooltips and click-to-select for records in the figure."""
    interaction.setup_interaction(figure, _format_record_tooltip, on_select)


def _config_mode_legends(ax: Any, configs: Sequence[str], modes: Sequence[str], colors: Dict[str, str]) -> None:
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    config_handles = [Patch(facecolor=colors[c], label=c) for c in configs]
    mode_handles = [
        Line2D([], [], marker=mode_style.mode_marker(m), color="0.35", linestyle="None", label=m) for m in modes
    ]
    if config_handles:
        first = ax.legend(handles=config_handles, title="config", loc="upper left", fontsize=mode_style.LEGEND_SIZE)
        mode_style.style_legend(first)
        ax.add_artist(first)
    if mode_handles:
        second = ax.legend(handles=mode_handles, title="mode", loc="lower right", fontsize=mode_style.LEGEND_SIZE)
        mode_style.style_legend(second)


def render_pareto(
    figure: Any,
    records: Sequence[ExecutionRecord],
    x_metric: str = "efficiency",
    y_metric: str = "speedup",
    config_filter: Optional[str] = None,
    valid_only: bool = False,
    show_frontier: bool = True,
    on_select: Optional[Callable[[ExecutionRecord], None]] = None,
) -> None:
    figure.clear()
    ax = figure.add_subplot(111)

    rows = [r for r in records if r.config == config_filter or config_filter in (None, "all")]
    rows = [r for r in rows if not r.timeout]
    # skipped runs have no coordinates to plot; they are reported by the annotation
    # below and listed in full in the Table tab
    chart_records = rows
    rows = [r for r in rows if r.has_measurement]
    if valid_only:
        rows = [r for r in rows if r.valid]
    points: List[Tuple[ExecutionRecord, float, float]] = []
    for r in rows:
        x = metric_value(r, x_metric)
        y = metric_value(r, y_metric)
        if x is None or y is None:
            continue
        points.append((r, x, y))
    if not points:
        _empty(ax)
        _annotate_not_applied(ax, chart_records)
        return

    colors = mode_style.assign_config_colors([r.config for r in records])
    # group by (config, mode, valid) so we can set colour, marker, and fill together
    groups: Dict[Tuple[str, str, bool], List[Tuple[ExecutionRecord, float, float]]] = {}
    for r, x, y in points:
        groups.setdefault((r.config, r.mode, r.valid), []).append((r, float(x), float(y)))
    for (config, mode, valid), rxy in groups.items():
        xs = [p[1] for p in rxy]
        ys = [p[2] for p in rxy]
        recs = [p[0] for p in rxy]
        color = colors.get(config, mode_style.CONFIG_PALETTE[0])
        if valid:
            coll = ax.scatter(
                xs,
                ys,
                marker=mode_style.mode_marker(mode),
                color=color,
                edgecolors="white",
                linewidths=0.6,
                s=mode_style.SCATTER_SIZE,
                zorder=3,
            )
        else:
            coll = ax.scatter(
                xs,
                ys,
                marker=mode_style.mode_marker(mode),
                facecolors="none",
                edgecolors=color,
                linewidths=1.8,
                s=mode_style.SCATTER_SIZE,
                zorder=3,
            )
        interaction.attach(coll, recs)

    # Pareto frontier only makes sense when both axes are "more is better"
    if show_frontier and more_is_better(x_metric) and more_is_better(y_metric):
        valid_points = [(x, y) for (r, x, y) in points if r.valid]
        frontier = pareto_frontier(valid_points)
        if len(frontier) > 1:
            fx = [valid_points[i][0] for i in frontier]
            fy = [valid_points[i][1] for i in frontier]
            ax.plot(
                fx,
                fy,
                color=mode_style.REFERENCE_COLOR,
                linestyle="--",
                linewidth=1.4,
                zorder=2,
                label="Pareto frontier",
            )

    x_label = METRICS.get(x_metric, (x_metric, True))[0]
    y_label = METRICS.get(y_metric, (y_metric, True))[0]
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    configs = sorted({r.config for r, _x, _y in points})
    modes = sorted({r.mode for r, _x, _y in points})
    _config_mode_legends(ax, configs, modes, colors)
    _annotate_not_applied(ax, chart_records)
    mode_style.style_axes(ax)
    _setup_record_interaction(figure, on_select)


def render_scaling(
    figure: Any,
    records: Sequence[ExecutionRecord],
    metric: str = "speedup",
    config_filter: Optional[str] = None,
    show_ideal: bool = True,
    on_select: Optional[Callable[[ExecutionRecord], None]] = None,
) -> None:
    figure.clear()
    ax = figure.add_subplot(111)

    candidates = [r for r in records if config_filter in (None, "all") or r.config == config_filter]
    rows = [r for r in candidates if r.valid and r.has_measurement]
    if not rows:
        _empty(ax)
        _annotate_not_applied(ax, candidates)
        return

    colors = mode_style.assign_config_colors([r.config for r in records])
    series: Dict[Tuple[str, str], List[Tuple[int, float]]] = {}
    for r in rows:
        value = metric_value(r, metric)
        if value is None:
            continue
        series.setdefault((r.config, r.mode), []).append((r.thread_count, float(value)))

    max_threads = 1
    for (config, mode), pts in sorted(series.items()):
        pts = sorted(pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        max_threads = max(max_threads, *xs) if xs else max_threads
        # scatter plot: the measurements of a series are not connected
        line_kwargs: Dict[str, Any] = {
            "color": colors.get(config, mode_style.CONFIG_PALETTE[0]),
            "marker": mode_style.mode_marker(mode),
            "markersize": mode_style.LINE_MARKER_SIZE,
            "linestyle": "None",
        }
        (line,) = ax.plot(xs, ys, **line_kwargs)
        # Store a representative record from this series (the best one by the metric).
        best_record = max(
            [r for r in rows if r.config == config and r.mode == mode], key=lambda r: metric_value(r, metric) or 0.0
        )
        interaction.attach(line, best_record)

    if show_ideal and metric == "speedup":
        ax.plot(
            [0, max_threads],
            [0, max_threads],
            color=mode_style.REFERENCE_COLOR,
            linestyle="--",
            linewidth=1.3,
            label="ideal (linear)",
        )

    ax.set_xlabel("Threads")
    ax.set_ylabel(METRICS.get(metric, (metric, True))[0])
    ax.set_ylim(bottom=0)
    configs = sorted({c for (c, _m) in series})
    modes = sorted({m for (_c, m) in series})
    _config_mode_legends(ax, configs, modes, colors)
    _annotate_not_applied(ax, candidates)
    mode_style.style_axes(ax)
    _setup_record_interaction(figure, on_select)


def render_bars(
    figure: Any,
    records: Sequence[ExecutionRecord],
    metric: str = "speedup",
    on_select: Optional[Callable[[ExecutionRecord], None]] = None,
) -> None:
    figure.clear()
    ax = figure.add_subplot(111)

    best = best_of(records, metric)
    if not best:
        _empty(ax, "No valid execution results yet")
        _annotate_not_applied(ax, records)
        return

    configs = sorted({config for (config, _mode) in best})
    modes = sorted({mode for (_config, mode) in best})
    n_modes = max(1, len(modes))
    bar_width = 0.8 / n_modes

    import numpy as np

    x = np.arange(len(configs))
    for i, mode in enumerate(modes):
        records_in_mode = []
        heights = []
        for config in configs:
            record = best.get((config, mode))
            records_in_mode.append(record)
            value = metric_value(record, metric) if record is not None else None
            heights.append(value if value is not None else 0.0)
        offset = (i - (n_modes - 1) / 2) * bar_width
        bars = ax.bar(
            x + offset,
            heights,
            width=bar_width,
            color=MODE_BAR_COLORS.get(mode, mode_style.CONFIG_PALETTE[i % len(mode_style.CONFIG_PALETTE)]),
            label=mode,
        )
        # Attach record metadata to each bar patch.
        for bar, record in zip(bars, records_in_mode):
            if record is not None:
                interaction.attach(bar, record)

    ax.set_xticks(list(x))
    ax.set_xticklabels(configs)
    ax.set_ylabel(METRICS.get(metric, (metric, True))[0])
    ax.set_xlabel("Configuration")
    legend = ax.legend(title="mode", fontsize=mode_style.LEGEND_SIZE)
    mode_style.style_legend(legend)
    _annotate_not_applied(ax, records)
    mode_style.style_axes(ax)
    _setup_record_interaction(figure, on_select)


# ── Amdahl ceilings ───────────────────────────────────────────────────────────

AMDAHL_X_MODES = ("both", "threads", "unlimited")


def amdahl_points(
    records: Sequence[ExecutionRecord],
    config_filter: Optional[str] = None,
    valid_only: bool = False,
) -> Tuple[List[ExecutionRecord], int]:
    """Records usable in the Amdahl charts, and how many measured records lack a ceiling.

    A record is usable when it was measured, has a speedup and efficiency, and its
    suggestions' runtime shares are known (``amdahl_ceiling``). The ceiling is an estimate
    derived from hotspot runtimes, so records without it are counted, not guessed.
    """
    rows = [r for r in records if r.config == config_filter or config_filter in (None, "all")]
    # seq/dp/hd runs apply no suggestions: their "ceiling" is trivially 1 and dp/hd are instrumented runs
    rows = [r for r in rows if r.mode not in ("seq", "dp", "hd")]
    rows = [r for r in rows if r.has_measurement and not r.timeout and r.speedup is not None]
    if valid_only:
        rows = [r for r in rows if r.valid]
    usable = [r for r in rows if r.amdahl_ceiling is not None]
    return usable, len(rows) - len(usable)


def _annotate_missing_ceilings(ax: Any, missing: int) -> None:
    if not missing:
        return
    ax.text(
        0.01,
        0.01,
        f"{missing} run(s) not shown: no Amdahl ceiling (hotspot runtimes unknown for their suggestions)",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=mode_style.ANNOTATION_SIZE,
        color=mode_style.REFERENCE_COLOR,
    )


def render_amdahl_scatter(
    figure: Any,
    records: Sequence[ExecutionRecord],
    x_mode: str = "both",
    config_filter: Optional[str] = None,
    valid_only: bool = False,
    on_select: Optional[Callable[[ExecutionRecord], None]] = None,
) -> None:
    """Achieved speedup (y) against the Amdahl ceiling (x), with the speedup = ceiling bound.

    ``x_mode``: ``threads`` plots the ceiling for each record's own thread count,
    ``unlimited`` the ceiling for unlimited threads, ``both`` the first as the point and the
    second as a hollow marker joined to it by a thin line. A point on the dashed diagonal
    reaches its ceiling; the distance below it is what the parallelization leaves unused.
    The unlimited ceiling can lie far beyond everything else, so it is clipped to the axis
    and drawn as an arrow marker at the edge.
    """
    figure.clear()
    ax = figure.add_subplot(111)
    usable, missing = amdahl_points(records, config_filter, valid_only)
    if not usable:
        _empty(ax, "No runs with an Amdahl ceiling yet")
        _annotate_missing_ceilings(ax, missing)
        return

    colors = mode_style.assign_config_colors([r.config for r in records])
    show_n = x_mode in ("both", "threads")
    show_limit = x_mode in ("both", "unlimited")
    heights = [float(r.speedup) for r in usable if r.speedup is not None]
    bounded = [float(r.amdahl_ceiling) for r in usable if r.amdahl_ceiling is not None]
    # sized by the measurements and the N-thread ceilings only: the unlimited ceiling can be orders of
    # magnitude larger and is clipped to the axis edge instead
    x_right = max(heights + bounded + [1.0]) * 1.15

    def limit_x(r: ExecutionRecord) -> Optional[float]:
        return None if r.amdahl_limit is None else float(r.amdahl_limit)

    groups: Dict[Tuple[str, str, bool], List[ExecutionRecord]] = {}
    for r in usable:
        groups.setdefault((r.config, r.mode, r.valid), []).append(r)
    for (config, mode, valid), recs in groups.items():
        color = colors.get(config, mode_style.CONFIG_PALETTE[0])
        ys = [float(r.speedup) for r in recs if r.speedup is not None]
        if show_n:
            xs = [float(r.amdahl_ceiling) for r in recs if r.amdahl_ceiling is not None]
            kwargs: Dict[str, Any] = (
                {"color": color, "edgecolors": "white", "linewidths": 0.6}
                if valid
                else {"facecolors": "none", "edgecolors": color, "linewidths": 1.8}
            )
            coll = ax.scatter(
                xs, ys, marker=mode_style.mode_marker(mode), s=mode_style.SCATTER_SIZE, zorder=3, **kwargs
            )
            interaction.attach(coll, recs)
        if show_limit:
            lx: List[float] = []
            ly: List[float] = []
            lrecs: List[ExecutionRecord] = []
            clipped: List[bool] = []
            for r in recs:
                lim = limit_x(r)
                if lim is None or r.speedup is None:
                    continue
                if show_n and r.amdahl_ceiling is not None:
                    ax.plot(
                        [r.amdahl_ceiling, min(lim, x_right)],
                        [r.speedup, r.speedup],
                        color=color,
                        alpha=0.35,
                        linewidth=1.0,
                        zorder=1,
                    )
                lx.append(min(lim, x_right))
                ly.append(float(r.speedup))
                lrecs.append(r)
                clipped.append(lim > x_right)
            for is_clipped in (False, True):
                sel = [i for i, c in enumerate(clipped) if c == is_clipped]
                if not sel:
                    continue
                coll = ax.scatter(
                    [lx[i] for i in sel],
                    [ly[i] for i in sel],
                    marker=">" if is_clipped else mode_style.mode_marker(mode),
                    facecolors="none",
                    edgecolors=color,
                    linewidths=1.4,
                    s=mode_style.SCATTER_SIZE * 0.7,
                    zorder=2,
                    clip_on=False,
                )
                interaction.attach(coll, [lrecs[i] for i in sel])

    diagonal = [0.0, x_right]
    ax.plot(diagonal, diagonal, color=mode_style.REFERENCE_COLOR, linestyle="--", linewidth=1.2, zorder=0)
    ax.annotate(
        "speedup = ceiling",
        xy=(x_right, x_right),
        xytext=(-4, -12),
        textcoords="offset points",
        ha="right",
        fontsize=mode_style.ANNOTATION_SIZE,
        color=mode_style.REFERENCE_COLOR,
    )
    x_label = {
        "both": "Amdahl ceiling × (filled: record's threads, hollow: unlimited threads)",
        "threads": "Amdahl ceiling × (record's thread count)",
        "unlimited": "Amdahl ceiling × (unlimited threads)",
    }.get(x_mode, "Amdahl ceiling ×")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Achieved speedup ×")
    ax.set_xlim(0, x_right)
    ax.set_ylim(0, x_right)
    _config_mode_legends(ax, sorted({r.config for r in usable}), sorted({r.mode for r in usable}), colors)
    _annotate_missing_ceilings(ax, missing)
    mode_style.style_axes(ax)
    _setup_record_interaction(figure, on_select)


def render_amdahl_3d(
    figure: Any,
    records: Sequence[ExecutionRecord],
    config_filter: Optional[str] = None,
    valid_only: bool = False,
) -> None:
    """Amdahl ceiling (x, record's thread count), efficiency (y) and speedup (z) in one 3D scatter.

    Only the ceiling for the record's own thread count is used: efficiency is speedup per
    thread, so the matching ceiling is the one for the same thread count. Matplotlib's 3D
    axes do not support the 2D charts' hover and click picking; rotate with the mouse.
    """
    from mpl_toolkits.mplot3d import Axes3D  # type: ignore[import-untyped]  # noqa: F401  registers the 3d projection

    figure.clear()
    usable, missing = amdahl_points(records, config_filter, valid_only)
    usable = [r for r in usable if r.efficiency is not None]
    if not usable:
        ax2 = figure.add_subplot(111)
        _empty(ax2, "No runs with an Amdahl ceiling yet")
        _annotate_missing_ceilings(ax2, missing)
        return

    ax = figure.add_subplot(111, projection="3d")
    colors = mode_style.assign_config_colors([r.config for r in records])
    groups: Dict[Tuple[str, str, bool], List[ExecutionRecord]] = {}
    for r in usable:
        groups.setdefault((r.config, r.mode, r.valid), []).append(r)
    for (config, mode, valid), recs in groups.items():
        color = colors.get(config, mode_style.CONFIG_PALETTE[0])
        xs = [float(r.amdahl_ceiling) for r in recs if r.amdahl_ceiling is not None]
        ys = [float(r.efficiency) for r in recs if r.efficiency is not None]
        zs = [float(r.speedup) for r in recs if r.speedup is not None]
        kwargs: Dict[str, Any] = (
            {"color": color} if valid else {"facecolors": "none", "edgecolors": color, "linewidths": 1.5}
        )
        ax.scatter(
            xs, ys, zs, marker=mode_style.mode_marker(mode), s=mode_style.SCATTER_SIZE, depthshade=False, **kwargs
        )
    ax.set_xlabel("Amdahl ceiling ×")
    ax.set_ylabel("Efficiency")
    ax.set_zlabel("Speedup ×")
    # legend: configs (colour) only; the marker shape is the mode as in the 2D charts
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles: List[Any] = [Patch(facecolor=colors[c], label=c) for c in sorted({r.config for r in usable})]
    handles += [
        Line2D([], [], marker=mode_style.mode_marker(m), color="0.35", linestyle="None", label=m)
        for m in sorted({r.mode for r in usable})
    ]
    mode_style.style_legend(ax.legend(handles=handles, loc="upper left", fontsize=mode_style.LEGEND_SIZE))
    if missing:
        figure.text(
            0.01,
            0.01,
            f"{missing} run(s) not shown: no Amdahl ceiling",
            fontsize=mode_style.ANNOTATION_SIZE,
            color=mode_style.REFERENCE_COLOR,
        )
