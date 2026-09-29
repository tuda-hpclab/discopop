# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Dict, Set, cast, Tuple

import networkx as nx  # type: ignore

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.classes.variable import Variable
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


# Data.xml: type="1"
class FunctionNode(Node):
    args: List[Variable] = []
    children_cu_ids: Optional[List[NodeID]] = None  # metadata to speedup some calculations
    reachability_pairs: Dict[NodeID, Set[NodeID]]
    immediate_post_dominators: Dict[NodeID, NodeID]
    immediate_post_dominators_present: bool
    memory_accesses: Dict[int, Dict[MemoryRegion, Set[Optional[int]]]]
    memory_accesses_present: bool

    def __init__(self, node_id: NodeID):
        super().__init__(node_id)
        self.type = NodeType.FUNC
        self.reachability_pairs = dict()
        self.immediate_post_dominators_present = False
        self.memory_accesses_present = False

    def get_entry_cu_id(self, pet: PEGraphX) -> NodeID:
        for child_cu_id in [t for s, t, d in out_edges(pet, self.id, EdgeType.CHILD)]:
            if len(in_edges(pet, child_cu_id, EdgeType.SUCCESSOR)) == 0:
                return child_cu_id
        raise ValueError("Mal-formatted function: ", self.id, " - No entry CU found!")

    def get_exit_cu_ids(self, pet: PEGraphX) -> Set[NodeID]:
        exit_cu_ids: Set[NodeID] = set()
        if self.children_cu_ids is not None:
            for child_cu_id in self.children_cu_ids:
                if (
                    len(out_edges(pet, child_cu_id, EdgeType.SUCCESSOR)) == 0
                    and len(in_edges(pet, child_cu_id, EdgeType.SUCCESSOR)) != 0
                ):
                    exit_cu_ids.add(child_cu_id)
        return exit_cu_ids

    def calculate_reachability_pairs(self, pet: PEGraphX) -> Dict[NodeID, Set[NodeID]]:
        children = cast(List[NodeID], self.children_cu_ids)
        children_set = set(children)

        # lazy, read-only view restricted to this function's own CUs and SUCCESSOR edges,
        # instead of copying and successor-filtering the whole-program graph for every
        # single function
        def is_successor_edge(u: NodeID, v: NodeID, k: int) -> bool:
            return cast(Dependency, pet.g.edges[u, v, k]["data"]).etype == EdgeType.SUCCESSOR

        subgraph = nx.subgraph_view(pet.g, filter_node=lambda n: n in children_set, filter_edge=is_successor_edge)

        # compute reachability bottom-up with memoization instead of one independent DFS per
        # node (which is O(N) DFS traversals, each up to O(N) - i.e. O(N^2) time and memory
        # for a function with N CUs): reachable(n) = {n} | union(reachable(succ) for succ in
        # successors(n)). Process in reverse topological order of the SCC condensation (this
        # handles local cycles/loops correctly - all members of one SCC share one reachable
        # set) so each node's result is built once from its already-computed successors.
        reachability_pairs: Dict[NodeID, Set[NodeID]] = dict()
        condensation = nx.condensation(subgraph)
        for scc_index in reversed(list(nx.topological_sort(condensation))):
            members = condensation.nodes[scc_index]["members"]
            combined: Set[NodeID] = set(members)
            for member in members:
                for succ in subgraph.successors(member):
                    if succ not in members:
                        combined.update(reachability_pairs[succ])
            for member in members:
                reachability_pairs[member] = combined
        return reachability_pairs

    def get_immediate_post_dominators(self, pet: PEGraphX) -> Dict[NodeID, NodeID]:
        if self.immediate_post_dominators_present:
            import sys

            print("METADATA HIT! ", self.node_id, file=sys.stderr)
            return self.immediate_post_dominators
        else:
            # copy graph since edges need to be removed
            copied_graph = pet.g.copy()
            exit_cu_ids = self.get_exit_cu_ids(pet)
            # remove all but successor edges
            to_be_removed = set()
            for edge in copied_graph.edges:
                edge_data = cast(Dependency, copied_graph.edges[edge]["data"])
                if edge_data.etype != EdgeType.SUCCESSOR:
                    to_be_removed.add(edge)
            for edge in to_be_removed:
                copied_graph.remove_edge(edge[0], edge[1])

            # reverse edges
            immediate_post_dominators: Set[Tuple[NodeID, NodeID]] = set()
            for exit_cu_id in exit_cu_ids:
                immediate_post_dominators.update(nx.immediate_dominators(copied_graph.reverse(), exit_cu_id).items())

            immediate_post_dominators_dict = dict(immediate_post_dominators)
            # add trivial cases for missing modes
            for child_id in cast(List[NodeID], self.children_cu_ids):
                if child_id not in immediate_post_dominators_dict:
                    immediate_post_dominators_dict[child_id] = child_id

            # initialize result dictionary and add trivial cases for all children
            self.immediate_post_dominators = dict()
            for child_id in cast(List[NodeID], self.children_cu_ids):
                if child_id not in self.immediate_post_dominators:
                    self.immediate_post_dominators[child_id] = child_id

            # find post dominator outside parent, if type(parent) != function
            for node_id in cast(List[NodeID], self.children_cu_ids):
                if type(pet.node_at(node_id)) != CUNode:
                    continue
                # initialize search with immediate post dominator
                post_dom_id = immediate_post_dominators_dict[node_id]
                visited = set()
                use_original = False
                while (
                    pet.get_node_parent_id(pet.node_at(node_id)) == pet.get_node_parent_id(pet.node_at(post_dom_id))
                    and type(pet.node_at(cast(NodeID, pet.get_node_parent_id(pet.node_at(post_dom_id)))))
                    != FunctionNode
                ):
                    if post_dom_id in visited:
                        # cycle detected!
                        use_original = True
                        break

                    visited.add(post_dom_id)
                    new_post_dom_id = immediate_post_dominators_dict[post_dom_id]
                    import sys

                    print("Post dom: ", post_dom_id, file=sys.stderr)
                    print("New post dom: ", new_post_dom_id, file=sys.stderr)
                    print(file=sys.stderr)
                    if post_dom_id == new_post_dom_id:
                        break
                    post_dom_id = new_post_dom_id
                if not use_original:
                    # found post dom
                    self.immediate_post_dominators[node_id] = post_dom_id
            self.immediate_post_dominators_present = True
            return self.immediate_post_dominators

    def get_memory_accesses(
        self, writes_by_device: Dict[int, Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]]
    ) -> Dict[int, Dict[MemoryRegion, Set[Optional[int]]]]:
        if not self.memory_accesses_present:
            self.memory_accesses = dict()
            self.memory_accesses_present = True

        for child_id in cast(List[NodeID], self.children_cu_ids):
            for device_id in writes_by_device:
                if device_id not in self.memory_accesses:
                    self.memory_accesses[device_id] = dict()
                if child_id in writes_by_device[device_id]:
                    for mem_reg in writes_by_device[device_id][child_id]:
                        if mem_reg not in self.memory_accesses[device_id]:
                            self.memory_accesses[device_id][mem_reg] = set()
                        self.memory_accesses[device_id][mem_reg].update(writes_by_device[device_id][child_id][mem_reg])
        return self.memory_accesses
