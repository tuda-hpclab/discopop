# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
import copy
import json
import os
import sys
from multiprocessing import Pool
from typing import TYPE_CHECKING, List, Dict, Optional, Set, Tuple, cast
import warnings
import networkx as nx  # type: ignore

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.EnterParallelNode import EnterParallelNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ExitParallelNode import ExitParallelNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ReductionModifierNode import ReductionModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.DoallModifierNode import DoAllModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.functions.PEGraph.properties.depends_ignore_readonly import depends_ignore_readonly
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.properties.is_readonly_inside_loop_body import is_readonly_inside_loop_body
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.queries.variables import get_variables
from discopop_explorer.functions.PEGraph.traversal.parent import get_all_parent_functions, get_parent_function
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType  # type: ignore

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.utils import classify_loop_variables, filter_for_hotspots
from discopop_explorer.classes.variable import Variable
from discopop_library.ParallelRegionMerger.ArgumentClasses import ParallelRegionMergerArguments
from discopop_library.ParallelRegionMerger.Types import SUGGESTION_ID

if TYPE_CHECKING:
    from discopop_library.result_classes.DetectionResult import DetectionResult


class ParallelRegionInfo(PatternInfo):
    """Class, that contains SimpleTask detection result"""

    contains_patterns: List[int]
    shared_vars: List[Variable]

    def __init__(self, pet: PEGraphX, start_node: Node, end_line: LineID):
        """
        :param pet: PET graph
        :param node: node, where SimpleTask was detected
        """
        PatternInfo.__init__(self, start_node)
        self.pattern_tag = self.get_tag()
        self.contains_patterns = []
        self.shared_vars = []
        self.end_line = end_line
        self.pragma = "#pragma omp parallel"

    def __str__(self) -> str:
        return (
            f"ParallelRegion at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            # f"iterations: {self.iterations_count}\n"
            # f"instructions: {self.instructions_count}\n"
            # f"workload: {self.workload}\n"
            f'pragma: "#pragma omp parallel"\n'
            f'shared: {",".join([v.name for v in self.shared_vars])}'
        )

    def get_tag(self) -> str:
        result = super().get_tag() + "_"
        return result


def run_detection(
    pet: PEGraphX,
    res: DetectionResult,
    arguments: ParallelRegionMergerArguments,
    jobs: Optional[int] = None,
) -> Tuple[List[ParallelRegionInfo], List[DoAllInfo], List[ReductionInfo]]:
    """Search for InflatedParallelRegion pattern

    :param pet: PET graph
    :return: List of detected pattern info
    """

    tg = TaskGraph()

    __setup_task_graph(pet, tg)

    # tg.show(dataflow=False)

    __import_parallelization(pet, res, tg, arguments)

    __add_cross_level_dataflow_edges(pet, tg)

    __simple_inflate_parallel_regions(pet, tg)

    __simple_combine_successive_regions(pet, tg)

    tg.print_to_console()

    if arguments.allow_plots:
        tg.show(dataflow=False)

    # NOTE: IEC/IAC can be used to determine, wheter a CU is task-friendly on a coarse-grain level
    # ------> by unpacking IEC/IAC, the innermost function call which the CU is still friendly towards can be determined
    # --> probably checking for hostility is the better approach

    # traverse the graph and select the parallel regions and modified DoAll patterns to be reported
    parallel_regions, modified_doall_patterns, modified_reduction_patterns = select_patterns(pet, tg)

    parallel_regions, modified_doall_patterns, modified_reduction_patterns = prevent_nested_patterns(
        pet, tg, parallel_regions, modified_doall_patterns, modified_reduction_patterns
    )

    parallel_regions = set_affected_cu_ids(tg, parallel_regions, modified_doall_patterns, modified_reduction_patterns)

    return parallel_regions, modified_doall_patterns, modified_reduction_patterns


def __setup_task_graph(pet: PEGraphX, tg: TaskGraph) -> None:
    # create nodes
    for func in all_nodes(pet, FunctionNode):
        tg.add_function_node(func)

    for loop in all_nodes(pet, LoopNode):
        tg.add_loop_node(loop)

    for cu in all_nodes(pet, CUNode):
        tg.add_cu_node(cu)

    # create contains edges
    for func in all_nodes(pet, FunctionNode):
        for out_contains_edge in out_edges(pet, func.id, EdgeType.CHILD):
            source = tg.get_node(func)
            target = tg.get_node(pet.node_at(out_contains_edge[1]))
            if source is None or target is None:
                continue
            tg.add_contains_edge(source, target)

    for loop in all_nodes(pet, LoopNode):
        for out_contains_edge in out_edges(pet, loop.id, EdgeType.CHILD):
            source = tg.get_node(loop)
            target = tg.get_node(pet.node_at(out_contains_edge[1]))
            if source is None or target is None:
                continue
            tg.add_contains_edge(source, target)

    # create successor edges
    for cu in all_nodes(pet, CUNode):
        for out_successor_edge in out_edges(pet, cu.id, EdgeType.SUCCESSOR):
            source = tg.get_node(cu)
            target = tg.get_node(pet.node_at(out_successor_edge[1]))
            if source is None or target is None:
                continue
            tg.add_successor_edge(source, target)

    # create call edges
    for cu in all_nodes(pet, CUNode):
        for out_call_edge in out_edges(pet, cu.id, EdgeType.CALLSNODE):
            source = tg.get_node(cu)
            target = tg.get_node(pet.node_at(out_call_edge[1]))
            if source is None or target is None:
                continue
            tg.add_call_edge(source, target)

    # replace Loop nodes with single task
    tg.replace_loops_with_single_tasks()


def __import_parallelization(
    pet: PEGraphX, res: DetectionResult, tg: TaskGraph, arguments: ParallelRegionMergerArguments
) -> None:
    considered_suggestions = __get_considered_suggestion_ids(arguments)

    # add identified loop parallelization to the task graph
    for reduction_pattern in res.patterns.reduction:
        if len(considered_suggestions) > 0 and reduction_pattern.pattern_id not in considered_suggestions:
            continue

        loop_node = tg.get_node(pet.node_at(reduction_pattern.node_id))
        if loop_node is None:
            continue
        tg.add_reduction_modifier_node(loop_node, reduction_pattern)
        # get the parent task node created in tg.replace_loops_with_single_tasks
        parent = tg.get_parent(loop_node)
        if parent is not None:
            # collect data sharing clauses from pattern
            tg.add_parallel_region_around(parent, reduction_pattern.shared)

    for doall_pattern in res.patterns.do_all:
        if len(considered_suggestions) > 0 and doall_pattern.pattern_id not in considered_suggestions:
            continue
        loop_node = tg.get_node(pet.node_at(doall_pattern.node_id))
        if loop_node is None:
            continue
        tg.add_doall_modifier_node(loop_node, doall_pattern)
        # get the parent task node created in tg.replace_loops_with_single_tasks
        parent = tg.get_parent(loop_node)
        if parent is not None:
            # collect data sharing clauses from pattern
            tg.add_parallel_region_around(parent, doall_pattern.shared)


def __get_considered_suggestion_ids(arguments: ParallelRegionMergerArguments) -> List[int]:
    # get list of suggestions ids to be considered
    considered_suggestions: List[SUGGESTION_ID] = []  # empty -> wildcard
    if arguments.suggestions is not None:
        if arguments.suggestions == "auto":
            with open(os.path.join(arguments.dot_dp_path, "auto_tuner", "results.json"), "r") as f:
                auto_tuner_results = json.load(f)
                if arguments.auto_tuner_config in auto_tuner_results:
                    considered_suggestions = [
                        int(s) for s in auto_tuner_results[arguments.auto_tuner_config]["applied_suggestions"]
                    ]
                else:
                    for config in auto_tuner_results:
                        considered_suggestions += [int(s) for s in auto_tuner_results[config]["applied_suggestions"]]
        else:
            considered_suggestions = [int(s) for s in arguments.suggestions.split(",")]
    return considered_suggestions


def __add_cross_level_dataflow_edges(pet: PEGraphX, tg: TaskGraph) -> None:
    # add edges representing data flow inbetween "contains" levels. Derived from the dependency edges in pet
    for cu in all_nodes(pet, CUNode):
        for out_dep in out_edges(pet, cu.id, EdgeType.DATA):
            if out_dep[2].dtype == DepType.RAW:
                source = tg.get_node(pet.node_at(out_dep[1]))
                target = tg.get_node(pet.node_at(out_dep[0]))
                if source is None or target is None:
                    continue
                if source != target and tg.get_parent(source) != tg.get_parent(target):
                    tg.add_dataflow_edge(source, target)
            elif out_dep[2].dtype == DepType.WAR:
                source = tg.get_node(pet.node_at(out_dep[0]))
                target = tg.get_node(pet.node_at(out_dep[1]))
                if source is None or target is None:
                    continue
                if source != target and tg.get_parent(source) != tg.get_parent(target):
                    tg.add_dataflow_edge(source, target)


def __simple_inflate_parallel_regions(pet: PEGraphX, tg: TaskGraph) -> None:
    # add edges marking friendly nodes towards parallel regions, i.e. such which could be included into the region
    # a node is friendly, if
    # - (1) it is an immediate predecessor / successors of a parallel region entry / exit, and
    # - (2) it is not a parallel region itself
    # - (3) it has at most one incoming and outgoing successor edge (i.e. no branching), and
    # - (4) it has only outgoing dataflow edges into the parallel region or incoming dataflow from the parallel region.
    # (5) Create a new Parallel region spaning the old parallel region and the friendly node.
    # (6) Attach a shared "friendly" marker to the friendly nodes and the newly created, containing parallel region.

    # inflate entry
    entry_queue: List[EnterParallelNode] = []
    for tgn in tg.get_all_nodes():
        if type(tgn) == EnterParallelNode:
            entry_queue.append(tgn)
    while entry_queue:
        current_entry = entry_queue.pop()
        # get predecessor (1)
        predecessor = tg.get_predecessor(current_entry)
        if predecessor is None:
            continue
        # check (2)
        if type(predecessor) == EnterParallelNode or type(predecessor) == ExitParallelNode:
            continue
        # check (3)
        if len(tg.get_successors(predecessor)) > 1 or len(tg.get_predecessors(predecessor)) > 1:
            continue
        # check (4)
        invalid = False
        for dft in tg.get_dataflow_targets(predecessor):
            if dft not in tg.get_nodes_contained_in_region(current_entry):
                invalid = True
                break
        if invalid:
            continue
        # (5)
        current_exit = tg.get_connected_exit(current_entry)
        if current_exit is None:
            continue
        created_entry = tg.add_parallel_region_around_nodes(predecessor, current_exit, current_entry.shared_vars)
        # (6)
        tg.add_friendly_modifier(predecessor, current_entry, created_entry)

    exit_queue: List[ExitParallelNode] = []
    for tgn in tg.get_all_nodes():
        if type(tgn) == ExitParallelNode:
            exit_queue.append(tgn)
    while exit_queue:
        current_exit = exit_queue.pop()
        # get successor (1)
        successors = tg.get_successors(current_exit)
        if len(successors) == 0:
            continue
        successor = successors[0]
        # check (2)
        if type(successor) == ExitParallelNode or type(successor) == EnterParallelNode:
            continue
        # check (3)
        if len(tg.get_successors(successor)) > 1 or len(tg.get_predecessors(successor)) > 1:
            continue
        # check (4)
        invalid = False
        for dft in tg.get_dataflow_sources(successor):
            if dft not in tg.get_nodes_contained_in_region(current_exit):
                invalid = True
                break
        if invalid:
            continue
        # (5)
        entry = tg.get_connected_entry(current_exit)
        if entry is None:
            continue
        created_entry = tg.add_parallel_region_around_nodes(entry, successor, entry.shared_vars)
        # (6)
        tg.add_friendly_modifier(entry, successor, created_entry)


def __simple_combine_successive_regions(pet: PEGraphX, tg: TaskGraph) -> None:
    """Combine parallel regions in immediate succession, if exactly one successor edge exists between them."""
    queue: List[EnterParallelNode] = []
    for tgn in tg.get_all_nodes():
        if type(tgn) == EnterParallelNode:
            queue.append(tgn)
    # for each EnterParallelNode, check if the predecessor is a ExitParallelNode.
    # If so, create a new parallel region spanning both and enter the newly created Region back into the queue.

    while queue:
        current_entry = queue.pop()
        predecessors = tg.get_predecessors(current_entry)
        if len(predecessors) != 1:
            continue
        predecessor = predecessors[0]
        if type(predecessor) != ExitParallelNode:
            continue

        predecessor_entry = tg.get_connected_entry(predecessor)
        current_exit = tg.get_connected_exit(current_entry)

        if predecessor_entry is None or current_exit is None:
            continue

        # collect shared vars

        shared_vars = __get_shared_vars_from_combination(predecessor_entry, current_entry)
        new_entry = tg.add_parallel_region_around_nodes(predecessor_entry, current_exit, shared_vars)
        queue.append(new_entry)


def __get_shared_vars_from_combination(entry_1: EnterParallelNode, entry_2: EnterParallelNode) -> List[Variable]:
    """calcuate and return the shared variables for a combined Parallel region spaning regions 1 and 2, where 1 is a direct predecessor of 2."""
    # TODO maybe a consideration of definition lines of the variables etc is necessary
    # TODO write unit tests
    shared_vars = [v for v in entry_1.shared_vars if v in entry_2.shared_vars]
    return shared_vars


def select_patterns(
    pet: PEGraphX, tg: TaskGraph
) -> Tuple[List[ParallelRegionInfo], List[DoAllInfo], List[ReductionInfo]]:
    parallel_regions: List[ParallelRegionInfo] = []
    modified_doall_patterns: List[DoAllInfo] = []
    modified_reduction_patterns: List[ReductionInfo] = []
    # traverse the graph and select the parallel regions and modified DoAll patterns to be reported
    # select the outer-most parallel regions and their contained DoAll and Reduciton Loops

    # select all functions as starting points, which have no incoming call edges
    function_nodes: List[TGFunctionNode] = []
    for tgn in tg.get_all_nodes():
        if type(tgn) == TGFunctionNode:
            if len(tg.get_callers(tgn)) == 0:
                function_nodes.append(tgn)
    print("ENTRY FUNCITONS:")
    for fn in function_nodes:
        print("-> ", fn.fn.start_position(), fn.fn.name)

    outermost_parallel_regions: List[EnterParallelNode] = []
    region_contains_dict: Dict[EnterParallelNode, List[int]] = dict()
    for func in function_nodes:
        queue: List[TGNode] = [func]
        visited: List[TGNode] = []
        entered_parallel_region: Optional[int] = None

        # traverse the graph and identify outermost parallel regions and contained parallel contructs
        while queue:
            current = queue.pop(0)
            visited.append(current)
            if type(current) == TGFunctionNode:
                print("encountered Function: ", current.fn.name)
            if type(current) == EnterParallelNode and entered_parallel_region is None:
                # found outer-most parallel region
                entered_parallel_region = current.parallel_region_id
                outermost_parallel_regions.append(current)
                print("Entered ", current.parallel_region_id)
                if current not in region_contains_dict:
                    region_contains_dict[current] = []
            elif (
                type(current) == ExitParallelNode
                and entered_parallel_region is not None
                and entered_parallel_region == current.parallel_region_id
            ):
                # found exit of the outer-most parallel region
                print("Exiting ", current.parallel_region_id)
                entered_parallel_region = None
            else:
                modifiers = tg.get_modifiers(current)
                for mod in modifiers:
                    if type(mod) == DoAllModifierNode:
                        modified_doall_pattern = copy.deepcopy(mod.do_all_pattern)
                        modified_doall_pattern.request_pattern_id()
                        modified_doall_pattern.standalone_pattern = False
                        modified_doall_pattern.applicable_pattern = False
                        modified_doall_pattern.pragma = "#pragma omp for"
                        modified_doall_pattern.shared = []
                        modified_doall_patterns.append(modified_doall_pattern)
                        # check if parallel region entered
                        if len(outermost_parallel_regions) > 0:
                            region_contains_dict[outermost_parallel_regions[-1]].append(
                                modified_doall_pattern.pattern_id
                            )
                    elif type(mod) == ReductionModifierNode:
                        modified_reduction_pattern = copy.deepcopy(mod.reduction_pattern)
                        modified_reduction_pattern.request_pattern_id()
                        modified_reduction_pattern.standalone_pattern = False
                        modified_reduction_pattern.applicable_pattern = False
                        modified_reduction_pattern.pragma = "#pragma omp for"
                        modified_reduction_pattern.shared = []
                        modified_reduction_patterns.append(modified_reduction_pattern)
                        # check if parallel region entered
                        if len(outermost_parallel_regions) > 0:
                            region_contains_dict[outermost_parallel_regions[-1]].append(
                                modified_reduction_pattern.pattern_id
                            )

            # first traverse called, then children, then successors due to queue.pop(0)
            for succ in tg.get_successors(current):
                if succ not in queue and succ not in visited:
                    queue.insert(0, succ)

            #            for child in tg.get_contained(current):
            #                # select entry to successor sequence
            #                if len(tg.get_predecessors(child)) == 0:
            #                    if child not in queue and child not in visited:
            #                        queue.insert(0, child)

            seen_child = False
            required_add_random_child = True
            for child in tg.get_contained(current):
                seen_child = True
                if child in visited or child in queue:
                    continue
                # select entry to successor sequence
                if len(tg.get_predecessors(child)) != 0:
                    continue
                queue.insert(0, child)
                required_add_random_child = False
            if seen_child and required_add_random_child:
                # select the child with the lowest line id
                children = tg.get_contained(current)
                children_first_pet_nodes = [tg.get_first_contained_pet_node(c) for c in children]
                children_first_lines = [p.start_line for p in children_first_pet_nodes]
                children_with_lines = [(children[idx], children_first_lines[idx]) for idx, c in enumerate(children)]
                sorted_children_with_lines = sorted(children_with_lines, key=lambda x: x[1])
                selected_child = sorted_children_with_lines[0][0]
                if selected_child not in visited:
                    queue.insert(0, selected_child)

            for called in tg.get_called(current):
                # select entry to successor sequence
                if len(tg.get_predecessors(called)) == 0:
                    if called not in queue and called not in visited:
                        queue.insert(0, called)

    for opr in outermost_parallel_regions:
        first_pet_node = tg.get_first_contained_pet_node(opr)
        last_pet_node = tg.get_last_contained_pet_node(opr.last_contained_task)
        last_line = (
            last_pet_node.end_position()
            if last_pet_node.return_instructions_count == 0
            else last_pet_node.start_position()
        )
        parallel_region_pattern = ParallelRegionInfo(pet, first_pet_node, last_line)
        parallel_region_pattern.shared_vars = opr.shared_vars
        parallel_region_pattern.contains_patterns = list(region_contains_dict[opr])
        parallel_regions.append(parallel_region_pattern)

    return parallel_regions, modified_doall_patterns, modified_reduction_patterns


def prevent_nested_patterns(
    pet: PEGraphX,
    tg: TaskGraph,
    parallel_regions: List[ParallelRegionInfo],
    modified_doall_patterns: List[DoAllInfo],
    modified_reduction_patterns: List[ReductionInfo],
) -> Tuple[List[ParallelRegionInfo], List[DoAllInfo], List[ReductionInfo]]:
    """check patterns for nested parallel loops.
    Collapse if possible, otherwise, remove nested pragma"""
    # prepare metadata
    patterns_by_id: Dict[int, PatternInfo] = dict()
    base_nodes_by_id: Dict[int, TGNode] = dict()
    pattern_id_by_base_node: Dict[TGNode, int] = dict()
    for pattern in parallel_regions + modified_doall_patterns + modified_reduction_patterns:
        patterns_by_id[pattern.pattern_id] = pattern
        base_node = tg.get_node(pattern._node)
        if base_node is None:
            raise ValueError("Could not find base_node for pattern " + str(pattern.pattern_id))
        base_nodes_by_id[pattern.pattern_id] = base_node
        pattern_id_by_base_node[base_nodes_by_id[pattern.pattern_id]] = pattern.pattern_id

    # check parallel regions
    for parallel_region in parallel_regions:
        queue: List[int] = [pid for pid in parallel_region.contains_patterns]
        while queue:
            # check each pattern as a basis
            current_pattern_id = queue.pop()
            pattern_base_node = base_nodes_by_id[current_pattern_id]
            contained_nodes = tg.get_nodes_contained_in_region(pattern_base_node)
            contained_pattern_base_nodes = [
                n for n in contained_nodes if n in base_nodes_by_id.values() and n != pattern_base_node
            ]
            contained_pattern_ids = [pattern_id_by_base_node[bn] for bn in contained_pattern_base_nodes]

            # check for collapsability (exactly one loop perfectly nested)
            collapsable: List[int] = []
            if len(contained_pattern_ids) == 1:
                for contained_pattern_id in contained_pattern_ids:
                    if tg.is_direct_child(pattern_base_node, base_nodes_by_id[contained_pattern_id]):
                        # found potential for collapse
                        collapsable.append(contained_pattern_id)

            # perform collapse if possible
            if len(collapsable) > 0:
                pattern_obj = patterns_by_id[current_pattern_id]
                if isinstance(pattern_obj, DoAllInfo) or isinstance(pattern_obj, ReductionInfo):
                    pattern_obj.collapse_level += 1

            # remove contained patterns
            for ncpid in [pid for pid in contained_pattern_ids]:
                if ncpid in queue:
                    queue.remove(ncpid)
                if ncpid in parallel_region.contains_patterns:
                    parallel_region.contains_patterns.remove(ncpid)

    return parallel_regions, modified_doall_patterns, modified_reduction_patterns


def set_affected_cu_ids(
    tg: TaskGraph,
    parallel_regions: List[ParallelRegionInfo],
    modified_doall_patterns: List[DoAllInfo],
    modified_reduction_patterns: List[ReductionInfo],
) -> List[ParallelRegionInfo]:
    # prepare metadata
    patterns_by_id: Dict[int, PatternInfo] = dict()
    for pattern in parallel_regions + modified_doall_patterns + modified_reduction_patterns:
        patterns_by_id[pattern.pattern_id] = pattern
        base_node = tg.get_node(pattern._node)
        if base_node is None:
            raise ValueError("Could not find base_node for pattern " + str(pattern.pattern_id))

    for par_reg in parallel_regions:
        affected_cus: List[NodeID] = par_reg.affected_cu_ids
        for contained_pattern_id in par_reg.contains_patterns:
            affected_cus += patterns_by_id[contained_pattern_id].affected_cu_ids
        affected_cus = list(dict.fromkeys(affected_cus))
        par_reg.affected_cu_ids = affected_cus
    return parallel_regions
