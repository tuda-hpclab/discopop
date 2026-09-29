# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for TaskGraph.__read_dependencies_from_files, the single place where the
profiled dependency files are parsed.

The callpath state markers ("<line_id>@<state_id>") in dynamic_dependencies.txt
serve double duty: they carry the state a dependency was observed in, and their
mere presence is what classifies a dependency as dynamic (DYN_*) rather than
static (STAT_*). --ignore-dependency-states drops them, so both effects are
asserted here."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

# {dep_type: {source_location: {source_state_id: {sink_location: {sink_state_id: [var_info]}}}}}
Dependencies = Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]]

# One dependency observed with state markers on both source and sink, one without any.
DEP_FILE_CONTENTS = "\n".join(
    [
        "# a comment line that must be skipped",
        "772@5294 NOM  RAW 1265@56|GEPRESULT_temp(99381316572105)",
        "503 NOM  RAW 772|GEPRESULT_result(99381316572120)",
        "",
    ]
)


def _read(tg: Any, dep_file: str) -> Dependencies:
    """Call the name-mangled private reader."""
    result: Dependencies = tg._TaskGraph__read_dependencies_from_files(dep_file, None)
    return result


@pytest.fixture  # type: ignore[misc]
def dep_file(tmp_path: Any) -> str:
    path = tmp_path / "dynamic_dependencies.txt"
    path.write_text(DEP_FILE_CONTENTS)
    return str(path)


def test_state_markers_are_kept_and_classify_the_dependency_as_dynamic(
    build_task_graph: Any, build_pet_graph: Any, dep_file: str
) -> None:
    tg = build_task_graph(build_pet_graph([]))

    deps = _read(tg, dep_file)

    # the dependency carrying markers keeps its state ids and is reported as dynamic
    assert "DYN_RAW" in deps
    assert deps["DYN_RAW"]["772"]["5294"]["1265"]["56"] == ["GEPRESULT_temp(99381316572105)"]
    # the dependency without markers is static, with both state ids unspecified
    assert deps["STAT_RAW"]["503"]["NO_STATE"]["772"]["NO_STATE"] == ["GEPRESULT_result(99381316572120)"]


def test_ignore_dependency_states_drops_markers_and_makes_every_dependency_static(
    build_task_graph: Any, build_pet_graph: Any, dep_file: str
) -> None:
    tg = build_task_graph(build_pet_graph([]))
    tg.ignore_dependency_states = True

    deps = _read(tg, dep_file)

    # nothing is dynamic any more: with no "@" left, both endpoints read as NO_STATE
    assert "DYN_RAW" not in deps
    assert deps["STAT_RAW"]["772"]["NO_STATE"]["1265"]["NO_STATE"] == ["GEPRESULT_temp(99381316572105)"]
    # the line that never had markers is unaffected
    assert deps["STAT_RAW"]["503"]["NO_STATE"]["772"]["NO_STATE"] == ["GEPRESULT_result(99381316572120)"]


def test_ignore_dependency_states_leaves_locations_and_variable_info_intact(
    build_task_graph: Any, build_pet_graph: Any, dep_file: str
) -> None:
    """Only the "@<state_id>" suffixes may be removed - line ids and the variable
    info (which contains digits and parentheses of its own) must survive."""
    tg = build_task_graph(build_pet_graph([]))
    tg.ignore_dependency_states = True

    deps = _read(tg, dep_file)

    assert sorted(deps["STAT_RAW"].keys()) == ["503", "772"]
    for source_deps in deps["STAT_RAW"].values():
        for sink_deps in source_deps["NO_STATE"].values():
            for var_infos in sink_deps.values():
                assert all("@" not in var_info for var_info in var_infos)
                assert all(var_info.endswith(")") for var_info in var_infos)
