# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import copy
import itertools
import random
from typing import Dict, List, Sequence, Tuple, Set, Optional, Type, TypeVar, cast, Union, overload, Any

import jsonpickle  # type: ignore
import matplotlib.pyplot as plt  # type: ignore
import networkx as nx  # type: ignore
from lxml.objectify import ObjectifiedElement  # type: ignore

from discopop_explorer.classes.PEGraph.NodeT import NodeT
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.properties.is_readonly_inside_loop_body import is_readonly_inside_loop_body
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.queries.variables import get_variables
from discopop_explorer.functions.PEGraph.traversal.children import direct_children, direct_children_or_called_nodes
from discopop_explorer.functions.PEGraph.traversal.parent import get_all_parents_until_function, get_parent_function
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType  # type: ignore
from discopop_library.StatusReporting.console import progress, warn
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

try:
    from discopop_gui.Extendables.Plottable import Plottable
    from discopop_gui.Visualizers.Base import Base as Visualizer
except (ImportError, ModuleNotFoundError):

    class Plottable:  # type: ignore[no-redef]
        def __init__(self, visualizer: object = None) -> None:
            pass

        def plottable(self) -> bool:
            return False

    Visualizer = object  # type: ignore[assignment, misc]

from discopop_explorer.utilities.PEGraphConstruction.parser import readlineToCUIdMap, writelineToCUIdMap
from discopop_explorer.utilities.PEGraphConstruction.classes.LoopData import LoopData
from discopop_explorer.utilities.PEGraphConstruction.classes.DependenceItem import DependenceItem
from discopop_explorer.utilities.PEGraphConstruction.PEGraphConstructionUtilities import parse_dependency, parse_cu
from discopop_explorer.classes.variable import Variable
import logging

global_pet = None

# unused
# node_props = [
#    ("BasicBlockID", "string", "''"),
#    ("pipeline", "float", "0"),
#    ("doAll", "bool", "False"),
#    ("geomDecomp", "bool", "False"),
#    ("reduction", "bool", "False"),
#    ("mwType", "int", "2"),
#    ("localVars", "object", "[]"),
#    ("globalVars", "object", "[]"),
#    ("args", "object", "[]"),
#    ("recursiveFunctionCalls", "object", "[]"),
# ]

# edge_props = [
#    ("type", "string"),
#    ("source", "string"),
#    ("sink", "string"),
#    ("var", "string"),
#    ("dtype", "string"),
# ]


#        # check format of newly created MemoryRegion
#        try:
#            int(id_string)
#        except ValueError:
#            raise ValueError("Mal-formatted MemoryRegion identifier: ", id_string)


class PEGraphX(Plottable, object):  # type: ignore[misc]
    g: nx.MultiDiGraph
    reduction_vars: List[Dict[str, str]]
    main: Node
    pos: Dict[Any, Any]

    def __init__(
        self,
        g: nx.MultiDiGraph,
        reduction_vars: List[Dict[str, str]],
        pos: Dict[Any, Any],
        visualizer: Visualizer | None = None,
    ):
        super().__init__(visualizer)
        self.g = g
        self.reduction_vars = reduction_vars
        for _, node in g.nodes(data="data"):
            if node.name == "main":
                self.main = node
        self.pos = pos

    @classmethod
    def from_parsed_input(
        cls,
        cu_dict: Dict[str, ObjectifiedElement],
        dependencies_list: List[DependenceItem],
        loop_data: Dict[str, LoopData],
        reduction_vars: List[Dict[str, str]],
        visualizer: Visualizer | None = None,
    ) -> PEGraphX:
        """Constructor for making a PETGraphX from the output of parser.parse_inputs()"""
        g = nx.MultiDiGraph()

        for id, node in progress(cu_dict.items(), desc="Adding nodes"):
            n = parse_cu(node)
            g.add_node(id, data=n)

        for node_id, node in progress(cu_dict.items(), desc="Adding edges"):
            source = node_id
            if "successors" in dir(node) and "CU" in dir(node.successors):
                for successor in [n.text for n in node.successors.CU]:
                    if successor not in g:
                        warn(f"no successor node {successor} found")
                    # do not allow "self-successor" edges (incorrect, but not critical. might occur in Data.xml)
                    if source != successor:
                        g.add_edge(source, successor, data=Dependency(EdgeType.SUCCESSOR))

            if "callsNode" in dir(node) and "nodeCalled" in dir(node.callsNode):
                for nodeCalled in [n.text for n in node.callsNode.nodeCalled]:
                    if nodeCalled not in g:
                        warn(f"no nodeCalled {nodeCalled} found")
                    g.add_edge(source, nodeCalled, data=Dependency(EdgeType.CALLSNODE))

            if "childrenNodes" in dir(node):
                for child in [n.text for n in node.childrenNodes]:
                    if child not in g:
                        warn(f"no child node {child} found")
                    if not (source, child) in g.edges:
                        g.add_edge(source, child, data=Dependency(EdgeType.CHILD))

        for _, node in progress(g.nodes(data="data"), desc="Adding loop data"):
            if isinstance(node, LoopNode):
                node.loop_data = loop_data.get(node.start_position(), None)
                # TODO remove loop_iterations property, was kept for backwards compatibility only
                if node.loop_data is not None:
                    # node.loop_iterations = node.loop_data.total_iteration_count
                    node.loop_iterations = node.loop_data.average_iteration_count

        # calculate position before dependencies affect them
        try:
            pos = nx.planar_layout(g)  # good
        except nx.exception.NetworkXException:
            try:
                # fallback layouts
                pos = nx.shell_layout(g)  # maybe
            except nx.exception.NetworkXException:
                pos = nx.random_layout(g)
        for idx, dep in progress(list(enumerate(dependencies_list)), desc="Adding dependencies"):
            if dep.type == "INIT":
                sink = readlineToCUIdMap[dep.sink]
                if len(sink) > 0:
                    for s in sink:
                        g.add_edge(s, s, data=parse_dependency(dep))
                else:
                    # check for write lines
                    sink = writelineToCUIdMap[dep.sink]
                    for s in sink:
                        g.add_edge(s, s, data=parse_dependency(dep))
                continue
            elif dep.type == "RAW" or dep.type == "WAR":
                sink_cu_ids = readlineToCUIdMap[dep.sink]
                source_cu_ids = writelineToCUIdMap[dep.source]
            elif dep.type == "WAW":
                sink_cu_ids = writelineToCUIdMap[dep.sink]
                source_cu_ids = writelineToCUIdMap[dep.source]
            else:
                raise ValueError("Unknown dep.type: " + dep.type + " for dependency: " + str(dep))

            for idx_1, sink_cu_id in enumerate(sink_cu_ids):
                for idx_2, source_cu_id in enumerate(source_cu_ids):
                    sink_node = g.nodes[sink_cu_id]["data"]
                    source_node = g.nodes[source_cu_id]["data"]
                    vars_in_sink_node = set()
                    vars_in_source_node = set()
                    if type(sink_node) == CUNode:
                        for var in itertools.chain(sink_node.local_vars, sink_node.global_vars):
                            vars_in_sink_node.add(var.name)
                    if type(source_node) == CUNode:
                        for var in itertools.chain(source_node.local_vars, source_node.global_vars):
                            vars_in_source_node.add(var.name)

                    # Note: consider all dependencies, independent of the variable names
                    #                    if dep.var_name not in vars_in_sink_node and dep.var_name not in vars_in_source_node:
                    #                        continue
                    if sink_cu_id and source_cu_id:
                        g.add_edge(sink_cu_id, source_cu_id, data=parse_dependency(dep))
        return cls(g, reduction_vars, pos, visualizer)

    def validate(self) -> None:
        logger = logging.getLogger("Explorer")
        for func_node in progress(all_nodes(self, FunctionNode), desc="Validating function scopes"):
            logger.debug("Validating function scope: " + func_node.name)
            min_start_line = func_node.start_line
            max_end_line = func_node.end_line
            for child in direct_children(self, func_node):
                if child.start_line < min_start_line:
                    min_start_line = child.start_line
                if child.end_line > max_end_line:
                    max_end_line = child.end_line
            if min_start_line != func_node.start_line:
                logger.debug(f"Fixed start line of {func_node.name}: {func_node.start_line} -> {min_start_line}")
                func_node.start_line = min_start_line
            if max_end_line != func_node.end_line:
                logger.debug(f"Fixed end line of {func_node.name}: {func_node.end_line} -> {max_end_line}")
                func_node.end_line = max_end_line

    def map_static_and_dynamic_dependencies(self) -> None:
        mem_reg_mappings: Dict[MemoryRegion, Set[MemoryRegion]] = dict()
        # initialize mappings
        for node_id in progress([n.id for n in all_nodes(self, CUNode)], desc="Mapping static/dynamic dependencies"):
            out_deps = [(s, t, d) for s, t, d in out_edges(self, node_id) if d.etype == EdgeType.DATA]

            # for outgoing dependencies, the scope must be equal
            # as a result, comparing variable names to match memory regions is valid
            #
            # Grouped by variable name rather than compared pairwise: the pairwise loop was
            # quadratic in the number of a CU's outgoing dependencies, and on larger inputs that
            # dominated the entire pattern detection - 142s of a 435s run on NPB MG, with the
            # sampled stack sitting on the inner comparison. Every pair which agrees on the
            # variable name and differs in the memory region maps the two regions onto each
            # other, so per variable only the set of memory regions it is accessed through
            # matters. A region which is None or a GEPRESULT_ is never mapped in either
            # direction, so it is dropped up front.
            regions_per_var: Dict[Optional[str], Set[MemoryRegion]] = dict()
            for _, _, dep in out_deps:
                if dep.memory_region is None or dep.memory_region.startswith("GEPRESULT_"):
                    continue
                regions_per_var.setdefault(dep.var_name, set()).add(dep.memory_region)
            for regions in regions_per_var.values():
                if len(regions) < 2:
                    # no region to map onto - the pairwise loop did not create an entry either
                    continue
                for memory_region in regions:
                    others = regions.difference({memory_region})
                    if memory_region in mem_reg_mappings:
                        mem_reg_mappings[memory_region].update(others)
                    else:
                        mem_reg_mappings[memory_region] = others

        # create copies of static dependency edges for all dynamic mappings
        for node_id in progress([n.id for n in all_nodes(self, CUNode)], desc="Instantiating static dependencies"):
            out_deps = [(s, t, d) for s, t, d in out_edges(self, node_id) if d.etype == EdgeType.DATA]
            for s, t, d in out_deps:
                if d.memory_region is None:
                    continue
                if d.memory_region.startswith("S"):
                    # Static dependency found
                    # check if mappings exist
                    if d.memory_region in mem_reg_mappings:
                        # create instances for all dynamic mappings
                        for dynamic_mapping in [
                            mapping for mapping in mem_reg_mappings[d.memory_region] if not mapping.startswith("S")
                        ]:
                            edge_data = copy.deepcopy(d)
                            edge_data.memory_region = dynamic_mapping
                            self.g.add_edge(s, t, data=edge_data)

    def synthesize_static_dependency_metadata(self) -> None:
        logger = logging.getLogger("Explorer")
        logger.info("Synthesizing disambiguation metadata for static data dependencies.")
        for edge in self.g.edges(data=True):
            dep = cast(Dependency, edge[2]["data"])
            if dep.etype != EdgeType.DATA:
                continue
            if dep.memory_region is None:
                continue
            if not dep.memory_region.startswith("S"):
                continue
            # dep is a static dependency
            sink_node = self.node_at(edge[0])
            source_node = self.node_at(edge[1])
            sink_parent_function = get_parent_function(self, self.node_at(edge[0]))
            source_parent_function = get_parent_function(self, self.node_at(edge[1]))

            synthesis_performed = False

            if sink_parent_function == source_parent_function:
                if dep.metadata_intra_call_dep is None:
                    raise ValueError()
                dep.metadata_intra_call_dep.append(sink_parent_function.start_position())
                synthesis_performed = True

            sink_parents = get_all_parents_until_function(self, sink_node)
            sink_immediate_parent_ids = [s for s, t, d in in_edges(self, edge[0], EdgeType.CHILD)]
            sink_immediate_parents = [self.node_at(s) for s in sink_immediate_parent_ids]
            sink_immediate_loop_parents = [p for p in sink_immediate_parents if p.type == NodeType.LOOP]
            sink_loop_parents = [
                p for p in sink_parents if p.type == NodeType.LOOP if p not in sink_immediate_loop_parents
            ]

            source_parents = get_all_parents_until_function(self, source_node)
            source_immediate_parent_ids = [s for s, t, d in in_edges(self, edge[1], EdgeType.CHILD)]
            source_immediate_parents = [self.node_at(s) for s in source_immediate_parent_ids]
            source_immediate_loop_parents = [p for p in source_immediate_parents if p.type == NodeType.LOOP]
            source_loop_parents = [
                p for p in source_parents if p.type == NodeType.LOOP if p not in source_immediate_loop_parents
            ]

            common_loop_parents = list(dict.fromkeys(sink_loop_parents + source_loop_parents))

            for loop in sink_immediate_loop_parents:
                if loop in source_immediate_loop_parents:
                    if dep.metadata_intra_iteration_dep is None:
                        raise ValueError()
                    if dep.metadata_inter_iteration_dep is None:
                        raise ValueError()
                    if sink_node.start_line < source_node.start_line:
                        dep.metadata_inter_iteration_dep.append(loop.start_position())
                        for parent_loop in common_loop_parents:
                            dep.metadata_inter_iteration_dep.append(parent_loop.start_position())
                    else:
                        dep.metadata_intra_iteration_dep.append(loop.start_position())
                        for parent_loop in common_loop_parents:
                            dep.metadata_intra_iteration_dep.append(parent_loop.start_position())
                    synthesis_performed = True

            if synthesis_performed:
                for sink_parent in get_all_parents_until_function(self, self.node_at(edge[0])):
                    if dep.metadata_sink_ancestors is None:
                        raise ValueError()
                    dep.metadata_sink_ancestors.append(sink_parent.start_position())
                for source_parent in get_all_parents_until_function(self, self.node_at(edge[1])):
                    if dep.metadata_source_ancestors is None:
                        raise ValueError()
                    dep.metadata_source_ancestors.append(source_parent.start_position())

            # logging
            if synthesis_performed:
                logger.debug(
                    "Synthesized: "
                    + str(dep.dtype)
                    + " "
                    + str(dep.sink_line)
                    + " "
                    + str(dep.source_line)
                    + " "
                    + str(dep.var_name)
                )
                logger.debug("--> IAI: " + str(dep.metadata_intra_iteration_dep))
                logger.debug("--> IAC: " + str(dep.metadata_intra_call_dep))
                logger.debug("--> SINK_ANC: " + str(dep.metadata_sink_ancestors))
                logger.debug("--> SOURCE_ANC: " + str(dep.metadata_source_ancestors))

    def calculateFunctionMetadata(
        self,
        hotspot_information: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]] = None,
        func_nodes: Optional[List[FunctionNode]] = None,
    ) -> None:
        # store id of parent function in each node
        # and store in each function node a list of all children ids
        if func_nodes is None:
            func_nodes = all_nodes(self, FunctionNode)

            if hotspot_information is not None:
                all_hotspot_functions: Set[Tuple[int, str]] = set()
                for key in hotspot_information:
                    for entry in hotspot_information[key]:
                        if entry[2] == HotspotNodeType.FUNCTION:
                            all_hotspot_functions.add((entry[0], entry[3]))

                # An empty set of hotspot functions means "nothing is known about which
                # functions are hot", not "no function is hot" - the hotspot loader returns
                # an empty dict when hotspot_detection/Hotspots.json is absent, and even a
                # present file may classify only LOOP regions in the requested hotspot
                # types. Filtering against the empty set in those cases would drop every
                # function and leave the graph without any reachability metadata, so keep
                # all functions instead. Mirrors the same guard in utils.filter_for_hotspots.
                if all_hotspot_functions:
                    filtered_func_nodes = [
                        func_node
                        for func_node in func_nodes
                        if (func_node.file_id, func_node.name) in all_hotspot_functions
                    ]
                    func_nodes = filtered_func_nodes

        from discopop_explorer.parallel_utils import (
            pet_function_metadata_initialize_worker,
            pet_function_metadata_parse_func,
        )

        param_list = func_nodes
        # This computation is run serially in-process, on purpose - it used to fan out over a
        # multiprocessing.Pool that passed the whole PEGraphX to every worker via initargs.
        # Under fork, each worker's graph traversal dirties copy-on-write pages of the shared
        # graph, so peak memory scaled linearly with the (uncapped, = os.cpu_count()) worker
        # count - roughly one graph copy per core (measured 146MiB -> 1.1GiB at 8 workers on
        # LULESH, and multi-GB OOM kills on many-core machines). The metadata computation is
        # cheap (the per-function reachability pass is memoized and effectively O(N)), so the
        # parallelism is not worth the OOM risk. Running serially never duplicates the graph
        # and subsumes the previous zero-work early-exit (an empty param_list is just an empty
        # loop). pet_function_metadata_initialize_worker binds the module-level graph handle
        # that pet_function_metadata_parse_func reads, exactly as the pool initializer did.
        pet_function_metadata_initialize_worker(self)
        tmp_result: List[Tuple[NodeID, Any, Set[NodeID]]] = [
            pet_function_metadata_parse_func(func_node)
            for func_node in progress(param_list, desc="Calculating function metadata")
        ]
        # calculate global result
        global_reachability_dict: Dict[NodeID, Set[NodeID]] = dict()
        for local_result in tmp_result:
            parsed_function_id, local_reachability_dict, local_children_ids = local_result
            # set reachability values to function nodes
            cast(FunctionNode, self.node_at(parsed_function_id)).reachability_pairs = local_reachability_dict
            # set parent function for visited nodes
            for child_id in local_children_ids:
                self.node_at(child_id).parent_function_id = parsed_function_id

        # cleanup dependencies (remove dependencies, if it is overwritten by a more specific Intra-iteration dependency
        # note: this can introduce false positives! Keep the analysis pessimistic to ensure correctness
        if False:
            print("Cleaning duplicated dependencies...")
            to_be_removed = []
            for cu_node in all_nodes(self, CUNode):
                out_deps = out_edges(self, cu_node.id, EdgeType.DATA)
                for dep_1 in out_deps:
                    for dep_2 in out_deps:
                        if dep_1 == dep_2:
                            continue
                        if (
                            dep_1[2].dtype == dep_2[2].dtype
                            and dep_1[2].etype == dep_2[2].etype
                            and dep_1[2].memory_region == dep_2[2].memory_region
                            and dep_1[2].sink_line == dep_2[2].sink_line
                            and dep_1[2].source_line == dep_2[2].source_line
                            and dep_1[2].var_name == dep_2[2].var_name
                        ):
                            if not dep_1[2].intra_iteration and dep_2[2].intra_iteration:
                                # dep_2 is a more specific duplicate of dep_1
                                # remove dep_1
                                to_be_removed.append(dep_1)

            to_be_removed_with_keys = []
            for dep in to_be_removed:
                graph_edges = self.g.out_edges(dep[0], keys=True, data="data")

                for s, t, key, data in graph_edges:
                    if dep[0] == s and dep[1] == t and dep[2] == data:
                        to_be_removed_with_keys.append((s, t, key))
            for edge in set(to_be_removed_with_keys):
                self.g.remove_edge(edge[0], edge[1], edge[2])
            print("Cleaning dependencies done.")

        # cleanup dependencies II : only consider the Intra-iteration dependencies with the highest level
        #
        # Grouped rather than compared pairwise, see map_static_and_dynamic_dependencies. A
        # dependency is superseded exactly when another one it agrees with on all of the fields
        # below carries a higher intra-iteration level, so per group only the highest level
        # matters. The pairwise loop reported the same dependency once per higher-level partner;
        # the duplicates were dropped when the edge keys were resolved, and reporting each
        # superseded dependency once instead saves that resolution work as well.
        superseded_deps: List[Tuple[NodeID, NodeID, Dependency]] = []
        for cu_node in progress(all_nodes(self, CUNode), desc="Cleaning duplicated dependencies"):
            out_deps = out_edges(self, cu_node.id, EdgeType.DATA)
            # the target node is deliberately not part of the key: the pairwise loop compared
            # only the dependencies themselves, so it also related edges to different targets
            grouped_deps: Dict[Tuple[Any, ...], List[Tuple[NodeID, NodeID, Dependency]]] = dict()
            for dep in out_deps:
                if not dep[2].intra_iteration:
                    continue
                group_key = (
                    dep[2].dtype,
                    dep[2].etype,
                    dep[2].memory_region,
                    dep[2].sink_line,
                    dep[2].source_line,
                    dep[2].var_name,
                )
                grouped_deps.setdefault(group_key, []).append(dep)
            for group in grouped_deps.values():
                if len(group) < 2:
                    continue
                deepest_level = max(dep[2].intra_iteration_level for dep in group)
                # dependencies from a shallower nesting level are less specific duplicates
                superseded_deps += [dep for dep in group if dep[2].intra_iteration_level < deepest_level]

        edges_to_remove: Set[Tuple[NodeID, NodeID, int]] = set()
        for dep in superseded_deps:
            for s, t, key, data in self.g.out_edges(dep[0], keys=True, data="data"):
                if dep[0] == s and dep[1] == t and dep[2] == data:
                    edges_to_remove.add((s, t, key))
        for edge in edges_to_remove:
            self.g.remove_edge(edge[0], edge[1], edge[2])

    def calculateLoopMetadata(self) -> None:
        # calculate loop indices
        loop_nodes = all_nodes(self, LoopNode)
        for loop in progress(loop_nodes, desc="Calculating loop indices"):
            subtree = subtree_of_type(self, loop, CUNode)
            # get variables used in loop
            candidates: Set[Variable] = set()
            for node in subtree:
                candidates.update(node.global_vars + node.local_vars)
            # identify loop indices
            loop_indices: Set[Variable] = set()
            for v in candidates:
                if is_loop_index(self, v.name, [loop.start_position()], subtree):
                    loop_indices.add(v)
            loop.loop_indices = [v.name for v in loop_indices]

    def enforce_single_function_exit_node(self) -> None:
        for func in all_nodes(self, FunctionNode):
            # define exit node
            file_id = func.file_id
            max_node_id_in_file = 0
            for node in all_nodes(self):
                if node.file_id != file_id:
                    continue
                if ":" in node.id:
                    id_int = int(node.id.split(":")[1])
                    if id_int > max_node_id_in_file:
                        max_node_id_in_file = id_int
            exit_id = NodeID(str(file_id) + ":" + str(max_node_id_in_file + 1))
            exit_node = Node(exit_id)
            exit_node.type = NodeType.CU
            exit_node.name = "FuncExit_" + func.name
            self.g.add_node(exit_id, data=exit_node)
            # find exit points
            subtree = subtree_of_type(self, func, CUNode, True)
            max_end_line = 0
            for node in subtree:
                if len(out_edges(self, node.id, EdgeType.SUCCESSOR)) == 0:
                    self.g.add_edge(node.id, exit_id, data=Dependency(EdgeType.SUCCESSOR))
                    max_end_line = max(max_end_line, node.end_line)
            exit_node.start_line = max_end_line
            exit_node.end_line = max_end_line

    def show(self) -> None:
        """Plots the graph

        :return:
        """
        # print("showing")
        plt.plot()  # type: ignore
        pos = self.pos

        # draw nodes
        nx.draw_networkx_nodes(
            self.g,
            pos=pos,
            node_size=200,
            node_color="#2B85FD",
            node_shape="o",
            nodelist=[n for n in self.g.nodes if isinstance(self.node_at(n), CUNode)],
        )
        nx.draw_networkx_nodes(
            self.g,
            pos=pos,
            node_size=200,
            node_color="#ff5151",
            node_shape="d",
            nodelist=[n for n in self.g.nodes if isinstance(self.node_at(n), LoopNode)],
        )
        nx.draw_networkx_nodes(
            self.g,
            pos=pos,
            node_size=200,
            node_color="grey",
            node_shape="s",
            nodelist=[n for n in self.g.nodes if isinstance(self.node_at(n), DummyNode)],
        )
        nx.draw_networkx_nodes(
            self.g,
            pos=pos,
            node_size=200,
            node_color="#cf65ff",
            node_shape="s",
            nodelist=[n for n in self.g.nodes if isinstance(self.node_at(n), FunctionNode)],
        )
        nx.draw_networkx_nodes(
            self.g,
            pos=pos,
            node_color="yellow",
            node_shape="h",
            node_size=250,
            nodelist=[n for n in self.g.nodes if self.node_at(n).name == "main"],
        )
        # id as label
        labels = {}
        for n in self.g.nodes:
            labels[n] = str(self.g.nodes[n]["data"])
        # fix missing positions
        x_min: float = min([pos[n][0] for n in self.g.nodes if n in pos])
        x_max: float = max([pos[n][0] for n in self.g.nodes if n in pos])
        y_min: float = min([pos[n][1] for n in self.g.nodes if n in pos])
        y_max: float = max([pos[n][1] for n in self.g.nodes if n in pos])
        for n in self.g.nodes:
            if n not in pos:
                rand_x = random.uniform(x_min, x_max)
                rand_y = random.uniform(y_min, y_max)
                pos[n] = (rand_x, rand_y)

        nx.draw_networkx_labels(self.g, pos, labels, font_size=7)

        nx.draw_networkx_edges(
            self.g,
            pos,
            edgelist=[e for e in self.g.edges(data="data") if e[2].etype == EdgeType.CHILD],
        )
        nx.draw_networkx_edges(
            self.g,
            pos,
            edge_color="green",
            edgelist=[e for e in self.g.edges(data="data") if e[2].etype == EdgeType.SUCCESSOR],
        )
        nx.draw_networkx_edges(
            self.g,
            pos,
            edge_color="red",
            edgelist=[e for e in self.g.edges(data="data") if e[2].etype == EdgeType.DATA],
        )
        nx.draw_networkx_edges(
            self.g,
            pos,
            edge_color="yellow",
            edgelist=[e for e in self.g.edges(data="data") if e[2].etype == EdgeType.CALLSNODE],
        )
        nx.draw_networkx_edges(
            self.g,
            pos,
            edge_color="orange",
            edgelist=[e for e in self.g.edges(data="data") if e[2].etype == EdgeType.PRODUCE_CONSUME],
        )

        plt.show()
        plt.savefig("graphX.svg")

    def node_at(self, node_id: NodeID) -> Node:
        """Gets node data by node id

        :param node_id: id of the node
        :return: Node
        """
        return cast(Node, self.g.nodes[node_id]["data"])

    def __cu_equal__(self, cu_1: Node, cu_2: Node) -> bool:
        """Alternative to CUNode.__eq__, bypasses the isinstance-check and relies on MyPy for type safety.
        :param cu_1: CUNode 1
        :param cu_2: CUNode 2
        :return: True, if cu_1 == cu_2. False, else"""
        if cu_1.file_id == cu_2.file_id and cu_1.node_id == cu_2.node_id:
            return True
        return False

    def get_node_parent_id(self, node: Node) -> Optional[NodeID]:
        """Returns the id of the FunctionNode which is the parent of the given node"""
        parents = [s for s, t, d in in_edges(self, node.id, EdgeType.CHILD)]
        if len(parents) == 0:
            return None
        elif len(parents) == 1:
            return parents[0]
        else:
            # it is possible that a node has a function-type and e.g. loop type parent
            # in this case, return the non-function type parent, since it will be a child of the function itself.
            if len(parents) > 2:
                raise ValueError("Node: ", node.id, "has too many parents!")
            else:
                for parent in parents:
                    if type(self.node_at(parent)) != FunctionNode:
                        return parent
        return None

    def get_dep(self, node: Node, dep_type: DepType, reversed: bool) -> List[Tuple[NodeID, NodeID, Dependency]]:
        """Searches all dependencies of specified type

        :param node: node
        :param dep_type: type of dependency
        :param reversed: if true the it looks for incoming dependencies
        :return: list of dependencies
        """
        return [
            e
            for e in (in_edges(self, node.id, EdgeType.DATA) if reversed else out_edges(self, node.id, EdgeType.DATA))
            if e[2].dtype == dep_type
        ]

    def path(self, source: Node, target: Node) -> List[Node]:
        """DFS from source to target over edges of child type

        :param source: source node
        :param target: target node
        :return: list of nodes from source to target
        """
        return self.__path_rec(source, target, set())

    def __path_rec(self, source: Node, target: Node, visited: Set[Node]) -> List[Node]:
        """DFS from source to target over edges of child type

        :param source: source node
        :param target: target node
        :return: list of nodes from source to target
        """
        visited.add(source)
        if source == target:
            return [source]

        for child in [c for c in direct_children_or_called_nodes(self, source) if c not in visited]:
            path = self.__path_rec(child, target, visited)
            if path:
                path.insert(0, source)
                return path
        return []
