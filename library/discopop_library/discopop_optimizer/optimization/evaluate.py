# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
from typing import Dict, List, Optional, Tuple, cast
import warnings

from sympy import Expr, Integer, Symbol  # type: ignore
import sympy
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.CostModels.DataTransfer.DataTransferCosts import add_data_transfer_costs
from discopop_library.discopop_optimizer.CostModels.utilities import (
    get_node_performance_models,
    get_performance_models_for_functions,
)
from discopop_library.discopop_optimizer.DataTransfers.DataTransfers import calculate_data_transfers
from discopop_library.discopop_optimizer.DataTransfers.NewDataTransfers import calculate_data_transfers_by_models

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.utilities.MOGUtilities import get_all_function_nodes, show
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def evaluate_configuration(
    experiment: Experiment,
    decisions: List[int],
    arguments: OptimizerArguments,
) -> Tuple[Tuple[int, ...], Expr, ContextObject]:
    """Evaluate the configuration specified by the decisions for the current set of substitutions.
    Returns the used decisions and the calculated costs as a tuple.
    Note: To compare values across ranges of system specifications, use the ranges obtainable via System.get_symbol_values_and_distributions
    to update the substitutions and execute evaluate_configuration for each set of values."""
    result = Expr(-42)
    # get main function
    main_function: Optional[FunctionRoot] = None
    funciton_node_ids = get_all_function_nodes(experiment.optimization_graph)
    function_root_nodes = [cast(FunctionRoot, data_at(experiment.optimization_graph, fid)) for fid in funciton_node_ids]
    for function_id in funciton_node_ids:
        if cast(FunctionRoot, data_at(experiment.optimization_graph, function_id)).name == "main":
            main_function = cast(FunctionRoot, data_at(experiment.optimization_graph, function_id))
    if main_function is None:
        raise ValueError("No main function found!")

    function_performance_models_without_context = get_performance_models_for_functions(
        experiment, experiment.optimization_graph, restrict_to_decisions=set(decisions)
    )
    function_performance_models = calculate_data_transfers_by_models(
        experiment.optimization_graph, function_performance_models_without_context, experiment
    )
    function_performance_models = add_data_transfer_costs(
        experiment.optimization_graph,
        function_performance_models,
        experiment,
    )

    selected_function_models: Dict[FunctionRoot, Tuple[CostModel, ContextObject]] = dict()
    for function in function_performance_models:
        if len(function_performance_models[function]) > 1:
            warnings.warn("Selection for function:" + function.name + " not unambiguous!")
            for m, c in function_performance_models[function]:
                print("--> ", m.path_decisions)
        elif len(function_performance_models[function]) < 1:
            raise ValueError("No generated models for function:", function.name, " for decisions: ", decisions)
        selected_function_models[function] = function_performance_models[function][0]

    # apply selected substitutions
    # collect substitutions
    local_substitutions = copy.deepcopy(experiment.substitutions)
    for function in function_performance_models:
        # register substitution
        local_substitutions[cast(Symbol, function.sequential_costs)] = selected_function_models[function][
            0
        ].sequential_costs
        local_substitutions[cast(Symbol, function.parallelizable_costs)] = selected_function_models[function][
            0
        ].parallelizable_costs

    result_model = copy.deepcopy(selected_function_models[main_function][0])
    result_context = copy.deepcopy(selected_function_models[main_function][1])

    # perform iterative substitutions
    modification_found = True
    while modification_found:
        modification_found = False
        # apply substitution to parallelizable costs
        tmp_model = result_model.parallelizable_costs.subs(local_substitutions)
        if tmp_model != result_model.parallelizable_costs:
            modification_found = True
        result_model.parallelizable_costs = tmp_model

        # apply substitutions to sequential costs
        tmp_model = result_model.sequential_costs.subs(local_substitutions)
        if tmp_model != result_model.sequential_costs:
            modification_found = True
        result_model.sequential_costs = result_model.sequential_costs.subs(local_substitutions)

    # replace Expr(0) with 0
    result_model.sequential_costs = result_model.sequential_costs.subs({Expr(Integer(0)): Integer(0)})
    result_model.parallelizable_costs = result_model.parallelizable_costs.subs({Expr(Integer(0)): Integer(0)})

    # unmark replaced free symbols
    local_sorted_free_symbols = copy.deepcopy(experiment.sorted_free_symbols)
    local_free_symbol_ranges = copy.deepcopy(experiment.free_symbol_ranges)
    for symbol in experiment.substitutions:
        if symbol in experiment.free_symbols:
            experiment.free_symbols.remove(symbol)
        if symbol in local_free_symbol_ranges:
            del local_free_symbol_ranges[symbol]
        if symbol in local_sorted_free_symbols:
            local_sorted_free_symbols.remove(symbol)

    # calculate costs
    result = sympy.re(result_model.parallelizable_costs + result_model.sequential_costs) + sympy.im(
        result_model.parallelizable_costs + result_model.sequential_costs
    )

    return (tuple(decisions), result, result_context)
