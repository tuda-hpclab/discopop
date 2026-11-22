# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from pathlib import Path
from typing import List

import pytest

from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import HotspotRegion, MeasurementRun, RegionKey
from discopop_library.ProjectManager.services import hotspot_view
from discopop_library.ProjectManager.services.hotspot_build import BUILD_CURRENT, BUILD_MISMATCH, BUILD_NONE
from discopop_library.ProjectManager.services.hotspot_view import next_sort, visible_regions


def region(line: int, kind: str, name: str, avg: float, hotness: str, runtimes: List[float]) -> HotspotRegion:
    key = RegionKey("/p/a.cpp", line, kind, name)
    return HotspotRegion(key, line, runtimes, avg, min(runtimes), max(runtimes), 0.5, hotness, share=avg / 4)


REGIONS = [
    region(1, hotspot_data.KIND_LOOP, "", 3.0, "YES", [1.0, 5.0]),
    region(2, hotspot_data.KIND_FUNCTION, "Zed", 1.0, "NO", [1.0]),
]


def test_next_sort_is_descending_first_then_ascending() -> None:
    first = next_sort(None, "Avg (s)")
    assert first == ("Avg (s)", True)
    assert next_sort(first, "Avg (s)") == ("Avg (s)", False)
    assert next_sort(first, "Kind") == ("Kind", True)


def test_visible_regions_filters_and_sorts() -> None:
    assert visible_regions(REGIONS) == REGIONS
    assert visible_regions(REGIONS, {"NO"}) == [REGIONS[1]]
    assert visible_regions(REGIONS, None, hotspot_data.KIND_LOOP) == [REGIONS[0]]
    assert visible_regions(REGIONS, None, "all", ("Avg (s)", False)) == [REGIONS[1], REGIONS[0]]
    assert visible_regions(REGIONS, None, "all", ("Unknown", True)) == REGIONS


def test_rows_and_details() -> None:
    assert hotspot_view.region_row(REGIONS[1])[:4] == ("● NO", hotspot_data.KIND_FUNCTION, "a.cpp:2", "Zed")
    assert hotspot_view.region_row(REGIONS[0])[3] == "-"
    fields = dict(hotspot_view.region_detail_fields(REGIONS[1]))
    assert fields["Runs measured"] == "1" and "Only one run" in fields["Note"]
    assert "Note" not in dict(hotspot_view.region_detail_fields(REGIONS[0]))
    assert hotspot_view.region_choice_label(REGIONS[0]) == "a.cpp:1  (3.0000s, YES)"

    ok, failed, external = (
        MeasurementRun(0, "c", "t", 1.5, 0, {"x": 1.0}),
        MeasurementRun(1, "c", None, None, 2),
        MeasurementRun(2),
    )
    assert hotspot_view.run_row(ok) == ("0", "c", "t", "1.500", "✓ ok", "1")
    assert hotspot_view.run_row(failed) == ("1", "c", "—", "—", "✗ code 2", "—")
    assert hotspot_view.run_row(external)[1:] == ("(external)", "—", "—", "—", "—")
    assert [hotspot_view.run_failed(run) for run in (ok, failed, external)] == [False, True, False]


@pytest.mark.parametrize(
    "state, runs, regions, warnings",
    [
        (BUILD_NONE, [], [], 0),
        (BUILD_CURRENT, [MeasurementRun(0, "c")], REGIONS, 1),
        (BUILD_MISMATCH, [MeasurementRun(0, "c")], REGIONS, 2),
        (BUILD_MISMATCH, [MeasurementRun(0, "c"), MeasurementRun(1)], REGIONS, 1),
    ],
)
def test_the_summary_warns_about_one_run_and_a_stale_build(
    state: str, runs: List[MeasurementRun], regions: List[HotspotRegion], warnings: int
) -> None:
    summary = hotspot_view.measurement_summary(state, "sources changed", runs, regions)
    assert len(summary.warnings) == warnings and summary.build_ok == (state == BUILD_CURRENT)
    assert summary.has_regions == bool(regions)


def test_the_summary_counts_regions_and_external_runs(tmp_path: Path) -> None:
    summary = hotspot_view.measurement_summary(BUILD_CURRENT, "", [MeasurementRun(0), MeasurementRun(1, "c")], REGIONS)
    assert summary.runs_text == "Accumulated runs: 2 (1 external)"
    assert summary.hotness_text == "Code regions: 2   YES 1 / MAYBE 0 / NO 1"


@pytest.mark.parametrize(
    "seconds, text",
    [
        (None, "—"),
        (float("nan"), "—"),
        (0.0, "0 s"),
        (0.000609, "609 µs"),
        (0.0000123, "12.3 µs"),
        (0.0123456, "12.3 ms"),
        (1.2, "1.20 s"),
        (123.456, "123 s"),
        (4567.0, "4567 s"),
    ],
)
def test_durations_have_three_significant_digits_and_a_unit(seconds: float, text: str) -> None:
    assert hotspot_view.format_duration(seconds) == text


def test_region_cells_are_readable() -> None:
    cells = hotspot_view.region_cells(REGIONS[0])
    assert cells == (
        "● YES",
        hotspot_data.KIND_LOOP,
        "a.cpp:1",
        "—",
        "3.00 s",
        "75 %",
        "1.00 s",
        "5.00 s",
        "0.500",
        "2",
    )
    assert len(cells) == len(hotspot_view.REGION_HEADERS) == len(hotspot_view.REGION_COLUMNS)


def test_the_status_is_one_short_text_with_the_explanation_as_detail() -> None:
    one = [MeasurementRun(0, "c")]
    two = [MeasurementRun(0, "c"), MeasurementRun(1, "c")]
    status = hotspot_view.measurement_status(BUILD_NONE, "", [], [])
    assert (status.level, status.text) == (hotspot_view.LEVEL_IDLE, "No measurement yet") and status.detail
    assert status.facts == "Accumulated runs: 0 · Code regions: no analysis results yet"
    status = hotspot_view.measurement_status(BUILD_CURRENT, "", one, REGIONS)
    assert (status.level, status.text) == (hotspot_view.LEVEL_WARN, "Only one run")
    assert "every ratio is 0.5" in status.detail and status.facts.endswith("Code regions: 2 (YES 1 / MAYBE 0 / NO 1)")
    status = hotspot_view.measurement_status(BUILD_CURRENT, "", two, REGIONS)
    assert (status.level, status.text, status.detail) == (hotspot_view.LEVEL_OK, "Up to date", "")
    status = hotspot_view.measurement_status(BUILD_MISMATCH, "Sources changed.", one, REGIONS)
    assert (status.level, status.text) == (hotspot_view.LEVEL_WARN, "Build stale — will be recompiled")
    assert (
        status.detail.startswith("Sources changed. The 1 recorded run(s) are kept") and "ratio is 0.5" in status.detail
    )
