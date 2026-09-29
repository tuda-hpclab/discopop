# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.Update import Update
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


def remove_same_device_updates(
    experiment: Experiment, configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    """Remove updates where source and device id are equal. These are artifacts from initializing device memory states during the data movement calculation."""
    cleaned_updates: List[Update] = []
    for update in configuration.data_movement:
        if (
            update.source_device_id == update.target_device_id and not update.delete_data
        ):  # delete updates can be issued with the same source and target device and need to be kept
            # ignore this update
            continue
        else:
            cleaned_updates.append(update)
    configuration.data_movement = cleaned_updates

    if arguments.verbose:
        print("Removed same device updates")
        for update in configuration.data_movement:
            print("# ", update)
        print()
    return configuration
