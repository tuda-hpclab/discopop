# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List

from discopop_library.ProjectManager.gui.plots import mode_style
from discopop_library.ProjectManager.gui.plots.hotspot_charts import (
    HOTNESS_COLORS,
    format_region_tooltip,
    hotness_color,
    kind_marker,
    top_regions,
)
from discopop_library.ProjectManager.gui.plots.hotspot_data import (
    HOTNESS_MAYBE,
    HOTNESS_NO,
    HOTNESS_YES,
    KIND_FUNCTION,
    KIND_LOOP,
    HotspotRegion,
    RegionKey,
)


def _region(csid: int, avg: float, hotness: str, kind: str = KIND_LOOP, name: str = "") -> HotspotRegion:
    return HotspotRegion(
        key=RegionKey(path="/proj/lulesh.cc", line=1000 + csid, kind=kind, name=name),
        csid=csid,
        runtimes=[avg * 0.5, avg * 1.5],
        avg=avg,
        minimum=avg * 0.5,
        maximum=avg * 1.5,
        ratio=0.6,
        hotness=hotness,
        share=0.25,
    )


def _regions() -> List[HotspotRegion]:
    return [
        _region(1, 4.8, HOTNESS_YES),
        _region(2, 2.0, HOTNESS_YES, kind=KIND_FUNCTION, name="CalcHourglass"),
        _region(3, 1.2, HOTNESS_MAYBE),
        _region(4, 0.03, HOTNESS_NO),
    ]


def test_hotness_color_uses_reserved_status_palette() -> None:
    assert hotness_color(HOTNESS_YES) == mode_style.STATUS_COLORS["valid"]
    assert hotness_color(HOTNESS_MAYBE) == mode_style.STATUS_COLORS["invalid"]
    # NO is deliberately the neutral reference grey, not a series colour
    assert hotness_color(HOTNESS_NO) == mode_style.REFERENCE_COLOR
    assert hotness_color("something else") == mode_style.REFERENCE_COLOR


def test_hotness_colors_are_distinct() -> None:
    assert len(set(HOTNESS_COLORS.values())) == len(HOTNESS_COLORS)


def test_kind_marker() -> None:
    assert kind_marker(KIND_LOOP) != kind_marker(KIND_FUNCTION)
    assert kind_marker("unknown") == kind_marker(KIND_LOOP)


def test_top_regions_orders_by_avg_and_truncates() -> None:
    selected = top_regions(_regions(), 2)
    assert [region.csid for region in selected] == [1, 2]


def test_top_regions_handles_small_and_degenerate_counts() -> None:
    assert len(top_regions(_regions(), 99)) == 4
    # never return an empty chart for a nonsensical count
    assert len(top_regions(_regions(), 0)) == 1
    assert top_regions([], 10) == []


def test_format_region_tooltip_contains_the_decisive_fields() -> None:
    text = format_region_tooltip(_region(2, 2.0, HOTNESS_MAYBE, kind=KIND_FUNCTION, name="CalcHourglass"))
    assert "CalcHourglass" in text
    assert "lulesh.cc:1002" in text
    assert HOTNESS_MAYBE in text
    assert "Ratio" in text and "Runs: 2" in text
