# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import random
from typing import List, Dict, cast, Set, Optional
import warnings

import networkx as nx  # type: ignore
import sympy  # type: ignore
from sympy import Integer, Expr, Symbol  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.classes.system.devices.GPU import GPU
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_in_mutex_edges,
    get_out_mutex_edges,
    get_successors,
    get_children,
    get_edge_data,
    get_requirements,
    get_out_options,
    get_in_options,
    get_all_parents,
    get_all_function_nodes,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def get_performance_models_for_functions(
    experiment: Experiment, graph: nx.DiGraph, restrict_to_decisions: Optional[Set[int]] = None
) -> Dict[FunctionRoot, List[CostModel]]:
    performance_models: Dict[FunctionRoot, List[CostModel]] = dict()
    # get called FunctionRoots from cu ids
    all_function_nodes = [
        cast(FunctionRoot, data_at(experiment.optimization_graph, fn_id))
        for fn_id in get_all_function_nodes(experiment.optimization_graph)
    ]

    for node_id in graph.nodes:
        node_data = graph.nodes[node_id]["data"]
        node_data.node_id = node_id  # fix potential mismatches due to node copying

        if isinstance(node_data, FunctionRoot):
            try:
                # ignore non-hotspot functions in the calculateion to save analysis time
                if (
                    node_id not in experiment.hotspot_function_node_ids
                    and len(experiment.hotspot_function_node_ids) > 0
                ):
                    print("SKIPPING NON-HOTPSOT FUNCTION: ", node_data.name, "ID: ", node_id, " SET COSTS TO 1")
                    performance_models[node_data] = [CostModel(Integer(0), Integer(1))]
                    continue

                # start the collection at the first child of the function
                for child_id in get_children(graph, node_id):
                    performance_models[node_data] = get_node_performance_models(
                        experiment,
                        graph,
                        child_id,
                        set(),
                        all_function_nodes,
                        restrict_to_decisions=restrict_to_decisions,
                        allow_sequential=True,
                    )

                # At this point, decisions are restricted to the specified parallelization or the sequential version.
                # Restrict them to the exact case specified in restrict_to_decisions
                if restrict_to_decisions is not None:
                    to_be_removed: List[int] = []
                    for idx, cost_model in enumerate(performance_models[node_data]):
                        for decision in cost_model.path_decisions:
                            if decision not in restrict_to_decisions:
                                # check if the decision to be removed is a sequential execution. If so, ignore it
                                if data_at(graph, decision).represents_sequential_version():
                                    continue
                                # decision represents a not-allowes, parallel execution. Remove it.
                                to_be_removed.append(idx)
                                break
                    for idx in sorted(to_be_removed, reverse=True):
                        del performance_models[node_data][idx]

                # filter out NaN - Models
                performance_models[node_data] = [
                    model for model in performance_models[node_data] if model.parallelizable_costs != sympy.nan
                ]
            except KeyError as ke:
                performance_models[node_data] = [CostModel(Integer(0), Integer(1))]
                warnings.warn(
                    "No performance model for "
                    + node_data.name
                    + "found due to the following error: "
                    + str(ke)
                    + ". Model set to Fallback (0,1)"
                )

    return performance_models


def get_node_performance_models(
    experiment: Experiment,
    graph: nx.DiGraph,
    node_id: int,
    visited_nodes: Set[int],
    all_function_nodes: List[FunctionRoot],
    restrict_to_decisions: Optional[Set[int]] = None,
    do_not_allow_decisions: Optional[Set[int]] = None,
    get_single_random_model: bool = False,
    ignore_node_costs: Optional[List[int]] = None,
    current_device_id: Optional[int] = None,
    allow_sequential: bool = False,
) -> List[CostModel]:
    """Returns the performance models for the given node.
    If a set of decision is specified for restrict_to_decisions, only those non-sequential decisions will be allowed.
    Caution: List might be empty!
    """
    try:
        result_list: List[CostModel] = []
        successors = get_successors(graph, node_id)
        successor_count = len(successors)
        node_data = data_at(graph, node_id)
        if node_data.execute_in_parallel:
            current_device_id = node_data.device_id
        visited_nodes.add(node_id)

        # consider performance models of children
        children_models = get_performance_models_for_children(
            experiment,
            graph,
            node_id,
            copy.deepcopy(visited_nodes),
            all_function_nodes,
            restrict_to_decisions=restrict_to_decisions,
            do_not_allow_decisions=do_not_allow_decisions,
            get_single_random_model=get_single_random_model,
        )

        if len(children_models) == 0:
            if ignore_node_costs is not None:
                if node_data.node_id in ignore_node_costs:
                    children_models = [CostModel(Integer(0), Integer(0))]
            else:
                children_models = [
                    node_data.get_cost_model(
                        experiment,
                        all_function_nodes,
                        experiment.get_system().get_device(current_device_id),
                    )
                ]

        else:
            if ignore_node_costs is not None:
                if node_data.node_id in ignore_node_costs:
                    tmp_node_cost_model = CostModel(Integer(0), Integer(0))
            else:
                tmp_node_cost_model = node_data.get_cost_model(
                    experiment,
                    all_function_nodes,
                    experiment.get_system().get_device(current_device_id),
                )

            for idx, child_model in enumerate(children_models):
                if ignore_node_costs is not None:
                    if node_data.node_id not in ignore_node_costs:
                        children_models[idx] = tmp_node_cost_model.register_child(
                            child_model,
                            node_data,
                            experiment,
                            all_function_nodes,
                            experiment.get_system().get_device(current_device_id),
                        )
                else:
                    children_models[idx] = tmp_node_cost_model.register_child(
                        child_model,
                        node_data,
                        experiment,
                        all_function_nodes,
                        experiment.get_system().get_device(current_device_id),
                    )

        # construct the performance models
        if successor_count >= 1:
            removed_successors = False
            if get_single_random_model and successor_count > 1:
                # pick only a single successor
                successors = [random.choice(successors)]
                removed_successors = True

            for children_model in children_models:
                for successor in successors:
                    # ## CHECK REQUIREMENTS ##
                    # check if successor validates a requirements edge to restrain the created combinations
                    # 1.1. check if optionEdge between any node in visited_nodes and successor exists
                    # 1.2. if so, check if option edge to other node in visited nodes exists
                    # 1.3. if so, check if a requirements edge between both option exists.
                    # 1.4. if not, the path is not valid since two options for the same
                    #      source code location would be selected
                    path_invalid = False
                    # 1.1
                    #               if successor in [109, 110, 111, 112, 113, 114]:
                    #                      print("VISITED NODES: ", visited_nodes)
                    for visited_node_id in visited_nodes:
                        options = get_out_mutex_edges(graph, visited_node_id)
                        if successor in options:
                            # 1.2
                            visited_options = [opt for opt in options if opt in visited_nodes]
                            if len(visited_options) > 0:
                                # 1.3
                                for vo in visited_options:
                                    # 1.4
                                    if successor not in get_requirements(graph, vo):
                                        path_invalid = True
                                        break
                        if path_invalid:
                            break
                    if path_invalid:
                        continue

                    # 2 check if a sibling of successor exists which has a requirements edge to a visited node
                    # 2.1 check if an incoming or outgoing option edge exists, get the node id for the sequential version
                    # 2.2 for all parallelization options
                    # 2.3 check if a requirements edge to a visited node exists
                    # 2.4 if so, stop if successor is NOT the parallelization option with the requirements edge
                    # 2.1
                    for sibling in successors:
                        sequential_version_ids = []
                        if len(get_out_mutex_edges(graph, sibling)) > 0:
                            sequential_version_ids = [sibling]
                        else:
                            for seq in get_in_mutex_edges(graph, sibling):
                                sequential_version_ids.append(seq)
                        # 2.2
                        for seq in sequential_version_ids:
                            for option in get_out_mutex_edges(graph, seq):
                                if option == successor:
                                    continue
                                # 2.3
                                for visited_req in [
                                    req for req in get_requirements(graph, option) if req in visited_nodes
                                ]:
                                    # 2.4
                                    if visited_req != successor:
                                        path_invalid = True
                                        break
                                if path_invalid:
                                    break
                        if path_invalid:
                            break

                    # do not allow nested parallelization suggestions on devices of type GPU
                    if True:  # option to disable this check
                        combined_visited_nodes = copy.deepcopy(visited_nodes)
                        combined_visited_nodes.add(successor)
                        gpu_suggestions = [
                            node_id
                            for node_id in combined_visited_nodes
                            if isinstance(
                                experiment.get_system().get_device(data_at(graph, node_id).device_id),
                                GPU,
                            )
                        ]
                        # check if two suggestions are in a contained-in relation
                        for suggestion_1 in gpu_suggestions:
                            all_parents = get_all_parents(graph, suggestion_1)
                            for suggestion_2 in gpu_suggestions:
                                if suggestion_1 == suggestion_2:
                                    continue
                                if suggestion_2 in all_parents:
                                    path_invalid = True
                                    break
                            if path_invalid:
                                break

                    # check if the current decision invalidates decision requirements, if some are specified
                    if restrict_to_decisions is not None:
                        if not (successor in restrict_to_decisions or data_at(graph, successor).suggestion is None):
                            path_invalid = True
                        if not path_invalid:
                            if data_at(graph, successor).suggestion is None:
                                # if the sequential "fallback" has been used, check if a different option is specifically
                                # mentioned in restrict_to_decisions. If so, the sequential fallback shall be ignored.
                                options = get_out_mutex_edges(graph, successor)
                                restricted_options = [opt for opt in options if opt in restrict_to_decisions]
                                if len(restricted_options) != 0:
                                    # do not use he sequential fallback since a required option exists
                                    path_invalid = True

                    if do_not_allow_decisions is not None:
                        if successor in do_not_allow_decisions:
                            path_invalid = True

                    if path_invalid:
                        continue

                    # ## END OF REQUIREMENTS CHECK ##

                    combined_model = children_model
                    # add transfer costs
                    transfer_costs_model = get_edge_data(graph, node_id, successor).get_cost_model()
                    combined_model = combined_model.parallelizable_plus_combine(transfer_costs_model)

                    # if the successor is "determined" by a path decision, add path decision to the combined model
                    if len(successors) > 1 or removed_successors:
                        combined_model.path_decisions.append(successor)
                    # append the model of the successor
                    for model in get_node_performance_models(
                        experiment,
                        graph,
                        successor,
                        copy.deepcopy(visited_nodes),
                        all_function_nodes,
                        restrict_to_decisions=restrict_to_decisions,
                        do_not_allow_decisions=do_not_allow_decisions,
                        get_single_random_model=get_single_random_model,
                        ignore_node_costs=ignore_node_costs,
                    ):
                        tmp = combined_model.parallelizable_plus_combine(model)
                        tmp.path_decisions += [d for d in model.path_decisions if d not in tmp.path_decisions]
                        result_list.append(tmp)
            if len(result_list) >= 1:
                return result_list

        # successor count == 0 or successor count > 1
        return children_models

    except RecursionError:
        warnings.warn("Allowed recursion depth exceeded at node " + str(node_id) + " . Results may be inaccurate.")
        node_data = data_at(graph, node_id)
        return [
            node_data.get_cost_model(
                experiment,
                all_function_nodes,
                experiment.get_system().get_device(current_device_id),
            )
        ]


def get_performance_models_for_children(
    experiment: Experiment,
    graph: nx.DiGraph,
    node_id: int,
    visited_nodes: Set[int],
    all_function_nodes: List[FunctionRoot],
    restrict_to_decisions: Optional[Set[int]] = None,
    do_not_allow_decisions: Optional[Set[int]] = None,
    get_single_random_model: bool = False,
) -> List[CostModel]:
    """Construct a performance model for the children of the given node, or return None if no children exist"""
    # todo: consider children
    child_models: List[CostModel] = []

    # create all combinations for models from children
    first_iteration = True
    for child_id in get_children(graph, node_id):
        if first_iteration:
            first_iteration = False
            for model in get_node_performance_models(
                experiment,
                graph,
                child_id,
                copy.deepcopy(visited_nodes),
                all_function_nodes,
                restrict_to_decisions=restrict_to_decisions,
                do_not_allow_decisions=do_not_allow_decisions,
                get_single_random_model=get_single_random_model,
            ):
                # initialize list of child models
                child_models.append(model)
        else:
            # create "product set" of child models
            product_set = []
            for model in get_node_performance_models(
                experiment,
                graph,
                child_id,
                copy.deepcopy(visited_nodes),
                all_function_nodes,
                restrict_to_decisions=restrict_to_decisions,
                do_not_allow_decisions=do_not_allow_decisions,
                get_single_random_model=get_single_random_model,
            ):
                temp_models = [cm.parallelizable_plus_combine(model) for cm in child_models]
                product_set += temp_models
            child_models = product_set
    return child_models


def print_introduced_symbols_per_node(graph: nx.DiGraph) -> None:
    print("Introduced Symbols:")
    for node_id in graph.nodes:
        print("NodeID: ", node_id)
        for symbol in data_at(graph, node_id).introduced_symbols:
            print("\t: ", symbol)
    print()


def get_random_path(
    experiment: Experiment, graph: nx.DiGraph, root_id: int, must_contain: Optional[Set[int]] = None
) -> CostModel:
    # get called FunctionRoots from cu ids
    all_function_nodes = [
        cast(FunctionRoot, data_at(experiment.optimization_graph, fn_id))
        for fn_id in get_all_function_nodes(experiment.optimization_graph)
    ]
    random_models = get_node_performance_models(
        experiment,
        graph,
        root_id,
        set(),
        all_function_nodes,
        restrict_to_decisions=must_contain,
        get_single_random_model=True,
        ignore_node_costs=[cast(FunctionRoot, data_at(graph, root_id)).node_id],
    )
    # filter out NaN - Models
    random_models = [model for model in random_models if model.parallelizable_costs != sympy.nan]
    return random.choice(random_models)
