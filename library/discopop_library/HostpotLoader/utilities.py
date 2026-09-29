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
from discopop_library.result_classes.DetectionResult import DetectionResult


from typing import Dict, List, Tuple


def get_patterns_by_hotspot_type(
    detection_result: DetectionResult,
    hotspot_information: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]],
) -> Dict[HotspotType, List[int]]:
    yes_hotspot_loops: List[Tuple[FILEID, STARTLINE]] = []
    no_hotspot_loops: List[Tuple[FILEID, STARTLINE]] = []
    maybe_hotspot_loops: List[Tuple[FILEID, STARTLINE]] = []
    if HotspotType.YES in hotspot_information:
        for entry in hotspot_information[HotspotType.YES]:
            if entry[2] == HotspotNodeType.LOOP:
                yes_hotspot_loops.append((entry[0], entry[1]))
    if HotspotType.NO in hotspot_information:
        for entry in hotspot_information[HotspotType.NO]:
            if entry[2] == HotspotNodeType.LOOP:
                no_hotspot_loops.append((entry[0], entry[1]))
    if HotspotType.MAYBE in hotspot_information:
        for entry in hotspot_information[HotspotType.MAYBE]:
            if entry[2] == HotspotNodeType.LOOP:
                maybe_hotspot_loops.append((entry[0], entry[1]))

    pattern_ids = detection_result.patterns.get_pattern_ids()

    result_dict: Dict[HotspotType, List[int]] = {HotspotType.YES: [], HotspotType.NO: [], HotspotType.MAYBE: []}

    for pattern_id in pattern_ids:
        pattern = detection_result.patterns.get_pattern_from_id(pattern_id)
        start_line = int(pattern.start_line.split(":")[1])
        end_line = int(pattern.end_line.split(":")[1])
        file_id = int(pattern.start_line.split(":")[0])

        if hotspot_information:
            # check for hotspot type if hotspot information exists
            found_type = False
            for entry_2 in yes_hotspot_loops:
                if file_id == entry_2[0]:
                    if start_line <= entry_2[1] and entry_2[1] <= end_line:
                        result_dict[HotspotType.YES].append(pattern_id)
                        found_type = True
                        break
            if found_type:
                continue

            for entry_2 in no_hotspot_loops:
                if file_id == entry_2[0]:
                    if start_line <= entry_2[1] and entry_2[1] <= end_line:
                        result_dict[HotspotType.NO].append(pattern_id)
                        found_type = True
                        break
            if found_type:
                continue

            for entry_2 in maybe_hotspot_loops:
                if file_id == entry_2[0]:
                    if start_line <= entry_2[1] and entry_2[1] <= end_line:
                        result_dict[HotspotType.MAYBE].append(pattern_id)
                        found_type = True
                        break
            if found_type:
                continue
        else:
            # fallback, consider all suggestions
            result_dict[HotspotType.YES].append(pattern_id)

    return result_dict
