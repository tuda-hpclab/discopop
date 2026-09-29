# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for TaskGraph.__get_state_mappings_from_file, which reconstructs the callpath of
every observed callpath state from the profiler's stateID_to_callpath_mapping.txt.

The profiler writes that file as a prefix tree ("<state_id> <parent_state_id> <label>"),
so a callpath is only complete once the ancestors of a state have been read as well. The
labels are what __assign_state_ids matches against the context tree, so a reader that
silently produces the wrong labels does not fail - it just makes data dependencies
disappear and turns negative pattern tests into false positives. Hence the format is
pinned here."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

# One dependency, observed with source state 24 and sink state 27.
DEP_FILE_CONTENTS = "\n".join(
    [
        "772@24 NOM  RAW 1265@27|GEPRESULT_temp(99381316572105)",
        "",
    ]
)

# Prefix tree as emitted by DiscoPoP::save_enumerated_paths. State 1 is the root and
# references itself. The line order is deliberately shuffled: the writer accumulates the
# lines via an OpenMP reduction, so it is not deterministic.
MAPPING_FILE_CONTENTS = "\n".join(
    [
        "# Format: <NodeID> <ParentID> <Label>",
        "24 23 main_loopstate1",
        "27 21 free",
        "1 1 ROOT",
        "23 11 main_loopstate0",
        "21 11 call_69",
        "11 1 main",
        "",
    ]
)


def _get_state_mappings(tg: Any, dep_file: str) -> Dict[str, List[str]]:
    """Call the name-mangled private reader."""
    result: Dict[str, List[str]] = tg._TaskGraph__get_state_mappings_from_file(dep_file)
    return result


@pytest.fixture  # type: ignore[misc]
def dep_file(tmp_path: Any) -> str:
    (tmp_path / "dynamic_dependencies.txt").write_text(DEP_FILE_CONTENTS)
    (tmp_path / "stateID_to_callpath_mapping.txt").write_text(MAPPING_FILE_CONTENTS)
    return str(tmp_path / "dynamic_dependencies.txt")


def test_callpaths_are_reconstructed_from_the_prefix_tree(
    build_task_graph: Any, build_pet_graph: Any, dep_file: str
) -> None:
    tg = build_task_graph(build_pet_graph([]))

    mappings = _get_state_mappings(tg, dep_file)

    # ordered from the root to the state itself, root label excluded
    assert mappings["24"] == ["main", "main_loopstate0", "main_loopstate1"]
    assert mappings["27"] == ["main", "call_69", "free"]


def test_source_and_sink_states_are_both_reported(build_task_graph: Any, build_pet_graph: Any, dep_file: str) -> None:
    """Dependency insertion looks up the source state as well as the sink state, so
    dropping either from the mapping loses the dependencies observed in it."""
    tg = build_task_graph(build_pet_graph([]))

    mappings = _get_state_mappings(tg, dep_file)

    assert "24" in mappings  # source state
    assert "27" in mappings  # sink state


def test_unobserved_and_root_states_are_filtered_out(
    build_task_graph: Any, build_pet_graph: Any, dep_file: str
) -> None:
    tg = build_task_graph(build_pet_graph([]))

    mappings = _get_state_mappings(tg, dep_file)

    # states 11, 21 and 23 only appear as ancestors, they were never observed themselves
    assert set(mappings) == {"24", "27"}
    # the root does not describe a callpath
    assert "1" not in mappings


def test_missing_mapping_file_yields_no_mappings(build_task_graph: Any, build_pet_graph: Any, tmp_path: Any) -> None:
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text(DEP_FILE_CONTENTS)
    tg = build_task_graph(build_pet_graph([]))

    assert _get_state_mappings(tg, str(dep_file)) == {}


def test_unparsable_mapping_file_warns_instead_of_failing_silently(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Any
) -> None:
    """A mapping file that carries no prefix tree nodes - e.g. one written in the previous
    "<state_id> <label>-->..." format - suppresses every data dependency, so it has to be
    reported rather than passed over."""
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text(DEP_FILE_CONTENTS)
    (tmp_path / "stateID_to_callpath_mapping.txt").write_text("24 main-->main_loopstate0-->main_loopstate1\n")
    tg = build_task_graph(build_pet_graph([]))

    with pytest.warns(UserWarning, match="No callpaths could be read"):
        assert _get_state_mappings(tg, str(dep_file)) == {}


@pytest.mark.parametrize(  # type: ignore[misc]
    ("mapping_contents", "expected"),
    [
        # parent that is not part of the tree: treated as the root. State 27 is observed but
        # absent from the tree, so it carries no callpath at all.
        ("24 999 orphan\n", {"24": ["orphan"]}),
        # two states referencing each other: must terminate rather than loop forever. Neither of
        # them is the root, so each callpath is cut where its own walk started. Both are asserted
        # to pin that the result does not depend on the order in which the states are resolved -
        # that order comes from a set of state ids and therefore varies with PYTHONHASHSEED.
        ("24 27 first\n27 24 second\n", {"24": ["second", "first"], "27": ["first", "second"]}),
    ],
    ids=["unknown_parent", "cyclic_parents"],
)
def test_malformed_prefix_tree_terminates(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Any, mapping_contents: str, expected: Dict[str, List[str]]
) -> None:
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text(DEP_FILE_CONTENTS)
    (tmp_path / "stateID_to_callpath_mapping.txt").write_text(mapping_contents)
    tg = build_task_graph(build_pet_graph([]))

    assert _get_state_mappings(tg, str(dep_file)) == expected
