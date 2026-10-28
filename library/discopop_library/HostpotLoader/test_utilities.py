# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""get_patterns_by_hotspot_type: the class the explorer attached to a pattern is used before the loop rule."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type


def _pattern(pattern_id: int, first: int, last: int, **attached: Any) -> Any:
    attached.setdefault("applicable_pattern", True)
    attached.setdefault("standalone_pattern", True)
    return SimpleNamespace(pattern_id=pattern_id, start_line=f"1:{first}", end_line=f"1:{last}", **attached)


def _result(*patterns: Any) -> Any:
    storage = SimpleNamespace(
        get_pattern_ids=lambda: [p.pattern_id for p in patterns],
        get_pattern_from_id=lambda i: next(p for p in patterns if p.pattern_id == i),
    )
    return SimpleNamespace(patterns=storage)


_LOOP_HOTSPOTS: Dict[HotspotType, List[Any]] = {HotspotType.YES: [(1, 10, HotspotNodeType.LOOP, "", 1.0)]}


def _classify(*patterns: Any, hotspots: Optional[Dict[HotspotType, List[Any]]] = None) -> Dict[HotspotType, List[int]]:
    return get_patterns_by_hotspot_type(_result(*patterns), _LOOP_HOTSPOTS if hotspots is None else hotspots)


def test_the_attached_class_is_used_for_a_pattern_without_a_loop_hotspot() -> None:
    recursive_group = _pattern(1, 30, 31, hotspot_type=HotspotType.YES)
    assert _classify(recursive_group)[HotspotType.YES] == [1]


def test_the_attached_class_takes_precedence_over_the_loop_rule() -> None:
    pattern = _pattern(1, 5, 15, hotspot_type=HotspotType.MAYBE)  # the lines contain a YES loop
    result = _classify(pattern)
    assert result[HotspotType.MAYBE] == [1] and result[HotspotType.YES] == []


def test_a_pattern_without_attached_class_follows_the_loop_rule() -> None:
    assert _classify(_pattern(1, 5, 15), _pattern(2, 20, 25))[HotspotType.YES] == [1]
    assert _classify(_pattern(1, 5, 15, hotspot_type=None))[HotspotType.YES] == [1]


def test_without_hotspot_information_every_pattern_is_considered() -> None:
    result = get_patterns_by_hotspot_type(
        _result(_pattern(1, 1, 2), _pattern(2, 3, 4, hotspot_type=HotspotType.NO)), {}
    )
    assert result[HotspotType.YES] == [1, 2]


def test_a_pattern_without_a_patch_of_its_own_is_no_candidate() -> None:
    # the tasks of a parallel region are applied by the region's patch only
    region = _pattern(1, 30, 31, hotspot_type=HotspotType.YES)
    task = _pattern(2, 30, 31, hotspot_type=HotspotType.YES, applicable_pattern=False, standalone_pattern=False)
    merged_doall = _pattern(3, 5, 15, standalone_pattern=False)
    result = _classify(region, task, merged_doall)
    assert result == {HotspotType.YES: [1], HotspotType.NO: [], HotspotType.MAYBE: []}
    without_hotspots = get_patterns_by_hotspot_type(_result(region, task, merged_doall), {})
    assert without_hotspots[HotspotType.YES] == [1]
