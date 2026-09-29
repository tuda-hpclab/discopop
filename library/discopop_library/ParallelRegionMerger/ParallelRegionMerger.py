# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import itertools
import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Set, Tuple, cast

import jsonpickle  # type: ignore
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

from discopop_explorer.json_serializer import PatternBaseSerializer
from discopop_library.FolderStructure.setup import setup_auto_tuner, setup_parallel_region_merger
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.ParallelRegionMerger.ArgumentClasses import ParallelRegionMergerArguments
from discopop_library.ParallelRegionMerger.Types import SUGGESTION_ID
from discopop_library.discopop_optimizer import suggestions
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.ParallelRegionMerger.inflated_parallel_region_pattern import (
    run_detection as detect_inflated_parallel_regions,
)

logger = logging.getLogger("ParallelRegionMerger")

configuration_counter = 1


def get_unique_configuration_id() -> int:
    global configuration_counter
    buffer = configuration_counter
    configuration_counter += 1
    return buffer


def run(arguments: ParallelRegionMergerArguments) -> None:
    logger.info("Starting..")

    setup_parallel_region_merger(os.getcwd())
    prm_dir = os.path.join(os.getcwd(), "parallel_region_merger")

    # load detection result
    with open(os.path.join(arguments.dot_dp_path, "explorer", "detection_result_dump.json"), "r") as f:
        tmp_str = f.read()
    detection_result: DetectionResult = jsonpickle.decode(tmp_str, keys=True)
    logger.debug("loaded detection result")

    pr, da, red = detect_inflated_parallel_regions(detection_result.pet, detection_result, arguments)
    detection_result.patterns.parallel_region = pr
    detection_result.patterns.do_all = da
    detection_result.patterns.reduction = red

    # create patterns.json
    del detection_result.pet
    pattern_file_path = os.path.join(prm_dir, "patterns.json")
    with open(pattern_file_path, "w+") as f:
        json.dump(detection_result, f, indent=2, cls=PatternBaseSerializer)

    # create results.json
    results_dict: Dict[str, Any] = dict()
    if arguments.auto_tuner_config not in results_dict:
        results_dict[arguments.auto_tuner_config] = dict()
        results_dict[arguments.auto_tuner_config]["applied_suggestions"] = [
            str(par_reg.pattern_id) for par_reg in detection_result.patterns.parallel_region
        ]
    with open(os.path.join(prm_dir, "results.json"), "w+") as f:
        json.dump(results_dict, f, indent=2)

    # create applicable patch files from the found suggestions
    logger.info("executing discopop_patch_generator")
    out = subprocess.check_output(
        ["discopop_patch_generator", "-a", pattern_file_path], cwd=arguments.dot_dp_path
    ).decode("utf-8")
    logger.debug("\t Out:\n" + out)
    logger.info("\tDone.")
