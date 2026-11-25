# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import jsonpickle  # type: ignore
import pytest

from discopop_library.Amdahl import regions
from discopop_library.Amdahl.model import SuggestionExtent, SuggestionRegion
from discopop_library.HostpotLoader.detailed_hotspot_loader import load_detailed_hotspots


class _Loop:
    """Stands in for a LoopNode: only its positions are used."""

    def __init__(self, start: str, end: str) -> None:
        self._start, self._end = start, end

    def start_position(self) -> str:
        return self._start

    def end_position(self) -> str:
        return self._end


def _pattern(pattern_id: int, start: str, end: str) -> SimpleNamespace:
    return SimpleNamespace(pattern_id=pattern_id, start_line=start, end_line=end)


def _detection_result() -> SimpleNamespace:
    # suggestion 1 sits on a loop reaching beyond its own end line, suggestion 2 does not, 3 has no position
    patterns = SimpleNamespace(
        do_all=[_pattern(1, "1:10", "1:12"), _pattern(2, "2:5", "2:9")],
        reduction=[_pattern(3, "?", "?")],
    )
    return SimpleNamespace(patterns=patterns, pet="the pet")


@pytest.fixture
def loops(monkeypatch: pytest.MonkeyPatch) -> None:
    from discopop_explorer.functions.PEGraph.queries import nodes

    found = [_Loop("1:10", "1:20"), _Loop("1:10", "1:15"), _Loop("3:1", "3:2")]
    monkeypatch.setattr(nodes, "all_nodes", lambda pet, _type: found if pet == "the pet" else [])


def _hotspots_entry(fid: int, line: int, typ: str, name: str, max_val: float) -> Dict[str, Any]:
    return {
        "csid": 0,
        "typ": typ,
        "fid": fid,
        "lineNum": line,
        "name": name,
        "hotness": "YES",
        "avr": max_val,
        "runtimes": [max_val],
        "maxVal": max_val,
    }


def _write_hotspots(dot_dp: Path, entries: List[Dict[str, Any]]) -> None:
    (dot_dp / "hotspot_detection").mkdir(parents=True, exist_ok=True)
    (dot_dp / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": entries}))


@pytest.fixture
def dot_dp(tmp_path: Path) -> Path:
    (tmp_path / "explorer").mkdir()
    (tmp_path / "explorer" / regions.DUMP_NAME).write_text("the dump")
    _write_hotspots(
        tmp_path,
        [_hotspots_entry(1, 1, "FUNCTION", "main", 10.0), _hotspots_entry(1, 10, "LOOP", "loop", 4.0)],
    )
    return tmp_path


@pytest.fixture
def no_decode(monkeypatch: pytest.MonkeyPatch, dot_dp: Path) -> None:
    """Fail on any attempt to read or decode the dump."""
    dump = os.path.abspath(dot_dp / "explorer" / regions.DUMP_NAME)
    real_open = builtins.open

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, os.PathLike)) and os.path.abspath(file) == dump:
            raise AssertionError("the dump was opened")
        return real_open(file, *args, **kwargs)

    def decode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the dump was decoded")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(jsonpickle, "decode", decode)


def test_extents_extend_suggestions_on_loops_to_the_longest_loop(loops: None) -> None:
    extents = regions.suggestion_extents(_detection_result())
    assert extents == {1: SuggestionExtent(1, 1, 10, 20), 2: SuggestionExtent(2, 2, 5, 9)}


def test_build_regions_is_extents_plus_shares(loops: None) -> None:
    result = regions.build_regions(_detection_result(), [])
    assert result == {1: SuggestionRegion(1, 1, 10, 20, None), 2: SuggestionRegion(2, 2, 5, 9, None)}


def test_shares_come_from_the_hotspot_results(dot_dp: Path) -> None:
    extents = {1: SuggestionExtent(1, 1, 10, 20), 2: SuggestionExtent(2, 2, 5, 9)}
    result = regions.regions_from_extents(extents, load_detailed_hotspots(str(dot_dp)))
    assert result == {1: SuggestionRegion(1, 1, 10, 20, 0.4), 2: SuggestionRegion(2, 2, 5, 9, None)}


def test_extents_file_round_trip(dot_dp: Path) -> None:
    dump = str(dot_dp / "explorer" / regions.DUMP_NAME)
    extents = {7: SuggestionExtent(7, 3, 1, 4)}
    path = regions.write_suggestion_extents(dump, extents)
    assert path == str(dot_dp / "explorer" / regions.EXTENTS_NAME)
    assert regions.read_suggestion_extents(dump) == extents
    assert not regions.needs_extraction(str(dot_dp))


def test_extents_of_another_dump_are_not_current(dot_dp: Path) -> None:
    dump = dot_dp / "explorer" / regions.DUMP_NAME
    regions.write_suggestion_extents(str(dump), {7: SuggestionExtent(7, 3, 1, 4)})
    dump.write_text("a new, longer dump")
    assert regions.read_suggestion_extents(str(dump)) is None
    assert regions.needs_extraction(str(dot_dp))


def test_same_size_but_newer_dump_is_not_current(dot_dp: Path) -> None:
    dump = dot_dp / "explorer" / regions.DUMP_NAME
    regions.write_suggestion_extents(str(dump), {7: SuggestionExtent(7, 3, 1, 4)})
    stat = os.stat(dump)
    os.utime(dump, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert regions.read_suggestion_extents(str(dump)) is None


@pytest.mark.parametrize("content", ["not json", "{}", '{"format": 99}', '{"format": 1, "dump": {}}'])
def test_unusable_extents_files_are_ignored(dot_dp: Path, content: str) -> None:
    (dot_dp / "explorer" / regions.EXTENTS_NAME).write_text(content)
    assert regions.read_suggestion_extents(str(dot_dp / "explorer" / regions.DUMP_NAME)) is None


def test_without_a_dump_there_are_no_regions(tmp_path: Path) -> None:
    assert regions.load_regions(str(tmp_path)) == {}
    assert not regions.needs_extraction(str(tmp_path))


def test_without_extents_nothing_is_decoded_by_default(dot_dp: Path, no_decode: None) -> None:
    assert regions.needs_extraction(str(dot_dp))
    assert regions.load_regions(str(dot_dp)) == {}


def test_new_hotspot_results_need_no_decode(dot_dp: Path, no_decode: None) -> None:
    dump = str(dot_dp / "explorer" / regions.DUMP_NAME)
    regions.write_suggestion_extents(dump, {1: SuggestionExtent(1, 1, 10, 20)})
    assert regions.load_regions(str(dot_dp)) == {1: SuggestionRegion(1, 1, 10, 20, 0.4)}
    # a hotspot measurement rewrites Hotspots.json
    _write_hotspots(
        dot_dp,
        [_hotspots_entry(1, 1, "FUNCTION", "main", 10.0), _hotspots_entry(1, 10, "LOOP", "loop", 5.0)],
    )
    os.utime(dot_dp / "hotspot_detection" / "Hotspots.json", ns=(1, 2_000_000_000_000_000_000))
    assert regions.load_regions(str(dot_dp)) == {1: SuggestionRegion(1, 1, 10, 20, 0.5)}


def test_allow_decode_extracts_once(dot_dp: Path, loops: None, monkeypatch: pytest.MonkeyPatch) -> None:
    decoded: List[str] = []

    def decode(text: str, **_kwargs: Any) -> Any:
        decoded.append(text)
        return _detection_result()

    monkeypatch.setattr(jsonpickle, "decode", decode)
    expected = {1: SuggestionRegion(1, 1, 10, 20, 0.4), 2: SuggestionRegion(2, 2, 5, 9, None)}
    assert regions.load_regions(str(dot_dp), allow_decode=True) == expected
    assert regions.load_regions(str(dot_dp), allow_decode=True) == expected
    assert regions.load_regions(str(dot_dp)) == expected
    assert decoded == ["the dump"]


def test_command_line_extraction(dot_dp: Path, loops: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jsonpickle, "decode", lambda _text, **_kwargs: _detection_result())
    assert regions.main(["--extract-extents", str(dot_dp)]) == 0
    assert not regions.needs_extraction(str(dot_dp))
    assert regions.main(["--extract-extents", str(dot_dp / "nothing")]) == 1


def test_regions_stamp_follows_the_inputs(dot_dp: Path) -> None:
    before = regions.regions_stamp(str(dot_dp))
    regions.write_suggestion_extents(str(dot_dp / "explorer" / regions.DUMP_NAME), {})
    with_extents = regions.regions_stamp(str(dot_dp))
    assert with_extents != before
    _write_hotspots(dot_dp, [_hotspots_entry(1, 1, "FUNCTION", "main", 12345.0)])
    assert regions.regions_stamp(str(dot_dp)) != with_extents
