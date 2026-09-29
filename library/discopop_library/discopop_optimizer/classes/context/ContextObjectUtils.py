# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import cast

from sympy import Integer, Symbol  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject


def get_transfer_costs(context: ContextObject, environment: Experiment) -> CostModel:
    """Calculates the amount of data transferred between devices as specified by self.necessary_updates and
    calculates an estimation for the added transfer costs under the assumption,
    that no transfers happen concurrently and every transfer is executed in a blocking, synchronous manner.
    """
    total_transfer_costs = Integer(0)
    symbolic_memory_region_sizes = True
    symbol_value_suggestions = dict()
    for update in context.necessary_updates:
        # add static costs incurred by the transfer initialization
        system = environment.get_system()
        source_device = system.get_device(cast(int, update.source_device_id))
        target_device = system.get_device(cast(int, update.target_device_id))
        initialization_costs = system.get_network().get_transfer_initialization_costs(source_device, target_device)

        total_transfer_costs += initialization_costs

        # add costs incurred by the transfer itself
        transfer_speed = system.get_network().get_transfer_speed(source_device, target_device)

        # value suggestion used for symbolic values
        transfer_size, value_suggestion = environment.get_memory_region_size(
            update.write_data_access.memory_region,
            use_symbolic_value=symbolic_memory_region_sizes,
        )
        # save suggested memory region size from Environment
        if symbolic_memory_region_sizes:
            symbol_value_suggestions[cast(Symbol, transfer_size)] = value_suggestion

        # transfer_costs [us] = [1000000 * s]
        # transfer_size [B]
        # transfer_speed [MB/s] = [1000000 * B/s]
        # * 1000000 gets removed due to mathematics
        transfer_costs = transfer_size / transfer_speed

        total_transfer_costs += transfer_costs
    if symbolic_memory_region_sizes:
        return CostModel(Integer(0), total_transfer_costs, symbol_value_suggestions=symbol_value_suggestions)
    else:
        return CostModel(Integer(0), total_transfer_costs)
