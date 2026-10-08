# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The comparison and the reports, on results shaped like the ones the benchmark drivers write."""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from benchmark_compare.report_html import format_html
from benchmark_compare.report_markdown import BREAKDOWN_LABEL, COMMENT_MARKER, format_report
from benchmark_compare.results import Manifest, load
from benchmark_compare.stats import IMPROVEMENT, REGRESSION, UNCHANGED, UNKNOWN


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _pass_report(run: List[float], size_factor: float = 2.0) -> Dict[str, Any]:
    """A report of run_pass_benchmark.py with one program whose uninstrumented build runs for 1 s."""
    return {
        "metadata": {"compiler_version": "clang version 21.1.0"},
        "programs": [
            {
                "name": "nested_loops",
                "description": "loops in loops",
                "baseline": {"compile_seconds": [1.0, 1.0, 1.0], "run_seconds": [1.0, 1.0, 1.0]},
                "instrumented": {"compile_seconds": [2.0, 2.0, 2.0], "run_seconds": run},
                "factors": {"binary_size": size_factor, "run": sum(run) / len(run)},
            }
        ],
    }


def _callback_report(full: List[float], call_only: List[float], with_samples: bool = True) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": "__dp_read",
        "calls_per_iteration": 1,
        "full_ns": sorted(full)[len(full) // 2],
        "call_only_ns": sorted(call_only)[len(call_only) // 2],
    }
    if with_samples:
        entry["full_samples_ns"] = full
        entry["call_only_samples_ns"] = call_only
    return {"callbacks": [entry]}


def _breakdown_report(read_factor: float, total: float) -> Dict[str, Any]:
    return {
        "programs": [
            {
                "name": "nested_loops",
                "factors": {"run": total},
                "callback_breakdown": {
                    "calls only": {"run_factor": 3.0},
                    "only __dp_read": {"run_factor": read_factor},
                },
            }
        ]
    }


def _manifest(base_available: bool, rounds: int, note: str = "") -> Dict[str, Any]:
    return Manifest(
        head_label="abc1234",
        base_label="def5678" if base_available else "",
        base_available=base_available,
        base_note=note,
        rounds=rounds,
        settings={"repetitions": 3},
    ).to_json()


def _results(
    tmp_path: Path,
    base_available: bool = True,
    head_run: Optional[List[float]] = None,
    callback_samples: bool = True,
) -> Path:
    results = tmp_path / "results"
    head_run = head_run or [12.0, 12.1, 11.9]
    _write(results / "pass_overhead" / "manifest.json", _manifest(base_available, 2, "no version to compare with"))
    _write(results / "callbacks" / "manifest.json", _manifest(base_available, 2, "no version to compare with"))
    _write(results / "breakdown" / "manifest.json", _manifest(base_available, 1, "no version to compare with"))
    for round_number in (1, 2):
        _write(results / "pass_overhead" / "head" / f"round_{round_number}.json", _pass_report(head_run))
        _write(
            results / "callbacks" / "head" / f"round_{round_number}.json",
            _callback_report([20.0, 20.5, 19.5], [2.0, 2.1, 1.9], callback_samples),
        )
        if base_available:
            _write(results / "pass_overhead" / "base" / f"round_{round_number}.json", _pass_report([10.0, 10.1, 9.9]))
            _write(
                results / "callbacks" / "base" / f"round_{round_number}.json",
                _callback_report([20.1, 20.4, 19.6], [2.0, 2.1, 1.9], callback_samples),
            )
    _write(results / "breakdown" / "head.json", _breakdown_report(5.0, 12.0))
    if base_available:
        _write(results / "breakdown" / "base.json", _breakdown_report(4.0, 10.0))
    return results


def test_a_significant_slowdown_is_a_regression(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path))
    assert comparison.pass_overhead is not None
    program = comparison.pass_overhead.programs[0]
    assert program.run_factor.base == pytest.approx(10.0)
    assert program.run_factor.head == pytest.approx(12.0)
    assert program.run_factor.change == pytest.approx(0.2)
    assert program.run_factor.verdict == REGRESSION
    assert program.compile_factor.verdict == UNCHANGED
    assert program.size_factor.verdict == UNCHANGED
    assert comparison.pass_overhead.geomean_run_factor.verdict == REGRESSION
    assert comparison.regressions == 1
    assert comparison.improvements == 0


def test_a_significant_speedup_is_an_improvement(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path, head_run=[8.0, 8.1, 7.9]))
    assert comparison.pass_overhead is not None
    assert comparison.pass_overhead.programs[0].run_factor.verdict == IMPROVEMENT
    assert comparison.improvements == 1


def test_callbacks_are_split_into_call_and_body(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path))
    assert comparison.callbacks is not None
    callback = comparison.callbacks.callbacks[0]
    assert callback.total.head == pytest.approx(20.0)
    assert callback.call_only.head == pytest.approx(2.0)
    assert callback.body.head == pytest.approx(18.0)
    assert callback.total.verdict == UNCHANGED


def test_tiny_callback_changes_are_not_flagged(tmp_path: Path) -> None:
    results = _results(tmp_path)
    for side, full in (("base", [0.10, 0.11, 0.09]), ("head", [0.20, 0.21, 0.19])):
        for round_number in (1, 2):
            path = results / "callbacks" / side / f"round_{round_number}.json"
            path.write_text(json.dumps(_callback_report(full, [0.05, 0.05, 0.05])))
    comparison = load(results)
    assert comparison.callbacks is not None
    callback = comparison.callbacks.callbacks[0]
    # twice as expensive and significant, but by a tenth of a nanosecond
    assert callback.total.change == pytest.approx(1.0)
    assert callback.total.p_value is not None and callback.total.p_value < 0.05
    assert callback.total.verdict == UNCHANGED


def test_compiler_version_is_shortened(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path))
    assert comparison.pass_overhead is not None
    assert comparison.pass_overhead.compiler == "clang 21.1.0"


def test_reports_without_samples_still_compare(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path, callback_samples=False))
    assert comparison.callbacks is not None
    callback = comparison.callbacks.callbacks[0]
    # one median per round and version
    assert len(callback.total.head_samples) == 2
    assert callback.total.verdict == UNCHANGED


def test_breakdown_compares_the_geometric_means(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path))
    breakdown = comparison.breakdown
    assert breakdown is not None
    assert breakdown.configurations[-1] == "all bodies (shipped runtime)"
    assert breakdown.geomeans["only __dp_read"].change == pytest.approx(0.25)
    # single runs are judged by the threshold alone
    assert breakdown.geomeans["only __dp_read"].p_value is None
    assert breakdown.geomeans["calls only"].verdict == UNCHANGED


def test_markdown_report(tmp_path: Path) -> None:
    report = format_report(load(_results(tmp_path)), run_url="https://example.invalid/run", report_url=None)
    assert report.startswith(COMMENT_MARKER)
    assert "**1 regression ⚠️, 0 improvements ✅**" in report
    assert "| nested_loops | ×10.00 → ×12.00 | +20.0% ⚠️ | 0.002 |" in report
    assert "`def5678` → `abc1234`" in report
    # the breakdown lists the configuration that changed by more than the threshold
    assert "| only __dp_read | ×4.00 → ×5.00 | +25.0% ⚠️ |" in report
    assert "[workflow run](https://example.invalid/run)" in report


def test_reports_without_a_version_to_compare_with(tmp_path: Path) -> None:
    comparison = load(_results(tmp_path, base_available=False))
    assert comparison.pass_overhead is not None
    assert comparison.pass_overhead.programs[0].run_factor.verdict == UNKNOWN
    report = format_report(comparison)
    assert "Nothing to compare with" in report
    assert "Not compared, only this version is shown: no version to compare with" in report
    assert "| nested_loops | ×12.00 | – |" in report
    assert "<svg" in format_html(comparison)


def test_html_report(tmp_path: Path) -> None:
    page = format_html(load(_results(tmp_path)), run_url="https://example.invalid/run")
    assert page.startswith("<!doctype html>")
    assert page.count("<svg") == 2
    assert 'class="heat"' in page
    assert "prefers-color-scheme: dark" in page
    # self-contained: nothing is loaded from elsewhere
    assert "<script" not in page and "<link" not in page


def test_the_breakdown_label_is_pointed_out_when_the_breakdown_is_missing(tmp_path: Path) -> None:
    results = _results(tmp_path)
    assert BREAKDOWN_LABEL not in format_report(load(results))
    shutil.rmtree(results / "breakdown")
    comparison = load(results)
    assert f"add the label `{BREAKDOWN_LABEL}`" in format_report(comparison)
    assert f"<code>{BREAKDOWN_LABEL}</code>" in format_html(comparison)


def test_missing_results_are_left_out(tmp_path: Path) -> None:
    comparison = load(tmp_path / "nothing")
    assert comparison.pass_overhead is None and comparison.callbacks is None and comparison.breakdown is None
    assert "No benchmark results were found" in format_report(comparison)
