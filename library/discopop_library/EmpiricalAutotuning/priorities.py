# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import itertools
from typing import Dict, List, Tuple

from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import AVERAGE_RUNTIME, FILEID, NAME, STARTLINE
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.result_classes.DetectionResult import DetectionResult


def get_prioritized_configurations(
    detection_result: DetectionResult,
    hotspot_information: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]],
) -> List[Tuple[int, ...]]:
    result_list: List[Tuple[int, ...]] = []

    pattern_ids = detection_result.patterns.get_pattern_ids()

    powerset = [x for length in range(len(pattern_ids) + 1) for x in itertools.combinations(pattern_ids, length)]

    # get list of pattern_ids targeting hotspot types YES, NO, and MAYBE
    patterns_by_hotspot_types = get_patterns_by_hotspot_type(detection_result, hotspot_information)

    ranking_list: List[Tuple[int, Tuple[int, ...]]] = []
    for entry in powerset:
        score = 0
        for suggestion in entry:
            if suggestion in patterns_by_hotspot_types[HotspotType.YES]:
                score += 3
            if suggestion in patterns_by_hotspot_types[HotspotType.MAYBE]:
                score += 1
        ranking_list.append((score, entry))

    sorted_ranking_list = sorted(ranking_list, key=lambda x: x[0], reverse=True)

    ranked_list = [x[1] for x in sorted_ranking_list if len(x[1]) > 0]

    result_list = ranked_list

    return result_list
