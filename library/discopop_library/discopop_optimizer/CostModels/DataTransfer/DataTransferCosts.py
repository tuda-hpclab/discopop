# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, List, Tuple

import networkx as nx  # type: ignore
from sympy import Integer  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.context.ContextObjectUtils import (
    get_transfer_costs,
)
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot


def add_data_transfer_costs(
    graph: nx.DiGraph,
    function_performance_models: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]],
    environment: Experiment,
) -> Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]]:
    """Calculates the data transfer costs for each of the given performance models and adds them to the respective model."""
    result_dict: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]] = dict()

    for function in function_performance_models:
        result_dict[function] = []
        for cost_model, context in function_performance_models[function]:
            # calculate costs of data transfers
            # For now, it is assumed, that only a single data transfer happens at once
            # and no asynchronous transfers happen.
            # todo: This should be extended in the future.
            data_transfer_costs = get_transfer_costs(context, environment=environment)
            # extend the cost_model
            cost_model = cost_model.parallelizable_plus_combine(data_transfer_costs)

            # add the updated entry to result_dict
            result_dict[function].append((cost_model, context))
    return result_dict
