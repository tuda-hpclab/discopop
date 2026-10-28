# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""How the tools phrase hotspots: one wording and one runtime format everywhere."""

from pathlib import Path
from typing import Optional

from discopop_library.HostpotLoader.detailed_hotspot_loader import HotspotRegionInfo
from discopop_library.HostpotLoader.HotspotType import HotspotType


def total_runtime(regions: list[HotspotRegionInfo]) -> float:
    """The runtime of the whole program in its longest profiled run.

    Runtimes are inclusive, so the outermost region (main) is the longest one.
    """
    return max((region.max_val for region in regions), default=0.0)


def hotspot_prefix(region: Optional[HotspotRegionInfo]) -> str:
    """'Hotspot ' or 'Potential Hotspot ' in front of a region's description, '' for any other region."""
    if region is None:
        return ""
    if region.hotness == HotspotType.YES:
        return "Hotspot "
    if region.hotness == HotspotType.MAYBE:
        return "Potential Hotspot "
    return ""


def runtime_text(region: HotspotRegionInfo, total: float) -> str:
    """'3.90 s, 99% of runtime': the longest measured runtime of a region and its share of the program's."""
    share = f", {round(100 * region.max_val / total)}% of runtime" if total > 0 else ""
    return f"{region.max_val:.2f} s{share}"


def display_path(project_path: str, path: Optional[Path]) -> str:
    """A source file as the tools show it: relative to the project when it lies in it."""
    if path is None:
        return "<unknown file>"
    try:
        return str(path.resolve().relative_to(Path(project_path).resolve()))
    except ValueError:
        return str(path)


def resolve_source_path(project_path: str, file_path: str) -> Path:
    """The file a caller named: absolute, or relative to the project."""
    path = Path(file_path)
    return (path if path.is_absolute() else Path(project_path) / path).resolve()
