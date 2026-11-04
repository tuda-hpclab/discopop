# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Maps suggestions to the share of the program's runtime they parallelize.

Built from the explorer's ``detection_result_dump.json`` (suggestion positions, loop
extents) and ``hotspot_detection/Hotspots.json`` (region runtimes). The result is cached
next to the explorer output, because decoding the dump is slow and the GUI asks again for
every report refresh; the cache is keyed by the modification times of both sources.
"""

import json
import os
from typing import Any, Dict, Optional, Sequence

from discopop_library.Amdahl.model import SuggestionRegion
from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    HotspotRegionInfo,
    hotspots_json_path,
    load_detailed_hotspots,
)
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType

CACHE_NAME = "amdahl_regions.json"


def program_runtime(hotspots: Sequence[HotspotRegionInfo]) -> Optional[float]:
    """Runtime of the whole program: ``main``'s longest run, else the longest region."""
    mains = [h.max_val for h in hotspots if h.node_type == HotspotNodeType.FUNCTION and h.name == "main"]
    candidates = mains if mains else [h.max_val for h in hotspots]
    best = max(candidates, default=0.0)
    return best if best > 0 else None


def _hotspot_at(hotspots: Sequence[HotspotRegionInfo], file_id: int, line: int) -> Optional[HotspotRegionInfo]:
    matches = [h for h in hotspots if h.file_id == file_id and h.start_line == line]
    if not matches:
        return None
    # prefer loops (suggestions mostly sit on loops), then the longest-running entry
    matches.sort(key=lambda h: (h.node_type != HotspotNodeType.LOOP, -h.max_val))
    return matches[0]


def build_regions(detection_result: Any, hotspots: Sequence[HotspotRegionInfo]) -> Dict[int, SuggestionRegion]:
    """Region and runtime share of every suggestion of ``detection_result``."""
    from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
    from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

    total = program_runtime(hotspots)
    loops: Dict[str, Any] = {}
    pet = getattr(detection_result, "pet", None)
    if pet is not None:
        for node in all_nodes(pet, LoopNode):
            key = str(node.start_position())
            previous = loops.get(key)
            if previous is None or _span(node) > _span(previous):
                loops[key] = node

    result: Dict[int, SuggestionRegion] = {}
    for pattern_type in sorted(detection_result.patterns.__dict__):
        for pattern in detection_result.patterns.__dict__[pattern_type]:
            try:
                file_id = int(str(pattern.start_line).split(":")[0])
                start = int(str(pattern.start_line).split(":")[1])
                end = int(str(pattern.end_line).split(":")[1])
            except (IndexError, ValueError):
                continue
            loop = loops.get(str(pattern.start_line))
            if loop is not None:
                end = max(end, int(str(loop.end_position()).split(":")[1]))
            hotspot = _hotspot_at(hotspots, file_id, start)
            share = None
            if hotspot is not None and total is not None:
                share = min(1.0, hotspot.max_val / total)
            result[int(pattern.pattern_id)] = SuggestionRegion(int(pattern.pattern_id), file_id, start, end, share)
    return result


def _span(node: Any) -> int:
    return int(str(node.end_position()).split(":")[1]) - int(str(node.start_position()).split(":")[1])


def _source_stamp(dot_dp: str) -> Dict[str, Optional[float]]:
    paths = {
        "detection_result": os.path.join(dot_dp, "explorer", "detection_result_dump.json"),
        "hotspots": hotspots_json_path(dot_dp),
    }
    return {k: (os.path.getmtime(p) if os.path.exists(p) else None) for k, p in paths.items()}


def load_regions(dot_dp: str) -> Dict[int, SuggestionRegion]:
    """Suggestion regions of a ``.discopop`` folder, from cache when current.

    Returns an empty dict when there is no explorer result, and regions without a
    ``time_share`` when there is no hotspot result: callers then get no ceiling.
    """
    dump_path = os.path.join(dot_dp, "explorer", "detection_result_dump.json")
    if not os.path.exists(dump_path):
        return {}
    stamp = _source_stamp(dot_dp)
    cache_path = os.path.join(dot_dp, "explorer", CACHE_NAME)
    try:
        with open(cache_path, "r") as f:
            cached = json.load(f)
        if cached.get("stamp") == stamp:
            return {int(k): SuggestionRegion(**v) for k, v in cached["regions"].items()}
    except (OSError, ValueError, TypeError, KeyError):
        pass

    import jsonpickle  # type: ignore

    with open(dump_path, "r") as f:
        detection_result = jsonpickle.decode(f.read(), keys=True)
    regions = build_regions(detection_result, load_detailed_hotspots(dot_dp))
    try:
        with open(cache_path, "w") as f:
            json.dump(
                {"stamp": stamp, "regions": {str(k): v.__dict__ for k, v in regions.items()}},
                f,
            )
    except OSError:
        pass  # read-only project: just recompute next time
    return regions
