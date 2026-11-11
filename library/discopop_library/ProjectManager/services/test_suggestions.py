# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from discopop_library.ProjectManager.services import suggestions
from discopop_library.ProjectManager.services.suggestions import (
    SuggestionInfo,
    load_suggestions,
    suggestion_detail_fields,
)


def _entry(
    pattern_id: int, start: str, end: str, pragma: str = "#pragma omp parallel for", **extra: Any
) -> Dict[str, Any]:
    entry = {
        "pattern_id": pattern_id,
        "start_line": start,
        "end_line": end,
        "pragma": pragma,
        "private": [],
        "shared": [],
        "reduction": [],
        "affected_functions": ["0:15:main"],
    }
    entry.update(extra)
    return entry


def _project(root: Path, patterns: Dict[str, List[Dict[str, Any]]], patch_dirs: List[str]) -> str:
    (root / "explorer").mkdir()
    (root / "explorer" / "patterns.json").write_text(json.dumps({"version": "x", "patterns": patterns}))
    (root / "FileMapping.txt").write_text("1\t/src/example.cpp\n2\t/src/other.cpp\n")
    for name in patch_dirs:
        (root / "patch_generator" / name).mkdir(parents=True)
        (root / "patch_generator" / name / "1.patch").write_text("")
    return str(root)


def _hotspots(root: Path, regions: List[Dict[str, Any]]) -> None:
    (root / "hotspot_detection").mkdir()
    (root / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))


def _region(fid: int, line: int, hotness: str, typ: str = "LOOP") -> Dict[str, Any]:
    return {"csid": 1, "typ": typ, "fid": fid, "lineNum": line, "name": "", "hotness": hotness, "avr": 1.0}


def test_normal_entries(tmp_path: Path) -> None:
    dot_dp = _project(
        tmp_path,
        {
            "do_all": [_entry(0, "1:20", "1:22", private=["i"], shared=["a", "b"])],
            "reduction": [_entry(1, "1:24", "1:26", "#pragma omp parallel for reduction(+:s)", reduction=["+:s"])],
        },
        ["0", "1"],
    )
    first, second = load_suggestions(dot_dp)
    assert first == SuggestionInfo(
        id="0",
        pattern_type="doall",
        file_name="example.cpp",
        file_path="/src/example.cpp",
        start_line=20,
        end_line=22,
        pragma="#pragma omp parallel for",
        function="main",
        hotness="",
        variables=(("Private", "i"), ("Shared", "a, b")),
    )
    assert first.location == "example.cpp:20"
    assert second.pattern_type == "reduction"
    assert second.variables == (("Reduction", "+:s"),)


def test_affected_functions_as_string_representation(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22", affected_functions="['0:15:main']")]}, ["0"])
    assert load_suggestions(dot_dp)[0].function == "main"


def test_mangled_function_name(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22", affected_functions=["0:3:_Z5heavyi"])]}, ["0"])
    assert load_suggestions(dot_dp)[0].function in ("heavy(int)", "_Z5heavyi")  # without a demangler: as is


def test_missing_patterns_json(tmp_path: Path) -> None:
    (tmp_path / "patch_generator" / "3").mkdir(parents=True)
    (tmp_path / "patch_generator" / "3" / "1.patch").write_text("")
    [info] = load_suggestions(str(tmp_path))
    assert info == SuggestionInfo(id="3")
    assert info.location == ""


def test_corrupt_files(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {}, ["0"])
    (tmp_path / "explorer" / "patterns.json").write_text("{not json")
    (tmp_path / "FileMapping.txt").write_bytes(b"\xff\xfe garbage")
    _hotspots(tmp_path, [])
    (tmp_path / "hotspot_detection" / "Hotspots.json").write_text("[[")
    assert load_suggestions(dot_dp) == [SuggestionInfo(id="0")]


def test_no_patch_directories(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22")]}, [])
    assert load_suggestions(dot_dp) == []


def test_patch_dir_without_pattern_and_pattern_without_patch_dir(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22"), _entry(5, "1:30", "1:31")]}, ["0", "7"])
    infos = load_suggestions(dot_dp)
    assert [info.id for info in infos] == ["0", "7"]
    assert infos[0].pattern_type == "doall"
    assert infos[1] == SuggestionInfo(id="7")


def test_unknown_file_id_and_malformed_location(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "9:20", "9:22"), _entry(1, "garbage", "")]}, ["0", "1"])
    first, second = load_suggestions(dot_dp)
    assert (first.file_path, first.start_line, first.location) == ("", 20, "")
    assert (second.start_line, second.end_line) == (0, 0)


def test_ordering_is_numeric_then_alphabetic(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {}, ["10", "2", "1", "merged"])
    assert [info.id for info in load_suggestions(dot_dp)] == ["1", "2", "10", "merged"]


def test_hotspot_match_and_no_match(tmp_path: Path) -> None:
    dot_dp = _project(
        tmp_path,
        {
            "do_all": [
                _entry(0, "1:20", "1:22"),
                _entry(1, "1:30", "1:32"),
                _entry(2, "1:40", "1:42"),
                _entry(3, "2:20", "2:22"),
            ]
        },
        ["0", "1", "2", "3"],
    )
    _hotspots(
        tmp_path,
        [
            _region(1, 21, "YES"),  # inside the loop of suggestion 0
            _region(1, 30, "NO"),
            _region(1, 41, "MAYBE", typ="FUNCTION"),  # functions do not classify loops
            _region(1, 100, "YES"),
        ],
    )
    assert [info.hotness for info in load_suggestions(dot_dp)] == ["YES", "NO", "", ""]


def test_hotness_unknown_without_hotspot_results(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22")]}, ["0"])
    assert load_suggestions(dot_dp)[0].hotness == ""


def test_hotspot_type_attached_to_pattern_is_used(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"task": [_entry(0, "1:20", "1:22", hotspot_type=2)]}, ["0"])
    _hotspots(tmp_path, [_region(1, 500, "YES")])
    info = load_suggestions(dot_dp)[0]
    assert (info.pattern_type, info.hotness) == ("task", "MAYBE")


def test_detail_fields(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22", shared=["a"])]}, ["0"])
    fields = dict(suggestion_detail_fields(load_suggestions(dot_dp)[0]))
    assert fields["Suggestion"] == "0"
    assert fields["Lines"] == "20-22"
    assert fields["File"] == "/src/example.cpp"
    assert fields["Shared"] == "a"
    assert "Hotness" not in fields
    assert suggestion_detail_fields(SuggestionInfo(id="4")) == [("Suggestion", "4")]


def test_results_are_cached_until_an_input_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22")]}, ["0"])
    calls: List[str] = []
    real = suggestions._load_suggestions

    def counting(dot_dp_path: str) -> List[SuggestionInfo]:
        calls.append(dot_dp_path)
        return real(dot_dp_path)

    monkeypatch.setattr(suggestions, "_load_suggestions", counting)
    first = load_suggestions(dot_dp)
    assert load_suggestions(dot_dp) == first and len(calls) == 1

    # a new suggestion directory, new patterns, new hotspot results and a new file mapping each invalidate
    (tmp_path / "patch_generator" / "1").mkdir()
    (tmp_path / "patch_generator" / "1" / "1.patch").write_text("")
    assert [info.id for info in load_suggestions(dot_dp)] == ["0", "1"] and len(calls) == 2
    (tmp_path / "explorer" / "patterns.json").write_text(
        json.dumps({"patterns": {"reduction": [_entry(0, "1:5", "1:6")]}})
    )
    assert load_suggestions(dot_dp)[0].pattern_type == "reduction" and len(calls) == 3
    _hotspots(tmp_path, [_region(1, 5, "YES")])
    assert load_suggestions(dot_dp)[0].hotness == "YES" and len(calls) == 4
    (tmp_path / "FileMapping.txt").write_text("1\t/other/dir/renamed.cpp\n")
    assert load_suggestions(dot_dp)[0].file_name == "renamed.cpp" and len(calls) == 5
    load_suggestions(dot_dp)
    assert len(calls) == 5


def test_the_cache_does_not_hand_out_its_own_list(tmp_path: Path) -> None:
    dot_dp = _project(tmp_path, {"do_all": [_entry(0, "1:20", "1:22")]}, ["0"])
    load_suggestions(dot_dp).clear()
    assert len(load_suggestions(dot_dp)) == 1
