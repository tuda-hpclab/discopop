# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import sys
from typing import Dict, List, Tuple, Set, cast

import networkx as nx  # type: ignore
from sympy import Symbol, Expr  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.CostModels.DataTransfer.DataTransferCosts import (
    add_data_transfer_costs,
)
from discopop_library.discopop_optimizer.CostModels.utilities import get_node_performance_models
from discopop_library.discopop_optimizer.DataTransfers.DataTransfers import calculate_data_transfers
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_all_function_nodes,
    get_successors,
    get_children,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def get_locally_optimized_models(
    experiment: Experiment,
    graph: nx.DiGraph,
    substitutions: Dict[Symbol, Expr],
    environment: Experiment,
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution],
) -> Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]]:
    result_dict: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]] = dict()
    all_function_ids = get_all_function_nodes(graph)
    all_function_nodes: List[FunctionRoot] = [cast(FunctionRoot, data_at(graph, fn_id)) for fn_id in all_function_ids]
    for function_node in all_function_ids:
        # get a list of all decisions that have to be made
        decisions_to_be_made = __find_decisions(graph, function_node)
        locally_optimal_choices: List[int] = []

        # create performance models for individual options of decisions
        for decision_options in decisions_to_be_made:
            decision_models: List[Tuple[int, Tuple[CostModel, ContextObject]]] = []
            for decision in decision_options:
                try:
                    # create a performance model for the specific decision
                    performance_models = get_node_performance_models(
                        experiment,
                        graph,
                        function_node,
                        set(),
                        all_function_nodes,
                        restrict_to_decisions={decision},
                        do_not_allow_decisions=set([o for o in decision_options if o != decision]),
                        ignore_node_costs=[
                            cast(FunctionRoot, data_at(graph, function_node)).node_id
                        ],  # ignore first node to prevent duplication of function costs
                    )
                    # calculate and append necessary data transfers to the models
                    performance_models_with_transfers = calculate_data_transfers(
                        graph, {cast(FunctionRoot, data_at(graph, function_node)): performance_models}, experiment
                    )

                    # calculate and append costs of data transfers to the performance models
                    complete_performance_models = add_data_transfer_costs(
                        graph, performance_models_with_transfers, environment
                    )
                    # add performance models to decision models for the later selection of the best candidate
                    for function in complete_performance_models:
                        for pair in complete_performance_models[function]:
                            decision_models.append((decision, pair))
                except ValueError as ex:
                    print(ex)
                    print("==> Ignoring Decision: ", decision)
                    continue

            # iteratively apply variable substitutions
            decision_models_with_substitutions: List[Tuple[int, Tuple[CostModel, ContextObject, CostModel]]] = []
            # initialize substitution
            for decision, pair in decision_models:
                model, context = pair
                decision_models_with_substitutions.append((decision, (model, context, copy.deepcopy(model))))

            modification_found = True
            while modification_found:
                modification_found = False
                for decision, tpl in decision_models_with_substitutions:
                    model, context, substituted_model = tpl

                    # apply substitutions to parallelizable costs
                    tmp_model = substituted_model.parallelizable_costs.subs(substitutions)
                    if tmp_model != substituted_model.parallelizable_costs:
                        modification_found = True
                    substituted_model.parallelizable_costs = substituted_model.parallelizable_costs.subs(substitutions)

                    # apply substitutions to sequential costs
                    tmp_model = substituted_model.sequential_costs.subs(substitutions)
                    if tmp_model != substituted_model.sequential_costs:
                        modification_found = True
                    substituted_model.sequential_costs = substituted_model.sequential_costs.subs(substitutions)

            #                    decision_models_with_substitutions.append(
            ##                        (decision, (model, context, substituted_model))
            #                   )

            # set free symbol ranges and distributions for comparisons
            for decision, tpl in decision_models_with_substitutions:
                model, context, substituted_model = tpl
                model.free_symbol_ranges = free_symbol_ranges
                model.free_symbol_distributions = free_symbol_distributions
                substituted_model.free_symbol_ranges = free_symbol_ranges
                substituted_model.free_symbol_distributions = free_symbol_distributions

            # find minimum in decision_models
            unpacked_models: List[Tuple[int, CostModel, CostModel]] = []
            for decision, tpl in decision_models_with_substitutions:
                model, context, substituted_model = tpl
                unpacked_models.append((decision, model, substituted_model))
            if len(unpacked_models) == 0:
                continue
            minimum = sorted(unpacked_models, key=lambda x: x[2])[0]
            locally_optimal_choices.append(minimum[0])

        if len(locally_optimal_choices) == 0:
            continue

        # construct locally optimal model
        sys.setrecursionlimit(100000)
        performance_models = get_node_performance_models(
            experiment,
            graph,
            function_node,
            set(),
            all_function_nodes,
            restrict_to_decisions=set(locally_optimal_choices),
            ignore_node_costs=[
                cast(FunctionRoot, data_at(graph, function_node)).node_id
            ],  # ignore first node to prevent duplication of function costs
        )
        sys.setrecursionlimit(1000)
        # calculate and append necessary data transfers to the models
        performance_models_with_transfers = calculate_data_transfers(
            graph, {cast(FunctionRoot, data_at(graph, function_node)): performance_models}, experiment
        )

        # calculate and append costs of data transfers to the performance models
        complete_performance_models = add_data_transfer_costs(graph, performance_models_with_transfers, environment)
        # merge dictionaries
        result_dict = {**result_dict, **complete_performance_models}

    return result_dict


def __find_decisions(graph: nx.DiGraph, root_node: int) -> Set[Tuple[int, ...]]:
    result_set: Set[Tuple[int, ...]] = set()
    successors = get_successors(graph, root_node)
    children = get_children(graph, root_node)

    # check if children have decisions
    for child in children:
        result_set.update(__find_decisions(graph, child))

    # check if current node has a decision
    if len(successors) > 1:
        local_decision = list()
        for successor in successors:
            local_decision.append(successor)
        result_set.add(tuple(local_decision))

    # check if successors have decisions
    for successor in successors:
        result_set.update(__find_decisions(graph, successor))

    return result_set
