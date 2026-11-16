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
from typing import Optional

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services import callpath_pruning as cp
from discopop_library.ProjectManager.services.hotspot_build import BUILD_CURRENT, BUILD_MISMATCH


def _arguments(root: Path) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=False,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


def _hotspots(arguments: ProjectManagerArguments, hotness: str = "YES") -> Path:
    directory = Path(arguments.dot_dp) / "hotspot_detection"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Hotspots.json"
    path.write_text(json.dumps({"code_regions": [{"hotness": hotness}]}))
    return path


@pytest.fixture
def arguments(tmp_path: Path) -> ProjectManagerArguments:
    return _arguments(tmp_path / "project")


def _enable(arguments: ProjectManagerArguments, **fields: object) -> None:
    cp.save_callpath_pruning(arguments.project_dir, cp.CallpathPruning(enabled=True, **fields))  # type: ignore[arg-type]


def test_default_is_off_and_roundtrip(arguments: ProjectManagerArguments) -> None:
    assert cp.load_callpath_pruning(arguments.project_dir) == cp.CallpathPruning()
    cp.save_callpath_pruning(arguments.project_dir, cp.CallpathPruning())
    assert not os.path.exists(cp.callpath_pruning_path(arguments.project_dir))  # the default is not written
    setting = cp.CallpathPruning(enabled=True, hot_depth=4, unclassified="prune")
    cp.save_callpath_pruning(arguments.project_dir, setting)
    assert cp.load_callpath_pruning(arguments.project_dir) == setting


@pytest.mark.parametrize(
    "content",
    [
        {"enabled": "yes", "hot_depth": -1, "seeds": "x", "unclassified": 3},
        {"enabled": False, "hot_depth": True},  # a bool is no depth
        {"hot_depth": 10**6},
        [1, 2],
    ],
)
def test_invalid_file_falls_back_to_the_defaults(arguments: ProjectManagerArguments, content: object) -> None:
    os.makedirs(arguments.project_dir)
    Path(cp.callpath_pruning_path(arguments.project_dir)).write_text(json.dumps(content))
    assert cp.load_callpath_pruning(arguments.project_dir) == cp.CallpathPruning()


def test_a_corrupt_file_is_the_default(arguments: ProjectManagerArguments) -> None:
    os.makedirs(arguments.project_dir)
    Path(cp.callpath_pruning_path(arguments.project_dir)).write_text("{ broken")
    assert cp.load_callpath_pruning(arguments.project_dir) == cp.CallpathPruning()


def test_warning_only_when_hotspots_are_current_and_pruning_is_off(arguments: ProjectManagerArguments) -> None:
    assert cp.inactive_warning(arguments, None) is None  # no hotspots
    _hotspots(arguments)
    assert cp.inactive_warning(arguments, None) is not None
    assert cp.environment(arguments, None) == {}
    _enable(arguments)
    assert cp.inactive_warning(arguments, None) is None
    assert cp.no_hotspots_warning(arguments, None) is None
    env = cp.environment(arguments, None)
    assert env[cp.HOTSPOTS_VARIABLE].endswith("Hotspots.json") and env[cp.HOT_DEPTH_VARIABLE] == "2"
    assert env[cp.UNCLASSIFIED_VARIABLE] == "keep" and env[cp.SEEDS_VARIABLE] == "both"


def test_enabled_without_hotspots_warns_and_sets_nothing(arguments: ProjectManagerArguments) -> None:
    _enable(arguments)
    assert cp.no_hotspots_warning(arguments, None) is not None
    assert cp.environment(arguments, None) == {}


def test_hotspots_without_a_hot_region_or_unreadable_are_not_current(arguments: ProjectManagerArguments) -> None:
    path = _hotspots(arguments, hotness="NO")
    assert cp.current_hotspots_file(arguments, None) is None
    path.write_text("{ truncated")
    assert cp.current_hotspots_file(arguments, None) is None
    assert cp.inactive_warning(arguments, None) is None


def test_hotspots_of_other_project_directories_are_not_current(arguments: ProjectManagerArguments) -> None:
    _hotspots(arguments)
    recorded = {"hd": {"included": ["/elsewhere"], "excluded": []}}
    Path(arguments.dot_dp, "instrumented_project_directories.json").write_text(json.dumps(recorded))
    assert cp.current_hotspots_file(arguments, None) is None


@pytest.mark.parametrize("state,current", [(BUILD_MISMATCH, False), (BUILD_CURRENT, True)])
def test_hotspots_of_changed_sources_are_not_current(
    arguments: ProjectManagerArguments, monkeypatch: pytest.MonkeyPatch, state: str, current: bool
) -> None:
    from discopop_library.ProjectManager.services import hotspot_session

    monkeypatch.setattr(hotspot_session.HotspotSession, "build_state", lambda self, config: (state, ""))
    _hotspots(arguments)
    assert (cp.current_hotspots_file(arguments, "cfg") is not None) is current
    # without a configuration the sources are not compared
    assert cp.current_hotspots_file(arguments, None) is not None


def test_the_state_changes_with_the_hotspots_content_and_the_parameters(arguments: ProjectManagerArguments) -> None:
    path = _hotspots(arguments)
    _enable(arguments)
    before = cp.state_of(cp.environment(arguments, None), arguments.dot_dp)
    assert cp.state_of(cp.environment(arguments, None), arguments.dot_dp) == before
    path.write_text(json.dumps({"code_regions": [{"hotness": "MAYBE"}, {"hotness": "YES"}]}))
    after_content = cp.state_of(cp.environment(arguments, None), arguments.dot_dp)
    assert after_content != before
    _enable(arguments, hot_depth=7)
    assert cp.state_of(cp.environment(arguments, None), arguments.dot_dp) != after_content


def test_the_state_of_a_disabled_setting_does_not_depend_on_the_hotspots(arguments: ProjectManagerArguments) -> None:
    path = _hotspots(arguments)
    before = cp.state_of(cp.environment(arguments, None), arguments.dot_dp)
    path.write_text(json.dumps({"code_regions": [{"hotness": "MAYBE"}]}))
    assert cp.state_of(cp.environment(arguments, None), arguments.dot_dp) == before


def _record(arguments: ProjectManagerArguments, state: Optional[str]) -> None:
    os.makedirs(arguments.dot_dp, exist_ok=True)
    Path(arguments.dot_dp, "instrumented_project_directories.json").write_text(
        json.dumps({"dp": {"included": [], "excluded": []}})
    )
    if state is not None:
        cp.record_state(arguments.dot_dp, state)


def test_profiling_data_is_stale_when_it_was_pruned_differently(arguments: ProjectManagerArguments) -> None:
    _hotspots(arguments)
    _record(arguments, cp.state_of({}, arguments.dot_dp))  # profiled without pruning
    assert cp.stale_message(arguments, None) is None
    _enable(arguments)  # pruning is switched on afterwards
    assert cp.stale_message(arguments, None) is not None
    _record(arguments, cp.state_of(cp.environment(arguments, None), arguments.dot_dp))
    assert cp.stale_message(arguments, None) is None
    _hotspots(arguments, hotness="MAYBE")  # the hotspot results changed
    assert cp.stale_message(arguments, None) is not None


def test_data_without_a_record_is_not_reported_stale(arguments: ProjectManagerArguments) -> None:
    _hotspots(arguments)
    _enable(arguments)
    assert cp.stale_message(arguments, None) is None
    _record(arguments, None)
    assert cp.stale_message(arguments, None) is None


def test_pruning_note_reports_what_the_pass_printed() -> None:
    output = (
        "x\nEnumerated 10 call path states with hotspot pruning\nEnumerated 5 call path states with hotspot pruning\n"
    )
    note = cp.pruning_note("/h.json", output)
    assert "2 module(s)" in note and "15 call path states" in note
    assert "did not report" in cp.pruning_note("/h.json", "nothing")
