# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Reading the raw benchmark results of both versions and comparing them.

The results directory, as written by ``run_ab_benchmarks.py``::

    <results>/pass_overhead/manifest.json   which versions were measured, and why one is missing
    <results>/pass_overhead/{head,base}/round_<n>.json   reports of benchmark/pass_overhead/run_pass_benchmark.py
    <results>/callbacks/manifest.json
    <results>/callbacks/{head,base}/round_<n>.json   reports of benchmark/injected_functions/run_callback_benchmark.py
    <results>/breakdown/manifest.json
    <results>/breakdown/{head,base}.json   reports of run_pass_benchmark.py --callback-breakdown

Every part may be missing (e.g. a job that did not run); the comparison then leaves that part out.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark_compare.stats import (
    DEFAULT_ALPHA,
    DEFAULT_THRESHOLD,
    IMPROVEMENT,
    REGRESSION,
    UNCHANGED,
    UNKNOWN,
    classify,
    geometric_mean,
    mann_whitney_p,
    median,
    relative_change,
)

HEAD = "head"
BASE = "base"

# the label of the shipped runtime in the breakdown of run_pass_benchmark.py
SHIPPED_RUNTIME_LABEL = "all bodies (shipped runtime)"

# callback times below a nanosecond change by large percentages from noise alone: a change of a callback time is
# only flagged when it also exceeds this many nanoseconds
CALLBACK_NOISE_FLOOR_NS = 0.25


@dataclass
class Manifest:
    """Which versions a part of the results covers."""

    head_label: str
    base_label: str = ""
    base_available: bool = False
    # why the version to compare with is missing, shown in the report
    base_note: str = ""
    rounds: int = 0
    settings: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> "Manifest":
        data = json.loads(path.read_text())
        return Manifest(
            head_label=str(data.get("head_label", "")),
            base_label=str(data.get("base_label", "")),
            base_available=bool(data.get("base_available", False)),
            base_note=str(data.get("base_note", "")),
            rounds=int(data.get("rounds", 0)),
            settings=dict(data.get("settings", {})),
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "head_label": self.head_label,
            "base_label": self.base_label,
            "base_available": self.base_available,
            "base_note": self.base_note,
            "rounds": self.rounds,
            "settings": self.settings,
        }


@dataclass
class Metric:
    """One quantity in both versions. Lower is better for every quantity compared here."""

    base: float
    head: float
    base_samples: List[float]
    head_samples: List[float]
    # None for quantities measured once per version (sizes, single runs, aggregates)
    p_value: Optional[float]
    change: float
    verdict: str

    @property
    def head_min(self) -> float:
        return min(self.head_samples) if self.head_samples else self.head

    @property
    def head_max(self) -> float:
        return max(self.head_samples) if self.head_samples else self.head

    @property
    def base_min(self) -> float:
        return min(self.base_samples) if self.base_samples else self.base

    @property
    def base_max(self) -> float:
        return max(self.base_samples) if self.base_samples else self.base

    def to_json(self) -> Dict[str, Any]:
        return {
            "base": _json_number(self.base),
            "head": _json_number(self.head),
            "base_samples": [_json_number(value) for value in self.base_samples],
            "head_samples": [_json_number(value) for value in self.head_samples],
            "p_value": None if self.p_value is None else _json_number(self.p_value),
            "change": _json_number(self.change),
            "verdict": self.verdict,
        }


def _json_number(value: float) -> Optional[float]:
    return value if math.isfinite(value) else None


def compare_samples(
    base_samples: List[float],
    head_samples: List[float],
    threshold: float = DEFAULT_THRESHOLD,
    alpha: float = DEFAULT_ALPHA,
    repeated: bool = True,
    noise_floor: float = 0.0,
) -> Metric:
    """Compare repeated measurements (``repeated``) or single values of both versions.

    A change smaller than ``noise_floor`` in absolute terms is never flagged, however large it is relatively.
    """
    base = median(base_samples) if base_samples else math.nan
    head = median(head_samples) if head_samples else math.nan
    change = relative_change(base, head)
    p_value: Optional[float] = None
    if repeated and base_samples and head_samples:
        p_value = mann_whitney_p(base_samples, head_samples)
    verdict = classify(change, p_value, threshold, alpha) if base_samples else UNKNOWN
    if verdict in (REGRESSION, IMPROVEMENT) and abs(head - base) < noise_floor:
        verdict = UNCHANGED
    return Metric(base, head, list(base_samples), list(head_samples), p_value, change, verdict)


# ---------------------------------------------------------------------------------------------
# pass overhead
# ---------------------------------------------------------------------------------------------


@dataclass
class ProgramComparison:
    name: str
    description: str
    run_factor: Metric
    compile_factor: Metric
    size_factor: Metric


@dataclass
class PassOverheadComparison:
    manifest: Manifest
    compiler: str
    programs: List[ProgramComparison]
    geomean_run_factor: Metric
    geomean_compile_factor: Metric
    geomean_size_factor: Metric


def _load_rounds(directory: Path) -> List[Dict[str, Any]]:
    if not directory.is_dir():
        return []
    paths = sorted(directory.glob("round_*.json"), key=lambda path: int(path.stem.split("_")[-1]))
    return [json.loads(path.read_text()) for path in paths]


def _factor_samples(rounds: List[Dict[str, Any]], program: str, kind: str) -> List[float]:
    """The instrumented times of a program over all rounds, each divided by the baseline median of its round.

    Dividing by the baseline of the same round keeps a change of the machine's speed between rounds out of the
    factors: both configurations of a round are measured back to back.
    """
    samples: List[float] = []
    for report in rounds:
        for entry in report.get("programs", []):
            if entry.get("name") != program:
                continue
            baseline = median([float(value) for value in entry["baseline"][f"{kind}_seconds"]])
            if not math.isfinite(baseline) or baseline <= 0.0:
                continue
            samples += [float(value) / baseline for value in entry["instrumented"][f"{kind}_seconds"]]
    return samples


def _size_factor(rounds: List[Dict[str, Any]], program: str) -> List[float]:
    for report in rounds:
        for entry in report.get("programs", []):
            if entry.get("name") == program:
                factor = entry.get("factors", {}).get("binary_size")
                return [float(factor)] if factor is not None else []
    return []


def short_compiler_version(version: str) -> str:
    """``clang 21.1.8`` instead of the distribution's full version line."""
    match = re.search(r"clang version (\d+(?:\.\d+)*)", version)
    return f"clang {match.group(1)}" if match else version


def load_pass_overhead(directory: Path, threshold: float = DEFAULT_THRESHOLD) -> Optional[PassOverheadComparison]:
    if not (directory / "manifest.json").is_file():
        return None
    manifest = Manifest.load(directory / "manifest.json")
    head_rounds = _load_rounds(directory / HEAD)
    if not head_rounds:
        return None
    base_rounds = _load_rounds(directory / BASE) if manifest.base_available else []

    programs: List[ProgramComparison] = []
    for entry in head_rounds[0].get("programs", []):
        name = str(entry["name"])
        programs.append(
            ProgramComparison(
                name=name,
                description=str(entry.get("description", "")),
                run_factor=compare_samples(
                    _factor_samples(base_rounds, name, "run"), _factor_samples(head_rounds, name, "run"), threshold
                ),
                compile_factor=compare_samples(
                    _factor_samples(base_rounds, name, "compile"),
                    _factor_samples(head_rounds, name, "compile"),
                    threshold,
                ),
                size_factor=compare_samples(
                    _size_factor(base_rounds, name), _size_factor(head_rounds, name), threshold, repeated=False
                ),
            )
        )

    def geomean(attribute: str) -> Metric:
        metrics = [getattr(program, attribute) for program in programs]
        base_values = [metric.base for metric in metrics if math.isfinite(metric.base)]
        head_values = [metric.head for metric in metrics]
        base = [geometric_mean(base_values)] if base_values else []
        return compare_samples(base, [geometric_mean(head_values)], threshold, repeated=False)

    metadata = head_rounds[0].get("metadata", {})
    return PassOverheadComparison(
        manifest=manifest,
        compiler=short_compiler_version(str(metadata.get("compiler_version", ""))),
        programs=programs,
        geomean_run_factor=geomean("run_factor"),
        geomean_compile_factor=geomean("compile_factor"),
        geomean_size_factor=geomean("size_factor"),
    )


# ---------------------------------------------------------------------------------------------
# callbacks
# ---------------------------------------------------------------------------------------------


@dataclass
class CallbackComparison:
    name: str
    calls_per_iteration: int
    # what a call costs with its body (what an instrumented program pays), the call alone, and the difference
    total: Metric
    call_only: Metric
    body: Metric


@dataclass
class CallbacksComparison:
    manifest: Manifest
    callbacks: List[CallbackComparison]


def _callback_samples(rounds: List[Dict[str, Any]], callback: str) -> Dict[str, List[float]]:
    """The per repetition times of one callback over all rounds: full, call only, and body.

    The body of a repetition is its full time minus the median call-only time of the same round. Reports written
    before the samples were recorded only hold the medians, which then serve as the single sample of a round.
    """
    samples: Dict[str, List[float]] = {"full": [], "call_only": [], "body": []}
    for report in rounds:
        for entry in report.get("callbacks", []):
            if entry.get("name") != callback:
                continue
            full = [float(value) for value in entry.get("full_samples_ns") or [entry["full_ns"]]]
            call_only = [float(value) for value in entry.get("call_only_samples_ns") or [entry["call_only_ns"]]]
            call_only_median = median(call_only)
            samples["full"] += full
            samples["call_only"] += call_only
            samples["body"] += [value - call_only_median for value in full]
    return samples


def load_callbacks(directory: Path, threshold: float = DEFAULT_THRESHOLD) -> Optional[CallbacksComparison]:
    if not (directory / "manifest.json").is_file():
        return None
    manifest = Manifest.load(directory / "manifest.json")
    head_rounds = _load_rounds(directory / HEAD)
    if not head_rounds:
        return None
    base_rounds = _load_rounds(directory / BASE) if manifest.base_available else []

    callbacks: List[CallbackComparison] = []
    for entry in head_rounds[0].get("callbacks", []):
        name = str(entry["name"])
        head = _callback_samples(head_rounds, name)
        base = _callback_samples(base_rounds, name)
        callbacks.append(
            CallbackComparison(
                name=name,
                calls_per_iteration=int(entry.get("calls_per_iteration", 1)),
                total=compare_samples(base["full"], head["full"], threshold, noise_floor=CALLBACK_NOISE_FLOOR_NS),
                call_only=compare_samples(
                    base["call_only"], head["call_only"], threshold, noise_floor=CALLBACK_NOISE_FLOOR_NS
                ),
                body=compare_samples(base["body"], head["body"], threshold, noise_floor=CALLBACK_NOISE_FLOOR_NS),
            )
        )
    return CallbacksComparison(manifest=manifest, callbacks=callbacks)


# ---------------------------------------------------------------------------------------------
# callback breakdown
# ---------------------------------------------------------------------------------------------


@dataclass
class BreakdownComparison:
    manifest: Manifest
    programs: List[str]
    # the configurations in the order run_pass_benchmark.py reports them, the shipped runtime last
    configurations: List[str]
    # configuration -> program -> run time factor against the uninstrumented baseline (single runs)
    factors: Dict[str, Dict[str, Metric]]
    geomeans: Dict[str, Metric]


def _breakdown_factors(report: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    factors: Dict[str, Dict[str, float]] = {}
    for entry in report.get("programs", []):
        program = str(entry["name"])
        for configuration, values in entry.get("callback_breakdown", {}).items():
            factors.setdefault(configuration, {})[program] = float(values.get("run_factor", math.nan))
        factors.setdefault(SHIPPED_RUNTIME_LABEL, {})[program] = float(entry.get("factors", {}).get("run", math.nan))
    return factors


def load_breakdown(directory: Path, threshold: float = DEFAULT_THRESHOLD) -> Optional[BreakdownComparison]:
    if not (directory / "manifest.json").is_file() or not (directory / f"{HEAD}.json").is_file():
        return None
    manifest = Manifest.load(directory / "manifest.json")
    head_report = json.loads((directory / f"{HEAD}.json").read_text())
    base_path = directory / f"{BASE}.json"
    base_report = json.loads(base_path.read_text()) if manifest.base_available and base_path.is_file() else {}

    head = _breakdown_factors(head_report)
    base = _breakdown_factors(base_report)
    programs = [str(entry["name"]) for entry in head_report.get("programs", [])]
    configurations = [name for name in head if name != SHIPPED_RUNTIME_LABEL] + [SHIPPED_RUNTIME_LABEL]

    factors: Dict[str, Dict[str, Metric]] = {}
    geomeans: Dict[str, Metric] = {}
    for configuration in configurations:
        factors[configuration] = {}
        for program in programs:
            base_value = base.get(configuration, {}).get(program)
            factors[configuration][program] = compare_samples(
                [base_value] if base_value is not None else [],
                [head[configuration].get(program, math.nan)],
                threshold,
                repeated=False,
            )
        base_values = [metric.base for metric in factors[configuration].values() if math.isfinite(metric.base)]
        geomeans[configuration] = compare_samples(
            [geometric_mean(base_values)] if base_values else [],
            [geometric_mean([metric.head for metric in factors[configuration].values()])],
            threshold,
            repeated=False,
        )
    return BreakdownComparison(manifest, programs, configurations, factors, geomeans)


@dataclass
class Comparison:
    """Everything the report shows."""

    pass_overhead: Optional[PassOverheadComparison]
    callbacks: Optional[CallbacksComparison]
    breakdown: Optional[BreakdownComparison]
    threshold: float

    @property
    def regressions(self) -> int:
        return self._count("regression")

    @property
    def improvements(self) -> int:
        return self._count("improvement")

    def _count(self, verdict: str) -> int:
        """Flagged rows of the measured quantities; the breakdown is only indicative and not counted."""
        count = 0
        if self.pass_overhead is not None:
            for program in self.pass_overhead.programs:
                count += sum(
                    metric.verdict == verdict
                    for metric in (program.run_factor, program.compile_factor, program.size_factor)
                )
        if self.callbacks is not None:
            count += sum(callback.total.verdict == verdict for callback in self.callbacks.callbacks)
        return count


def load(results: Path, threshold: float = DEFAULT_THRESHOLD) -> Comparison:
    return Comparison(
        pass_overhead=load_pass_overhead(results / "pass_overhead", threshold),
        callbacks=load_callbacks(results / "callbacks", threshold),
        breakdown=load_breakdown(results / "breakdown", threshold),
        threshold=threshold,
    )
