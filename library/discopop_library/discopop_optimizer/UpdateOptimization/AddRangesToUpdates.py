# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Dict, List, Optional, Set, cast
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.variable import Variable
from discopop_explorer.functions.PEGraph.queries.variables import get_variables
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


def add_ranges_to_updates(
    experiment: Experiment, configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    mem_reg_to_elem_size_in_bytes: Dict[MemoryRegion, int] = dict()
    # determine element sizes by memory regions
    for update in configuration.data_movement:
        # find the Variable object which belongs to the update
        candidate_variables: Dict[Variable, Set[MemoryRegion]] = dict()
        # collect known variables from source

        variables = get_variables(
            experiment.detection_result.pet,
            [experiment.detection_result.pet.node_at(cast(NodeID, update.source_cu_id))],
        )

        for v in variables:
            if v not in candidate_variables:
                candidate_variables[v] = set()
            candidate_variables[v].update(variables[v])

        # collect known variabled from target

        variables = get_variables(
            experiment.detection_result.pet,
            [experiment.detection_result.pet.node_at(cast(NodeID, update.target_cu_id))],
        )

        for v in variables:
            if v not in candidate_variables:
                candidate_variables[v] = set()
            candidate_variables[v].update(variables[v])

        if update.originated_from_node is not None:
            # collect known variabled from originated_from_node
            variables = get_variables(
                experiment.detection_result.pet,
                [
                    experiment.detection_result.pet.node_at(
                        cast(NodeID, data_at(experiment.optimization_graph, update.originated_from_node).original_cu_id)
                    )
                ],
            )
            for v in variables:
                if v not in candidate_variables:
                    candidate_variables[v] = set()
                candidate_variables[v].update(variables[v])

        # search candidate variables for a match
        matching_variables: List[Variable] = []
        for v in candidate_variables:
            if update.write_data_access.memory_region in candidate_variables[v]:
                # only add ranges for consecutive memory, i.e. arrays etc.
                if "**" in v.type:
                    matching_variables.append(v)

        # determine object size in bytes for the update
        if update.write_data_access.memory_region not in mem_reg_to_elem_size_in_bytes:
            mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region] = -1
        # find the maximum
        for v in matching_variables:
            if mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region] == -1:
                # initialize
                mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region] = v.sizeInByte
            if v.sizeInByte > mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region]:
                mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region] = v.sizeInByte

    # determine ranges and set a value
    for update in configuration.data_movement:
        # check if a element size for update has been identified
        if mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region] == -1:
            # no value identified. skip.
            continue

        if update.write_data_access.memory_region in mem_reg_to_elem_size_in_bytes:
            # determine transfer range
            range_start = 0
            mem_reg_size = int(experiment.get_memory_region_size(update.write_data_access.memory_region, False)[0])
            range_end = int(mem_reg_size / mem_reg_to_elem_size_in_bytes[update.write_data_access.memory_region])

            # set the transfer range of the update, if range_end - range_start != 1
            if range_end - range_start != 1:
                update.range = (range_start, range_end)

    return configuration
