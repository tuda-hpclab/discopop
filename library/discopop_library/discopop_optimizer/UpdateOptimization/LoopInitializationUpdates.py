# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.utilities.MOGUtilities import get_parents
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


def fix_loop_initialization_updates(
    experiment: Experiment, best_configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    """Move updates to initialize device loops before the loop"""
    for update in best_configuration.data_movement:
        if update.source_node_id == update.target_node_id:
            continue
        source_parents = [
            id
            for id in get_parents(experiment.optimization_graph, update.source_node_id)
            if id in best_configuration.decisions
        ]
        target_parents = [
            id
            for id in get_parents(experiment.optimization_graph, update.target_node_id)
            if id in best_configuration.decisions
        ]

        if len(source_parents) != 0 and len(target_parents) != 0:
            source_parent = source_parents[0]
            target_parent = target_parents[0]

            if source_parent == target_parent and type(data_at(experiment.optimization_graph, source_parent)) == Loop:
                # set the loop node as the new update source and target
                update.source_node_id = source_parent
                update.source_cu_id = data_at(experiment.optimization_graph, source_parent).original_cu_id
                update.target_node_id = source_parent
                update.target_cu_id = update.source_cu_id
                continue

        if len(target_parents) != 0:
            # move updates originating from the loop node to the inside before the loop
            if (
                type(data_at(experiment.optimization_graph, update.source_node_id)) == Loop
                and update.source_node_id in target_parents
            ):
                update.target_node_id = update.source_node_id
                update.target_cu_id = data_at(experiment.optimization_graph, update.source_node_id).original_cu_id

    if arguments.verbose:
        print("Fixed loop initialization updates")
        for update in best_configuration.data_movement:
            print("# ", update)
        print()

    return best_configuration
