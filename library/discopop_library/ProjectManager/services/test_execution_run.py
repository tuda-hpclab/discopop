# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import dataclasses
import json
from pathlib import Path

import pytest

from discopop_library.ProjectManager.services.execution_run import (
    ExecutionRequest,
    describe_execution_time,
    execution_time_summary,
    suggestion_ids_to_apply,
)


def test_suggestion_ids_to_apply(tmp_path: Path) -> None:
    results = tmp_path / "auto_tuner" / "results.json"
    results.parent.mkdir()
    results.write_text(json.dumps({"tiny": {"applied_suggestions": [3, 1]}}))
    dot_dp = str(tmp_path)
    assert suggestion_ids_to_apply("none", ["5"], dot_dp, "tiny") == ()
    assert suggestion_ids_to_apply("manual", ["5", "6"], dot_dp, "tiny") == ("5", "6")
    assert suggestion_ids_to_apply("autotuner", ["5"], dot_dp, "tiny") == ("3", "1")
    assert suggestion_ids_to_apply("autotuner", [], dot_dp, "other") == ()


def test_execution_time_summary() -> None:
    assert execution_time_summary(None, False) == "wall clock of execute.sh"
    assert execution_time_summary(None, True) == "from the console output (see Editor -> execute.sh)"
    assert execution_time_summary("", True) == "wall clock of execute.sh (forced by --execution-time-regex)"
    assert execution_time_summary("t=(.*)", False) == "from the console output (forced by --execution-time-regex)"


def test_describe_execution_time() -> None:
    assert describe_execution_time(1.5, "", "", None) == "1.50s"
    assert describe_execution_time(1.5, "time: 1.2", "", r"time: ([0-9.]+)") == "1.50s reported by the program"
    assert "wall clock" in describe_execution_time(1.5, "nothing", "", r"time: ([0-9.]+)")


def test_the_request_is_immutable() -> None:
    request = ExecutionRequest("c", ("seq",), False, False, 1, "", 0, 0, 0, 1, "INFO", ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.thread_count = 2  # type: ignore[misc]
