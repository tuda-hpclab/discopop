# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import json
import logging
import os
from typing import Dict, List, Tuple
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType, get_HotspotNodeType_from_string
from discopop_library.HostpotLoader.HotspotType import HotspotType, get_HotspotType_from_string

FILEID = int
STARTLINE = int
NAME = str
AVERAGE_RUNTIME = float


def run(
    arguments: HotspotLoaderArguments,
) -> Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]]:
    """Loads Hotspots for processing in other tools of the framework"""

    logger = logging.getLogger("HotspotLoader")

    dot_discopop_path = arguments.dot_discopop_path if len(arguments.dot_discopop_path) > 0 else os.getcwd()

    result_dict: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]] = dict()

    if not os.path.exists(os.path.join(dot_discopop_path, "hotspot_detection")):
        return result_dict
    if not os.path.exists(os.path.join(dot_discopop_path, "hotspot_detection", "Hotspots.json")):
        return result_dict
    with open(os.path.join(dot_discopop_path, "hotspot_detection", "Hotspots.json"), "r") as f:
        hotspots = json.load(f)

        for key in hotspots:
            for entry in hotspots[key]:
                # check if hotness is considered
                if entry["hotness"] in arguments.get_considered_hotness():
                    # check if type is considered
                    if entry["typ"] in arguments.get_considered_types():
                        if get_HotspotType_from_string(entry["hotness"]) not in result_dict:
                            result_dict[get_HotspotType_from_string(entry["hotness"])] = []

                        result_dict[get_HotspotType_from_string(entry["hotness"])].append(
                            (
                                int(entry["fid"]),
                                int(entry["lineNum"]),
                                get_HotspotNodeType_from_string(entry["typ"]),
                                entry["name"],
                                float(entry["avr"]),
                            )
                        )
    return result_dict
