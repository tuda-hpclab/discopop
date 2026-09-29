# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os

from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.UpdateOptimization.AddRangesToUpdates import add_ranges_to_updates
from discopop_library.discopop_optimizer.UpdateOptimization.LoopInitializationUpdates import (
    fix_loop_initialization_updates,
)
from discopop_library.discopop_optimizer.UpdateOptimization.RemoveDuplicatedUpdates import remove_duplicated_updates
from discopop_library.discopop_optimizer.UpdateOptimization.RemoveLoopIndexUpdates import remove_loop_index_updates
from discopop_library.discopop_optimizer.UpdateOptimization.RemoveSameDeviceUpdates import remove_same_device_updates
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.utilities.visualization.update_graph import show_update_graph
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


def optimize_updates(
    experiment: Experiment, configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    logger = logging.getLogger("Optimizer").getChild("UpdateOptimization")
    logger.setLevel(arguments.log_level)
    # plot raw update graph
    # show_update_graph(experiment.optimization_graph, best_configuration, experiment)

    # print original updates
    if arguments.verbose:
        print("Original updates")
        for update in configuration.data_movement:
            print("# ", update)
        print()

    # remove same-device updates
    configuration = remove_same_device_updates(experiment, configuration, arguments)

    # optimize updates
    configuration = fix_loop_initialization_updates(experiment, configuration, arguments)

    # remove duplicated updates
    configuration = remove_duplicated_updates(configuration, arguments)

    # remove loop index updates
    # configuration = remove_loop_index_updates(experiment, configuration, arguments)

    # add ranges to be transferred to the updates
    configuration = add_ranges_to_updates(experiment, configuration, arguments)

    # plt optimized update graph
    # show_update_graph(experiment.optimization_graph, best_configuration, experiment)

    # print optimized updates

    logger.debug("Optimized updates")
    for update in configuration.data_movement:
        logger.debug("# " + str(update))
    logger.debug("")

    return configuration


#    # export the updated configuration to the disk
#    updated_configuration_path = os.path.join("optimizer", "updated_configuration.json")
#    best_configuration.dump_to_file(updated_configuration_path)
