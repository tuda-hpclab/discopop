# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from discopop_library.EmpiricalAutotuning.output.progress import (
    PROGRESS_PREFIX,
    DebugStatEntry,
    ProgressList,
    ProgressReporter,
    count_outcomes,
    get_active_reporter,
    set_active_reporter,
)


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    with open(path, "r") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_reporter_emits_stdout_and_jsonl(tmp_path: Path, capsys: "pytest.CaptureFixture[str]") -> None:
    jsonl = os.path.join(tmp_path, "progress.jsonl")
    reporter = ProgressReporter("tiny", jsonl)
    reporter.baseline(10.0, True, 8)
    reporter.measurement([3, 7], 4.0, 0, True, True)
    reporter.close()

    # stdout: one tagged line per event, parseable as JSON after the prefix
    out_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(PROGRESS_PREFIX)]
    assert len(out_lines) == 2
    parsed = [json.loads(ln[len(PROGRESS_PREFIX) :]) for ln in out_lines]
    assert parsed[0]["event"] == "baseline"
    assert parsed[0]["config"] == "tiny"

    # jsonl mirrors stdout
    events = _read_jsonl(jsonl)
    assert [e["event"] for e in events] == ["baseline", "measurement"]


def test_measurement_speedup_relative_to_baseline(tmp_path: Path) -> None:
    reporter = ProgressReporter("tiny", os.path.join(tmp_path, "p.jsonl"))
    reporter.baseline(10.0, True, 8)
    reporter.measurement([3], 4.0, 0, True, True)
    reporter.close()
    events = _read_jsonl(os.path.join(tmp_path, "p.jsonl"))
    measurement = events[1]
    assert measurement["speedup"] == 2.5  # 10.0 / 4.0
    assert measurement["index"] == 1
    assert measurement["suggestions"] == [3]


def test_measurement_speedup_none_before_baseline(tmp_path: Path) -> None:
    reporter = ProgressReporter("tiny", os.path.join(tmp_path, "p.jsonl"))
    reporter.measurement([3], 4.0, 0, True, True)
    reporter.close()
    events = _read_jsonl(os.path.join(tmp_path, "p.jsonl"))
    assert events[0]["speedup"] is None


def test_progress_list_emits_on_append(tmp_path: Path, capsys: "pytest.CaptureFixture[str]") -> None:
    reporter = ProgressReporter("tiny", os.path.join(tmp_path, "p.jsonl"))
    reporter.baseline(10.0, True, 8)
    set_active_reporter(reporter)
    try:
        stats = ProgressList()
        stats.append(([3, 7], 5.0, 0, True, True, "/tmp/x", []))
        assert len(stats) == 1  # behaves like a list
    finally:
        set_active_reporter(None)
        reporter.close()

    events = _read_jsonl(os.path.join(tmp_path, "p.jsonl"))
    assert events[-1]["event"] == "measurement"
    assert events[-1]["suggestions"] == [3, 7]
    assert events[-1]["speedup"] == 2.0  # 10.0 / 5.0


def test_progress_list_is_noop_without_active_reporter() -> None:
    set_active_reporter(None)
    assert get_active_reporter() is None
    stats = ProgressList()
    stats.append(([1], 1.0, 0, True, True, "/tmp/x", []))  # must not raise
    assert len(stats) == 1


def test_count_outcomes() -> None:
    debug_stats: List[DebugStatEntry] = [
        ([], 10.0, 0, True, True, "p0", []),  # valid
        ([1], 5.0, 0, True, True, "p1", []),  # valid
        ([2], 6.0, 0, False, True, "p2", []),  # invalid (result check failed)
        ([3], 7.0, 0, True, False, "p3", []),  # invalid (tsan failed)
        ([4], 1.0, 1, False, False, "p4", []),  # failed (non-zero return code)
        ([5], 0.0, 0, False, False, "p5", [5]),  # not applied (patch did not apply)
    ]
    assert count_outcomes(debug_stats) == (2, 2, 1, 1)


def test_generation_event_carries_the_measured_average(tmp_path: Path) -> None:
    jsonl = os.path.join(tmp_path, "progress.jsonl")
    reporter = ProgressReporter("tiny", jsonl)
    reporter.generation(2, 3.0, 2.0, 2.7, 17, generation_avg_fitness=1.25)
    reporter.close()

    event = _read_jsonl(jsonl)[0]
    assert event["event"] == "generation"
    assert event["avg_fitness"] == 2.0
    assert event["generation_avg_fitness"] == 1.25


def test_generation_event_omits_the_measured_average_when_unknown(tmp_path: Path) -> None:
    jsonl = os.path.join(tmp_path, "progress.jsonl")
    reporter = ProgressReporter("tiny", jsonl)
    reporter.generation(0, 1.0, 1.0, 1.0, 3)
    reporter.close()

    assert "generation_avg_fitness" not in _read_jsonl(jsonl)[0]
