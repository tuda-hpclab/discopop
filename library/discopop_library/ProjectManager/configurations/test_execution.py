# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for what ``execution_results.json`` records about suggestion application."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, cast

from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import (
    NOT_EXECUTED_RETURN_CODE,
    _store_execution_result,
    record_skipped_execution,
)


def _arguments(project_dir: str, label_prefix: str = "") -> ProjectManagerArguments:
    """A stand-in exposing only what the results writer reads."""
    return cast(
        ProjectManagerArguments,
        SimpleNamespace(project_dir=project_dir, label_prefix=label_prefix, apply_suggestions=None),
    )


def _entries(project_dir: str) -> Any:
    with open(os.path.join(project_dir, "execution_results.json"), "r") as f:
        results = json.load(f)
    return results["tiny"]["execute.sh"]["par_settings.json"]


def _measurement(time: float = 1.0, thread_count: int = 8) -> Dict[str, Any]:
    return {
        "code": 0,
        "stdout": "",
        "stderr": "",
        "timeout_expired": False,
        "time": time,
        "thread_count": thread_count,
        "executed": True,
    }


def test_successful_run_records_no_failed_suggestions(tmp_path: Path) -> None:
    arguments = _arguments(str(tmp_path))
    application = PatchApplicationResult(requested=["3"], applied=["3"])
    _store_execution_result(arguments, "tiny", "execute.sh", "par_settings.json", [3], application, _measurement())
    entry = _entries(str(tmp_path))[0]
    assert entry["applied_suggestions"] == [3]
    assert entry["requested_suggestions"] == [3]
    assert entry["failed_suggestions"] == []
    assert entry["suggestion_application_failed"] is False


def test_skipped_run_is_recorded_as_a_placeholder(tmp_path: Path) -> None:
    project_copy = tmp_path / "copy"
    os.makedirs(project_copy / ".discopop")
    arguments = _arguments(str(tmp_path))
    application = PatchApplicationResult(requested=["27"], failed=["27"])

    record_skipped_execution(
        arguments,
        str(project_copy),
        "tiny",
        "par_settings.json",
        "execute.sh",
        8,
        application,
    )

    entry = _entries(str(tmp_path))[0]
    assert entry["suggestion_application_failed"] is True
    assert entry["requested_suggestions"] == [27]
    assert entry["failed_suggestions"] == [27]
    # a placeholder carries no measurement: not a successful run at time 0
    assert entry["executed"] is False
    assert entry["code"] == NOT_EXECUTED_RETURN_CODE
    assert entry["time"] == 0.0
    assert "27" in entry["stderr"]


def test_a_skipped_run_does_not_overwrite_the_unsuggested_baseline(tmp_path: Path) -> None:
    """Both entries have an empty applied set; the duplicate key must still separate them."""
    project_copy = tmp_path / "copy"
    os.makedirs(project_copy / ".discopop")
    arguments = _arguments(str(tmp_path))

    # the genuine no-suggestion baseline run
    _store_execution_result(arguments, "tiny", "execute.sh", "par_settings.json", [], None, _measurement(time=2.0))
    # a run whose suggestions could not be applied -- also nothing applied
    record_skipped_execution(
        arguments,
        str(project_copy),
        "tiny",
        "par_settings.json",
        "execute.sh",
        8,
        PatchApplicationResult(requested=["27"], failed=["27"]),
    )

    entries = _entries(str(tmp_path))
    assert len(entries) == 2
    baseline = [e for e in entries if not e["suggestion_application_failed"]]
    skipped = [e for e in entries if e["suggestion_application_failed"]]
    assert len(baseline) == 1 and baseline[0]["time"] == 2.0
    assert len(skipped) == 1 and skipped[0]["requested_suggestions"] == [27]


def test_an_equivalent_rerun_still_replaces_the_previous_entry(tmp_path: Path) -> None:
    arguments = _arguments(str(tmp_path))
    application = PatchApplicationResult(requested=["3"], applied=["3"])
    _store_execution_result(
        arguments, "tiny", "execute.sh", "par_settings.json", [3], application, _measurement(time=5.0)
    )
    _store_execution_result(
        arguments, "tiny", "execute.sh", "par_settings.json", [3], application, _measurement(time=4.0)
    )
    entries = _entries(str(tmp_path))
    assert len(entries) == 1 and entries[0]["time"] == 4.0
