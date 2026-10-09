# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The comparison as a self-contained HTML page with charts: no external scripts, styles or fonts, so it can be
opened from a downloaded artifact without network access."""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from benchmark_compare.report_markdown import (
    BREAKDOWN_HINT,
    rounds_text,
    format_change,
    format_factor,
    format_nanoseconds,
    format_p,
)
from benchmark_compare.results import (
    BreakdownComparison,
    CallbacksComparison,
    Comparison,
    Manifest,
    Metric,
    PassOverheadComparison,
)
from benchmark_compare.stats import IMPROVEMENT, REGRESSION

STYLE = """
:root {
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --grid: #d1d9e0; --card: #f6f8fa;
  --base: #8c959f; --head: #0969da; --call: #bf8700; --bad: #cf222e; --good: #1a7f37;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --grid: #3d444d; --card: #151b23;
    --base: #6e7681; --head: #4493f8; --call: #d29922; --bad: #f85149; --good: #3fb950;
  }
}
:root[data-theme="dark"] {
  --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --grid: #3d444d; --card: #151b23;
  --base: #6e7681; --head: #4493f8; --call: #d29922; --bad: #f85149; --good: #3fb950;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 36px 0 8px; padding-bottom: 4px; border-bottom: 1px solid var(--grid); }
p { margin: 6px 0; }
.muted { color: var(--muted); }
.summary { background: var(--card); border: 1px solid var(--grid); border-radius: 6px; padding: 12px 16px;
  margin: 16px 0; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; margin: 12px 0; font-variant-numeric: tabular-nums; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { font-weight: 600; }
.regression { color: var(--bad); font-weight: 600; }
.improvement { color: var(--good); font-weight: 600; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin: 8px 0; color: var(--muted); }
.legend span::before { content: ""; display: inline-block; width: 12px; height: 12px; margin-right: 6px;
  vertical-align: -1px; border-radius: 2px; background: var(--swatch); }
svg text { fill: var(--fg); font-size: 12px; }
svg .axis { stroke: var(--grid); }
svg .whisker { stroke: var(--fg); stroke-width: 1; }
.heat td.cell { min-width: 64px; }
"""


@dataclass
class Bar:
    """One bar of a chart, made of segments stacked from left to right."""

    segments: List[float]
    colors: List[str]
    low: Optional[float] = None
    high: Optional[float] = None


@dataclass
class BarGroup:
    label: str
    bars: List[Bar]


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def bar_chart(groups: Sequence[BarGroup], value_format: Callable[[float], str], label_width: int = 230) -> str:
    """Horizontal bars, grouped per category, with optional whiskers from ``low`` to ``high``."""
    bar_height, gap, group_gap, chart_width = 14, 3, 12, 520
    finite = [
        value
        for group in groups
        for bar in group.bars
        for value in [sum(bar.segments), bar.high if bar.high is not None else 0.0]
        if math.isfinite(value)
    ]
    maximum = max(finite) if finite else 1.0
    maximum = maximum if maximum > 0.0 else 1.0
    scale = chart_width / (maximum * 1.08)
    value_width = 80
    width = label_width + chart_width + value_width

    parts: List[str] = []
    y = 4
    for group in groups:
        group_height = len(group.bars) * (bar_height + gap) - gap
        parts.append(
            f'<text x="{label_width - 8}" y="{y + group_height / 2 + 4:.1f}" text-anchor="end">'
            f"{_escape(group.label)}</text>"
        )
        for bar in group.bars:
            x = float(label_width)
            for value, color in zip(bar.segments, bar.colors):
                if not math.isfinite(value) or value <= 0.0:
                    continue
                parts.append(
                    f'<rect x="{x:.1f}" y="{y}" width="{value * scale:.1f}" height="{bar_height}" '
                    f'fill="var({color})" rx="2"/>'
                )
                x += value * scale
            if bar.low is not None and bar.high is not None and math.isfinite(bar.low) and math.isfinite(bar.high):
                middle = y + bar_height / 2
                x_low, x_high = label_width + bar.low * scale, label_width + bar.high * scale
                parts.append(
                    f'<line class="whisker" x1="{x_low:.1f}" y1="{middle}" x2="{x_high:.1f}" y2="{middle}"/>'
                    f'<line class="whisker" x1="{x_low:.1f}" y1="{y + 3}" x2="{x_low:.1f}" y2="{y + bar_height - 3}"/>'
                    f'<line class="whisker" x1="{x_high:.1f}" y1="{y + 3}" x2="{x_high:.1f}" '
                    f'y2="{y + bar_height - 3}"/>'
                )
            total = sum(value for value in bar.segments if math.isfinite(value))
            end = x
            if bar.high is not None and math.isfinite(bar.high):
                end = max(end, label_width + bar.high * scale)
            parts.append(f'<text x="{end + 6:.1f}" y="{y + bar_height - 3}">{_escape(value_format(total))}</text>')
            y += bar_height + gap
        y += group_gap - gap
    height = y + 4
    axis = f'<line class="axis" x1="{label_width}" y1="0" x2="{label_width}" y2="{height}"/>'
    return (
        f'<div class="scroll"><svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img">{axis}{"".join(parts)}</svg></div>'
    )


def _verdict_class(metric: Metric) -> str:
    return {REGRESSION: "regression", IMPROVEMENT: "improvement"}.get(metric.verdict, "")


def _change_cell(metric: Metric) -> str:
    return f'<td class="{_verdict_class(metric)}">{_escape(format_change(metric))}</td>'


def _values_cell(metric: Metric, formatter: Callable[[float], str]) -> str:
    if not math.isfinite(metric.base):
        return f"<td>{_escape(formatter(metric.head))}</td>"
    return f"<td>{_escape(formatter(metric.base))} → {_escape(formatter(metric.head))}</td>"


def _versions(manifest: Manifest) -> str:
    if manifest.base_available:
        return f"<code>{_escape(manifest.base_label)}</code> → <code>{_escape(manifest.head_label)}</code>"
    return f"<code>{_escape(manifest.head_label)}</code> (not compared: {_escape(manifest.base_note)})"


def _legend(manifest: Manifest, extra: Sequence[str] = ()) -> str:
    items = []
    if manifest.base_available:
        items.append(f'<span style="--swatch: var(--base)">{_escape(manifest.base_label)} (before)</span>')
    items.append(f'<span style="--swatch: var(--head)">{_escape(manifest.head_label)} (after)</span>')
    items += list(extra)
    return f'<div class="legend">{"".join(items)}</div>'


def _metric_bars(metric: Metric, manifest: Manifest) -> List[Bar]:
    bars = []
    if manifest.base_available:
        bars.append(Bar([metric.base], ["--base"], metric.base_min, metric.base_max))
    bars.append(Bar([metric.head], ["--head"], metric.head_min, metric.head_max))
    return bars


def _pass_overhead_html(section: PassOverheadComparison) -> str:
    manifest = section.manifest
    groups = [BarGroup(program.name, _metric_bars(program.run_factor, manifest)) for program in section.programs]
    rows = "".join(
        f"<tr><td>{_escape(program.name)}</td>"
        f"{_values_cell(program.run_factor, format_factor)}{_change_cell(program.run_factor)}"
        f"<td>{_escape(format_p(program.run_factor))}</td>"
        f"{_values_cell(program.compile_factor, format_factor)}{_change_cell(program.compile_factor)}"
        f"<td>{_escape(format_p(program.compile_factor))}</td>"
        f"{_values_cell(program.size_factor, format_factor)}{_change_cell(program.size_factor)}</tr>"
        for program in section.programs
    )
    rows += (
        f"<tr><th>geometric mean</th>{_values_cell(section.geomean_run_factor, format_factor)}"
        f"{_change_cell(section.geomean_run_factor)}<td></td>"
        f"{_values_cell(section.geomean_compile_factor, format_factor)}{_change_cell(section.geomean_compile_factor)}"
        f"<td></td>{_values_cell(section.geomean_size_factor, format_factor)}"
        f"{_change_cell(section.geomean_size_factor)}</tr>"
    )
    descriptions = "".join(
        f"<li><b>{_escape(program.name)}</b>: {_escape(program.description)}</li>"
        for program in section.programs
        if program.description
    )
    return (
        "<h2>Profiling overhead (pass_overhead_benchmark)</h2>"
        f"<p>Run time of the instrumented program as a factor of the same program built without the pass. "
        f"{_versions(manifest)}, <code>{_escape(section.compiler)}</code>, {rounds_text(manifest.rounds)} × "
        f"{_escape(str(manifest.settings.get('repetitions', '?')))} repetitions per version. Bars show the median, "
        "whiskers the range of the repetitions.</p>"
        f"{_legend(manifest)}{bar_chart(groups, format_factor)}"
        '<div class="scroll"><table><tr><th>program</th><th>run time slowdown</th><th>Δ</th><th>p</th>'
        "<th>compile time</th><th>Δ</th><th>p</th><th>binary size</th><th>Δ</th></tr>"
        f"{rows}</table></div>"
        f'<ul class="muted">{descriptions}</ul>'
    )


CALL_ONLY_LEGEND = '<span style="--swatch: var(--call)">call only</span>'


def _callbacks_html(section: CallbacksComparison) -> str:
    manifest = section.manifest
    groups = []
    for callback in section.callbacks:
        bars = []
        if manifest.base_available:
            bars.append(
                Bar(
                    [callback.call_only.base, max(callback.total.base - callback.call_only.base, 0.0)],
                    ["--call", "--base"],
                    callback.total.base_min,
                    callback.total.base_max,
                )
            )
        bars.append(
            Bar(
                [callback.call_only.head, max(callback.total.head - callback.call_only.head, 0.0)],
                ["--call", "--head"],
                callback.total.head_min,
                callback.total.head_max,
            )
        )
        groups.append(BarGroup(callback.name, bars))
    rows = "".join(
        f"<tr><td><code>{_escape(callback.name)}</code>{' (2 calls)' if callback.calls_per_iteration > 1 else ''}</td>"
        f"{_values_cell(callback.total, format_nanoseconds)}{_change_cell(callback.total)}"
        f"<td>{_escape(format_p(callback.total))}</td>"
        f"{_values_cell(callback.call_only, format_nanoseconds)}{_change_cell(callback.call_only)}"
        f"{_values_cell(callback.body, format_nanoseconds)}{_change_cell(callback.body)}"
        f"<td>{_escape(format_p(callback.body))}</td></tr>"
        for callback in section.callbacks
    )
    return (
        "<h2>Cost of the injected callbacks (callback_benchmark)</h2>"
        f"<p>Nanoseconds per iteration, split into the call (runtime without callback bodies) and the body. "
        f"{_versions(manifest)}, {rounds_text(manifest.rounds)} × "
        f"{_escape(str(manifest.settings.get('repetitions', '?')))} repetitions per version.</p>"
        f"{_legend(manifest, [CALL_ONLY_LEGEND])}"
        f"{bar_chart(groups, lambda value: format_nanoseconds(value) + ' ns', label_width=280)}"
        '<div class="scroll"><table><tr><th>callback</th><th>call + body [ns]</th><th>Δ</th><th>p</th>'
        "<th>call only [ns]</th><th>Δ</th><th>body [ns]</th><th>Δ</th><th>p</th></tr>"
        f"{rows}</table></div>"
    )


def _heat_style(metric: Metric) -> str:
    """The background of a heatmap cell: red for a larger, green for a smaller factor, by the size of the change."""
    if not math.isfinite(metric.change):
        return ""
    strength = min(abs(metric.change) / 0.5, 1.0) * 60.0
    color = "--bad" if metric.change > 0 else "--good"
    return f' style="background: color-mix(in srgb, var({color}) {strength:.0f}%, transparent)"'


def _breakdown_html(section: BreakdownComparison) -> str:
    manifest = section.manifest
    header = "".join(f"<th>{_escape(program)}</th>" for program in section.programs)
    rows = ""
    for configuration in section.configurations:
        cells = ""
        for program in section.programs:
            metric = section.factors[configuration][program]
            title = f"{format_factor(metric.base)} → {format_factor(metric.head)} ({format_change(metric)})"
            cells += f'<td class="cell"{_heat_style(metric)} title="{_escape(title)}">{format_factor(metric.head)}</td>'
        geomean = section.geomeans[configuration]
        rows += (
            f"<tr><td>{_escape(configuration)}</td>{cells}"
            f'<td class="cell"{_heat_style(geomean)}><b>{format_factor(geomean.head)}</b></td>'
            f"{_change_cell(geomean)}</tr>"
        )
    explanation = (
        "Cells show the factor of this version; their color the change against the version compared with "
        "(red: larger, green: smaller; hover for both values)."
        if manifest.base_available
        else "Cells show the factor of this version."
    )
    return (
        "<h2>Where the overhead comes from (callback breakdown)</h2>"
        "<p>Run time factor of every program against its uninstrumented build, linked against the runtime without "
        "callback bodies (<code>calls only</code>) and with exactly one body switched on (<code>only __dp_*</code>). "
        f"One run per version ({_versions(manifest)}): read it as a ranking. {explanation}</p>"
        f'<div class="scroll"><table class="heat"><tr><th>configuration</th>{header}<th>geomean</th><th>Δ</th></tr>'
        f"{rows}</table></div>"
    )


def format_html(comparison: Comparison, run_url: Optional[str] = None) -> str:
    regressions, improvements = comparison.regressions, comparison.improvements
    summary = (
        f"<b>{regressions} regression{'s' if regressions != 1 else ''}</b> and "
        f"<b>{improvements} improvement{'s' if improvements != 1 else ''}</b> beyond ±{comparison.threshold:.0%} "
        "(significant where measured repeatedly: two-sided Mann-Whitney U test, p &lt; 0.05). Lower is better "
        "everywhere. Informative only, never fails the CI."
    )
    sections = ""
    if comparison.pass_overhead is not None:
        sections += _pass_overhead_html(comparison.pass_overhead)
        if comparison.breakdown is None:
            hint = re.sub(r"`([^`]+)`", r"<code>\1</code>", _escape(BREAKDOWN_HINT))
            sections += f'<p class="muted">{hint}</p>'
    if comparison.callbacks is not None:
        sections += _callbacks_html(comparison.callbacks)
    if comparison.breakdown is not None:
        sections += _breakdown_html(comparison.breakdown)
    if not sections:
        sections = "<p>No benchmark results were found.</p>"
    link = f'<p><a href="{_escape(run_url)}">Workflow run</a></p>' if run_url else ""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Benchmark comparison</title><style>{STYLE}</style></head>"
        f'<body><main><h1>Benchmark comparison</h1><div class="summary">{summary}</div>{link}{sections}'
        "</main></body></html>\n"
    )
