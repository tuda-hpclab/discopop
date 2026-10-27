# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

from discopop_library.ProjectManager.services.autotuner_results import (
    autotuner_results_exist,
    read_autotuner_applied_suggestions,
)


def _write(root: Path, content: str) -> None:
    (root / "auto_tuner").mkdir()
    (root / "auto_tuner" / "results.json").write_text(content)


def test_missing_results(tmp_path: Path) -> None:
    assert not autotuner_results_exist(str(tmp_path))
    assert read_autotuner_applied_suggestions(str(tmp_path), "tiny") == []


def test_ids_are_returned_as_strings_in_the_stored_order(tmp_path: Path) -> None:
    _write(tmp_path, json.dumps({"tiny": {"applied_suggestions": [10, 2]}, "other": {"applied_suggestions": [1]}}))
    assert autotuner_results_exist(str(tmp_path))
    assert read_autotuner_applied_suggestions(str(tmp_path), "tiny") == ["10", "2"]
    assert read_autotuner_applied_suggestions(str(tmp_path), "unknown") == []


def test_unreadable_results_count_as_empty(tmp_path: Path) -> None:
    _write(tmp_path, "{not json")
    assert autotuner_results_exist(str(tmp_path))
    assert read_autotuner_applied_suggestions(str(tmp_path), "tiny") == []
