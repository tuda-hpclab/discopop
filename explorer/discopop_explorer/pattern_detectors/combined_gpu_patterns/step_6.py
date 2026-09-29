# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import sys
from typing import Any, Set, Tuple, Dict, List, cast, Union

from networkx import MultiDiGraph  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_predecessor import is_predecessor
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.paths import get_path_nodes_between
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.EntryPoint import EntryPoint
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Enums import (
    UpdateType,
    EntryPointType,
    ExitPointType,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.ExitPoint import ExitPoint
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Update import Update


def convert_updates_to_entry_and_exit_points(
    pet: PEGraphX,
    issued_updates: Set[Update],
    memory_region_liveness_by_device: Dict[int, Dict[MemoryRegion, List[NodeID]]],
) -> Tuple[Set[EntryPoint], Set[ExitPoint], Set[Update]]:
    entry_points: Set[EntryPoint] = set()
    exit_points: Set[ExitPoint] = set()
    updates: Set[Update] = set()

    for issued_update in issued_updates:
        if issued_update.update_type == UpdateType.TO_DEVICE or issued_update.update_type == UpdateType.ALLOCATE:
            # check if the memory region was live on the device before the update
            qualifies_as_entry = True
            for mem_reg in issued_update.memory_regions:
                if mem_reg not in memory_region_liveness_by_device[1]:
                    continue
                if issued_update.synchronous_source_cu_id in memory_region_liveness_by_device[1][mem_reg]:
                    qualifies_as_entry = False
                    break
            if qualifies_as_entry:
                if issued_update.update_type == UpdateType.TO_DEVICE:
                    if issued_update.asynchronous_possible:
                        # asynchronous entry possible
                        enp = EntryPoint(
                            pet,
                            issued_update.variable_names,
                            issued_update.memory_regions,
                            cast(NodeID, issued_update.asynchronous_source_cu_id),
                            issued_update.sink_cu_id,
                            EntryPointType.ASYNC_TO_DEVICE,
                        )
                        # add dependencies to EntryPoint
                        for dependency in issued_update.dependencies:
                            enp.dependencies.add(dependency)
                        entry_points.add(enp)
                    else:
                        # asynchronous entry not possible
                        # create a synchronous entry point
                        entry_points.add(
                            EntryPoint(
                                pet,
                                issued_update.variable_names,
                                issued_update.memory_regions,
                                issued_update.synchronous_source_cu_id,
                                issued_update.sink_cu_id,
                                EntryPointType.TO_DEVICE,
                            )
                        )
                else:
                    entry_points.add(
                        EntryPoint(
                            pet,
                            issued_update.variable_names,
                            issued_update.memory_regions,
                            issued_update.synchronous_source_cu_id,
                            issued_update.sink_cu_id,
                            EntryPointType.ALLOCATE,
                        )
                    )
            else:
                updates.add(issued_update)

        elif issued_update.update_type == UpdateType.FROM_DEVICE:
            # check if the memory region is live on the device after the update
            qualifies_as_exit = True
            for mem_reg in issued_update.memory_regions:
                if mem_reg not in memory_region_liveness_by_device[1]:
                    continue
                if issued_update.sink_cu_id in memory_region_liveness_by_device[1][mem_reg]:
                    qualifies_as_exit = False
                    break
            if qualifies_as_exit:
                # check if asynchronous exiting is possible
                if issued_update.asynchronous_possible:
                    # asynchronous exit possible
                    exp = ExitPoint(
                        pet,
                        issued_update.variable_names,
                        issued_update.memory_regions,
                        cast(NodeID, issued_update.asynchronous_source_cu_id),
                        issued_update.sink_cu_id,
                        ExitPointType.ASYNC_FROM_DEVICE,
                    )
                    # add dependencies to EntryPoint
                    for dependency in issued_update.dependencies:
                        exp.dependencies.add(dependency)
                    exit_points.add(exp)
                else:
                    # asynchronous exiting not possible
                    exit_points.add(
                        ExitPoint(
                            pet,
                            issued_update.variable_names,
                            issued_update.memory_regions,
                            issued_update.synchronous_source_cu_id,
                            issued_update.sink_cu_id,
                            ExitPointType.FROM_DEVICE,
                        )
                    )
            else:
                updates.add(issued_update)
        else:
            raise ValueError("Unsupported update type: ", issued_update.update_type)

    return entry_points, exit_points, updates


def add_aliases(
    pet: PEGraphX,
    issued_updates: Set[Update],
    memory_regions_to_functions_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]],
) -> Set[Update]:
    for update in issued_updates:
        source_parent_function_node = get_parent_function(pet, pet.node_at(update.synchronous_source_cu_id))
        sink_parent_function_node = get_parent_function(pet, pet.node_at(update.sink_cu_id))
        if source_parent_function_node == sink_parent_function_node:
            # add alias information from function level
            modification_found = True
            while modification_found:
                modification_found = False
                # add missing variable names
                for mem_reg in update.memory_regions:
                    alias_var_names = memory_regions_to_functions_and_variables[mem_reg][source_parent_function_node.id]
                    len_pre = len(update.variable_names)
                    update.variable_names.update(alias_var_names)
                    # add variable name to dependency if required
                    for dependency in update.dependencies:
                        if mem_reg in dependency.memory_regions:
                            dependency.var_names.update(alias_var_names)
                    len_post = len(update.variable_names)
                    if len_pre != len_post:
                        modification_found = True

                # add missing memory regions
                for var_name in update.variable_names:
                    for mem_reg in memory_regions_to_functions_and_variables:
                        if source_parent_function_node.id not in memory_regions_to_functions_and_variables[mem_reg]:
                            continue
                        potential_aliases = memory_regions_to_functions_and_variables[mem_reg][
                            source_parent_function_node.id
                        ]
                        if var_name in potential_aliases:
                            len_pre = len(update.memory_regions)
                            update.memory_regions.add(mem_reg)
                            len_post = len(update.memory_regions)
                            if len_pre != len_post:
                                modification_found = True

    return issued_updates


def identify_end_of_life_points(
    pet: PEGraphX,
    entry_points: Set[EntryPoint],
    exit_points: Set[ExitPoint],
    memory_region_liveness_by_device: Dict[int, Dict[MemoryRegion, List[NodeID]]],
    memory_regions_to_functions_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]],
) -> Set[ExitPoint]:
    eol_points: Set[Tuple[NodeID, NodeID, Tuple[MemoryRegion, ...]]] = set()

    print("Identifying end of live for variables...", file=sys.stderr)

    # get list of seen aliases:
    mem_reg_aliases: Dict[MemoryRegion, Set[MemoryRegion]] = dict()
    for entry_point in entry_points:
        for mem_reg in entry_point.memory_regions:
            if mem_reg not in mem_reg_aliases:
                mem_reg_aliases[mem_reg] = set()
            mem_reg_aliases[mem_reg].update(entry_point.memory_regions)
    for exit_point in exit_points:
        for mem_reg in exit_point.memory_regions:
            if mem_reg not in mem_reg_aliases:
                mem_reg_aliases[mem_reg] = set()
            mem_reg_aliases[mem_reg].update(exit_point.memory_regions)

    print("\tUsed Aliases: ", mem_reg_aliases, file=sys.stderr)

    # actual search for EOL
    for device_id in memory_region_liveness_by_device:
        if device_id == 0:
            # do not search for EOL on host
            continue
        for mem_reg in memory_region_liveness_by_device[device_id]:
            # check if mem_reg is live in all successors of all contained cu's
            for cu_id in memory_region_liveness_by_device[device_id][mem_reg]:
                for successor_node in direct_successors(pet, pet.node_at(cu_id)):
                    if successor_node.id not in memory_region_liveness_by_device[device_id][mem_reg]:
                        # mem_reg is not live anymore. create an EOL point
                        if mem_reg in mem_reg_aliases:
                            eol_points.add(
                                (
                                    cu_id,
                                    successor_node.id,
                                    tuple(mem_reg_aliases[mem_reg]),
                                )
                            )
                        else:
                            eol_points.add((cu_id, successor_node.id, tuple([mem_reg])))

    # remove eols which are covered by known exit points
    for exit_point in exit_points:
        to_be_removed: Set[Tuple[NodeID, NodeID, Tuple[MemoryRegion, ...]]] = set()
        for eol in eol_points:
            # check if either exit_point is reachable from eol or vice versa.
            # in both cases, eol is covered by the exit_point and can be ignored
            if (
                (
                    is_predecessor(pet, exit_point.source_cu_id, eol[0])
                    and is_predecessor(pet, exit_point.sink_cu_id, eol[1])
                )
                or is_predecessor(pet, eol[0], exit_point.source_cu_id)
                and is_predecessor(pet, eol[1], exit_point.sink_cu_id)
            ):
                # check if memory regions overlap, i.e. if the exit_point covers eol
                if len([mem_reg for mem_reg in exit_point.memory_regions if mem_reg in eol[2]]) > 0:
                    # overlap exists, remove eol
                    to_be_removed.add(eol)

        for elem in to_be_removed:
            if elem in eol_points:
                eol_points.remove(elem)

    eol_exit_points: Set[ExitPoint] = set()
    for eol in eol_points:
        parent_function_node_id = get_parent_function(pet, pet.node_at(eol[0])).id
        var_names: Set[VarName] = set()
        for mem_reg in eol[2]:
            if parent_function_node_id in memory_regions_to_functions_and_variables[mem_reg]:
                var_names.update(memory_regions_to_functions_and_variables[mem_reg][parent_function_node_id])
        memory_regions = set(eol[2])
        # check if the exited data is required by another function
        # if so, mark the exit point as ExitPointType.FROM
        path_nodes = get_path_nodes_between(
            pet,
            cast(CUNode, pet.node_at(eol[1])),
            cast(CUNode, pet.node_at(eol[0])),
            [EdgeType.SUCCESSOR, EdgeType.CHILD],
        )

        in_raw_edges_from_outside = []
        for path_node in path_nodes:
            in_raw_edges_from_outside += [
                (s, t, d)
                for s, t, d in in_edges(pet, path_node.id, EdgeType.DATA)
                if d.dtype == DepType.RAW
                and d.memory_region in memory_regions
                and get_parent_function(pet, pet.node_at(s)) != get_parent_function(pet, pet.node_at(t))
            ]
        if len(in_raw_edges_from_outside) > 0:
            # value is read -> Copy back to the host so the value does not get discarded
            eol_exit_points.add(ExitPoint(pet, var_names, memory_regions, eol[0], eol[1], ExitPointType.FROM_DEVICE))
        else:
            # otherwise, mark it as ExitPointType.DELETE
            eol_exit_points.add(ExitPoint(pet, var_names, memory_regions, eol[0], eol[1], ExitPointType.DELETE))

    print("\tDone.", file=sys.stderr)
    print(file=sys.stderr)

    return eol_exit_points


def extend_region_liveness_using_unrolled_functions(
    pet: PEGraphX,
    liveness: Dict[MemoryRegion, List[NodeID]],
    unrolled_function_graphs: Dict[FunctionNode, MultiDiGraph],
) -> Dict[MemoryRegion, List[NodeID]]:
    # TODO: potential optimization: invert the 'liveness' dict to allow faster membership check

    for function in all_nodes(pet, FunctionNode):
        print("FUNCTION: ", function.name)
        unrolled_function_graph = unrolled_function_graphs[function]
        queue: List[Tuple[NodeID, MemoryRegion, List[NodeID]]] = []
        # initialize queue
        # entry_node_id = function.get_entry_cu_id(pet)
        for child_node_id in cast(List[NodeID], function.children_cu_ids):
            for mem_reg in liveness:
                if child_node_id in liveness[mem_reg]:
                    queue.append((child_node_id, mem_reg, []))

        # process queue
        while queue:
            print("Queue len: ", len(queue))
            current_node_id, current_mem_reg, visited_nodes = queue.pop()
            visited_nodes.append(current_node_id)

            successors = [t for s, t, d in unrolled_function_graph.out_edges(current_node_id, data="data")]

            for successor in successors:
                # if mem_reg is live in successor, create a new, clean queue entry and set all visited nodes to live
                # else, create a new queue entry for the successor and use visited_nodes again

                if successor in liveness[current_mem_reg]:
                    # create a clean queue entry
                    queue.append((successor, current_mem_reg, []))
                    # set visited nodes to live
                    for node_id in visited_nodes:
                        if node_id not in liveness[current_mem_reg]:
                            liveness[current_mem_reg].append(node_id)
                            print("Set ", current_mem_reg, " live in ", node_id)
                else:
                    queue.append((successor, current_mem_reg, copy.deepcopy(visited_nodes)))

    return liveness


def remove_duplicates(
    target_set: Union[Set[Update], Set[EntryPoint], Set[ExitPoint]],
) -> Union[Set[Update], Set[EntryPoint], Set[ExitPoint]]:
    to_be_removed = []
    for element_1 in target_set:
        for element_2 in target_set:
            if element_1 is element_2:
                continue
            if element_1 == element_2:
                to_be_removed.append(element_2)

    for element in to_be_removed:
        if element in target_set:
            target_set.remove(element)  # type: ignore

    return target_set


def join_update_elements(target_set: Set[Update]) -> Set[Update]:
    grouping_dict: Dict[Any, List[Any]] = dict()

    for elem in target_set:
        if elem.get_position_identifier() not in grouping_dict:
            grouping_dict[elem.get_position_identifier()] = []
        grouping_dict[elem.get_position_identifier()].append(elem)

    result_set = set()

    for key in grouping_dict:
        # assemble a single EntryPoint
        joined_entry_point = None
        for elem in grouping_dict[key]:
            if joined_entry_point is None:
                joined_entry_point = elem
            else:
                joined_entry_point.join(elem)
        result_set.add(cast(Update, joined_entry_point))

    return result_set


def join_entryPoint_elements(target_set: Set[EntryPoint]) -> Set[EntryPoint]:
    grouping_dict: Dict[Any, List[Any]] = dict()

    for elem in target_set:
        if elem.get_position_identifier() not in grouping_dict:
            grouping_dict[elem.get_position_identifier()] = []
        grouping_dict[elem.get_position_identifier()].append(elem)

    result_set = set()

    for key in grouping_dict:
        # assemble a single EntryPoint
        joined_entry_point = None
        for elem in grouping_dict[key]:
            if joined_entry_point is None:
                joined_entry_point = elem
            else:
                joined_entry_point.join(elem)
        result_set.add(cast(EntryPoint, joined_entry_point))

    return result_set


def join_exitPoint_elements(target_set: Set[ExitPoint]) -> Set[ExitPoint]:
    grouping_dict: Dict[Any, List[Any]] = dict()

    for elem in target_set:
        if elem.get_position_identifier() not in grouping_dict:
            grouping_dict[elem.get_position_identifier()] = []
        grouping_dict[elem.get_position_identifier()].append(elem)

    result_set = set()

    for key in grouping_dict:
        # assemble a single EntryPoint
        joined_entry_point = None
        for elem in grouping_dict[key]:
            if joined_entry_point is None:
                joined_entry_point = elem
            else:
                joined_entry_point.join(elem)
        result_set.add(cast(ExitPoint, joined_entry_point))

    return result_set
