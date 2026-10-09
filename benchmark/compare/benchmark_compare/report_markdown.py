# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The comparison as markdown: the pull request comment and the job summary."""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

from benchmark_compare.results import (
    BreakdownComparison,
    CallbacksComparison,
    Comparison,
    Manifest,
    Metric,
    PassOverheadComparison,
)
from benchmark_compare.stats import IMPROVEMENT, REGRESSION

# identifies the comment of this report, so that a new run updates it instead of adding another one
COMMENT_MARKER = "<!-- discopop-benchmark-report -->"

FLAGS = {REGRESSION: " ⚠️", IMPROVEMENT: " ✅"}

# the pull request label that adds the callback breakdown to the benchmarks (see .github/workflows/ci.yml)
BREAKDOWN_LABEL = "benchmark-breakdown"
BREAKDOWN_HINT = (
    f"Which callbacks the overhead comes from: add the label `{BREAKDOWN_LABEL}` to the pull request; the next run "
    "then adds the callback breakdown (it takes long, remove the label again afterwards)."
)


def format_factor(value: float) -> str:
    return "n/a" if not math.isfinite(value) else f"×{value:.2f}"


def format_nanoseconds(value: float) -> str:
    return "n/a" if not math.isfinite(value) else f"{value:.2f}"


def format_change(metric: Metric) -> str:
    if not math.isfinite(metric.change):
        return "–"
    if abs(metric.change) < 0.0005:
        text = "±0%"
    else:
        text = f"{metric.change:+.1%}"
    return text + FLAGS.get(metric.verdict, "")


def format_p(metric: Metric) -> str:
    if metric.p_value is None or not math.isfinite(metric.p_value):
        return "–"
    return "<0.001" if metric.p_value < 0.001 else f"{metric.p_value:.3f}"


def format_values(metric: Metric, formatter: Callable[[float], str]) -> str:
    """``before → after``, or only the value of this version when there is nothing to compare with."""
    if not math.isfinite(metric.base):
        return formatter(metric.head)
    return f"{formatter(metric.base)} → {formatter(metric.head)}"


def rounds_text(rounds: int) -> str:
    return f"{rounds} interleaved round{'s' if rounds != 1 else ''}"


def _versions(manifest: Manifest) -> str:
    if manifest.base_available:
        return f"`{manifest.base_label}` → `{manifest.head_label}`"
    return f"`{manifest.head_label}`"


def _not_compared(manifest: Manifest) -> List[str]:
    if manifest.base_available:
        return []
    return [f"_Not compared, only this version is shown: {manifest.base_note or 'no version to compare with'}._", ""]


def _pass_overhead_section(section: PassOverheadComparison, breakdown_hint: bool) -> List[str]:
    settings = section.manifest.settings
    lines = [
        "### Profiling overhead (`pass_overhead_benchmark`)",
        "",
        f"Factors against the same program built without the pass. {_versions(section.manifest)}, "
        f"`{section.compiler}`, {rounds_text(section.manifest.rounds)} × "
        f"{settings.get('repetitions', '?')} repetitions per version.",
        "",
        *_not_compared(section.manifest),
        "| program | run time slowdown | Δ | p | compile time | Δ | p | binary size | Δ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for program in section.programs:
        lines.append(
            f"| {program.name} "
            f"| {format_values(program.run_factor, format_factor)} | {format_change(program.run_factor)} "
            f"| {format_p(program.run_factor)} "
            f"| {format_values(program.compile_factor, format_factor)} | {format_change(program.compile_factor)} "
            f"| {format_p(program.compile_factor)} "
            f"| {format_values(program.size_factor, format_factor)} | {format_change(program.size_factor)} |"
        )
    lines.append(
        f"| **geometric mean** "
        f"| **{format_values(section.geomean_run_factor, format_factor)}** "
        f"| **{format_change(section.geomean_run_factor)}** | "
        f"| {format_values(section.geomean_compile_factor, format_factor)} "
        f"| {format_change(section.geomean_compile_factor)} | "
        f"| {format_values(section.geomean_size_factor, format_factor)} "
        f"| {format_change(section.geomean_size_factor)} |"
    )
    lines.append("")
    if breakdown_hint:
        lines += [f"_{BREAKDOWN_HINT}_", ""]
    return lines


def _callbacks_section(section: CallbacksComparison) -> List[str]:
    settings = section.manifest.settings
    lines = [
        "### Cost of the injected callbacks (`callback_benchmark`)",
        "",
        f"Nanoseconds per iteration. {_versions(section.manifest)}, {rounds_text(section.manifest.rounds)} × "
        f"{settings.get('repetitions', '?')} repetitions per version. `call + body` is what an instrumented "
        "program pays, `body` what the runtime does inside the call.",
        "",
        *_not_compared(section.manifest),
        "| callback | call + body [ns] | Δ | p | body [ns] | Δ |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for callback in section.callbacks:
        label = f"`{callback.name}`" + (" (2 calls)" if callback.calls_per_iteration > 1 else "")
        lines.append(
            f"| {label} "
            f"| {format_values(callback.total, format_nanoseconds)} | {format_change(callback.total)} "
            f"| {format_p(callback.total)} "
            f"| {format_values(callback.body, format_nanoseconds)} | {format_change(callback.body)} |"
        )
    lines.append("")
    return lines


def _breakdown_table(rows: List[Tuple[str, Metric]]) -> List[str]:
    lines = ["| configuration | run time factor | Δ |", "| --- | ---: | ---: |"]
    lines += [f"| {name} | {format_values(metric, format_factor)} | {format_change(metric)} |" for name, metric in rows]
    return lines


def _breakdown_section(section: BreakdownComparison, threshold: float) -> List[str]:
    lines = [
        "### Where the overhead comes from (callback breakdown)",
        "",
        f"Geometric mean of the run time factors, one run per version ({_versions(section.manifest)}): a ranking, "
        "not a measurement precise enough for a verdict.",
        "",
        *_not_compared(section.manifest),
    ]
    rows = [(name, section.geomeans[name]) for name in section.configurations]
    if not section.manifest.base_available:
        return lines + _breakdown_table(rows) + [""]

    changed = [(name, metric) for name, metric in rows if abs(metric.change) > threshold]
    if changed:
        lines += [f"Configurations whose factor changed by more than {threshold:.0%}:", ""]
        lines += _breakdown_table(changed) + [""]
    else:
        lines += [f"No configuration changed by more than {threshold:.0%}.", ""]
    lines += ["<details><summary>All configurations</summary>", "", *_breakdown_table(rows), "", "</details>", ""]
    return lines


def format_report(comparison: Comparison, run_url: Optional[str] = None, report_url: Optional[str] = None) -> str:
    """The whole report: summary line, one section per benchmark, legend and links."""
    lines = [COMMENT_MARKER, "## Benchmark comparison", ""]
    regressions, improvements = comparison.regressions, comparison.improvements
    compared = any(
        part is not None and part.manifest.base_available for part in (comparison.pass_overhead, comparison.callbacks)
    )
    if not compared:
        lines.append("Nothing to compare with: the tables show this version only.")
    elif regressions or improvements:
        lines.append(
            f"**{regressions} regression{'s' if regressions != 1 else ''} ⚠️, "
            f"{improvements} improvement{'s' if improvements != 1 else ''} ✅** beyond ±{comparison.threshold:.0%}."
        )
    else:
        lines.append(f"No significant change beyond ±{comparison.threshold:.0%}.")
    lines += ["This comparison is informative; it never fails the CI.", ""]

    if comparison.pass_overhead is not None:
        lines += _pass_overhead_section(comparison.pass_overhead, breakdown_hint=comparison.breakdown is None)
    if comparison.callbacks is not None:
        lines += _callbacks_section(comparison.callbacks)
    if comparison.breakdown is not None:
        lines += _breakdown_section(comparison.breakdown, comparison.threshold)
    if comparison.pass_overhead is None and comparison.callbacks is None and comparison.breakdown is None:
        lines += ["_No benchmark results were found._", ""]

    lines += [
        f"<sub>⚠️ / ✅: more than {comparison.threshold:.0%} slower / faster and, where measured repeatedly, "
        "significant (two-sided Mann-Whitney U test over the repetitions, p < 0.05). Values are medians. "
        "Lower is better everywhere. Times depend on the runner: compare versions of one run, not runs.</sub>",
    ]
    links = []
    if report_url:
        links.append(f"[full report with charts]({report_url})")
    if run_url:
        links.append(f"[workflow run]({run_url})")
    if links:
        lines += ["", " · ".join(links)]
    lines.append("")
    return "\n".join(lines)
