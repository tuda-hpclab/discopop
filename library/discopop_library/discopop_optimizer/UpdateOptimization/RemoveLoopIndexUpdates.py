# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
from typing import List, Set, cast
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.Update import Update
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern

logger = logging.getLogger("Optimizer")


def remove_loop_index_updates(
    experiment: Experiment, best_configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    mem_reg_blacklist: Set[MemoryRegion] = set()
    to_be_removed: List[Update] = []
    for update in best_configuration.data_movement:
        # check for loop nodes as update targets
        condition = type(data_at(experiment.optimization_graph, update.target_node_id)) == Loop
        if (not condition) and (update.originated_from_node is not None):
            condition = condition or type(data_at(experiment.optimization_graph, update.originated_from_node)) == Loop

        if condition:
            # get loop indices from PEGraph
            loop_cu_id = data_at(experiment.optimization_graph, update.target_node_id).original_cu_id
            if loop_cu_id is None:
                continue
            loop_indices = cast(LoopNode, experiment.detection_result.pet.node_at(loop_cu_id)).loop_indices
            # check for loop indices as targeted varbiables
            if update.write_data_access.var_name in loop_indices:
                # found update to loop index
                logger.info(
                    "# ignoring updates to mem_reg: "
                    + str(update.write_data_access.memory_region)
                    + " name: "
                    + update.write_data_access.var_name
                    + " since it targets a loop index."
                )
                mem_reg_blacklist.add(update.write_data_access.memory_region)
    # remove identified loop index updates
    for update in best_configuration.data_movement:
        if update.write_data_access.memory_region in mem_reg_blacklist:
            to_be_removed.append(update)

    for tbr in to_be_removed:
        if tbr in best_configuration.data_movement:
            best_configuration.data_movement.remove(tbr)

    # ensure correct formatting
    if arguments.verbose:
        if len(to_be_removed) > 0:
            print()

    if arguments.verbose:
        print("Removed loop index updates")
        for update in best_configuration.data_movement:
            print("# ", update)
        print()

    return best_configuration
