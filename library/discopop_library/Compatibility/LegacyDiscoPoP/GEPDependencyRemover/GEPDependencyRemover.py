# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import re
from typing import List, Tuple, cast

import jsonpickle  # type: ignore
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_library.Compatibility.LegacyDiscoPoP.GEPDependencyRemover.ArgumentClasses import (
    GEPDependencyRemoverArguments,
)
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Statistics.StatisticsGraph import NodeColor, NodeShape, StatisticsGraph
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.EmpiricalAutotuning.utils import get_applicable_suggestion_ids
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.result_classes.DetectionResult import DetectionResult

logger = logging.getLogger("GEPDependencyRemover")


def run(arguments: GEPDependencyRemoverArguments) -> None:
    logger.info("Starting DiscoPoP GEPDependencyRemover.")

    filtered_lines: List[str] = []

    # unpack dynamic dependency file
    with open(arguments.dyndep_file_path, "r") as dyn_dep_file:
        for line in dyn_dep_file.readlines():
            line = line.replace("\n", "")
            # unpack line and remove GEPRESULT dependencies
            logger.debug("line: \t" + line)
            line = re.sub(r"((RAW)|(WAR)|(WAW)|(INIT))\s+[\*(\d+\:\d+)]+\|\S+\(GEPRESULT_\S+\)\s*", "", line)
            logger.debug("Line post:\t" + line)
            line = line + "\n"
            filtered_lines.append(line)
            logger.debug("")

    # write the updated file
    logger.info("Overwriting " + arguments.dyndep_file_path)
    with open(arguments.dyndep_file_path, "w") as dyn_dep_file:
        for line in filtered_lines:
            dyn_dep_file.write(line)
    logger.info("Done writing " + arguments.dyndep_file_path)
