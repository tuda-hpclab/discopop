# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for how the generated reports read a skipped run."""

from typing import Any, Dict

from discopop_library.ProjectManager.reports import entries


def _measured(time: float = 4.0, thread_count: int = 8) -> Dict[str, Any]:
    return {
        "applied_suggestions": [3],
        "requested_suggestions": [3],
        "failed_suggestions": [],
        "suggestion_application_failed": False,
        "executed": True,
        "code": 0,
        "time": time,
        "thread_count": thread_count,
    }


def _skipped(thread_count: int = 8) -> Dict[str, Any]:
    return {
        "applied_suggestions": [],
        "requested_suggestions": [27],
        "failed_suggestions": [27],
        "suggestion_application_failed": True,
        "executed": False,
        "code": -1,
        "time": 0.0,
        "thread_count": thread_count,
    }


def test_was_executed() -> None:
    assert entries.was_executed(_measured())
    assert not entries.was_executed(_skipped())
    # entries written before these fields existed are measurements
    assert entries.was_executed({"code": 0, "time": 1.0})


def test_skipped_run_has_no_speedup_instead_of_dividing_by_zero() -> None:
    assert entries.speedup_of(10.0, _skipped()) is None
    assert entries.efficiency_of(10.0, _skipped()) is None
    assert entries.format_metric(entries.speedup_of(10.0, _skipped())) == "-"
    assert entries.runtime_text(_skipped()) == "-"


def test_measured_run_reports_its_metrics() -> None:
    speedup = entries.speedup_of(10.0, _measured())
    assert speedup == 2.5
    efficiency = entries.efficiency_of(10.0, _measured())
    assert efficiency is not None and abs(efficiency - 2.5 / 8) < 1e-9
    assert entries.runtime_text(_measured()) == "4.0"


def test_missing_baseline_yields_no_metric() -> None:
    assert entries.speedup_of(-1.0, _measured()) is None


def test_suggestion_cell_names_the_unapplied_suggestions() -> None:
    text = entries.applied_suggestions_text(_skipped())
    assert "27" in text and entries.NOT_APPLIED_TEXT in text
    assert entries.applied_suggestions_text(_measured()) == "[3]"
