# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, cast, Set
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_all_function_nodes,
    get_children,
    get_in_mutex_edges,
    get_in_options,
    get_out_mutex_edges,
    get_out_options,
    get_requirements,
    get_successors,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def check_configuration_validity(
    experiment: Experiment, arguments: OptimizerArguments, configuration: List[int]
) -> bool:
    """Returns True if the given configuration is valid. Returns False otherwise."""
    # check requirements edges
    for node_id in configuration:
        requirements = get_requirements(experiment.optimization_graph, node_id)
        for r in requirements:
            if r not in configuration:
                # requirement not satisfied
                return False
    # check option edges (for mutual exclusivity)
    for node_id in configuration:
        mutex_options = get_out_mutex_edges(experiment.optimization_graph, node_id)
        if len([e for e in configuration if e in mutex_options]) != 0:
            # mutual exclusivity of suggestions violated
            return False
    # check for nested parallelism
    if not arguments.allow_nested_parallelism:
        if __nested_parallelism_found(experiment, configuration, arguments):
            return False
    # check for duplicated suggestion ids
    # note: this check should not be necessary and might be removed in the future
    applied_suggestion_ids: Set[int] = set()
    for node_id in configuration:
        if node_id in experiment.node_id_to_suggestion_dict:
            if experiment.node_id_to_suggestion_dict[node_id] in applied_suggestion_ids:
                return False
            applied_suggestion_ids.add(experiment.node_id_to_suggestion_dict[node_id])

    return True


def __nested_parallelism_found(experiment: Experiment, configuration: List[int], arguments: OptimizerArguments) -> bool:
    """checks for nested parallelism in the given configuration.
    Returns True if the configuration leads to nested parallelism.
    Returns False otherwise."""
    visited_nodes = []
    children_queue = []
    # initialize knowledge
    all_function_nodes = [
        data_at(experiment.optimization_graph, nid) for nid in get_all_function_nodes(experiment.optimization_graph)
    ]

    # initialize_queue
    for node_id in configuration:
        node = data_at(experiment.optimization_graph, node_id)
        if not node.represents_sequential_version():
            children_queue += __filter_for_relevant_options(
                experiment, configuration, get_children(experiment.optimization_graph, node_id)
            )

    while children_queue:
        current_node_id = children_queue.pop(0)
        current_node = data_at(experiment.optimization_graph, current_node_id)
        # check for nested parallelism
        if not current_node.represents_sequential_version():
            return True

        # add successors and children
        visited_nodes.append(current_node_id)
        children_queue += __filter_for_relevant_options(
            experiment,
            configuration,
            [
                sid
                for sid in get_successors(experiment.optimization_graph, current_node_id)
                if sid not in visited_nodes and sid not in children_queue
            ],
        )

        children_queue += __filter_for_relevant_options(
            experiment,
            configuration,
            [
                cid
                for cid in get_children(experiment.optimization_graph, current_node_id)
                if cid not in visited_nodes and cid not in children_queue
            ],
        )
        if arguments.check_called_function_for_nested_parallelism:
            # add called functions
            called_cu_ids: List[str] = [
                str(t)
                for s, t, d in out_edges(
                    experiment.detection_result.pet, cast(NodeID, current_node.original_cu_id), EdgeType.CALLSNODE
                )
            ]
            # filter for called FunctionRoots
            called_function_nodes = [fr for fr in all_function_nodes if str(fr.original_cu_id) in called_cu_ids]

            # remove duplicates
            called_function_nodes = list(dict.fromkeys(called_function_nodes))
            # add to children_queue
            children_queue += [
                fid.node_id
                for fid in called_function_nodes
                if fid.node_id not in visited_nodes and fid.node_id not in children_queue
            ]

    return False


def __filter_for_relevant_options(
    experiment: Experiment, configuration: List[int], to_be_cleaned: List[int]
) -> List[int]:
    """removes all node_ids from the list to_be_cleaned which are not relevant for the given configuration (i.e. parallelization opportunities which are not chosen.)"""
    cleaned_list: List[int] = []
    for node_id in to_be_cleaned:
        if node_id in configuration:
            cleaned_list.append(node_id)
            continue
        options = get_out_mutex_edges(experiment.optimization_graph, node_id) + get_in_mutex_edges(
            experiment.optimization_graph, node_id
        )
        if len(options) == 0:
            cleaned_list.append(node_id)
            continue
        else:
            # node_id is not in configuration and options exist, i.e. it is not selected by the configuration and has to be ignored
            continue
    return cleaned_list
