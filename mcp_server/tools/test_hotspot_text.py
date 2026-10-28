# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

import pytest

from discopop_library.HostpotLoader.detailed_hotspot_loader import HotspotRegionInfo
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from mcp_server.tools.hotspot_text import (
    display_path,
    hotspot_prefix,
    resolve_source_path,
    runtime_text,
    total_runtime,
)


def _region(hotness: HotspotType, longest: float) -> HotspotRegionInfo:
    return HotspotRegionInfo(1, HotspotNodeType.LOOP, 1, 5, "", hotness, [longest], longest, longest, longest)


@pytest.mark.parametrize(
    "hotness, prefix",
    [(HotspotType.YES, "Hotspot "), (HotspotType.MAYBE, "Potential Hotspot "), (HotspotType.NO, "")],
)
def test_the_prefix_names_the_class(hotness: HotspotType, prefix: str) -> None:
    assert hotspot_prefix(_region(hotness, 1.0)) == prefix


def test_a_region_without_hotspot_data_has_no_prefix() -> None:
    assert hotspot_prefix(None) == ""


def test_the_runtime_is_given_with_its_share_of_the_program() -> None:
    regions = [_region(HotspotType.YES, 3.9), _region(HotspotType.NO, 4.0)]
    assert total_runtime(regions) == 4.0
    assert runtime_text(regions[0], 4.0) == "3.90 s, 98% of runtime"


def test_without_a_total_only_the_runtime_is_given() -> None:
    assert total_runtime([]) == 0.0
    assert runtime_text(_region(HotspotType.NO, 0.0), 0.0) == "0.00 s"


def test_paths_inside_the_project_are_shown_relative_to_it(tmp_path: Path) -> None:
    assert display_path(str(tmp_path), tmp_path / "src" / "a.cpp") == str(Path("src") / "a.cpp")
    assert display_path(str(tmp_path), Path("/elsewhere/a.cpp")) == "/elsewhere/a.cpp"
    assert display_path(str(tmp_path), None) == "<unknown file>"


def test_relative_source_paths_are_taken_relative_to_the_project(tmp_path: Path) -> None:
    assert resolve_source_path(str(tmp_path), "src/a.cpp") == (tmp_path / "src" / "a.cpp").resolve()
    assert resolve_source_path(str(tmp_path), "/abs/a.cpp") == Path("/abs/a.cpp")
