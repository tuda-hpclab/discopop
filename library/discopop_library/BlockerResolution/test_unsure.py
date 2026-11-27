# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Reading explorer/unsure_suggestions.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from discopop_library.BlockerResolution.unsure import Location, load_unsure_suggestions


def _load_end(tmp_path: Path, region: Optional[Dict[str, Any]]) -> Location:
    entry: Dict[str, Any] = {"pattern_id": 2, "start_line": "1:17", "end_line": "1:17", "blockers": []}
    if region is not None:
        entry["region"] = region
    (tmp_path / "explorer").mkdir()
    (tmp_path / "explorer" / "unsure_suggestions.json").write_text(
        json.dumps({"format_version": 1, "suggestions": [entry]})
    )
    [suggestion] = load_unsure_suggestions(str(tmp_path))
    assert suggestion.start == Location(1, 17)
    return suggestion.end


def test_the_loop_ends_where_its_region_ends(tmp_path: Path) -> None:
    region = {"file_id": 1, "start_line": 17, "end_line": 19, "kind": "loop"}
    assert _load_end(tmp_path, region) == Location(1, 19)


@pytest.mark.parametrize(
    "region",
    [
        None,  # written before regions were recorded
        {"file_id": 2, "start_line": 17, "end_line": 19, "kind": "loop"},  # another file
        {"file_id": 1, "start_line": 3, "end_line": 9, "kind": "loop"},  # ends before the loop starts
        {"file_id": 1, "end_line": "x"},
    ],
)
def test_without_a_usable_region_the_end_line_counts(tmp_path: Path, region: Optional[Dict[str, Any]]) -> None:
    assert _load_end(tmp_path, region) == Location(1, 17)
