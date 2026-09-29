# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Full-fidelity access to ``Hotspots.json``.

``hostpot_loader.run()`` collapses every code region to
``(fid, lineNum, HotspotNodeType, name, avr)`` and thus drops the per-run
``runtimes`` list, ``maxVal`` and the scaling indicator ``ratio``. Algorithms that
want to *rank* regions rather than only classify them need those fields, so this
module parses the same file into a dataclass without losing anything.

The loader is deliberately independent of
``ProjectManager.gui.plots.hotspot_data``, which keys regions by ``RegionKey``
resolved against ``hotspot_detection/merged/cs_id.txt``; that coupling would drag
the GUI's merge bookkeeping into every consumer.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType, get_HotspotNodeType_from_string
from discopop_library.HostpotLoader.HotspotType import HotspotType, get_HotspotType_from_string

# ``ratio`` is 1 / ((minVal / maxVal) + 1), so it is exactly 0.5 iff minVal == maxVal,
# i.e. iff the region shows no runtime change across the profiling runs.
NEUTRAL_RATIO = 0.5


@dataclass
class HotspotRegionInfo:
    """One entry of ``Hotspots.json``, with every field preserved."""

    csid: int
    node_type: HotspotNodeType
    file_id: int
    start_line: int
    name: str
    hotness: HotspotType
    runtimes: List[float] = field(default_factory=list)
    avr: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    ratio: float = NEUTRAL_RATIO
    top_avr: bool = False
    top_ratio: bool = False


def hotspots_json_path(dot_discopop_path: str) -> str:
    """Path of the hotspot analyzer's result file below the given .discopop folder."""
    return os.path.join(dot_discopop_path, "hotspot_detection", "Hotspots.json")


def load_detailed_hotspots(dot_discopop_path: str) -> List[HotspotRegionInfo]:
    """Load every code region of ``Hotspots.json``, unfiltered.

    Returns an empty list when no hotspot detection results exist, mirroring
    ``hostpot_loader.run()``. Reporting that as an error is left to the caller,
    which knows whether hotspot data is optional or mandatory for it.
    """
    path = hotspots_json_path(dot_discopop_path if len(dot_discopop_path) > 0 else os.getcwd())
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        contents = json.load(f)

    regions: List[HotspotRegionInfo] = []
    # Iterate over every top-level list, not only "code_regions", to stay compatible
    # with the tolerant behaviour of hostpot_loader.run().
    for key in contents:
        for entry in contents[key]:
            regions.append(__parse_region(entry))
    return regions


def __parse_region(entry: Dict[str, Any]) -> HotspotRegionInfo:
    # Older result files omit the derived flags, so fall back instead of raising:
    # a missing topAvr/topRatio only affects logging, never the classification,
    # which is already baked into "hotness".
    runtimes = [float(runtime) for runtime in entry.get("runtimes", [])]
    return HotspotRegionInfo(
        csid=int(entry["csid"]),
        node_type=get_HotspotNodeType_from_string(entry["typ"]),
        file_id=int(entry["fid"]),
        start_line=int(entry["lineNum"]),
        name=entry["name"],
        hotness=get_HotspotType_from_string(entry["hotness"]),
        runtimes=runtimes,
        avr=float(entry["avr"]),
        min_val=float(entry.get("minVal", min(runtimes) if runtimes else 0.0)),
        max_val=float(entry.get("maxVal", max(runtimes) if runtimes else 0.0)),
        ratio=float(entry.get("ratio", NEUTRAL_RATIO)),
        top_avr=bool(entry.get("topAvr", False)),
        top_ratio=bool(entry.get("topRatio", False)),
    )


def hotspots_are_degenerate(regions: Sequence[HotspotRegionInfo]) -> bool:
    """True if the scaling ratio carries no information.

    That is the case when the project was profiled with a single input: every
    region then has minVal == maxVal and thus ratio == 0.5. Since the analyzer
    derives ``topRatio`` from ``ratio >= mean(ratio)``, all regions pass that test
    and the YES/MAYBE/NO classification degenerates to a single threshold on the
    average runtime. Callers should say so rather than pretend to rank by scaling.
    """
    if not regions:
        return True
    return all(region.ratio == NEUTRAL_RATIO for region in regions)
