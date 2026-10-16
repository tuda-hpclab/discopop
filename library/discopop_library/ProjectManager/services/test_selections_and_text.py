# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

from discopop_library.ProjectManager.services.selections import (
    load_deselected,
    parse_id_ranges,
    save_deselected,
    selections_path,
)
from discopop_library.ProjectManager.services.text import clean_ansi_output

AVAILABLE = ["1", "2", "3", "5", "6", "7", "8", "12"]


def test_parse_id_ranges() -> None:
    assert parse_id_ranges("1,3,5-8", AVAILABLE) == {"1", "3", "5", "6", "7", "8"}
    assert parse_id_ranges("8-5", AVAILABLE) == {"5", "6", "7", "8"}
    assert parse_id_ranges("012, 99, x, 4-y,", AVAILABLE) == {"12"}
    assert parse_id_ranges("", AVAILABLE) == set()


def test_deselection_round_trip_keeps_other_selectors(tmp_path: Path) -> None:
    dot_dp = str(tmp_path)
    assert load_deselected(dot_dp, "a") == set()
    save_deselected(dot_dp, "a", ["10", "2"])
    save_deselected(dot_dp, "b", ["7"])
    assert load_deselected(dot_dp, "a") == {"2", "10"}
    assert load_deselected(dot_dp, "b") == {"7"}
    with open(selections_path(dot_dp)) as f:
        assert json.load(f)["a"] == {"deselected": ["2", "10"]}


def test_a_corrupt_selection_file_counts_as_empty(tmp_path: Path) -> None:
    path = Path(selections_path(str(tmp_path)))
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    assert load_deselected(str(tmp_path), "a") == set()


def test_clean_ansi_output() -> None:
    assert clean_ansi_output("\x1b[31mred\x1b[0m") == "red"
    assert clean_ansi_output("10%\r50%\r100%") == "100%"
    assert clean_ansi_output("a\n\n  \nb") == "a\nb"
    assert clean_ansi_output("done\r") == "done"
