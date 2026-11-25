# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Maps suggestions to the share of the program's runtime they parallelize.

Two inputs: the *extents* of the suggestions (file, first and last line, a loop's suggestion extended to the end
of the loop) and the region runtimes of ``hotspot_detection/Hotspots.json``.

The extents come from the explorer's detection result. Decoding ``detection_result_dump.json`` takes minutes and
many times its size in memory (gigabytes for a large program), so the explorer also writes the extents into the
small ``suggestion_extents.json`` next to the dump. It records the size and modification time of the dump it was
made from, which tell whether it is current. Readers that must stay responsive (the GUI) only use that file
(:func:`load_regions` without ``allow_decode``); a detection result of an older explorer is extracted once, in a
process of its own: ``python -m discopop_library.Amdahl.regions --extract-extents <.discopop>``.

The runtimes are read on every call, so new hotspot measurements never require the dump.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from discopop_library.Amdahl.model import SuggestionExtent, SuggestionRegion
from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    HotspotRegionInfo,
    hotspots_json_path,
    load_detailed_hotspots,
)
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType

EXTENTS_NAME = "suggestion_extents.json"
EXTENTS_FORMAT = 1
DUMP_NAME = "detection_result_dump.json"

EXTRACT_COMMAND_HINT = "python -m discopop_library.Amdahl.regions --extract-extents <.discopop directory>"


def dump_path_of(dot_dp: str) -> str:
    """The detection result dump the explorer writes by default."""
    return os.path.join(dot_dp, "explorer", DUMP_NAME)


def extents_path_of(dump_path: str) -> str:
    """The extents file belonging to the dump ``dump_path`` (next to it)."""
    return os.path.join(os.path.dirname(os.path.abspath(dump_path)), EXTENTS_NAME)


# ── the regions ──────────────────────────────────────────────────────────────


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


def suggestion_extents(detection_result: Any) -> Dict[int, SuggestionExtent]:
    """The source range of every suggestion of ``detection_result``: a suggestion on a loop reaches to the end of
    the longest loop starting at its first line."""
    # imported here: the library must not import the explorer when it is loaded
    from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
    from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

    loops: Dict[str, Any] = {}
    pet = getattr(detection_result, "pet", None)
    if pet is not None:
        for node in all_nodes(pet, LoopNode):
            key = str(node.start_position())
            previous = loops.get(key)
            if previous is None or _span(node) > _span(previous):
                loops[key] = node

    result: Dict[int, SuggestionExtent] = {}
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
            result[int(pattern.pattern_id)] = SuggestionExtent(int(pattern.pattern_id), file_id, start, end)
    return result


def regions_from_extents(
    extents: Dict[int, SuggestionExtent], hotspots: Sequence[HotspotRegionInfo]
) -> Dict[int, SuggestionRegion]:
    """Region and runtime share of every suggestion of ``extents``; the share is None if no hotspot region starts
    where the suggestion does (or there are no hotspot results)."""
    total = program_runtime(hotspots)
    result: Dict[int, SuggestionRegion] = {}
    for suggestion_id, extent in extents.items():
        hotspot = _hotspot_at(hotspots, extent.file_id, extent.start_line)
        share = None
        if hotspot is not None and total is not None:
            share = min(1.0, hotspot.max_val / total)
        result[suggestion_id] = SuggestionRegion(
            suggestion_id, extent.file_id, extent.start_line, extent.end_line, share
        )
    return result


def build_regions(detection_result: Any, hotspots: Sequence[HotspotRegionInfo]) -> Dict[int, SuggestionRegion]:
    """Region and runtime share of every suggestion of ``detection_result``."""
    return regions_from_extents(suggestion_extents(detection_result), hotspots)


def _span(node: Any) -> int:
    return int(str(node.end_position()).split(":")[1]) - int(str(node.start_position()).split(":")[1])


# ── the extents file ─────────────────────────────────────────────────────────


def _file_identity(path: str) -> Optional[Tuple[int, int]]:
    """``(size, mtime_ns)`` of ``path``; None if it does not exist."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def write_suggestion_extents(dump_path: str, extents: Dict[int, SuggestionExtent]) -> str:
    """Write ``extents`` (made from the dump ``dump_path``, which must exist) next to the dump; returns the path.

    The file records the size and modification time of the dump: it is current only as long as they match.
    """
    identity = _file_identity(dump_path)
    if identity is None:
        raise FileNotFoundError(dump_path)
    path = extents_path_of(dump_path)
    content = {
        "format": EXTENTS_FORMAT,
        "dump": {"size": identity[0], "mtime_ns": identity[1]},
        "extents": {str(k): [e.file_id, e.start_line, e.end_line] for k, e in sorted(extents.items())},
    }
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(content, f)
    os.replace(temporary, path)
    return path


def read_suggestion_extents(dump_path: str) -> Optional[Dict[int, SuggestionExtent]]:
    """The extents belonging to the dump ``dump_path``; None if there is no extents file, it is unreadable, or it
    was made from another dump (or another version of it)."""
    identity = _file_identity(dump_path)
    if identity is None:
        return None
    try:
        with open(extents_path_of(dump_path), "r") as f:
            content = json.load(f)
        if content.get("format") != EXTENTS_FORMAT:
            return None
        dump = content["dump"]
        if (int(dump["size"]), int(dump["mtime_ns"])) != identity:
            return None
        return {
            int(k): SuggestionExtent(int(k), int(v[0]), int(v[1]), int(v[2])) for k, v in content["extents"].items()
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def needs_extraction(dot_dp: str) -> bool:
    """Whether there is a detection result dump without current extents (it was written by an older explorer)."""
    dump_path = dump_path_of(dot_dp)
    return os.path.exists(dump_path) and read_suggestion_extents(dump_path) is None


def extract_suggestion_extents(dot_dp: str) -> Dict[int, SuggestionExtent]:
    """Decode the detection result dump of ``dot_dp`` and write its extents file. Slow and memory hungry (the
    detection result is decoded, without the callpath tree of the PET, which the extents do not need, see
    ``result_classes/loading.py``): run it in a process of its own, never in the GUI."""
    from discopop_library.result_classes.loading import load_detection_result

    dump_path = dump_path_of(dot_dp)
    detection_result = load_detection_result(dump_path)
    extents = suggestion_extents(detection_result)
    write_suggestion_extents(dump_path, extents)
    return extents


# ── loading ──────────────────────────────────────────────────────────────────

# the parsed Hotspots.json of the last call, by (path, size, mtime_ns)
_hotspots_cache: Dict[Tuple[str, int, int], List[HotspotRegionInfo]] = {}


def _hotspots_of(dot_dp: str) -> List[HotspotRegionInfo]:
    path = os.path.abspath(hotspots_json_path(dot_dp))
    identity = _file_identity(path)
    if identity is None:
        return []
    key = (path, identity[0], identity[1])
    cached = _hotspots_cache.get(key)
    if cached is None:
        cached = load_detailed_hotspots(dot_dp)
        _hotspots_cache.clear()
        _hotspots_cache[key] = cached
    return cached


def regions_stamp(dot_dp: str) -> Tuple[Optional[Tuple[int, int]], ...]:
    """Changes whenever :func:`load_regions` may return something else (the dump, its extents file, the hotspot
    results): a key for callers that cache what they derive from the regions."""
    dump_path = dump_path_of(dot_dp)
    return (
        _file_identity(dump_path),
        _file_identity(extents_path_of(dump_path)),
        _file_identity(hotspots_json_path(dot_dp)),
    )


def load_regions(dot_dp: str, allow_decode: bool = False) -> Dict[int, SuggestionRegion]:
    """Suggestion regions of a ``.discopop`` folder.

    Returns an empty dict when there is no explorer result, and regions without a ``time_share`` when there is no
    hotspot result: callers then get no ceiling. Without current extents (a detection result of an older
    explorer), the result is empty too, unless ``allow_decode``: then the dump is decoded once and its extents are
    written (slow, memory hungry: not in the GUI process, see :func:`needs_extraction`).
    """
    dump_path = dump_path_of(dot_dp)
    if not os.path.exists(dump_path):
        return {}
    extents = read_suggestion_extents(dump_path)
    if extents is None:
        if not allow_decode:
            return {}
        extents = extract_suggestion_extents(dot_dp)
    return regions_from_extents(extents, _hotspots_of(dot_dp))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m discopop_library.Amdahl.regions",
        description="Write the suggestion extents (needed for the Amdahl ceilings) of an existing detection result.",
    )
    parser.add_argument(
        "--extract-extents",
        metavar="DOT_DISCOPOP",
        required=True,
        help="the .discopop directory whose explorer/" + DUMP_NAME + " is decoded",
    )
    arguments = parser.parse_args(argv)
    dot_dp = arguments.extract_extents
    if not os.path.exists(dump_path_of(dot_dp)):
        print("No detection result: " + dump_path_of(dot_dp) + " does not exist.", file=sys.stderr)
        return 1
    print("Decoding " + dump_path_of(dot_dp) + " ...", flush=True)
    extents = extract_suggestion_extents(dot_dp)
    print("Wrote the extents of " + str(len(extents)) + " suggestions to " + extents_path_of(dump_path_of(dot_dp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
