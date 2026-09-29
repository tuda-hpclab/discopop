# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPULoop import GPULoopPattern
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPURegions import (
    GPURegions,
    GPURegionInfo,
)
from discopop_explorer.classes.variable import Variable
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.StatusReporting.console import progress


def run_detection(pet: PEGraphX, res: DetectionResult, project_folder_path: str) -> List[PatternInfo]:
    """Search for do-all loop pattern

    :param pet: PET graph
    :param res: DetectionResult object
    :return: List of detected pattern info
    """
    gpu_patterns: List[GPULoopPattern] = []

    for node in progress(all_nodes(pet, type=LoopNode), desc="Creating GPU patterns"):
        # check for lastprivates, since they are not supported by the suggested pragma:
        #  pragma omp target teams distribute
        # todo: instead of omitting, suggest #pragma omp target parallel for instead
        if any(node.id == d.node_id for d in res.patterns.do_all if len(d.last_private) == 0) or any(
            node.id == r.node_id for r in res.patterns.reduction if len(r.last_private) == 0
        ):
            reduction_vars: List[Variable] = []
            if node.id in [r.node_id for r in res.patterns.reduction]:
                parent_reduction = [r for r in res.patterns.reduction if r.node_id == node.id][0]
                reduction_vars = parent_reduction.reduction
            gpulp = GPULoopPattern(
                pet,
                node.id,
                LineID(str(node.file_id) + ":" + str(node.start_line)),
                LineID(str(node.file_id) + ":" + str(node.end_line)),
                node.loop_iterations,
                project_folder_path,
                reduction_vars,
            )
            gpulp.getNestedLoops(pet, node.id)
            gpulp.setParentLoop(node.id)
            gpulp.classifyLoopVars(pet, node)
            gpu_patterns.append(gpulp)

    if len(gpu_patterns) == 0:
        return []

    regions = GPURegions(pet, gpu_patterns, project_folder_path)

    for i in gpu_patterns:
        i.setCollapseClause(pet, i.node_id, res)

    regions.identifyGPURegions()
    # regions.old_mapData()
    regions.determineDataMapping()

    # construct GPURegions
    gpu_region_info: List[GPURegionInfo] = regions.get_gpu_region_info(pet, project_folder_path)

    return cast(List[PatternInfo], gpu_region_info)
