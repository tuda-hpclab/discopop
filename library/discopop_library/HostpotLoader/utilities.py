# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import AVERAGE_RUNTIME, FILEID, NAME, STARTLINE


from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    # only for the annotation: importing it loads the explorer (and with it the Tk GUI's classes), which the
    # toolkit-free services of the ProjectManager GUI (services/suggestions.py) must not do
    from discopop_library.result_classes.DetectionResult import DetectionResult


def applicable_on_its_own(pattern: Any) -> bool:
    """Whether the pattern can be applied by itself, i.e. whether the patch generator creates a patch for it.
    A pattern that is not, e.g. a task of a parallel region, is applied as part of the pattern containing it."""
    return bool(pattern.applicable_pattern and pattern.standalone_pattern)


HotspotInformation = Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]]

# the order in which a code region is matched against the hotspot loops: the first class with a loop in the region wins
LOOP_MATCH_ORDER = (HotspotType.YES, HotspotType.NO, HotspotType.MAYBE)


def hotspot_loops(hotspot_information: HotspotInformation) -> Dict[HotspotType, List[Tuple[FILEID, STARTLINE]]]:
    """The locations of the hotspot loops by class."""
    loops: Dict[HotspotType, List[Tuple[FILEID, STARTLINE]]] = {t: [] for t in LOOP_MATCH_ORDER}
    for hotspot_type in LOOP_MATCH_ORDER:
        for entry in hotspot_information.get(hotspot_type, []):
            if entry[2] == HotspotNodeType.LOOP:
                loops[hotspot_type].append((entry[0], entry[1]))
    return loops


def classify_by_loops(
    file_id: int, start_line: int, end_line: int, loops: Dict[HotspotType, List[Tuple[FILEID, STARTLINE]]]
) -> Optional[HotspotType]:
    """The class of the code region file_id:start_line-end_line by the hotspot loops starting in it (see
    LOOP_MATCH_ORDER); None if no hotspot loop starts in it. The rule get_patterns_by_hotspot_type applies to
    patterns, shared with the blocker resolution, which classifies the unsure suggestions by it."""
    for hotspot_type in LOOP_MATCH_ORDER:
        for loop_file_id, loop_line in loops.get(hotspot_type, []):
            if file_id == loop_file_id and start_line <= loop_line <= end_line:
                return hotspot_type
    return None


def get_patterns_by_hotspot_type(
    detection_result: "DetectionResult",
    hotspot_information: HotspotInformation,
) -> Dict[HotspotType, List[int]]:
    loops = hotspot_loops(hotspot_information)

    pattern_ids = detection_result.patterns.get_pattern_ids()

    result_dict: Dict[HotspotType, List[int]] = {HotspotType.YES: [], HotspotType.NO: [], HotspotType.MAYBE: []}

    for pattern_id in pattern_ids:
        pattern = detection_result.patterns.get_pattern_from_id(pattern_id)
        if not applicable_on_its_own(pattern):
            # no candidate: it has no patch of its own
            continue
        start_line = int(pattern.start_line.split(":")[1])
        end_line = int(pattern.end_line.split(":")[1])
        file_id = int(pattern.start_line.split(":")[0])

        attached = getattr(pattern, "hotspot_type", None)
        if hotspot_information and attached is not None:
            # the explorer classified the pattern by its contents (task and parallel_region patterns: the hotspot
            # loops in the region and the hotspot functions its tasks call, see design/task_suggestions.md, 3.9)
            result_dict[HotspotType(attached)].append(pattern_id)
            continue

        if hotspot_information:
            # check for hotspot type if hotspot information exists
            found_type = classify_by_loops(file_id, start_line, end_line, loops)
            if found_type is not None:
                result_dict[found_type].append(pattern_id)
        else:
            # fallback, consider all suggestions
            result_dict[HotspotType.YES].append(pattern_id)

    return result_dict
