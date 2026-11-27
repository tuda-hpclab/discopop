# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The hotspot filter of the check: classified like patch repair's suggestions, cold loops are not checked."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.BlockerResolution import hotspots
from discopop_library.BlockerResolution.check import Agent
from discopop_library.BlockerResolution.conftest import Project, ScriptedAgent, json_answer
from discopop_library.BlockerResolution.run import EDIT, run
from discopop_library.BlockerResolution.BlockerResolutionArguments import BlockerResolutionArguments
from discopop_library.BlockerResolution.test_run import _arguments, _dot_discopop
from discopop_library.BlockerResolution.unsure import Location, UnsureSuggestion

# pattern id: (first line, last line of the pattern, last line of the loop's region)
_LOOPS = {5: (7, 7, 10), 6: (20, 20, 25), 7: (30, 30, 35), 8: (40, 40, 45)}
# 5 hot, 6 cold, 7 maybe, 8 without a hotspot entry; 31 is a cold loop nested in 7, 50 a hot loop elsewhere
_HOTSPOTS = [(7, "YES"), (20, "NO"), (30, "MAYBE"), (31, "NO"), (50, "YES")]


def _write_hotspots(dot: Path, entries: List[Tuple[int, str]]) -> None:
    (dot / "hotspot_detection").mkdir()
    loops = [
        {"fid": 1, "lineNum": line, "typ": "LOOP", "hotness": hot, "name": "", "avr": 1.0} for line, hot in entries
    ]
    (dot / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code": loops}))


def _with_lines(dot: Path) -> None:
    path = dot / "explorer" / "unsure_suggestions.json"
    data = json.loads(path.read_text())
    for entry in data["suggestions"]:
        first, last, region_end = _LOOPS[entry["pattern_id"]]
        entry["start_line"], entry["end_line"] = "1:" + str(first), "1:" + str(last)
        entry["region"] = {"file_id": 1, "start_line": first, "end_line": region_end, "kind": "loop"}
    path.write_text(json.dumps(data))


def _project(project: Project, with_hotspots: bool = True) -> Path:
    dot = _dot_discopop(project, sorted(_LOOPS))
    _with_lines(dot)
    if with_hotspots:
        _write_hotspots(dot, _HOTSPOTS)
    return dot


class _Recorder:
    """rejects every suggestion, and records which ones it was asked about"""

    def __init__(self) -> None:
        self.checked = 0

    def __call__(self, mode: str) -> Agent:
        if mode == EDIT:
            self.checked += 1
        return ScriptedAgent([json_answer(verdict="rejected", reason="no")])


def _results(dot: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = json.loads((dot / "blocker_resolution" / "results.json").read_text())
    return result


def _checked(dot: Path) -> Dict[int, str]:
    return {s["pattern_id"]: s["hotspot_type"] for s in _results(dot)["suggestions"]}


def test_the_classes_agree_with_those_of_patch_repairs_suggestions() -> None:
    information = {
        HotspotType(t): [(1, line, HotspotNodeType.LOOP, "", 1.0) for line, hot in _HOTSPOTS if hot == t.name]
        for t in HotspotType
    }
    suggestions = [
        UnsureSuggestion(i, "do_all", Location(1, a), Location(1, region_end), "", [], {"end_line": "1:" + str(b)})
        for i, (a, b, region_end) in _LOOPS.items()
    ]
    patterns = [
        SimpleNamespace(
            pattern_id=i,
            start_line="1:" + str(a),
            end_line="1:" + str(b),
            applicable_pattern=True,
            standalone_pattern=True,
        )
        for i, (a, b, _region_end) in _LOOPS.items()
    ]
    storage = SimpleNamespace(
        get_pattern_ids=lambda: [p.pattern_id for p in patterns],
        get_pattern_from_id=lambda i: next(p for p in patterns if p.pattern_id == i),
    )
    by_type = get_patterns_by_hotspot_type(SimpleNamespace(patterns=storage), information)  # type: ignore[arg-type]
    expected = {i: t.name.lower() for t, ids in by_type.items() for i in ids}
    classes = hotspots.classify(suggestions, information)
    assert classes == {**{i: hotspots.UNKNOWN for i in _LOOPS}, **expected}
    # the lines of the pattern, not the loop's region: the cold loop nested in 7 does not make it cold
    assert classes == {5: "yes", 6: "no", 7: "maybe", 8: "unknown"}
    assert hotspots.classify(suggestions, {}) == {i: "yes" for i in _LOOPS}


def test_cold_suggestions_are_skipped_and_recorded(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    dot = _project(project)
    agents = _Recorder()
    assert run(_arguments(dot, review=False), agents) == 0
    # without a hotspot entry a suggestion is checked: there is nothing to filter it by
    assert _checked(dot) == {5: "yes", 7: "maybe", 8: "unknown"}
    assert agents.checked == 3
    assert _results(dot)["skipped_by_hotspot"] == [{"pattern_id": 6, "hotspot_type": "no"}]
    events = [json.loads(line) for line in (dot / "blocker_resolution" / "progress.jsonl").read_text().splitlines()]
    assert events[0] == {"event": "skipped_by_hotspot", "suggestions": [{"pattern_id": 6, "hotspot_type": "no"}]}
    assert events[1]["suggestions"] == [5, 7, 8]
    assert "skipped 1 cold suggestion(s)" in capsys.readouterr().out


def test_the_selected_types_decide(project: Project) -> None:
    dot = _project(project)
    run(_arguments(dot, review=False, hotspot_types="yes,maybe,no"), _Recorder())
    assert sorted(_checked(dot)) == [5, 6, 7, 8]
    assert _results(dot)["skipped_by_hotspot"] == []


def test_explicit_ids_are_checked_whatever_their_type(project: Project) -> None:
    dot = _project(project)
    run(_arguments(dot, review=False, suggestions="6", hotspot_types="yes"), _Recorder())
    assert _checked(dot) == {6: "no"}
    assert _results(dot)["skipped_by_hotspot"] == []


def test_without_hotspot_results_nothing_is_skipped(project: Project) -> None:
    dot = _project(project, with_hotspots=False)
    run(_arguments(dot, review=False), _Recorder())
    assert _checked(dot) == {i: "yes" for i in _LOOPS}
    assert _results(dot)["skipped_by_hotspot"] == []


def test_the_limit_counts_checked_suggestions_only(project: Project) -> None:
    dot = _project(project)
    agents = _Recorder()
    run(_arguments(dot, review=False, hotspot_types="maybe", max_suggestions=1), agents)
    # 5 and 6 are skipped, 7 is checked
    assert _checked(dot) == {7: "maybe"}
    assert [s["pattern_id"] for s in _results(dot)["skipped_by_hotspot"]] == [5, 6]


def test_a_run_which_skips_everything_records_it(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    dot = _project(project, with_hotspots=False)
    _write_hotspots(dot, [(line, "NO") for line in (7, 20, 30, 40)])
    agents = _Recorder()
    assert run(_arguments(dot, review=False), agents) == 0
    assert agents.checked == 0
    results = _results(dot)
    assert results["suggestions"] == []
    assert [s["hotspot_type"] for s in results["skipped_by_hotspot"]] == ["no"] * 4
    assert "Checked 0 unsure suggestion(s), skipped 4 cold suggestion(s). Approvals" in capsys.readouterr().out


@pytest.mark.parametrize("types", ["", "hot", "yes,lukewarm"])
def test_unknown_hotspot_types_are_an_error(tmp_path: Path, types: str) -> None:
    with pytest.raises(ValueError, match="--hotspot-types"):
        BlockerResolutionArguments(log_level="WARNING", write_log=False, dot_dp_path=str(tmp_path), hotspot_types=types)


def test_types_are_case_insensitive(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path, hotspot_types=" YES, Maybe ")
    assert arguments.selected_hotspot_types() == ["yes", "maybe"]
