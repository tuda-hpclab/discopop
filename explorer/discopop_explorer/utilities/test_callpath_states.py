# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from pathlib import Path

from discopop_explorer.utilities.callpath_states import call_instructions_of_state, read_callpath_tree

# main -> h -> put (called by the instruction 68), and a second call of put by the instruction 72
TREE = {
    "14": ("1", "main"),
    "21": ("14", "call_85"),
    "22": ("21", "h"),
    "24": ("22", "call_68"),
    "25": ("24", "put"),
    "23": ("22", "call_72"),
    "31": ("23", "put"),
}


def test_the_calls_on_the_callpath_of_a_state_are_listed() -> None:
    assert call_instructions_of_state(TREE, "25") == {85, 68}
    assert call_instructions_of_state(TREE, "31") == {85, 72}
    assert call_instructions_of_state(TREE, "22") == {85}


def test_an_unknown_state_or_none_has_no_callpath() -> None:
    assert call_instructions_of_state(TREE, "99") is None
    assert call_instructions_of_state(TREE, None) is None


def test_a_cycle_in_the_tree_ends_the_walk() -> None:
    assert call_instructions_of_state({"1": ("2", "call_5"), "2": ("1", "call_6")}, "1") == {5, 6}


def test_the_tree_is_read_from_the_mapping_file(tmp_path: Path) -> None:
    mapping = tmp_path / "stateID_to_callpath_mapping.txt"
    mapping.write_text("# comment\n1 1 ROOT\n14 1 main\n21 14 call_85\n\n")
    assert read_callpath_tree(str(mapping)) == {"1": ("1", "ROOT"), "14": ("1", "main"), "21": ("14", "call_85")}
    assert read_callpath_tree(str(tmp_path / "missing.txt")) == {}
