# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

from discopop_library.ProjectManager.services.explorer_state import (
    explorer_prerequisites_met,
    missing_explorer_files,
    pattern_detection_executed,
    patterns_found,
)


def test_profiling_files(tmp_path: Path) -> None:
    assert not explorer_prerequisites_met(str(tmp_path))
    assert len(missing_explorer_files(str(tmp_path))) == 5
    (tmp_path / "profiler").mkdir()
    (tmp_path / "profiler" / "Data.xml").write_text("")
    (tmp_path / "FileMapping.txt").write_text("")
    assert explorer_prerequisites_met(str(tmp_path))
    assert [Path(path).name for path in missing_explorer_files(str(tmp_path))] == [
        "dynamic_dependencies.txt",
        "loop_counter_output.txt",
        "reduction.txt",
    ]


def test_patterns(tmp_path: Path) -> None:
    assert not pattern_detection_executed(str(tmp_path)) and not patterns_found(str(tmp_path))
    (tmp_path / "explorer").mkdir()
    assert pattern_detection_executed(str(tmp_path)) and not patterns_found(str(tmp_path))
    (tmp_path / "explorer" / "patterns.json").write_text(json.dumps({"patterns": {"do_all": [], "reduction": []}}))
    assert not patterns_found(str(tmp_path))
    (tmp_path / "explorer" / "patterns.json").write_text(json.dumps({"patterns": {"do_all": [{"id": 1}]}}))
    assert patterns_found(str(tmp_path))
    (tmp_path / "explorer" / "patterns.json").write_text("{")
    assert not patterns_found(str(tmp_path))
