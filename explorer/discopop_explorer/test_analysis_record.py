# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The explorer's pattern default is the shared definition, and a finished detection is recorded."""

import json
from pathlib import Path
from typing import Any, List

from discopop_explorer.__main__ import parse_args
from discopop_explorer.discopop_explorer import record_pattern_detection
from discopop_library.AnalysisRecord import DEFAULT_PATTERNS, RECORD_FILENAME
from discopop_library.result_classes.DetectionResult import DetectionResult


def _dot_discopop(tmp_path: Path) -> Path:
    dot = tmp_path / ".discopop"
    (dot / "profiler").mkdir(parents=True)
    for name in ("Data.xml", "dynamic_dependencies.txt", "loop_counter_output.txt", "reduction.txt"):
        (dot / "profiler" / name).write_text("")
    (dot / "FileMapping.txt").write_text("")
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    return dot


def _parse(dot: Path, extra: List[str]) -> Any:
    return parse_args(["--path", str(dot)] + extra)


def test_default_patterns_are_the_shared_definition(tmp_path: Path) -> None:
    arguments = _parse(_dot_discopop(tmp_path), [])
    assert arguments.enable_patterns == ",".join(DEFAULT_PATTERNS)


def test_recorded_detection_has_patterns_and_no_options_by_default(tmp_path: Path) -> None:
    dot = _dot_discopop(tmp_path)
    arguments = _parse(dot, [])
    (dot / "explorer").mkdir()
    (dot / "explorer" / "patterns.json").write_text("{}")
    result = DetectionResult(None)  # type: ignore[arg-type]
    result.enabled_patterns = ["task", "doall", "reduction"]

    record_pattern_detection(arguments, result)

    with open(dot / RECORD_FILENAME) as f:
        params = json.load(f)["steps"]["pattern_detection"]["params"]
    assert params == {"enabled_patterns": ["doall", "reduction", "task"], "options": {}}


def test_result_changing_options_are_recorded_when_not_default(tmp_path: Path) -> None:
    dot = _dot_discopop(tmp_path)
    arguments = _parse(dot, ["--hotspot-types", "yes", "--ignore-dependency-states"])
    (dot / "explorer").mkdir()
    (dot / "explorer" / "patterns.json").write_text("{}")
    result = DetectionResult(None)  # type: ignore[arg-type]
    result.enabled_patterns = ["doall"]

    record_pattern_detection(arguments, result)

    with open(dot / RECORD_FILENAME) as f:
        params = json.load(f)["steps"]["pattern_detection"]["params"]
    assert params["options"] == {"hotspot_types": ["yes"], "ignore_dependency_states": True}


def test_nothing_is_recorded_without_a_patterns_file(tmp_path: Path) -> None:
    dot = _dot_discopop(tmp_path)
    arguments = _parse(dot, [])
    result = DetectionResult(None)  # type: ignore[arg-type]
    record_pattern_detection(arguments, result)
    assert not (dot / RECORD_FILENAME).exists()
