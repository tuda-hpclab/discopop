# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import sys
from typing import Dict, Set, Tuple, Optional, List, cast

import networkx as nx  # type: ignore
from networkx import NetworkXNoCycle, MultiDiGraph

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_predecessor import is_predecessor
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.pattern_detectors.combined_gpu_patterns.CombinedGPURegions import CombinedGPURegion
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Enums import UpdateType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Update import Update


class Context(object):
    cu_id: NodeID
    device_id: int
    seen_writes_by_device: Dict[int, Dict[MemoryRegion, Set[Tuple[Optional[int], Optional[NodeID]]]]]

    def __init__(self, cu_id: NodeID, device_id: int):
        self.cu_id = cu_id
        self.device_id = device_id
        self.seen_writes_by_device = dict()
        self.print()

    def __str__(self) -> str:
        result_str = ""
        result_str += "Context:\n"
        result_str += "\tcu_id: " + str(self.cu_id) + "\n"
        result_str += "\tdevice: " + str(self.device_id) + "\n"
        result_str += "\twrites:\n"
        for device_id in self.seen_writes_by_device:
            result_str += "\t\tDEVICE: " + str(device_id) + "\n"
            for mem_reg in self.seen_writes_by_device[device_id]:
                result_str += "\t\t\t" + mem_reg + ": "
                for ident in self.seen_writes_by_device[device_id][mem_reg]:
                    result_str += str(ident) + ", "
                result_str += "\n"
            result_str += "\n"
        return result_str

    def print(self) -> None:
        print(self, file=sys.stderr)

    def update_writes(
        self,
        device_id_to_update: int,
        writes: Dict[MemoryRegion, Set[Optional[int]]],
        origin_cu_id: NodeID,
    ) -> Set[Tuple[MemoryRegion, bool]]:
        """Returns the updated memory regions"""
        updated_memory_regions: Set[Tuple[MemoryRegion, bool]] = set()

        if device_id_to_update not in self.seen_writes_by_device:
            self.seen_writes_by_device[device_id_to_update] = dict()
        for mem_reg in writes:
            is_initialization = (
                True
                if (mem_reg not in self.seen_writes_by_device[device_id_to_update])
                and (mem_reg not in self.seen_writes_by_device[self.device_id])
                else False
            )
            if mem_reg not in self.seen_writes_by_device[device_id_to_update]:
                self.seen_writes_by_device[device_id_to_update][mem_reg] = set()
                print("==> added ", mem_reg, " to device: ", device_id_to_update, file=sys.stderr)
            for ident in writes[mem_reg]:
                if ident not in [t[0] for t in self.seen_writes_by_device[device_id_to_update][mem_reg]]:
                    # list of seen writes will be updated
                    updated_memory_regions.add((mem_reg, is_initialization))
                    print(
                        "--> adding memreg: ",
                        mem_reg,
                        " ident: ",
                        ident,
                        " initialization? ",
                        is_initialization,
                        file=sys.stderr,
                    )
                print("ADD : ", (ident, origin_cu_id), file=sys.stderr)
                # todo: do not simply add, but replace current entry with origin_cu_id if it is a successor of the current entry
                #  necessary, since relying on set behavior is not sufficient anymore
                if ident not in [t[0] for t in self.seen_writes_by_device[device_id_to_update][mem_reg]]:
                    self.seen_writes_by_device[device_id_to_update][mem_reg].add((ident, origin_cu_id))
        return updated_memory_regions

    def find_required_updates(self, pet: PEGraphX, new_device_id: int) -> Set[Tuple[MemoryRegion, int, int, NodeID]]:
        # update required, if seen writes of new device is not a superset of old device id
        required_updates: Set[Tuple[MemoryRegion, int, int, NodeID]] = set()

        # check if unsynchronized changes exist
        device_id_1 = self.device_id
        device_id_2 = new_device_id

        overlapping_mem_reg = [
            mem_reg
            for mem_reg in self.seen_writes_by_device[device_id_1]
            if mem_reg in self.seen_writes_by_device[device_id_2]
        ]
        for mem_reg in overlapping_mem_reg:
            # issue update, if writes of new device is not a superset of old device
            missing_write_identifiers = [
                (ident, origin)
                for (ident, origin) in self.seen_writes_by_device[device_id_1][mem_reg]
                if ident not in [t[0] for t in self.seen_writes_by_device[device_id_2][mem_reg]] and ident is not None
            ]
            if len(missing_write_identifiers) > 0:
                # get position of the last write
                last_write_location: Optional[NodeID] = None
                for ident, origin in missing_write_identifiers:
                    if last_write_location is None:
                        last_write_location = origin
                    if is_predecessor(pet, cast(NodeID, last_write_location), cast(NodeID, origin)):
                        last_write_location = origin

                required_updates.add((mem_reg, device_id_1, device_id_2, cast(NodeID, last_write_location)))

        return required_updates

    def synchronize_states(self, new_device_id: int) -> None:
        overlapping_mem_reg = [
            mem_reg
            for mem_reg in self.seen_writes_by_device[self.device_id]
            if mem_reg in self.seen_writes_by_device[new_device_id]
        ]
        for mem_reg in overlapping_mem_reg:
            # synchronize from old to new device
            # issue update, if writes of new device is not a superset of old device
            for ident, origin in self.seen_writes_by_device[self.device_id][mem_reg]:
                if ident not in [t[0] for t in self.seen_writes_by_device[new_device_id][mem_reg]]:
                    print("SYNCHRONIZED: ", mem_reg, (ident, origin), file=sys.stderr)
                self.seen_writes_by_device[new_device_id][mem_reg].add((ident, origin))

    def request_updates_from_other_devices(
        self, pet: PEGraphX, new_device_id: int
    ) -> Set[Tuple[MemoryRegion, int, int, NodeID]]:
        required_updates: Set[Tuple[MemoryRegion, int, int, NodeID]] = set()
        to_be_removed = set()
        for mem_reg in self.seen_writes_by_device[new_device_id]:
            # check if updates on other devices exist
            for other_device_id in self.seen_writes_by_device:
                if other_device_id == new_device_id:
                    continue
                if mem_reg not in self.seen_writes_by_device[other_device_id]:
                    continue
                # update exist, if entries for new_device_id are not a superset of other_device_id
                missing_identifiers = [
                    (ident, origin)
                    for (ident, origin) in self.seen_writes_by_device[other_device_id][mem_reg]
                    if ident not in [t[0] for t in self.seen_writes_by_device[new_device_id][mem_reg]]
                ]
                if len(missing_identifiers) > 0:
                    # get position of the last write
                    last_write_location: Optional[NodeID] = None
                    for ident, origin in missing_identifiers:
                        if last_write_location is None:
                            last_write_location = origin
                        if is_predecessor(pet, cast(NodeID, last_write_location), cast(NodeID, origin)):
                            last_write_location = origin

                    required_updates.add((mem_reg, other_device_id, new_device_id, cast(NodeID, last_write_location)))

                # remove none identifier
                for ident, origin in self.seen_writes_by_device[new_device_id][mem_reg]:
                    if ident is None:
                        to_be_removed.add((new_device_id, mem_reg, (ident, origin)))

        # update seen writes according to required updates
        for mem_reg, other_device_id, new_device_id, last_write_location in required_updates:
            missing_identifiers = [
                (ident, origin)
                for (ident, origin) in self.seen_writes_by_device[other_device_id][mem_reg]
                if ident not in [t[0] for t in self.seen_writes_by_device[new_device_id][mem_reg]]
            ]

            print("ADDING: ", missing_identifiers, " TO ", mem_reg, file=sys.stderr)

            self.seen_writes_by_device[new_device_id][mem_reg].update(missing_identifiers)

        for entry in to_be_removed:
            if entry[2] in self.seen_writes_by_device[entry[0]][entry[1]]:
                self.seen_writes_by_device[entry[0]][entry[1]].remove(entry[2])
        return required_updates

    def update_to(
        self,
        pet: PEGraphX,
        next_cu_id: NodeID,
        comb_gpu_reg: CombinedGPURegion,
        writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]],
    ) -> Set[Update]:
        print("UPDATE TO: ", next_cu_id, file=sys.stderr)

        required_updates: Set[Update] = set()
        # cuid is always the CUID currently saved in the context

        # calculate device id of new cu
        new_device_id = get_device_id(comb_gpu_reg, next_cu_id)

        # check for device switch
        device_switch_occurred = True if new_device_id != self.device_id else False

        # apply updates to written memory regions
        writes_for_update = dict()
        if next_cu_id in writes_by_device[new_device_id]:
            writes_for_update = writes_by_device[new_device_id][next_cu_id]
        self_updated_memory_regions = self.update_writes(new_device_id, writes_for_update, next_cu_id)
        print("UPDATED MEMORY REGIONS: ", self_updated_memory_regions, file=sys.stderr)

        # identify required updates
        updated_memory_regions = self.find_required_updates(pet, new_device_id)

        # synchronize states between old and new device
        self.synchronize_states(new_device_id)

        # check if update has to be requested from other device due to a read (identifier: None)
        requested_updates = self.request_updates_from_other_devices(pet, new_device_id)

        # report data movement
        for mem_reg, from_device, to_device, last_write_to_mem_reg in updated_memory_regions:
            update_direction = get_update_type(from_device, to_device)
            print(
                "REPORTED! ",
                update_direction,
                " -> ",
                str(mem_reg),
                from_device,
                "->",
                to_device,
                " last_write@",
                last_write_to_mem_reg,
                file=sys.stderr,
            )
            required_updates.add(
                Update(
                    self.cu_id,
                    next_cu_id,
                    {mem_reg},
                    update_direction,
                    {mem_reg: last_write_to_mem_reg},
                )
            )

        # report data movement
        for mem_reg, from_device, to_device, last_write_to_mem_reg in requested_updates:
            update_direction = get_update_type(from_device, to_device)
            print(
                "REQUESTED! ",
                update_direction,
                " -> ",
                str(mem_reg),
                from_device,
                "->",
                to_device,
                " last_write@",
                last_write_to_mem_reg,
                file=sys.stderr,
            )
            required_updates.add(
                Update(
                    self.cu_id,
                    next_cu_id,
                    {mem_reg},
                    update_direction,
                    {mem_reg: last_write_to_mem_reg},
                )
            )

        # update the context
        self.cu_id = next_cu_id
        self.device_id = new_device_id

        print("DONE: \n", file=sys.stderr)

        return required_updates


def get_device_id(comb_gpu_reg: CombinedGPURegion, cu_id: NodeID) -> int:
    if cu_id in comb_gpu_reg.device_cu_ids:
        return 1
    return 0


def __identify_merge_node(pet: PEGraphX, successors: List[NodeID]) -> Optional[NodeID]:
    def check_validity_of_potential_merge_node(node_id: NodeID) -> bool:
        # return True if the given node is a valid merge node.
        # return False otherwise.
        # do not allow return BB's as merge nodes, since this would be trivially true for every path split
        potential_merge_node = pet.node_at(node_id)
        if type(potential_merge_node) != CUNode:
            return False
        if (
            "return" in str(potential_merge_node.basic_block_id)
            and potential_merge_node.end_position() == get_parent_function(pet, potential_merge_node).end_position()
        ):
            # do not consider return BB as merge node
            return False
        return True

    if len(successors) == 0:
        raise ValueError("Empty list of successors!")

    parent_function = get_parent_function(pet, pet.node_at(successors[0]))
    post_dominators = parent_function.get_immediate_post_dominators(pet)

    # initialize lists of current post dominators
    current_post_dominators: List[NodeID] = [post_dominators[node_id] for node_id in successors]
    # initialize lists of visited post dominators for each node in "successors"
    visited_post_dominators: List[Set[NodeID]] = []
    for idx, cpd in enumerate(current_post_dominators):
        # add the node itself as well as it's first post dominator to visited nodes for the initialization
        visited_post_dominators.append({cpd, successors[idx]})

    if len(visited_post_dominators) == 0 and len(current_post_dominators) == 0:
        raise ValueError("No post dominators found!")

    # check for common post dominators
    while True:
        # check if a common post dominator exists
        common_post_dominators = visited_post_dominators[0]
        for idx, vpd_set in enumerate(visited_post_dominators):
            common_post_dominators.intersection_update(vpd_set)
            if len(common_post_dominators) == 0:
                break

        if len(common_post_dominators) > 0:
            # return identified merge node
            for potential_merge_node_id in common_post_dominators:
                if check_validity_of_potential_merge_node(potential_merge_node_id):
                    return potential_merge_node_id

        if len(current_post_dominators) == 0:
            # No merge node found and no node to be checked anymore. Exit the loop.
            break

        # if not, add current post dominators to the visited list and resolve each post dominator by one step
        # break if new post dominator is equal to the old (end of path reached)
        for idx, cpd in enumerate(current_post_dominators):
            visited_post_dominators[idx].add(cpd)
        new_post_dominators = []
        for cpd in current_post_dominators:
            if cpd not in post_dominators:
                post_dominators[cpd] = cpd
            tmp = post_dominators[cpd]
            if tmp == cpd:
                # end of path reached, do not add tmp to list of new post dominators
                continue
            # get the next post dominator
            new_post_dominators.append(tmp)
        # replace the list of current post dominators (~ frontier)
        current_post_dominators = new_post_dominators
    # no merge node found
    return None


def identify_updates(
    comb_gpu_reg: CombinedGPURegion,
    pet: PEGraphX,
    writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]],
    unrolled_function_graph: MultiDiGraph,
) -> Set[Update]:
    identified_updates: Set[Update] = set()
    # get parent functions
    parent_functions: Set[NodeID] = set()
    for region in comb_gpu_reg.contained_regions:
        parent_functions.add(get_parent_function(pet, pet.node_at(region.node_id)).id)

    for parent_function_id in parent_functions:
        print("IDENTIFY UPDATES FOR: ", pet.node_at(parent_function_id).name, file=sys.stderr)
        # determine entry points
        entry_points: List[NodeID] = []
        for function_child_id in [t for s, t, d in out_edges(pet, parent_function_id, EdgeType.CHILD)]:
            in_successor_edges = in_edges(pet, function_child_id, EdgeType.SUCCESSOR)
            if len(in_successor_edges) == 0 and pet.node_at(function_child_id).type == NodeType.CU:
                entry_points.append(function_child_id)

        for entry_point in entry_points:
            print(
                "\tEntry point: ",
                entry_point,
                "@L.",
                pet.node_at(entry_point).start_line,
                file=sys.stderr,
            )

            # create a new context
            # todo add contexts support for multiple devices
            device_id = get_device_id(comb_gpu_reg, entry_point)
            context = Context(entry_point, device_id)

            try:
                entry_point_writes = writes_by_device[device_id][entry_point]
            except KeyError:
                entry_point_writes = dict()

            context.update_writes(device_id, entry_point_writes, entry_point)

            # start calculation of updates for entry_point
            identified_updates.update(
                __calculate_updates(
                    pet,
                    comb_gpu_reg,
                    context,
                    entry_point,
                    writes_by_device,
                    set(),
                    unrolled_function_graph,
                )
            )

    return identified_updates


def get_update_type(from_device_id: int, to_device_id: int) -> UpdateType:
    if from_device_id == 0 and to_device_id != 0:
        return UpdateType.TO_DEVICE
    elif from_device_id != 0 and to_device_id == 0:
        return UpdateType.FROM_DEVICE
    raise ValueError(
        "Unsupported update type requested for device IDS: " + str(from_device_id) + " -> " + str(to_device_id)
    )


def __calculate_updates(
    pet: PEGraphX,
    comb_gpu_reg: CombinedGPURegion,
    context: Context,
    cur_node_id: NodeID,
    writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]],
    visited_nodes: Set[NodeID],
    unrolled_function_graph: MultiDiGraph,
) -> Set[Update]:
    # calculate and return updates between ctx.cu_id and its immediate successor cur_node
    identified_updates: Set[Update] = set()

    # pass on calculation
    end_reached = False
    while not end_reached:
        context.print()

        # todo: update context to current node and save required updates
        required_updates = context.update_to(pet, cur_node_id, comb_gpu_reg, writes_by_device)
        identified_updates.update(required_updates)

        # calculate successors of current node
        # successors = [cast(NodeID, t) for s, t, d in out_edges(pet, cur_node_id, EdgeType.SUCCESSOR)]
        successors = [t for s, t, d in unrolled_function_graph.out_edges(cur_node_id, data="data")]

        if len(successors) == 0:
            end_reached = True
            continue
        elif len(successors) == 1:
            if cur_node_id == successors[0]:
                # cycle! break
                end_reached = True
                continue
            # start calculation for successor of current node
            cur_node_id = successors[0]
            print("PROCEED TO ", cur_node_id, file=sys.stderr)
            continue
        else:
            # multiple successors exist

            # determine merge node if existing
            if False:
                # Disabled merge node calculation, since new graph structures are free of cycles!
                # Keep the old code for now.
                print("SUCCESSORS: ", successors)
                merge_node = __identify_merge_node(pet, successors)
                print("MERGE NODE: ", merge_node)

                # if merge node exists, skip branched section and treat it as a single node
                if merge_node is not None:
                    cur_node_id = merge_node
                    print("PROCEED TO MERGE NODE ", cur_node_id, file=sys.stderr)
                    continue
            else:
                merge_node = None

            # if no merge node exists, start recursion calculation of updates for each branch
            if merge_node is None:
                # recursive calculation will stop at the end of the funciton body, thus return identified updates
                # without executing a new loop iteration
                for successor in successors:
                    if successor in visited_nodes:
                        # prevent endless cycles
                        continue
                    # enter recursion
                    print("ENTER RECURSION FOR: ", successor, file=sys.stderr)
                    tmp_visited_set = copy.deepcopy(visited_nodes)
                    tmp_visited_set.add(successor)

                    identified_updates.update(
                        __calculate_updates(
                            pet,
                            comb_gpu_reg,
                            copy.deepcopy(context),
                            successor,
                            writes_by_device,
                            tmp_visited_set,
                            unrolled_function_graph,
                        )
                    )
                return identified_updates

    return identified_updates


def create_circle_free_function_graphs(pet: PEGraphX, add_dummy_node: bool = True) -> Dict[FunctionNode, MultiDiGraph]:
    """Remove loops from the CUGraph by unrolling loops in the successor graphs of each function."""
    import networkx as nx

    unrolled_function_graphs: Dict[FunctionNode, nx.MultiDiGraph] = dict()

    # initialize the function graphs
    for function in all_nodes(pet, type=FunctionNode):
        # get subgraph for function
        function_subgraph = pet.g.subgraph(function.children_cu_ids).copy()
        # remove all but successor edges
        to_be_removed = set()
        for edge in function_subgraph.edges:
            edge_data = cast(Dependency, function_subgraph.edges[edge]["data"])
            if edge_data.etype != EdgeType.SUCCESSOR:
                to_be_removed.add(edge)
        for edge in to_be_removed:
            function_subgraph.remove_edge(edge[0], edge[1])
        # store function subgraph
        unrolled_function_graphs[function] = function_subgraph

    # UNROLLING ALGORITHM:
    # for function:
    # while cycle in function_graph:
    # unroll found cycle
    # ==> Identify cycle entries
    # ==> Identify cycle exits
    # create branch equivalent to "not entering the cycle"
    # create branch equivalent to "entering the cycle"
    # TODO insert a second iteration of the cycle?

    # unroll each function separately
    for function in unrolled_function_graphs:
        print("UNROLLING FUNCTION: ", function.name)
        try:
            cycle_edges = nx.find_cycle(unrolled_function_graphs[function])
            print("\tCycle: ", cycle_edges)
        except NetworkXNoCycle:
            print("\tNo cycle found.")
            continue
        # while cycle in graph:
        exit_node_buffer = []
        while len(cycle_edges) > 0:
            cycle_nodes: Set[NodeID] = set()
            for s, t, d in cycle_edges:
                cycle_nodes.add(s)
                cycle_nodes.add(t)
            # unroll cycle
            # ==> Identify cycle entries
            entry_nodes: Set[NodeID] = set()
            for node_id, _, _ in cycle_edges:
                predecessors = [s for s, t, d in in_edges(pet, node_id, EdgeType.SUCCESSOR)]
                if len(predecessors) == 0:
                    entry_nodes.add(node_id)
                    continue
                predecessors = [s for s in predecessors if s not in cycle_nodes]
                if len(predecessors) > 0:
                    entry_nodes.add(node_id)

            # ==> Identify cycle exits
            for potential_exit_node in set([s for s, t, d in cycle_edges] + [t for s, t, d in cycle_edges]):
                print("cyc: ", cycle_nodes)
                print("exit: ", potential_exit_node)
                potential_cycle_successor_nodes = [
                    t for s, t, d in out_edges(pet, potential_exit_node, EdgeType.SUCCESSOR) if t not in cycle_nodes
                ]
                print("POT: ", potential_cycle_successor_nodes)

                # only consider such cycle_successors which DO NOT share a direct parent with the potential_exit_node, except for functions
                pen_parents = [
                    s
                    for s, t, d in in_edges(pet, potential_exit_node, EdgeType.CHILD)
                    if type(pet.node_at(s)) != FunctionNode
                ]
                filtered_pcsn = []
                for pcsn in potential_cycle_successor_nodes:
                    pcsn_parents = [
                        s for s, t, d in in_edges(pet, pcsn, EdgeType.CHILD) if type(pet.node_at(s)) != FunctionNode
                    ]
                    if len([nid for nid in pen_parents if nid in pcsn_parents]) == 0:
                        # no shared parents
                        filtered_pcsn.append(pcsn)
                    # second chance: add pcsn, if it has a successor outside the given parent
                    for successor in direct_successors(pet, pet.node_at(pcsn)):
                        valid = True
                        for parent in [s for s, t, d in in_edges(pet, successor.id)]:
                            if parent in pcsn_parents:
                                valid = False
                                break
                        if valid:
                            filtered_pcsn.append(pcsn)
                            break

                # prevent endless cycling
                if potential_exit_node in exit_node_buffer:
                    filtered_pcsn = potential_cycle_successor_nodes

                if len(filtered_pcsn) == 0:
                    # not a valid exit node, add to buffer and skip it
                    exit_node_buffer.append(potential_exit_node)
                    continue

                # reset buffer, since action will be performed
                exit_node_buffer = []

                print("EXITS: ", filtered_pcsn)

                # create branch equivalent to "not entering the cycle"
                # --> nothing to be done, already represented by the edge "potential_exit_node --> cycle_successor"

                # create branch equivalent to "entering the cycle"
                # --> create a copy of the exit node

                if add_dummy_node:
                    unrolled_function_graphs[function].add_node(
                        "dummy:" + potential_exit_node,
                        data=unrolled_function_graphs[function].nodes[potential_exit_node]["data"],
                    )

                # --> redirect the last edge in the cycle to cycle_successor, and insert the created copy into the path
                buffer = set()
                for cycle_edge in cycle_edges:
                    if cycle_edge[1] == potential_exit_node:
                        print("Redirecting: ", cycle_edge, " TO (", cycle_edge[0], ", ", end="")
                        unrolled_function_graphs[function].remove_edge(cycle_edge[0], cycle_edge[1], cycle_edge[2])
                        if add_dummy_node:
                            unrolled_function_graphs[function].add_edge(
                                cycle_edge[0],
                                "dummy:" + potential_exit_node,
                                type=EdgeType.SUCCESSOR,
                            )
                        else:
                            buffer.add(cycle_edge[0])

                for cycle_successor in filtered_pcsn:
                    if add_dummy_node:
                        print("dummy:" + potential_exit_node, ",", end="")
                    print(
                        cycle_successor,
                        ")",
                    )
                    if add_dummy_node:
                        unrolled_function_graphs[function].add_edge("dummy:" + potential_exit_node, cycle_successor)
                    else:
                        for buffered_node_id in buffer:
                            unrolled_function_graphs[function].add_edge(
                                buffered_node_id, cycle_successor, type=EdgeType.SUCCESSOR
                            )

            # prepare next iteration
            try:
                cycle_edges = nx.find_cycle(unrolled_function_graphs[function])
                print("\tCycle: ", cycle_edges)
            except NetworkXNoCycle:
                print("\tNo cycle found.")
                # break the unrolling loop
                cycle_edges = []

    return unrolled_function_graphs


def add_accesses_from_called_functions(
    pet: PEGraphX,
    writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]],
    force_called_functions_to_host: bool = False,
) -> Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]]:
    """Gather written and read memory regions on a function level.
    Add the gathered information to calling CU nodes."""
    values_propagated = True
    cycles = 0
    while values_propagated:
        cycles += 1
        values_propagated = False
        for function in all_nodes(pet, type=FunctionNode):
            print("FUNCTION: ", function.name)
            memory_accesses = function.get_memory_accesses(writes_by_device)
            if force_called_functions_to_host:
                for device_id in memory_accesses:
                    if device_id != 0:
                        for mem_reg in memory_accesses[device_id]:
                            if mem_reg not in memory_accesses[0]:
                                memory_accesses[0][mem_reg] = set()
                            memory_accesses[0][mem_reg].update(memory_accesses[device_id][mem_reg])
                to_be_removed = [key for key in memory_accesses if key != 0]
                for key in to_be_removed:
                    del memory_accesses[key]

            # add memory_accesses to calling CU's in writes_by_device
            called_by = [s for s, t, d in in_edges(pet, function.id, EdgeType.CALLSNODE)]
            print("\tcalled by: ", called_by)
            for device_id in memory_accesses:
                if device_id not in writes_by_device:
                    writes_by_device[device_id] = dict()
                for calling_cu_id in called_by:
                    if calling_cu_id not in writes_by_device[device_id]:
                        writes_by_device[device_id][calling_cu_id] = dict()
                    for mem_reg in memory_accesses[device_id]:
                        if mem_reg not in writes_by_device[device_id][calling_cu_id]:
                            writes_by_device[device_id][calling_cu_id][mem_reg] = set()
                        len_pre = len(writes_by_device[device_id][calling_cu_id][mem_reg])
                        writes_by_device[device_id][calling_cu_id][mem_reg].update(memory_accesses[device_id][mem_reg])
                        len_post = len(writes_by_device[device_id][calling_cu_id][mem_reg])
                        values_propagated = (
                            (values_propagated or True) if len_pre < len_post else (values_propagated or False)
                        )
    print("cycles: ", cycles)
    return writes_by_device


def identify_updates_in_unrolled_function_graphs(
    comb_gpu_reg: CombinedGPURegion,
    pet: PEGraphX,
    writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]],
    unrolled_function_graphs: Dict[FunctionNode, MultiDiGraph],
) -> Set[Update]:
    identified_updates: Set[Update] = set()
    # get parent functions
    parent_functions: Set[NodeID] = set()
    for region in comb_gpu_reg.contained_regions:
        parent_functions.add(get_parent_function(pet, pet.node_at(region.node_id)).id)

    for parent_function_id in parent_functions:
        print("IDENTIFY UPDATES FOR: ", pet.node_at(parent_function_id).name, file=sys.stderr)
        # determine entry points
        entry_points: List[NodeID] = []
        for function_child_id in [t for s, t, d in out_edges(pet, parent_function_id, EdgeType.CHILD)]:
            in_successor_edges = in_edges(pet, function_child_id, EdgeType.SUCCESSOR)
            if len(in_successor_edges) == 0 and pet.node_at(function_child_id).type == NodeType.CU:
                entry_points.append(function_child_id)

        for entry_point in entry_points:
            print(
                "\tEntry point: ",
                entry_point,
                "@L.",
                pet.node_at(entry_point).start_line,
                file=sys.stderr,
            )

            # create a new context
            # todo add contexts support for multiple devices
            device_id = get_device_id(comb_gpu_reg, entry_point)
            context = Context(entry_point, device_id)

            try:
                entry_point_writes = writes_by_device[device_id][entry_point]
            except KeyError:
                entry_point_writes = dict()

            context.update_writes(device_id, entry_point_writes, entry_point)

            # start calculation of updates for entry_point
            identified_updates.update(
                __calculate_updates(
                    pet,
                    comb_gpu_reg,
                    context,
                    entry_point,
                    writes_by_device,
                    set(),
                    unrolled_function_graphs[cast(FunctionNode, pet.node_at(parent_function_id))],
                )
            )

    return identified_updates
