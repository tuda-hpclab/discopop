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
from typing import Any, Dict

from discopop_library.ProjectManager.gui.plots.hotspot_data import (
    HOTNESS_MAYBE,
    HOTNESS_NO,
    HOTNESS_YES,
    KIND_FUNCTION,
    KIND_LOOP,
    MeasurementLog,
    MeasurementRun,
    RegionKey,
    canonical_region_keys,
    deserialize_log,
    hotness_counts,
    hotspots_available_for_explorer,
    invert_file_mapping,
    load_json_file,
    merge_external_runs,
    parse_cs_id,
    parse_file_mapping,
    parse_hotspot_result,
    parse_hotspots_json,
    quadrant_thresholds,
    ratio_is_degenerate,
    region_fingerprint,
    resolve_keys,
    result_file_indices,
    serialize_log,
    write_merged_analysis_input,
)

# cs_id.txt as the instrumentation pass writes it: 4 fields for loops
# ("<id> loop <line> <fid>"), 5 for functions (trailing name).
_CS_ID_TEXT = """1 loop 1284 2
2 func 2140 2 CalcHourglass
3 loop 77 5
"""


def _hotspots_json() -> Dict[str, Any]:
    return {
        "code_regions": [
            {
                "csid": 1,
                "typ": KIND_LOOP,
                "fid": 2,
                "lineNum": 1284,
                "name": "",
                "runtimes": [0.9, 4.8],
                "avr": 2.85,
                "minVal": 0.9,
                "maxVal": 4.8,
                "ratio": 0.842,
                "hotness": HOTNESS_YES,
            },
            {
                "csid": 2,
                "typ": KIND_FUNCTION,
                "fid": 2,
                "lineNum": 2140,
                "name": "CalcHourglass",
                "runtimes": [1.0, 1.05],
                "avr": 1.025,
                "minVal": 1.0,
                "maxVal": 1.05,
                "ratio": 0.512,
                "hotness": HOTNESS_MAYBE,
            },
            {
                "csid": 3,
                "typ": KIND_LOOP,
                "fid": 5,
                "lineNum": 77,
                "name": "",
                "runtimes": [0.03, 0.031],
                "avr": 0.0305,
                "minVal": 0.03,
                "maxVal": 0.031,
                "ratio": 0.504,
                "hotness": HOTNESS_NO,
            },
        ]
    }


def _file_mapping() -> Dict[int, Path]:
    return {2: Path("/proj/lulesh.cc"), 5: Path("/proj/util.cc")}


# ---------------------------------------------------------------------------
# cs_id.txt / hotspot_result_<N>.txt
# ---------------------------------------------------------------------------


def test_parse_cs_id_handles_both_line_formats() -> None:
    regions = parse_cs_id(_CS_ID_TEXT)
    assert regions[1] == (KIND_LOOP, 1284, 2, "")
    assert regions[2] == (KIND_FUNCTION, 2140, 2, "CalcHourglass")
    assert regions[3] == (KIND_LOOP, 77, 5, "")


def test_parse_cs_id_skips_malformed_and_unknown_kinds() -> None:
    text = "1 loop 10 2\nbroken\n2 gadget 11 2\nx loop 12 2\n3 loop y 2\n"
    assert set(parse_cs_id(text)) == {1}


def test_parse_cs_id_later_entry_wins() -> None:
    """The pass appends without truncating, so the newest table is authoritative."""
    text = "1 loop 10 2\n1 loop 999 2\n"
    assert parse_cs_id(text)[1] == (KIND_LOOP, 999, 2, "")


def test_resolve_keys_uses_file_mapping() -> None:
    keys = resolve_keys(parse_cs_id(_CS_ID_TEXT), _file_mapping())
    assert keys[1] == RegionKey(path="/proj/lulesh.cc", line=1284, kind=KIND_LOOP, name="")
    assert keys[2].name == "CalcHourglass"
    assert keys[3].path == "/proj/util.cc"


def test_parse_file_mapping() -> None:
    text = "1\t/proj/main.cc\n2\t/proj/lulesh.cc\nno-tab-here\nx\t/proj/bad.cc\n3\t\n"
    assert parse_file_mapping(text) == {1: "/proj/main.cc", 2: "/proj/lulesh.cc"}


def test_parse_file_mapping_keeps_paths_that_no_longer_exist() -> None:
    # The path is only displayed, so a deleted/moved file must still resolve
    # rather than degrading the region to "file_<fid>".
    assert parse_file_mapping("7\t/gone/removed.cc\n") == {7: "/gone/removed.cc"}


def test_parse_file_mapping_later_entry_wins() -> None:
    assert parse_file_mapping("1\t/a.cc\n1\t/b.cc\n") == {1: "/b.cc"}


def test_resolve_keys_falls_back_for_unmapped_fid() -> None:
    # A region is never dropped just because FileMapping.txt lacks its fid.
    keys = resolve_keys({7: (KIND_LOOP, 5, 42, "")}, {})
    assert keys[7].path == "file_42"


def test_region_key_serialize_and_display() -> None:
    loop = RegionKey(path="/proj/lulesh.cc", line=1284, kind=KIND_LOOP)
    function = RegionKey(path="/proj/lulesh.cc", line=2140, kind=KIND_FUNCTION, name="CalcHourglass")
    assert loop.serialize() == "/proj/lulesh.cc:1284:LOOP"
    assert function.serialize() == "/proj/lulesh.cc:2140:FUNCTION:CalcHourglass"
    assert loop.location == "lulesh.cc:1284"
    # loops have no name, so they display as their location
    assert loop.display_name() == "lulesh.cc:1284"
    assert function.display_name() == "CalcHourglass"


def test_parse_hotspot_result() -> None:
    assert parse_hotspot_result("1 0.500000\n2 1.250000\nbroken\n") == {1: 0.5, 2: 1.25}


def test_region_fingerprint_is_order_independent_and_detects_change() -> None:
    a = RegionKey("/p/a.cc", 10, KIND_LOOP)
    b = RegionKey("/p/b.cc", 20, KIND_FUNCTION, "f")
    assert region_fingerprint([a, b]) == region_fingerprint([b, a])
    # a moved loop is a different build: this is what guards the accumulation
    assert region_fingerprint([a, b]) != region_fingerprint([RegionKey("/p/a.cc", 11, KIND_LOOP), b])
    assert region_fingerprint([]) != region_fingerprint([a])


# ---------------------------------------------------------------------------
# Hotspots.json
# ---------------------------------------------------------------------------


def test_parse_hotspots_json_sorts_by_avg_and_derives_share() -> None:
    keys = resolve_keys(parse_cs_id(_CS_ID_TEXT), _file_mapping())
    regions = parse_hotspots_json(_hotspots_json(), keys)

    assert [region.csid for region in regions] == [1, 2, 3]  # hottest first
    assert regions[0].key.path == "/proj/lulesh.cc"
    assert abs(sum(region.share for region in regions) - 1.0) < 1e-9
    total = 2.85 + 1.025 + 0.0305
    assert abs(regions[0].share - 2.85 / total) < 1e-9
    assert regions[0].runtimes == [0.9, 4.8]


def test_parse_hotspots_json_without_matching_ids_keeps_regions() -> None:
    # A stale id table must degrade the location, not hide the region.
    regions = parse_hotspots_json(_hotspots_json(), {})
    assert len(regions) == 3
    assert regions[0].key.path == "file_2"
    assert regions[0].key.line == 1284


def test_parse_hotspots_json_skips_entries_without_id() -> None:
    assert parse_hotspots_json({"code_regions": [{"typ": KIND_LOOP}]}, {}) == []
    assert parse_hotspots_json({}, {}) == []


def _write_hotspots_json(dot_dp: Path, data: Dict[str, Any]) -> None:
    target = dot_dp / "hotspot_detection"
    target.mkdir(parents=True, exist_ok=True)
    (target / "Hotspots.json").write_text(json.dumps(data))


def test_hotspots_available_for_explorer(tmp_path: Path) -> None:
    dot_dp = tmp_path / ".discopop"
    # no file at all
    assert not hotspots_available_for_explorer(str(dot_dp))

    _write_hotspots_json(dot_dp, _hotspots_json())
    assert hotspots_available_for_explorer(str(dot_dp))

    # MAYBE alone is enough -- the loader asks for YES and MAYBE
    _write_hotspots_json(dot_dp, {"code_regions": [{"csid": 1, "hotness": HOTNESS_MAYBE}]})
    assert hotspots_available_for_explorer(str(dot_dp))


def test_hotspots_available_for_explorer_ignores_cold_and_broken_files(tmp_path: Path) -> None:
    dot_dp = tmp_path / ".discopop"

    # everything cold: the loader keeps nothing, so this is as good as no results
    _write_hotspots_json(
        dot_dp,
        {"code_regions": [{"csid": 1, "hotness": HOTNESS_NO}, {"csid": 2, "hotness": HOTNESS_NO}]},
    )
    assert not hotspots_available_for_explorer(str(dot_dp))

    _write_hotspots_json(dot_dp, {"code_regions": []})
    assert not hotspots_available_for_explorer(str(dot_dp))

    # unreadable / unexpected content must not raise
    (dot_dp / "hotspot_detection" / "Hotspots.json").write_text("{ truncated")
    assert not hotspots_available_for_explorer(str(dot_dp))
    _write_hotspots_json(dot_dp, {"code_regions": "not-a-list"})
    assert not hotspots_available_for_explorer(str(dot_dp))


def test_quadrant_thresholds_match_the_analyzers_means() -> None:
    regions = parse_hotspots_json(_hotspots_json(), {})
    mean_avg, mean_ratio = quadrant_thresholds(regions)
    assert abs(mean_avg - (2.85 + 1.025 + 0.0305) / 3) < 1e-9
    assert abs(mean_ratio - (0.842 + 0.512 + 0.504) / 3) < 1e-9


def test_quadrant_thresholds_empty() -> None:
    assert quadrant_thresholds([]) == (0.0, 0.0)


def test_hotness_counts_covers_all_values() -> None:
    counts = hotness_counts(parse_hotspots_json(_hotspots_json(), {}))
    assert counts == {HOTNESS_YES: 1, HOTNESS_MAYBE: 1, HOTNESS_NO: 1}


def test_ratio_is_degenerate_for_a_single_run() -> None:
    """One run => min == max => ratio is exactly 0.5 for every region."""
    single_run = {
        "code_regions": [
            {"csid": 1, "runtimes": [2.0], "avr": 2.0, "minVal": 2.0, "maxVal": 2.0, "ratio": 0.5},
            {"csid": 2, "runtimes": [1.0], "avr": 1.0, "minVal": 1.0, "maxVal": 1.0, "ratio": 0.5},
        ]
    }
    assert ratio_is_degenerate(parse_hotspots_json(single_run, {}))
    assert not ratio_is_degenerate(parse_hotspots_json(_hotspots_json(), {}))
    assert ratio_is_degenerate([])


# ---------------------------------------------------------------------------
# the measurement-run sidecar
# ---------------------------------------------------------------------------


def test_log_round_trip() -> None:
    log = MeasurementLog(
        region_fingerprint="sha1:abc",
        instrumented_at="2026-07-31T10:01:44",
        compile_script="/p/.discopop/project/configs/compile.sh",
        runs=[
            MeasurementRun(index=0, config="small", timestamp="t0", time=3.4, code=0, regions={"a.cc:1:LOOP": 1.5}),
            MeasurementRun(index=1, config="medium", timestamp="t1", time=12.8, code=0),
        ],
    )
    restored = deserialize_log(serialize_log(log))
    assert restored.region_fingerprint == "sha1:abc"
    assert restored.compile_script is not None and restored.compile_script.endswith("compile.sh")
    assert [run.config for run in restored.runs] == ["small", "medium"]
    assert restored.runs[0].regions == {"a.cc:1:LOOP": 1.5}
    assert not restored.runs[0].is_external


def test_deserialize_log_sorts_and_skips_unusable_entries() -> None:
    log = deserialize_log({"runs": [{"run": 2}, {"config": "x"}, {"run": 0}, {"run": "nope"}]})
    assert [run.index for run in log.runs] == [0, 2]


def test_deserialize_log_empty() -> None:
    log = deserialize_log({})
    assert log.runs == [] and log.region_fingerprint is None


def test_merge_external_runs_synthesizes_unrecorded_indices() -> None:
    log = MeasurementLog(runs=[MeasurementRun(index=0, config="small")])
    # index 1 exists on disk but was produced outside the GUI; index 5 is recorded
    # but its file is gone, so it must not be reported.
    log.runs.append(MeasurementRun(index=5, config="stale"))
    merged = merge_external_runs(log, [0, 1])
    assert [run.index for run in merged] == [0, 1]
    assert merged[0].config == "small" and not merged[0].is_external
    assert merged[1].is_external


# ---------------------------------------------------------------------------
# the merged (cross-build) analyzer input
# ---------------------------------------------------------------------------


def test_region_key_serialize_round_trip() -> None:
    for key in (
        RegionKey(path="/p/a.cc", line=12, kind=KIND_LOOP),
        RegionKey(path="/p/a.cc", line=12, kind=KIND_FUNCTION, name="main"),
        # a Windows-style path and a C++ symbol both contain colons, so the split
        # cannot rely on a field count
        RegionKey(path="C:/p/a.cc", line=3, kind=KIND_FUNCTION, name="ns::f(int)"),
    ):
        assert RegionKey.deserialize(key.serialize()) == key


def test_region_key_deserialize_rejects_non_keys() -> None:
    assert RegionKey.deserialize("not a key") is None
    assert RegionKey.deserialize("/p/a.cc:notanumber:LOOP") is None
    assert RegionKey.deserialize("") is None


def test_invert_file_mapping_prefers_the_lowest_fid() -> None:
    # FileMapping.txt is appended to, so one path can hold several ids.
    assert invert_file_mapping({2: "/p/a.cc", 1: "/p/a.cc", 3: "/p/b.cc"}) == {"/p/a.cc": 1, "/p/b.cc": 3}


def test_canonical_region_keys_unions_runs_and_skips_junk() -> None:
    runs = [
        MeasurementRun(index=0, regions={"/p/b.cc:9:LOOP": 1.0, "/p/a.cc:1:LOOP": 2.0}),
        MeasurementRun(index=1, regions={"/p/a.cc:1:LOOP": 3.0, "/p/a.cc:5:FUNCTION:f": 4.0, "junk": 5.0}),
    ]
    keys = canonical_region_keys(runs)
    assert [key.serialize() for key in keys] == ["/p/a.cc:1:LOOP", "/p/a.cc:5:FUNCTION:f", "/p/b.cc:9:LOOP"]


def test_write_merged_analysis_input_builds_one_id_space(tmp_path: Path) -> None:
    """The same source region measured by two builds becomes one canonical id."""
    runs = [
        MeasurementRun(index=0, config="tiny", regions={"/p/a.cc:1:LOOP": 0.5, "/p/a.cc:7:FUNCTION:main": 1.0}),
        MeasurementRun(index=3, config="medium", regions={"/p/a.cc:1:LOOP": 9.0}),
    ]
    count = write_merged_analysis_input(runs, {2: "/p/a.cc"}, str(tmp_path))
    assert count == 2

    # cs_id.txt numbers from 1 and carries the real fid, so the explorer's
    # HostpotLoader resolves the region to the right file.
    assert (tmp_path / "cs_id.txt").read_text().splitlines() == ["1 loop 1 2", "2 func 7 2 main"]

    # Runs are renumbered contiguously from 0 in run order, regardless of the
    # sparse on-disk indices they came from.
    assert sorted(p.name for p in tmp_path.glob("hotspot_result_*.txt")) == [
        "hotspot_result_0.txt",
        "hotspot_result_1.txt",
    ]
    assert parse_hotspot_result((tmp_path / "hotspot_result_0.txt").read_text()) == {1: 0.5, 2: 1.0}
    # The region absent from the second run is omitted rather than written as 0.0:
    # the analyzer averages over the lines present, so omission means "not
    # measured" instead of a zero that would collapse min/max.
    assert parse_hotspot_result((tmp_path / "hotspot_result_1.txt").read_text()) == {1: 9.0}


def test_write_merged_analysis_input_keeps_unmapped_fid_and_clears_stale(tmp_path: Path) -> None:
    (tmp_path / "hotspot_result_7.txt").write_text("1 1.0\n")
    runs = [MeasurementRun(index=0, regions={"file_4:1:LOOP": 0.5})]
    write_merged_analysis_input(runs, {}, str(tmp_path))
    # resolve_keys' file_<fid> placeholder still yields the original fid
    assert (tmp_path / "cs_id.txt").read_text().splitlines() == ["1 loop 1 4"]
    # a leftover result file from a longer previous series must not be analyzed
    assert sorted(p.name for p in tmp_path.glob("hotspot_result_*.txt")) == ["hotspot_result_0.txt"]


# ---------------------------------------------------------------------------
# filesystem helpers
# ---------------------------------------------------------------------------


def test_result_file_indices(tmp_path: Path) -> None:
    for name in ("hotspot_result_0.txt", "hotspot_result_2.txt", "hotspot_result_x.txt", "cs_id.txt"):
        (tmp_path / name).write_text("")
    assert result_file_indices(str(tmp_path)) == [0, 2]
    assert result_file_indices(str(tmp_path / "missing")) == []


def test_load_json_file(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}))
    assert load_json_file(str(good)) == {"a": 1}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert load_json_file(str(broken)) is None

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[1, 2]")
    assert load_json_file(str(not_an_object)) is None

    assert load_json_file(str(tmp_path / "absent.json")) is None


def test_path_helpers_are_relative_to_dot_discopop() -> None:
    from discopop_library.ProjectManager.gui.plots.hotspot_data import (
        cs_id_path,
        hotspots_json_path,
        private_dir,
        sidecar_path,
    )

    dot_dp = os.path.join("proj", ".discopop")
    assert private_dir(dot_dp).endswith(os.path.join("hotspot_detection", "private"))
    assert cs_id_path(dot_dp).endswith(os.path.join("private", "cs_id.txt"))
    assert hotspots_json_path(dot_dp).endswith(os.path.join("hotspot_detection", "Hotspots.json"))
    assert sidecar_path(dot_dp).endswith(os.path.join("hotspot_detection", "measurement_runs.json"))
