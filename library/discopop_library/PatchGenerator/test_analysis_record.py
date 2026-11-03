# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A finished patch generation is recorded."""

import json
import os
from pathlib import Path

import pytest

from discopop_library.AnalysisRecord import RECORD_FILENAME, record_step
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.patch_generator import run


def _arguments(tmp_path: Path, **overrides: bool) -> PatchGeneratorArguments:
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    return PatchGeneratorArguments(
        log_level="WARNING",
        write_log=False,
        verbose=False,
        discopop_build_path=str(tmp_path),
        CC=str(tmp_path / "main.cpp"),
        CXX=str(tmp_path / "main.cpp"),
        add_from_json="None",
        only_optimizer_output_patterns=overrides.get("only_optimizer_output_patterns", False),
        only_maximum_id_pattern=False,
    )


def _project(tmp_path: Path) -> Path:
    dot = tmp_path / ".discopop"
    (dot / "explorer").mkdir(parents=True)
    (dot / "explorer" / "patterns.json").write_text(json.dumps({"patterns": {}}))
    (dot / "profiler").mkdir()
    (dot / "profiler" / "Data.xml").write_text("<x/>")
    (dot / "profiler" / "dynamic_dependencies.txt").write_text("x")
    (dot / "FileMapping.txt").write_text("")
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    record_step(str(dot), "dependence_profiling", {"config": "c", "compile_script": "c.sh"})
    record_step(str(dot), "pattern_detection", {"enabled_patterns": ["doall"], "options": {}})
    return dot


def test_patch_generation_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dot = _project(tmp_path)
    monkeypatch.chdir(dot)
    run(_arguments(tmp_path))
    with open(dot / RECORD_FILENAME) as f:
        steps = json.load(f)["steps"]
    assert steps["patch_generation"]["inputs"] == {"pattern_detection": steps["pattern_detection"]["run_id"]}
    assert os.path.isdir(dot / "patch_generator")


def test_a_restricted_patch_set_is_not_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dot = _project(tmp_path)
    monkeypatch.chdir(dot)
    run(_arguments(tmp_path, only_optimizer_output_patterns=True))
    with open(dot / RECORD_FILENAME) as f:
        assert "patch_generation" not in json.load(f)["steps"]
