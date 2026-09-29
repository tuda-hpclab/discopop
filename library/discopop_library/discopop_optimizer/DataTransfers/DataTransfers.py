# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, List, Optional, Set, Tuple, cast

import networkx as nx  # type: ignore
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.enums.EdgeType import EdgeType

from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.nodes.ContextNode import ContextNode
from discopop_library.discopop_optimizer.classes.nodes.DeviceSwitch import DeviceSwitch
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.nodes.SynchronizationTrigger import SynchronizationTrigger
from discopop_library.discopop_optimizer.classes.types.DataAccessType import ReadDataAccess, WriteDataAccess
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_all_nodes_in_function,
    get_function_return_node,
    get_predecessors,
    get_requirements,
    get_successors,
    get_children,
    show,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def calculate_data_transfers(
    graph: nx.DiGraph, function_performance_models: Dict[FunctionRoot, List[CostModel]], experiment: Experiment
) -> Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]]:
    """Calculate data transfers for each performance model and append the respective ContextObject to the result."""
    result_dict: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]] = dict()
    for function in function_performance_models:
        result_dict[function] = []
        for model in function_performance_models[function]:
            # create a ContextObject for the current path
            context = ContextObject(function.node_id, [function.device_id])
            context = get_path_context_iterative(
                function.node_id, graph, model, context, experiment, top_level_call=False
            )
            result_dict[function].append((model, context))
    return result_dict


def get_path_context_iterative(
    root_node_id: int,
    graph: nx.DiGraph,
    model: CostModel,
    context: ContextObject,
    experiment: Experiment,
    top_level_call: bool = False,
) -> ContextObject:
    """passes the context Object along the path and returns the context once the end has been reached"""
    node_id = None
    next_node_id: Optional[int] = root_node_id

    while next_node_id is not None:
        node_id = next_node_id

        # push device id to stack if necessary
        node_data = data_at(graph, node_id)
        if node_data.device_id is not None:
            context.last_seen_device_ids.append(node_data.device_id)

        # calculate context modifications for the current node
        context = __check_current_node(node_id, graph, model, context, experiment)

        # set last_visited_device id
        if node_data.device_id is not None:
            context.last_visited_device_id = node_data.device_id
        else:
            context.last_visited_device_id = context.last_seen_device_ids[-1]

        # calculate context modifications for the children of the current node
        context = __check_children(node_id, graph, model, context, experiment)

        # pop device id from stack if necessary
        if node_data.device_id is not None:
            # condition to prevent issues due to added dummy nodes
            if len(context.last_seen_device_ids) > 1:
                context.last_seen_device_ids.pop()

        # set last_visited_node_id to the original node_id,
        # since the calculation continues from node_id after the children have been visited
        context.last_visited_node_id = node_id

        # pass context to the right successor of the current node
        # At most a single node can be a successor, since the given model represents a single path through the graph.
        successors = get_successors(graph, node_id)
        if len(successors) == 0:
            # stop the loop
            next_node_id = None
        elif len(successors) == 1:
            # pass context to the single successor
            next_node_id = successors[0]
        else:
            # multiple successors exist
            # find the successor which represents the path decision included in the model
            suitable_successors = [succ for succ in successors if succ in model.path_decisions]
            if len(suitable_successors) != 1:
                requirements: List[int] = []
                for dec in model.path_decisions:
                    requirements += [r for r in get_requirements(graph, dec) if r not in requirements]
                if len(requirements) == 0:
                    # select the sequential version
                    for succ in successors:
                        if data_at(graph, succ).represents_sequential_version() and data_at(graph, succ).device_id in [
                            None,
                            experiment.get_system().get_host_device_id(),
                        ]:
                            suitable_successors = [succ]
                            model.path_decisions.append(succ)
                            break
                else:
                    # select the correct successor
                    for succ in successors:
                        if succ in requirements:
                            suitable_successors = [succ]
                            model.path_decisions.append(succ)
                            break
                if len(suitable_successors) != 1:
                    print("No correction possible")
                    show(graph)

                    raise ValueError(
                        "Invalid amount of potential successors (",
                        len(suitable_successors),
                        ") for path split at node:",
                        node_id,
                        "using decisions: ",
                        model.path_decisions,
                        "successors:",
                        successors,
                    )
            # suitable successor identified.
            # pass the current context to the successor
            next_node_id = suitable_successors[0]

    # force update to host device of the function (not system host device, to allow offloading functions to devices)
    # TODO CURRENTLY UNUSED, REACTIVATE?
    if top_level_call:
        # force synchronization with executing device

        # create a filter for the data accesses to be synchronized
        # only consider such memory regions which are used outside the function
        filter: Set[MemoryRegion] = set()
        nodes_in_function = get_all_nodes_in_function(graph, root_node_id)
        cu_nodes_in_function = set([data_at(graph, n).original_cu_id for n in nodes_in_function])
        for node in nodes_in_function:
            node_data = data_at(graph, node)
            if node_data.original_cu_id is None:
                continue
            for out_dep_edge in out_edges(
                experiment.detection_result.pet, node_data.original_cu_id, etype=EdgeType.DATA
            ):
                target = out_dep_edge[1]
                if target in cu_nodes_in_function:
                    continue
                # target outside the function. MemoryRegions qualifies for synchronization at the end of the function
                if out_dep_edge[2].memory_region is None:
                    raise ValueError("Value is None!")
                filter.add(out_dep_edge[2].memory_region)

        # collect all write data accesses which might need synchronization
        seen_writes: Set[WriteDataAccess] = set()
        for device_id in context.seen_writes_by_device:
            for mem_reg in context.seen_writes_by_device[device_id]:
                for wda in context.seen_writes_by_device[device_id][mem_reg]:
                    # check wda against filter
                    if wda.memory_region in filter:
                        seen_writes.add(wda)

        reading_device_id = data_at(graph, root_node_id).device_id
        reading_device_id = (
            experiment.get_system().get_host_device_id() if reading_device_id is None else reading_device_id
        )
        forced_sync_context = context.calculate_and_perform_necessary_updates(
            cast(Set[ReadDataAccess], seen_writes),
            reading_device_id,
            get_function_return_node(graph, root_node_id),
            graph,
            experiment,
        )

        # add the writes performed by the given node to the context
        forced_sync_context = forced_sync_context.add_writes(
            node_data.written_memory_regions, cast(int, context.last_seen_device_ids[-1])
        )

    return context


def get_path_context(
    node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject, experiment: Experiment
) -> ContextObject:
    """passes the context Object along the path and returns the context once the end has been reached"""
    # push device id to stack if necessary
    node_data = data_at(graph, node_id)
    if node_data.device_id is not None:
        context.last_seen_device_ids.append(node_data.device_id)

    # calculate context modifications for the current node
    context = __check_current_node(node_id, graph, model, context, experiment)

    # calculate context modifications for the children of the current node
    context = __check_children(node_id, graph, model, context, experiment)

    # pop device id from stack if necessary
    if node_data.device_id is not None:
        context.last_seen_device_ids.pop()

    # set last_visited_node_id to the original node_id,
    # since the calculation continues from node_id after the children have been visited
    context.last_visited_node_id = node_id

    # pass context to the right successor of the current node
    # At most a single node can be a successor, since the given model represents a single path through the graph.
    successors = get_successors(graph, node_id)
    if len(successors) == 1:
        # pass context to the single successor
        return get_path_context(successors[0], graph, model, context, experiment)

    elif len(successors) == 0:
        # no successor exists, return the current context
        return context

    else:
        # multiple successors exist
        # find the successor which represents the path decision included in the model
        suitable_successors = [succ for succ in successors if succ in model.path_decisions]
        if len(suitable_successors) != 1:
            requirements: List[int] = []
            for dec in model.path_decisions:
                requirements += [r for r in get_requirements(graph, dec) if r not in requirements]
            if len(requirements) == 0:
                # select the sequential version
                for succ in successors:
                    if data_at(graph, succ).represents_sequential_version() and data_at(graph, succ).device_id in [
                        None,
                        experiment.get_system().get_host_device_id(),
                    ]:
                        suitable_successors = [succ]
                        model.path_decisions.append(succ)
                        break
            else:
                # select the correct successor
                for succ in successors:
                    if succ in requirements:
                        suitable_successors = [succ]
                        model.path_decisions.append(succ)
                        break
            if len(suitable_successors) != 1:
                print("No correction possible")
                show(graph)

                raise ValueError(
                    "Invalid amount of potential successors (",
                    len(suitable_successors),
                    ") for path split at node:",
                    node_id,
                    "using decisions: ",
                    model.path_decisions,
                    "successors:",
                    successors,
                )
        # suitable successor identified.
        # pass the current context to the successor
        return get_path_context(suitable_successors[0], graph, model, context, experiment)


def __check_current_node(
    node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject, experiment: Experiment
) -> ContextObject:
    """Check if the given node results in modifications to the given context.
    Return a modified version of the context which contains the required updates."""
    # due to the Read-Compute-Write paradigm used to create the Computational Units,
    # this structure is assumed for the nodes and their MemoryAccesses as well.

    # check if any data needs to be updated from a different device before reading
    # if so, the context will be supplemented with the identified updates
    node_data = data_at(graph, node_id)

    if isinstance(node_data, ContextNode):
        # apply modifications according to encountered context node
        updated_context = cast(ContextNode, data_at(graph, node_id)).get_modified_context(
            node_id, graph, model, context
        )
        return updated_context

    # only allow updates on device switches

    device_switch_occured = False
    if data_at(graph, node_id).device_id is None:
        if context.last_seen_device_ids[-1] != context.last_visited_device_id:
            device_switch_occured = True
    elif context.last_visited_device_id != data_at(graph, node_id).device_id:
        device_switch_occured = True

    # TODO: if a device switch is encountered, collect read / written data unitl next device switch

    #    if device_switch or type(node_data) == SynchronizationTrigger or True:

    if type(node_data) == SynchronizationTrigger or type(node_data) == DeviceSwitch:
        # identify updates at a designated synchronization point
        context = context.calculate_and_perform_necessary_updates(
            node_data.read_memory_regions,
            cast(int, context.last_seen_device_ids[-1]),
            node_data.node_id,
            graph,
            experiment,
        )
    elif device_switch_occured:
        # identify updates due to suggestion entries
        # attribute the updates to the last visited DeviceSwitch if necessary
        last_seen_device_switch_node = None
        queue = [node_id]
        while len(queue) > 0:
            current = queue.pop()
            current_data = data_at(graph, current)
            if type(current_data) == DeviceSwitch:
                last_seen_device_switch_node = current
                break
            queue += [p for p in get_predecessors(graph, current) if p not in queue]

        if last_seen_device_switch_node is not None:
            context = context.calculate_and_perform_necessary_updates(
                node_data.read_memory_regions,
                cast(int, context.last_seen_device_ids[-1]),
                last_seen_device_switch_node,
                graph,
                experiment,
                updates_originated_from=node_id,
            )
        else:
            # this can be the case for function nodes and similar
            pass

    # add the writes performed by the given node to the context
    context = context.add_writes(node_data.written_memory_regions, cast(int, context.last_seen_device_ids[-1]))

    return context


def __check_children(
    node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject, experiment: Experiment
) -> ContextObject:
    # pass context to all children
    for child in get_children(graph, node_id):
        # reset last_visited_node_id inbetween visiting children
        context.last_visited_node_id = node_id
        context = get_path_context_iterative(child, graph, model, context, experiment)
    return context
