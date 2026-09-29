# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import logging
from multiprocessing import Pool
from typing import Dict, List, Set, Tuple, cast
from sympy import Integer, Symbol  # type: ignore

import networkx as nx  # type: ignore

import tqdm  # type: ignore
from discopop_library.discopop_optimizer.classes.nodes.ContextNode import ContextNode  # type: ignore
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern  # type: ignore
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo  # type: ignore
from discopop_library.PatternIdManagement.unique_pattern_id import get_unique_pattern_id
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.edges.MutuallyExclusiveEdge import MutuallyExclusiveEdge
from discopop_library.discopop_optimizer.classes.edges.OptionEdge import OptionEdge
from discopop_library.discopop_optimizer.classes.edges.RequirementEdge import RequirementEdge
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_all_function_nodes,
    get_all_loop_nodes,
    get_all_parents,
    get_children,
    get_out_mutex_edges,
    get_parents,
    get_predecessors,
    get_successors,
    show,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at

logger = logging.getLogger("Optimizer")

global_graph = None
global_experiment = None


def collapse_loops(experiment: Experiment) -> nx.DiGraph:
    """identifies collapse loops and depicts them in the optimization graph"""

    global global_graph
    global global_experiment
    global_graph = experiment.optimization_graph
    global_experiment = experiment

    param_list = [(function_node) for function_node in get_all_function_nodes(experiment.optimization_graph)]

    #   NOTE: Multiprocessing disabled due to inconsistencies when modifying the graph
    #    with Pool(
    #    initializer=__initialize_worker,
    #    initargs=(experiment.optimization_graph, experiment),
    #    ) as pool:
    #        tmp_result = list(
    #            tqdm.tqdm(pool.imap_unordered(__collapse_loops_in_function, param_list), total=len(param_list))
    #        )
    for idx, function in enumerate(param_list):
        print("COLLAPSE LOOPS IN FUNCTION: ", idx, "/", len(param_list))
        __collapse_loops_in_function(function)

    return global_graph


def __initialize_worker(graph: nx.DiGraph, experiment: Experiment) -> None:
    global global_graph
    global global_experiment
    global_graph = graph
    global_experiment = experiment


def __collapse_loops_in_function(function_node_id: int) -> bool:
    """Return True, if a modification has been found. Return False otherwise."""
    global global_graph
    global global_experiment

    if global_experiment is None:
        raise ValueError("global_experiment is None!")
    if global_graph is None:
        raise ValueError("global_graph is None!")

    modifiation_found = True
    return_value = False
    visited_inner_loop: Set[int] = set()

    relevant_loops: Set[int] = set()
    for loop in get_all_loop_nodes(global_graph):
        if function_node_id in get_all_parents(global_graph, loop):
            relevant_loops.add(loop)

    while modifiation_found:
        modifiation_found = False

        #        # set of loops could change when modifications are applied, hence the copy
        #        loops = get_all_loop_nodes(global_graph)
        for loop in copy.deepcopy(relevant_loops):
            logging.info("Checking loop collapse for @ " + str(loop))
            loop_data = cast(Loop, data_at(global_graph, loop))
            #            if function_node_id not in get_all_parents(global_graph, loop):
            #                continue
            # loop contained in function
            # check for loop nesting
            queue: List[int] = get_parents(global_graph, loop)
            collapse_sources: Set[int] = set()
            while queue:
                current = queue.pop()
                logger.debug("\tCurrent: " + str(current))
                current_data = data_at(global_graph, current)

                if type(current_data) == Loop:
                    # parent is parallelizable loop -> collapse and end search
                    if current_data.suggestion_type == "do_all":
                        # if loops are located on the same device, collapse
                        if loop_data.device_id == current_data.device_id:
                            if loop not in visited_inner_loop:
                                # calculate distance of loop to parent to check for perfect nesting (distance <= 2 due to graph structure)
                                distance_to_parent = 0
                                inner_queue: List[Tuple[int, int]] = [(loop, 0)]
                                while inner_queue:
                                    logger.debug("\tInner queue: " + str(inner_queue))
                                    inner_current, tmp_dist = inner_queue.pop()
                                    preds = get_predecessors(global_graph, inner_current)
                                    if len(preds) == 0:
                                        if tmp_dist > distance_to_parent:
                                            distance_to_parent = tmp_dist
                                        continue
                                    else:
                                        inner_queue += [
                                            (
                                                p,
                                                (
                                                    tmp_dist
                                                    if isinstance(data_at(global_graph, p), ContextNode)
                                                    else tmp_dist + 1
                                                ),
                                            )
                                            for p in preds
                                        ]
                                logger.debug("\t\tCollapse at distance: " + str(distance_to_parent))
                                if distance_to_parent <= 2:
                                    collapse_sources.add(current)
                                    visited_inner_loop.add(loop)
                            continue
                    # parent is regular loop -> end search on this path
                    continue

                # parent is empty node -> skip
                if isinstance(current_data, Workload):
                    if current_data.sequential_workload == Integer(0):
                        queue += get_parents(global_graph, current)
                        continue
                # parent is regular node -> end search on this path (no perfect nesting)
                continue

            # validate collapse sources (check perfect nesting)
            # todo: improve check for perfect nesting using AST analysis or similar approach
            invalid: Set[int] = set()
            for csrc in collapse_sources:
                # check that only a single loop exists as a direct child
                queue = get_children(global_graph, csrc)
                ignore_list: List[int] = []
                found_loop: bool = False
                while queue:
                    current = queue.pop()
                    if type(data_at(global_graph, current)) == Loop and current not in ignore_list:
                        # more than one loop contained!
                        if found_loop:
                            invalid.add(csrc)
                            break
                        found_loop = True
                        ignore_list.append(current)
                        ignore_list += get_out_mutex_edges(global_graph, current)
                    queue += get_successors(global_graph, current)
                print()

            for inv in invalid:
                collapse_sources.remove(inv)

            # apply collapses
            for csrc in collapse_sources:
                modifiation_found = True
                # create new collapse node
                new_node_id = global_experiment.get_next_free_node_id()
                relevant_loops.add(new_node_id)
                node_data_copy = cast(Loop, copy.deepcopy(data_at(global_graph, csrc)))
                node_data_copy.node_id = new_node_id
                # increase and set collapse level
                node_data_copy.collapse_level = loop_data.collapse_level + 1

                # register a new pattern
                if node_data_copy.original_cu_id is None:
                    raise ValueError("Node is not assigned to an original cu id!")
                pattern_info = DoAllInfo(
                    global_experiment.detection_result.pet,
                    global_experiment.detection_result.pet.node_at(node_data_copy.original_cu_id),
                )
                pattern_id = pattern_info.pattern_id
                pattern_info.collapse_level = node_data_copy.collapse_level
                pattern_info.device_id = node_data_copy.device_id
                pattern_info.device_type = (
                    global_experiment.get_system().get_device(node_data_copy.device_id).get_device_type()
                )
                pattern_info.applicable_pattern = False  # patterns are only applicable via the optimizer output pattern interfaces due to potential data movement
                global_experiment.suggestion_to_node_ids_dict[pattern_id] = [new_node_id]
                global_experiment.node_id_to_suggestion_dict[new_node_id] = pattern_id

                # create a new node
                global_graph.add_node(new_node_id, data=node_data_copy)

                # copy edges
                for edge in global_graph.in_edges(csrc):
                    edge_data = copy.deepcopy(global_graph.edges[edge]["data"])
                    global_graph.add_edge(edge[0], new_node_id, data=edge_data)
                for edge in global_graph.out_edges(csrc):
                    edge_data = copy.deepcopy(global_graph.edges[edge]["data"])
                    global_graph.add_edge(new_node_id, edge[1], data=edge_data)
                # identify the sequential version of the inner loop
                seq_loop_option = -1
                for option in [
                    e[0] for e in global_graph.in_edges(loop, data="data") if isinstance(e[2], MutuallyExclusiveEdge)
                ]:
                    if cast(Loop, data_at(global_graph, option)).suggestion == None:
                        seq_loop_option = option
                        break
                # create a copy of the sequential version of the inner loop with only a single iteration
                copy_seq_loop_option_id = global_experiment.get_next_free_node_id()
                relevant_loops.add(copy_seq_loop_option_id)
                copy_seq_loop_option_data = copy.deepcopy(data_at(global_graph, seq_loop_option))
                copy_seq_loop_option_data.node_id = copy_seq_loop_option_id
                print("CREATED COPY LOOP: ", copy_seq_loop_option_id, "from ", seq_loop_option)

                cast(Loop, copy_seq_loop_option_data).iterations = 1
                cast(Loop, copy_seq_loop_option_data).iterations_symbol = Symbol(
                    "loop_"
                    + str(copy_seq_loop_option_id)
                    + "_pos_"
                    + str(cast(Loop, copy_seq_loop_option_data).position)
                    + "_iterations"
                )
                global_experiment.register_free_symbol(
                    cast(Loop, copy_seq_loop_option_data).iterations_symbol,
                    value_suggestion=Integer(cast(Loop, copy_seq_loop_option_data).iterations),
                )
                global_graph.add_node(copy_seq_loop_option_id, data=copy_seq_loop_option_data)

                # create a mutex edge between the original seq loop and the copied version
                global_graph.add_edge(copy_seq_loop_option_id, seq_loop_option, data=MutuallyExclusiveEdge())
                global_graph.add_edge(seq_loop_option, copy_seq_loop_option_id, data=MutuallyExclusiveEdge())

                # copy edges
                for edge in global_graph.in_edges(seq_loop_option):
                    edge_data = copy.deepcopy(global_graph.edges[edge]["data"])
                    global_graph.add_edge(edge[0], copy_seq_loop_option_id, data=edge_data)
                for edge in global_graph.out_edges(seq_loop_option):
                    edge_data = copy.deepcopy(global_graph.edges[edge]["data"])
                    global_graph.add_edge(copy_seq_loop_option_id, edge[1], data=edge_data)

                # update the iteration count for the collapse root
                cast(Loop, data_at(global_graph, new_node_id)).iterations *= cast(
                    Loop, data_at(global_graph, seq_loop_option)
                ).iterations
                cast(Loop, data_at(global_graph, new_node_id)).iterations_symbol = Symbol(
                    "loop_" + str(new_node_id) + "_pos_" + str(node_data_copy.position) + "_iterations"
                )
                global_experiment.register_free_symbol(
                    node_data_copy.iterations_symbol,
                    value_suggestion=Integer(node_data_copy.iterations),
                )

                # create a new requirements edge to the single-iteration sequential version of the inner loop
                global_graph.add_edge(copy_seq_loop_option_id, new_node_id, data=RequirementEdge())
                global_graph.add_edge(new_node_id, copy_seq_loop_option_id, data=RequirementEdge())

                # register pattern for output
                # todo: find a nicer solution to duplicating the patterns for each device mapping
                global_experiment.detection_result.patterns.do_all.append(pattern_info)
                # construct optimizer output pattern to represent the non-standalone pattern_info
                optimizer_output_pattern = OptimizerOutputPattern(
                    pattern_info._node,
                    [new_node_id],
                    global_experiment.get_system().get_host_device_id(),
                    global_experiment,
                )
                optimizer_output_pattern.add_pattern(
                    pattern_info.pattern_id, pattern_info.device_id, pattern_info.device_type
                )
                global_experiment.detection_result.patterns.optimizer_output.append(optimizer_output_pattern)
                print("REGISTERED PATTERN INFO: ", pattern_id, " for Device: ", data_at(global_graph, csrc).device_id)
                print(pattern_info)
                print()

        return_value = return_value or modifiation_found
    return return_value
