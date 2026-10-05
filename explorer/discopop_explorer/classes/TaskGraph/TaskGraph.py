# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
from collections import deque
import os
from pathlib import Path
import random
import re
import signal
import logging
import sys
from typing import Any, Deque, Dict, FrozenSet, List, NamedTuple, Optional, Set, Tuple, Union, cast
import warnings
import networkx as nx  # type: ignore
import matplotlib
from matplotlib.axes import Axes
from networkx import Graph
import matplotlib.lines as mlines

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import CARRIED_OUTSIDE, Dependency

from discopop_explorer.classes.TaskGraph.Branching.TGEndBranchNode import TGEndBranchNode
from discopop_explorer.classes.TaskGraph.Branching.TGEndBranchParentNode import TGEndBranchParentNode
from discopop_explorer.classes.TaskGraph.Branching.TGStartBranchNode import TGStartBranchNode
from discopop_explorer.classes.TaskGraph.Branching.TGStartBranchParentNode import TGStartBranchParentNode
from discopop_explorer.classes.TaskGraph.Contexts.BranchContext import BranchContext
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.ContextStack import ContextStack
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Contexts.utils import (
    CallStackElementType,
    convert_callstacks_to_lineIDs,
    get_context_call_stack,
)
from discopop_explorer.classes.TaskGraph.Functions.TGEndFunctionNode import TGEndFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGEndInlinedFunctionNode import TGEndInlinedFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGStartFunctionNode import TGStartFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGStartInlinedFunctionNode import TGStartInlinedFunctionNode
from discopop_explorer.classes.TaskGraph.Loops.TGEndLoopNode import TGEndLoopNode
from discopop_explorer.classes.TaskGraph.Loops.TGEndtIterationNode import TGEndIterationNode
from discopop_explorer.classes.TaskGraph.Loops.TGStartIterationNode import TGStartIterationNode
from discopop_explorer.classes.TaskGraph.Loops.TGStartLoopNode import TGStartLoopNode
from discopop_explorer.classes.TaskGraph.RootNode import RootNode
from discopop_explorer.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_explorer.classes.TaskGraph.VisitorMarker import EndFunctionMarker, VisitorMarker
from discopop_explorer.classes.TaskGraph.loopstate_positions import (
    LOOPSTATE_POSITIONS_FILE,
    LoopstatePosition,
    read_loopstate_digit_counts,
    read_loopstate_positions,
)
from discopop_explorer.classes.TaskGraph.Work.TGEndWorkNode import TGEndWorkNode
from discopop_explorer.classes.TaskGraph.Work.TGStartWorkNode import TGStartWorkNode
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.traversal.called_functions import (
    get_call_instruction_id,
    get_called_node_ids,
    get_called_nodes,
)
from discopop_explorer.functions.PEGraph.traversal.children import get_entry_child
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.functions.PEGraph.traversal.predecessors import direct_predecessors
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_library.StatusReporting.console import progress, stage, warn

if os.environ.get("DISPLAY") or sys.platform in ("darwin", "win32"):
    try:
        matplotlib.use("TkAgg")
    except Exception:
        matplotlib.use("Agg")
else:
    # no display available (e.g. headless server via ssh): avoid an interactive
    # backend, which would crash as soon as a figure is created
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # type: ignore
from matplotlib.patches import Rectangle

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Aliases import (
    FunctionID,
    LevelIndex,
    PETNode,
    PETNodeID,
    PositionIndex,
    TGNodeID,
)
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

try:
    from discopop_gui.Enums.EdgeType import EdgeType as TreeEdgeType
    from discopop_gui.Extendables.Plottable import Plottable
    from discopop_gui.Visualizers.Base import Base as Visualizer
    from discopop_gui.Objects.Frames.CanvasViewerWithTrees import CanvasViewerWithTrees
except (ImportError, ModuleNotFoundError):

    class Plottable:  # type: ignore[no-redef]
        def __init__(self, visualizer: object = None) -> None:
            pass

        def plottable(self) -> bool:
            return False

    Visualizer = object  # type: ignore[assignment, misc]
    CanvasViewerWithTrees = object  # type: ignore[assignment, misc]

logger = logging.getLogger("Explorer")

# how __validate_graph_structure refers to code that no function entry node reaches any more
DETACHED_REGION = "a region not reachable from any function entry node"

# callpath state markers ("<line_id>@<state_id>") as emitted by the profiler into
# dynamic_dependencies.txt. Removing them is what --ignore-dependency-states does.
STATE_MARKER_PATTERN = re.compile(r"@\d+")


# Aliases
TGConstructionQueueElement = Tuple[Optional[TGNode], Union[PETNode, VisitorMarker]]  # (Predecessor, current element)


class MappedDependencyRecord(NamedTuple):
    """A dynamic dependency record of the profiler with its ends mapped to work contexts (see
    TaskGraph.map_dynamic_dependency_records). An end is (instruction id, state id, line id); the
    first end is the first column of the profiler's line, i.e. the later access."""

    dep_type: str
    var_name: str
    first: Tuple[int, int, Optional[LineID]]
    other: Optional[Tuple[int, int, Optional[LineID]]]
    # (first context, other context), filtered like the edges of the dependency insertion
    pairs: List[Tuple[Context, Context]]
    first_contexts: List[Context]
    other_contexts: List[Context]


class _ContextFallback:
    """Maps a dependency end whose state no work context at its location carries (a loop header
    line, a structure the state assignment could not resolve), instead of dropping it: dropping a
    dependency is unsound for parallelism detection, since a missing loop-carried dependency
    allows a false do-all or reduction suggestion.

    The end is mapped to the work contexts at the location below the closest common scope: the
    contexts carrying the state itself (or their closest ancestor) whose subtree contains contexts
    at the location; if there is none, to all contexts at the location. Both over-approximate.
    The (location, state) pairs mapped this way are collected in `approximate`."""

    def __init__(self, contexts: List[Context]) -> None:
        self.contexts_by_state: Dict[int, List[Context]] = {}
        for ctx in contexts:
            for state_id in ctx.state_ids:
                self.contexts_by_state.setdefault(int(state_id), []).append(ctx)
        self.ancestors: Dict[Context, Set[Context]] = {}
        self.approximate: Set[Tuple[str, int]] = set()
        self.location_only = 0
        self.scoped = 0

    def _ancestors(self, ctx: Context) -> Set[Context]:
        cached = self.ancestors.get(ctx)
        if cached is None:
            cached = set(ctx.get_ancestor_contexts())
            cached.add(ctx)
            self.ancestors[ctx] = cached
        return cached

    def resolve(self, location: str, state_id: int, contexts: Set[Context]) -> Set[Context]:
        self.approximate.add((location, state_id))
        for anchor in self.contexts_by_state.get(state_id, []):
            scope: Optional[Context] = anchor
            depth = 0
            while scope is not None and depth < 10000:
                below = {ctx for ctx in contexts if scope in self._ancestors(ctx)}
                if len(below) > 0:
                    self.scoped += 1
                    return below
                scope = scope.parent_context
                depth += 1
        self.location_only += 1
        return set(contexts)


class TaskGraph(Plottable, object):  # type: ignore[misc]
    pet: PEGraphX
    graph: nx.MultiDiGraph
    # class-level default so instances created without __init__ (e.g. the test
    # fixtures, which bypass it) still read as "states are interpreted"
    ignore_dependency_states: bool = False
    dynamic_dependency_file: Optional[str] = None
    static_dependency_file: Optional[str] = None
    root: TGNode
    function_id_map: Dict[PETNodeID, FunctionID] = dict()
    TGNode_pet_node_id_to_tg_node: Dict[PETNodeID, TGNode] = dict()
    TGFunctionNode_pet_node_id_to_tg_node: Dict[PETNodeID, TGFunctionNode] = dict()
    TGStartFunctionNode_pet_node_id_to_tg_node: Dict[PETNodeID, TGStartFunctionNode] = dict()
    TGEndFunctionNode_pet_node_id_to_tg_node: Dict[PETNodeID, TGEndFunctionNode] = dict()
    contexts: List[Context] = []
    current_level: LevelIndex = 0
    current_position: Dict[LevelIndex, PositionIndex] = {0: 0}
    plotting_graph_buffer = None
    plotting_postions_buffer = None
    # __inline_function_calls stops at this depth ("depth >= limit"), so calls are inlined at most
    # CALL_PATH_LIMIT - 1 levels deep
    CALL_PATH_LIMIT: int = 6
    # CUs reachable only through an early exit out of a loop (exit(), abort()), deleted by
    # __fix_loop_structures together with their dependencies
    cus_deleted_by_early_exits: Set[PETNodeID] = set()
    # CUs reachable only through exception landing pads, see __cut_exception_unwind_paths
    cus_deleted_by_exception_unwinding: Set[PETNodeID] = set()
    # source of TGNode.creation_index, see add_node
    __node_counter: int = 0
    # the loops (by their entry CU, LoopParentContext.parent_loop) whose exits __fix_loop_structures
    # cut (break, return, exit()), with the lines of the cut edges' sources. Such a loop is no
    # candidate for a parallel loop: an OpenMP for loop cannot be left early.
    loops_with_cut_exits: Dict[PETNodeID, Set[str]] = dict()
    # the LoopNodes whose lines contain a catch handler deleted by __cut_exception_unwind_paths: the
    # dependencies of the handler were never inserted
    loop_nodes_with_cut_exception_handlers: Set[NodeID] = set()
    # the PET loops (by their entry CU) per (function name, loopstate position), see
    # __assign_loopstate_positions_within_functions. Used to name the loop a dependency is carried
    # by from the callpath states of its ends alone (Dependency.carried_by_pet_loop).
    loop_pet_ids_by_loopstate_position: Dict[Tuple[str, int], Set[PETNodeID]] = dict()
    # dynamic dependency records with an end on a line only covered by CUs deleted by the cuts
    # (early exits, exception unwind paths), see __insert_data_dependencies_from_files
    records_on_deleted_lines: int = 0
    # the lines of the ends of the dynamic dependency records, i.e. code executed during profiling
    lines_with_dynamic_records: Set[LineID] = set()
    # counters of __split_branch_region_side_entries over all functions
    branch_region_side_entry_statistics: Dict[str, int] = dict()
    # copy -> original of every node __split_branch_region_side_entries duplicated, so that the
    # intended copies of a context can be told apart from structural errors (see the tests)
    tail_duplication_origins: Dict[TGNode, TGNode] = dict()
    # states __assign_state_ids attached by the suffix fallback, see there
    approximately_assigned_state_ids: Set[int] = set()
    # counters of the approximately mapped dependency ends, see _ContextFallback
    approximate_dependency_end_statistics: Dict[str, int] = dict()
    # counters of the last __assign_state_ids run, see there
    state_assignment_statistics: Dict[str, int] = dict()

    def __init__(
        self,
        pet: PEGraphX,
        dynamic_dependency_file: Optional[str] = None,
        static_dependency_file: Optional[str] = None,
        visualizer: Visualizer | None = None,
        ignore_dependency_states: bool = False,
    ) -> None:
        super().__init__(visualizer)

        self.pet = pet
        self.graph = nx.MultiDiGraph()
        self.ignore_dependency_states = ignore_dependency_states
        # kept for map_dynamic_dependency_records (side effect export)
        self.dynamic_dependency_file = dynamic_dependency_file
        self.static_dependency_file = static_dependency_file
        # shadow the class-level defaults with per-instance state: the construction passes
        # look up previously created nodes in these maps, so sharing them between TaskGraph
        # instances (e.g. two runs within one GUI session) would wire a fresh graph up to
        # nodes belonging to the previous one
        self.function_id_map = dict()
        self.TGNode_pet_node_id_to_tg_node = dict()
        self.TGFunctionNode_pet_node_id_to_tg_node = dict()
        self.TGStartFunctionNode_pet_node_id_to_tg_node = dict()
        self.TGEndFunctionNode_pet_node_id_to_tg_node = dict()
        self.contexts = []
        self.current_level = 0
        self.current_position = {0: 0}
        self.loops_with_cut_exits = dict()
        self.loop_nodes_with_cut_exception_handlers = set()
        self.loop_pet_ids_by_loopstate_position = dict()
        self.records_on_deleted_lines = 0
        self.lines_with_dynamic_records = set()
        self._loop_nodes_by_size = None

        # start processing
        with stage("Assigning function ids", 1, total=6):
            self.__assign_function_ids(pet)
        with stage("Constructing TaskGraph structure", 2, total=6):
            self.__construct_from_pet(pet)
        with stage("Assigning state ids", 3, total=6):
            self.__assign_state_ids(dynamic_dependency_file)
        with stage("Inserting data dependencies", 4, total=6):
            self.__insert_data_dependencies_from_files(dynamic_dependency_file, static_dependency_file)
        with stage("Determining loop variables", 5, total=6):
            self.__determine_loop_variables()
        with stage("Cleaning up loop dependencies", 6, total=6):
            self.__cleanup_loop_dependencies()

    def __assign_function_ids(self, pet: PEGraphX) -> None:
        id = 0
        for function in all_nodes(pet, type=FunctionNode):
            self.function_id_map[function.id] = id
            id += 1
        logger.info("Assigned function ids:\n" + str(self.function_id_map))

    def __construct_from_pet(self, pet: PEGraphX) -> None:
        # prepare function graphs without calling
        with stage("Visiting PET nodes", 1, total=14):
            self.__visit_pet(pet)
            self.__cut_exception_unwind_paths()
        with stage("Breaking cycles", 2, total=14):
            self.__break_cycles()
        with stage("Fixing loop structures", 3, total=14):
            self.__fix_loop_structures()
        with stage("Duplicating loop iterations", 4, total=14):
            self.__duplicate_loop_iterations()
        with stage("Validating graph structure", 5, total=14):
            self.__validate_graph_structure()
        with stage("Adding work nodes", 6, total=14):
            self.__add_work_nodes()
        with stage("Assigning loop-state positions", 7, total=14):
            self.__assign_loopstate_positions_within_functions()
        with stage("Inlining function calls", 8, total=14):
            self.__inline_function_calls()
        with stage("Adding branching nodes", 9, total=14):
            self.__add_branching_nodes()

        # assign contexts before inlining to keep runtime of branching context detection in check
        with stage("Assigning contexts", 10, total=14):
            self.__assign_contexts()
        with stage("Assigning node levels", 11, total=14):
            self.__assign_node_levels()
        with stage("Calculating context nesting", 12, total=14):
            self.__calculate_context_nesting()
        with stage("Calculating context successions", 13, total=14):
            self.__calculate_context_successions()
        with stage("Validating context structure", 14, total=14):
            self.__validate_context_structure()
        # self.__insert_pessimistic_data_dependencies()
        # self.__insert_data_dependencies()
        # self.__validate_data_dependencies()

    def add_node(self, node: TGNode) -> None:
        # a stable tie-breaker for orders among nodes of one pet node (copies of iterations,
        # inlined functions and duplicated tails), see __pet_node_order
        self.__node_counter += 1
        node.creation_index = self.__node_counter
        self.graph.add_node(node)

    def add_edge(self, source: Optional[TGNode], target: Optional[TGNode]) -> None:
        if source is None or target is None:
            return
        # disallow duplicate edges
        if self.graph.has_edge(source, target):
            return
        self.graph.add_edge(source, target)

    def __get_next_level(self) -> LevelIndex:
        buffer = self.current_level
        self.current_level += 1
        self.current_position[self.current_level] = 0
        return buffer

    def __get_current_level(self) -> LevelIndex:
        return self.current_level

    def __get_next_position(self, level: LevelIndex) -> PositionIndex:
        buffer = self.current_position[self.current_level]
        self.current_position[self.current_level] += 1
        return buffer

    def plot(self, highlight_nodes: Optional[List[TGNode]] = None) -> None:
        ax = plt.gca()  # type: ignore[attr-defined]
        self.update_plot(ax, self.graph, highlight_nodes=highlight_nodes)
        print("Waiting for user to close the Window...")
        plt.show()

    def quick_layout(self, subgraph: Optional[Graph] = None) -> Dict[TGNode, Tuple[float, float]]:
        logger.info("----> generating quick layout...")
        if subgraph is None:
            graph = self.graph
        else:
            graph = subgraph
        positions: Dict[TGNode, Tuple[float, float]] = dict()
        entries: List[TGNode] = []
        for node in graph.nodes:
            if graph.in_degree(node) > 0:
                continue
            entries.append(node)

        # assign positions by dfs-traversing
        occupied_positions: Dict[int, int] = dict()
        current_x_offset = 0
        for entry in entries:
            # get x offset of the current tree and reset the occupied positions
            current_x_offset = max(occupied_positions.values()) if len(occupied_positions.values()) > 0 else 0
            occupied_positions.clear()
            # assign positions
            queue: List[Tuple[TGNode, int]] = [(entry, 0)]
            while len(queue) > 0:
                current_node, current_level = queue.pop()
                if current_node in positions:
                    continue

                if current_level not in occupied_positions:
                    occupied_positions[current_level] = current_x_offset
                occupied_positions[current_level] += 1
                current_position = occupied_positions[current_level]
                positions[current_node] = (float(current_position), float(-current_level))

                out_edges = graph.out_edges(current_node)

                for _, target in out_edges:
                    queue.append((target, current_level + 1))
        return positions

    def update_plot(
        self, axis: Axes, subgraph: Optional[Graph] = None, highlight_nodes: Optional[List[TGNode]] = None
    ) -> None:
        logger.info("Plotting..")
        if subgraph is None:
            graph = self.graph
        else:
            graph = subgraph
        #         signal.signal(signal.SIGINT, signal.SIG_DFL)

        # TODO implement custon positioning for cases where only contexts are printed
        logger.info("---> generating layout...")
        # positions = nx.nx_pydot.pydot_layout(graph, prog="dot")
        positions = self.quick_layout(graph)
        logger.info("--->    Done.")

        # draw context patches
        min_patch_width = 1.0

        ax = axis

        for ctx in self.contexts:
            # calculate bounding box
            x_min = None
            x_max = None
            y_min = None
            y_max = None
            for ctx_node in ctx.get_contained_nodes(inclusive=True):
                if not graph.has_node(ctx_node):  # in case subgraphs are plotted
                    continue
                x, y = positions[ctx_node]
                if x_min is None:
                    x_min = x
                else:
                    x_min = min(x_min, x)
                if x_max is None:
                    x_max = x
                else:
                    x_max = max(x_max, x)
                if y_min is None:
                    y_min = y
                else:
                    y_min = min(y_min, y)
                if y_max is None:
                    y_max = y
                else:
                    y_max = max(y_max, y)

            if x_min is None:
                continue
            if x_max is None:
                continue
            if y_min is None:
                continue
            if y_max is None:
                continue

            # draw bounding box
            x_span = x_max - x_min
            y_span = y_max - y_min

            # force minimum x_span
            if x_span < min_patch_width:
                difference = min_patch_width - x_span
                x_span = min_patch_width
                x_min = x_min - (difference / 2)

            axis.add_patch(  # type: ignore
                Rectangle(
                    (x_min, y_min),
                    width=x_span,
                    height=y_span,
                    linewidth=1,
                    edgecolor=ctx.get_plot_border_color(),
                    facecolor=ctx.get_plot_face_color(),
                    alpha=ctx.get_plot_face_alpha(),
                )
            )

        # TODO add option to show contexts only
        # draw regular nodes
        if highlight_nodes is None:
            nx.draw_networkx_nodes(graph, positions, ax=ax)
        else:
            nx.draw_networkx_nodes(
                graph, positions, nodelist=[n for n in graph.nodes() if n not in highlight_nodes], ax=ax
            )
        # draw highlighted nodes
        if highlight_nodes is not None:
            nx.draw_networkx_nodes(graph, positions, nodelist=highlight_nodes, node_color="red", ax=ax)

        # draw edges
        nx.draw_networkx_edges(graph, positions, ax=ax)

        # get node labels
        labels = {}
        for node in graph.nodes():
            labels[node] = node.get_label()
        nx.draw_networkx_labels(graph, positions, labels, font_size=7, ax=ax)
        logger.info("---> showing...")

        self.plotting_graph_buffer = graph
        self.plotting_postions_buffer = positions

        # plt.pause(0.01)

    def update_plot_node_color(self, nodes: List[TGNode], color: str) -> None:
        nx.draw_networkx_nodes(
            self.plotting_graph_buffer, self.plotting_postions_buffer, nodelist=nodes, node_color=color
        )

    def plot_context_graph(self, axis: Axes) -> None:
        logger.info("Plotting context graph...")

        ctx_graph = nx.MultiDiGraph()
        for ctx in self.contexts:
            ctx_graph.add_node(ctx)
        # add contained edges for positioning
        for ctx in self.contexts:
            for contained_ctx in ctx.contained_contexts:
                ctx_graph.add_edge(ctx, contained_ctx)
        # add successor edges for positioning
        for ctx in self.contexts:
            if ctx.successor is not None:
                ctx_graph.add_edge(ctx, ctx.successor)
        # calculate layout
        positions = nx.nx_pydot.pydot_layout(ctx_graph, prog="dot")
        # remove successor edges for plotting contained edges
        for ctx in self.contexts:
            if ctx.successor is not None:
                ctx_graph.remove_edge(ctx, ctx.successor)
        # draw nodes
        node_colors = [ctx.get_plot_face_color() for ctx in self.contexts]
        nx.draw_networkx_nodes(ctx_graph, positions, nodelist=self.contexts, node_color=node_colors, ax=axis)
        # draw contained edges
        nx.draw_networkx_edges(ctx_graph, positions, ax=axis)
        # remove contained edges
        to_be_removed: List[Tuple[Any, Any]] = []
        for edge in ctx_graph.edges:
            to_be_removed.append(edge)
        for tbr in to_be_removed:
            ctx_graph.remove_edge(tbr[0], tbr[1])
        # draw successor edges
        for ctx in self.contexts:
            if ctx.successor is not None:
                ctx_graph.add_edge(ctx, ctx.successor)
        nx.draw_networkx_edges(ctx_graph, positions, edge_color="green", ax=axis)
        # remove successor edges
        to_be_removed = []
        for edge in ctx_graph.edges:
            to_be_removed.append(edge)
        for tbr in to_be_removed:
            ctx_graph.remove_edge(tbr[0], tbr[1])
        # draw static dependency edges
        for ctx in self.contexts:
            targets: Set[Any] = set()
            for outgoing_dependency in ctx.outgoing_dependencies:
                if outgoing_dependency[1].origin == DepOrigin.STATIC_ANALYSIS:
                    targets.add(outgoing_dependency[0])
                if outgoing_dependency[1].origin is None:
                    raise ValueError("HERE")
            for target in targets:
                ctx_graph.add_edge(ctx, target)
        nx.draw_networkx_edges(
            ctx_graph,
            positions,
            edge_color="blue",
            ax=axis,
            connectionstyle="arc3,rad=0.3",
        )
        # remove dependency edges
        to_be_removed = []
        for edge in ctx_graph.edges:
            to_be_removed.append(edge)
        for tbr in to_be_removed:
            ctx_graph.remove_edge(tbr[0], tbr[1])
        # draw dynamic dependency edges
        for ctx in self.contexts:
            targets_dyn: Set[Any] = set()
            for outgoing_dependency in ctx.outgoing_dependencies:
                if outgoing_dependency[1].origin == DepOrigin.DYNAMIC_ANALYSIS:
                    targets.add(outgoing_dependency[0])
                if outgoing_dependency[1].origin is None:
                    raise ValueError("HERE")
            for target in targets_dyn:
                ctx_graph.add_edge(ctx, target)
        nx.draw_networkx_edges(
            ctx_graph,
            positions,
            edge_color="red",
            ax=axis,
            connectionstyle="arc3,rad=0.2",
        )

        # draw labels
        labels: Dict[Any, str] = {}
        for ctx in self.contexts:
            if isinstance(ctx, WorkContext):
                labels[ctx] = ctx.get_label_with_defined_vars(self.pet)
            else:
                labels[ctx] = ctx.get_label()
        nx.draw_networkx_labels(ctx_graph, positions, labels, font_size=7, ax=axis)

        # define legend
        black_line = mlines.Line2D([], [], color="black", markersize=15, label="contained")  # marker='*',
        red_line = mlines.Line2D([], [], color="red", markersize=15, label="dynamic dep")  # marker='*',
        blue_line = mlines.Line2D([], [], color="blue", markersize=15, label="static dep")  # marker='*',
        green_line = mlines.Line2D(
            [],
            [],
            color="green",
            markersize=15,
            label="successor",
        )  # marker='*',

        axis.legend(
            loc="upper left", handles=[black_line, red_line, blue_line, green_line]
        )  # labels=["control", "data", "control + data", "imaginary"], labelcolor=["black", "red", "blue", "green"], )

    def plot_context_debug_graph(self, axis: Axes) -> None:
        logger.info("Plotting context debug graph...")

        ctx_graph = nx.MultiDiGraph()
        for ctx in self.contexts:
            ctx_graph.add_node(ctx)
            for ctx_cont_node in ctx.contained_nodes:
                ctx_graph.add_node(ctx_cont_node)
        # add contained edges for positioning
        for ctx in self.contexts:
            for contained_ctx in ctx.contained_contexts:
                ctx_graph.add_edge(ctx, contained_ctx)
            for ctx_cont_node in ctx.contained_nodes:
                ctx_graph.add_edge(ctx, ctx_cont_node)
        # calculate layout
        positions = nx.nx_pydot.pydot_layout(ctx_graph, prog="dot")
        # draw nodes
        nx.draw_networkx_nodes(ctx_graph, positions, nodelist=self.contexts, node_color="orange", ax=axis)
        nx.draw_networkx_nodes(
            ctx_graph,
            positions,
            nodelist=[n for n in ctx_graph.nodes if n not in self.contexts],
            node_color="cyan",
            ax=axis,
        )
        # draw contained edges
        nx.draw_networkx_edges(ctx_graph, positions, ax=axis)
        # draw dependency edges
        tbr = []
        for edge in ctx_graph.edges:
            tbr.append(edge)
        for edge in tbr:
            ctx_graph.remove_edge(edge[0], edge[1])
        for ctx in self.contexts:
            for deps in ctx.outgoing_dependencies:
                ctx_graph.add_edge(ctx, deps[0])
        nx.draw_networkx_edges(ctx_graph, positions, edge_color="red", ax=axis)
        # draw labels
        labels = {}
        for node in ctx_graph.nodes:
            labels[node] = node.get_label()
        nx.draw_networkx_labels(ctx_graph, positions, labels, font_size=7, ax=axis)

    def new_plot_context_debug_graph(self, canvas: CanvasViewerWithTrees) -> None:
        logger.info("Plotting context debug graph...")

        ctx_graph = nx.MultiDiGraph()

        for ctx in self.contexts:
            ctx_graph.add_node(ctx)

            for node in ctx.contained_nodes:
                ctx_graph.add_node(node)

        for ctx in self.contexts:
            for contained_ctx in ctx.contained_contexts:
                ctx_graph.add_edge(
                    ctx,
                    contained_ctx,
                    edge_type=TreeEdgeType.MAIN,
                )

            for node in ctx.contained_nodes:
                ctx_graph.add_edge(
                    ctx,
                    node,
                    edge_type=TreeEdgeType.MAIN,
                )

        for ctx in self.contexts:
            for dep in ctx.outgoing_dependencies:
                ctx_graph.add_edge(
                    ctx,
                    dep[0],
                    edge_type=TreeEdgeType.DEPENDENCY,
                )

        canvas.build_initial(ctx_graph)

    def __get_or_insert_TGNode(self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex) -> TGNode:
        if pet_node_id is not None:
            if pet_node_id in self.TGNode_pet_node_id_to_tg_node:
                return self.TGNode_pet_node_id_to_tg_node[pet_node_id]
            node = TGNode(pet_node_id, level, position)
            self.TGNode_pet_node_id_to_tg_node[pet_node_id] = node
            return node
        return TGNode(pet_node_id, level, position)

    def __get_or_insert_TGFunctionNode(
        self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex
    ) -> TGFunctionNode:
        if pet_node_id is not None:
            if pet_node_id in self.TGFunctionNode_pet_node_id_to_tg_node:
                return self.TGFunctionNode_pet_node_id_to_tg_node[pet_node_id]
            node = TGFunctionNode(pet_node_id, level, position)
            self.TGFunctionNode_pet_node_id_to_tg_node[pet_node_id] = node
            return node
        return TGFunctionNode(pet_node_id, level, position)

    def __get_or_insert_TGStartFunctionNode(
        self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex
    ) -> TGStartFunctionNode:
        if pet_node_id is not None:
            if pet_node_id in self.TGStartFunctionNode_pet_node_id_to_tg_node:
                return self.TGStartFunctionNode_pet_node_id_to_tg_node[pet_node_id]
            node = TGStartFunctionNode(pet_node_id, level, position)
            self.TGStartFunctionNode_pet_node_id_to_tg_node[pet_node_id] = node
            return node
        return TGStartFunctionNode(pet_node_id, level, position)

    def __get_or_insert_TGEndFunctionNode(
        self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex
    ) -> TGEndFunctionNode:
        if pet_node_id is not None:
            if pet_node_id in self.TGEndFunctionNode_pet_node_id_to_tg_node:
                return self.TGEndFunctionNode_pet_node_id_to_tg_node[pet_node_id]
            node = TGEndFunctionNode(pet_node_id, level, position)
            self.TGEndFunctionNode_pet_node_id_to_tg_node[pet_node_id] = node
            return node
        return TGEndFunctionNode(pet_node_id, level, position)

    def node_registered(self, pet_node_id: PETNodeID) -> bool:
        return pet_node_id in self.TGNode_pet_node_id_to_tg_node

    # basic block names clang gives the code run only while an exception unwinds the stack
    _EXCEPTION_UNWIND_BLOCK_PREFIXES = ("lpad", "ehcleanup", "eh.resume", "terminate.lpad", "terminate.handler")

    def __cut_exception_unwind_paths(self) -> None:
        """Removes the edges into exception landing pads, and the code reachable only through
        them (destructor cleanups, eh.resume, catch handlers).

        Every call that may throw has an edge to a landing pad, and the cleanup chains of a
        function are shared by all of its calls, so they cross every branch region of the function
        (see __split_branch_region_side_entries), while they run only when an exception unwinds
        the stack. They are cut like the early exits out of loops (see __fix_loop_structures),
        and recorded in cus_deleted_by_exception_unwinding: dependencies observed at their lines
        are lost (a profiled run that threw an exception)."""
        self.cus_deleted_by_exception_unwinding = set()

        def is_unwind_block(node: TGNode) -> bool:
            if type(node) is not TGNode or node.pet_node_id is None:
                return False
            pet_node = self.pet.node_at(node.pet_node_id)
            block = getattr(pet_node, "basic_block_id", "") or ""
            return block.startswith(self._EXCEPTION_UNWIND_BLOCK_PREFIXES)

        cut_targets: List[TGNode] = []
        for node in list(self.graph.nodes):
            if not is_unwind_block(node):
                continue
            for pred in self.get_predecessors(node):
                if is_unwind_block(pred):
                    continue
                if len([succ for succ in self.get_successors(pred) if not is_unwind_block(succ)]) == 0:
                    # the only way on (e.g. a call which always throws); keep it
                    continue
                while self.graph.has_edge(pred, node):
                    self.graph.remove_edge(pred, node)
                cut_targets.append(node)
        # delete the nodes no longer reachable, as __fix_loop_structures does
        queue: Deque[TGNode] = deque(cut_targets)
        while len(queue) > 0:
            current = queue.popleft()
            if not self.graph.has_node(current) or len(self.get_predecessors(current)) > 0:
                continue
            queue.extend(self.get_successors(current))
            if type(current) is TGNode and current.pet_node_id is not None:
                self.cus_deleted_by_exception_unwinding.add(current.pet_node_id)
            self.graph.remove_node(current)
        self.loop_nodes_with_cut_exception_handlers = self.__loops_containing_catch_handlers(
            self.cus_deleted_by_exception_unwinding
        )
        if len(self.cus_deleted_by_exception_unwinding) > 0:
            logger.info(
                "Cut the exception unwind paths: deleted "
                + str(len(self.cus_deleted_by_exception_unwinding))
                + " CUs reachable only through landing pads"
            )

    def __ends_without_return(self, node: TGNode, limit: int = 8) -> bool:
        """whether every path from node reaches the function's exit CU (the one added by
        PEGraphX.enforce_single_function_exit_node) within limit nodes, without passing a return
        instruction: the code behind a call which does not return (exit(), abort(), a throw) ends
        without successors, and is linked to that exit CU."""
        seen: Set[TGNode] = set()
        queue: Deque[TGNode] = deque([node])
        while len(queue) > 0:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            if len(seen) > limit:
                return False
            if type(current) is TGNode and current.pet_node_id is not None and current.pet_node_id in self.pet.g:
                pet_node = self.pet.node_at(current.pet_node_id)
                if pet_node.name is not None and pet_node.name.startswith("FuncExit_"):
                    continue
                if isinstance(pet_node, CUNode) and pet_node.return_instructions_count > 0:
                    return False
            successors = self.get_successors(current)
            if len(successors) == 0:
                # the end of a function without passing its exit CU
                return False
            queue.extend(successors)
        return True

    def __loops_containing_catch_handlers(self, deleted_cus: Set[PETNodeID]) -> Set[NodeID]:
        """The LoopNodes whose lines contain one of the deleted CUs that belongs to a catch handler
        (basic block "catch..."). A destructor cleanup only runs while an exception leaves the loop,
        but a handler inside the loop continues it, and its accesses are missing from the graph."""
        handler_lines: Set[Tuple[int, int]] = set()
        for cu_id in deleted_cus:
            if cu_id is None:
                continue
            pet_node = self.pet.node_at(cu_id)
            block = getattr(pet_node, "basic_block_id", "") or ""
            if block.startswith("catch"):
                handler_lines.add((int(pet_node.file_id), int(pet_node.start_line)))
        if len(handler_lines) == 0:
            return set()
        result: Set[NodeID] = set()
        for loop in all_nodes(self.pet, type=LoopNode):
            for file_id, line in handler_lines:
                if int(loop.file_id) == file_id and loop.start_line <= line <= loop.end_line:
                    result.add(loop.id)
                    break
        return result

    def __visit_pet(self, pet: PEGraphX) -> None:
        # construct Taskgraph by visiting the PET Graph
        root = RootNode(None, self.__get_next_level(), self.__get_next_position(self.__get_current_level()))
        self.add_node(root)
        self.root = root

        pet_root = pet.main
        pet_root_node = self.__get_or_insert_TGFunctionNode(
            pet_root.id, self.__get_next_level(), self.__get_next_position(self.__get_current_level())
        )

        functions = all_nodes(self.pet, FunctionNode)

        queue: Deque[TGConstructionQueueElement] = deque([(root, pet_root)] + [(None, func) for func in functions])

        while len(queue) > 0:
            predecessor, current = queue.popleft()
            if isinstance(current, VisitorMarker):
                queue = self.__visit_marker(predecessor, current, queue)
            else:
                queue = self.__visit_node(predecessor, current, queue)

    def __visit_node(
        self, predecessor: Optional[TGNode], pet_node: PETNode, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        if pet_node.type == NodeType.CU:
            queue = self.__visit_CUNode(predecessor, pet_node, queue)
        elif pet_node.type == NodeType.FUNC:
            queue = self.__visit_FunctionNode(predecessor, pet_node, queue)
        elif pet_node.type == NodeType.LOOP:
            queue = self.__visit_LoopNode(predecessor, pet_node, queue)
        else:
            warnings.warn("Unsupported node type encountered: " + str(type(pet_node)) + " NodeID: " + str(pet_node.id))
        return queue

    def __visit_marker(
        self, predecessor: Optional[TGNode], marker: VisitorMarker, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        if isinstance(marker, EndFunctionMarker):
            queue = self.__visit_EndFunctionMarker(predecessor, marker, queue)
        return queue

    def __visit_EndFunctionMarker(
        self, predecessor: Optional[TGNode], marker: EndFunctionMarker, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        #        self.context_stack.remove(marker.context)
        node = self.__get_or_insert_TGEndFunctionNode(
            marker.function_node, self.__get_next_level(), self.__get_next_position(self.__get_current_level())
        )
        self.add_node(node)
        self.add_edge(predecessor, node)
        return queue

    def __visit_CUNode(
        self, predecessor: Optional[TGNode], pet_node: PETNode, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        successors = direct_successors(self.pet, pet_node)
        if len(successors) > 1:
            return self.__visit_branching(predecessor, pet_node, queue)
        node = self.__get_or_insert_TGNode(
            pet_node.id, self.__get_next_level(), self.__get_next_position(self.__get_current_level())
        )
        self.add_node(node)
        self.add_edge(predecessor, node)

        if len(successors) > 0:
            queue.append((node, successors[0]))
        else:
            # determine parent function
            for pred in direct_predecessors(self.pet, pet_node):
                try:
                    parent_function = get_parent_function(self.pet, pred)
                    queue.append(
                        (
                            node,
                            EndFunctionMarker(
                                parent_function.id,
                                self.__get_next_level(),
                                self.__get_next_position(self.__get_current_level()),
                            ),
                        )
                    )
                    break
                except:
                    continue

        return queue

    def __visit_branching(
        self, predecessor: Optional[TGNode], pet_node: PETNode, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        node = self.__get_or_insert_TGNode(
            pet_node.id, self.__get_next_level(), self.__get_next_position(self.__get_current_level())
        )
        self.add_node(node)
        self.add_edge(predecessor, node)

        for successor in direct_successors(self.pet, pet_node):
            if not self.node_registered(successor.id):
                queue.append((node, successor))
            else:
                # The successor has already been visited, so it must not be queued again -
                # doing so would make the traversal loop forever on cyclic control flow (the
                # single-successor path in __visit_CUNode queues unconditionally, so a cycle
                # only terminates because branch points stop re-visiting known nodes). The
                # edge to it, however, is created by the *successor's* visit, and therefore
                # still needs to be added here: dropping it silently deletes real control
                # flow. The typical victim is a loop's exit edge whose target CU was already
                # reached through an earlier, shorter path (e.g. an early return sharing the
                # function's exit CU). __break_cycles then sees an exit-less cycle, mistakes
                # a branch inside the loop body for the loop header and the other arm for the
                # loop exit, and produces a TGStartLoopNode that cannot reach its
                # TGEndLoopNode - which fails much later in __assign_loop_contexts.
                self.add_edge(node, self.TGNode_pet_node_id_to_tg_node[successor.id])

        return queue

    def __visit_FunctionNode(
        self, predecessor: Optional[TGNode], pet_node: PETNode, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:

        func_node = self.__get_or_insert_TGFunctionNode(
            pet_node.id, self.__get_current_level(), self.__get_next_position(self.__get_current_level())
        )
        self.add_node(func_node)
        self.add_edge(predecessor, func_node)

        func_start_node = self.__get_or_insert_TGStartFunctionNode(
            pet_node.id, self.__get_current_level(), self.__get_next_position(self.__get_current_level())
        )
        self.add_node(func_start_node)
        self.add_edge(func_node, func_start_node)

        queue.append((func_start_node, get_entry_child(self.pet, pet_node)[0]))

        return queue

    def __visit_LoopNode(
        self, predecessor: Optional[TGNode], pet_node: PETNode, queue: Deque[TGConstructionQueueElement]
    ) -> Deque[TGConstructionQueueElement]:
        warnings.warn("Not implemented!")
        return queue

    def __find_loop_entry_node(self, function_node: TGNode, cycle_nodes: Set[TGNode]) -> Optional[TGNode]:
        """The node a cycle is entered through: the first of its nodes reached when walking forward
        from the function entry, which is also the node the back edges point back to.

        Identifying it by its outgoing edges instead - "one successor inside the cycle, one outside"
        - finds the loop's *condition* node, which is only the same node for a loop tested at its
        top. As soon as the loop is rotated (`while` compiled with the test at the bottom, or a
        `for` whose increment block precedes the test), the condition sits behind the entry node,
        and treating it as the entry makes the edge from the entry node to it look like a back edge.
        Removing that edge then severs the only way into the loop and detaches it, together with its
        whole body, from the function - which is invisible until a later pass treats the detached
        region as a program entry point of its own."""
        queue: Deque[TGNode] = deque([function_node])
        visited: Set[TGNode] = {function_node}
        while len(queue) > 0:
            current = queue.popleft()
            if current in cycle_nodes:
                return current
            for successor in self.get_successors(current):
                if successor not in visited:
                    visited.add(successor)
                    queue.append(successor)
        return None

    def __find_loop_exit_edge(
        self, entry_node: Optional[TGNode], cycle_nodes: Set[TGNode]
    ) -> Tuple[Optional[TGNode], Optional[TGNode]]:
        """The edge by which control leaves the cycle, as (source inside, target outside). Prefers
        an edge starting at the entry node, so a loop tested at its top is restructured exactly as
        before. Loops without any exit (`while (true)`) have none, and are left to the caller's
        fallback."""
        if entry_node is None:
            return None, None
        candidates: List[Tuple[TGNode, TGNode]] = []
        for source in sorted(cycle_nodes, key=lambda node: node.get_label()):
            for target in self.get_successors(source):
                if target not in cycle_nodes:
                    candidates.append((source, target))
        for source, target in candidates:
            if source is entry_node:
                return source, target
        return candidates[0] if len(candidates) > 0 else (None, None)

    def __get_cyclic_region(self, node: TGNode) -> Set[TGNode]:
        """Every node lying on a cycle through `node`: the nodes it reaches which also reach it back,
        i.e. the strongly connected component it belongs to. For a loop this is the whole loop -
        including everything nested inside it - rather than the single path `nx.find_cycle` returns,
        so all of its back edges and all of its exits are visible at once."""
        region: Set[TGNode] = nx.descendants(self.graph, node) & nx.ancestors(self.graph, node)
        region.add(node)
        return region

    @staticmethod
    def __pet_node_order(node: TGNode) -> Tuple[int, ...]:
        """A deterministic order of TGNodes by their PET node id "<file>:<cu>", numerically, and by
        creation among nodes of the same PET node (set iteration order would follow addresses)."""
        return tuple(int(part) if part.isdigit() else -1 for part in str(node.pet_node_id).split(":")) + (
            node.creation_index,
        )

    def __break_cycles(self) -> None:
        # search for cycles in each function and replace them with two distinct iteraions
        for function_node in progress(self.TGFunctionNode_pet_node_id_to_tg_node.values(), desc="Breaking cycles"):
            logger.debug("Breaking cycles in: " + function_node.get_label())
            # progress search if cycle can not be broken
            search_source: TGNode = function_node
            search_source_queue = deque(self.get_descendants(function_node))

            while True:
                # find cycle
                try:
                    cycle = nx.find_cycle(self.graph, source=search_source)
                except nx.NetworkXNoCycle:
                    # no further cycles in function
                    break
                # a loop with more than one back edge - a "continue", or a nested loop whose exit
                # branches back to the outer condition - consists of several distinct cycles, and
                # nx.find_cycle returns just one of them. Restructuring that one alone would leave
                # the loop's remaining back edges in place, so the very same loop is found again on
                # the next pass and wrapped a second time, nesting duplicate loop and iteration
                # markers for one PET node inside each other. Widening the cycle to its strongly
                # connected component keeps the loop a single unit: all of its latches are cut
                # together, and only edges truly leaving the loop are considered as its exit.
                cycle_nodes: Set[TGNode] = self.__get_cyclic_region(cycle[0][0])

                # find entry node and exit node
                entry_node = self.__find_loop_entry_node(function_node, cycle_nodes)
                exit_source, exit_node = self.__find_loop_exit_edge(entry_node, cycle_nodes)
                iteration_entry_points: List[TGNode] = [n for n in self.get_successors(entry_node) if n in cycle_nodes]

                # the edges back to the entry node end an iteration, and so does the edge leaving the
                # loop when it starts at a node other than the entry node (a rotated loop, whose
                # condition sits behind the entry node): both continue into the loop end marker
                latches: List[TGNode] = [p for p in self.get_predecessors(entry_node) if p in cycle_nodes]
                iteration_exit_points: List[TGNode] = list(latches)
                if exit_source is not None and exit_source is not entry_node:
                    iteration_exit_points.append(exit_source)

                if entry_node is not None and len(latches) == len(self.get_predecessors(entry_node)):
                    # every way into the entry node comes from inside the cycle, so removing the
                    # latches below would detach the whole loop from its function - see the crude
                    # fallback instead, which keeps it reachable
                    logger.warning(
                        "Refusing to restructure the loop at %s: all of its incoming edges come "
                        "from inside the cycle, so it has no reachable entry.",
                        entry_node.get_label(),
                    )
                    entry_node = None

                #                print("Found entry node: ", entry_node.get_label() if entry_node is not None else "NONE")
                #                print("Found exit node: ", exit_node.get_label() if exit_node is not None else "NONE")
                #                print("Found iteration entry points: ", [n.get_label() for n in iteration_entry_points])
                #                print("Found iteration exit points: ", [n.get_label() for n in iteration_exit_points])

                if entry_node is not None and exit_node is not None:
                    # cycle can be broken. Reset search point for cycle search
                    search_source_queue = deque(self.get_descendants(function_node))
                    search_source = function_node

                    # break cycle
                    for latch in latches:
                        self.graph.remove_edge(latch, entry_node)
                        logger.info("  --> Removed edge " + latch.get_label() + " --> " + entry_node.get_label())

                    # add loop start marking between entry_node and its predecessors
                    lsm = TGStartLoopNode(entry_node.pet_node_id, entry_node.level, entry_node.position)
                    self.add_node(lsm)
                    for pred in self.get_predecessors(entry_node):
                        self.graph.remove_edge(pred, entry_node)
                        self.add_edge(pred, lsm)
                    self.add_edge(lsm, entry_node)

                    # add loop end marking in front of exit_node. The edge leaving the loop starts at
                    # exit_source, which is the entry node itself for a loop tested at its top and
                    # the condition node behind it for a rotated one
                    lem = TGEndLoopNode(entry_node.pet_node_id, entry_node.level, entry_node.position)
                    self.add_node(lem)
                    self.graph.remove_edge(exit_source, exit_node)
                    self.add_edge(entry_node, lem)
                    self.add_edge(lem, exit_node)

                    # add one iteration entry marking between entry_node and its successors in the
                    # cycle, and one iteration exit marking after all nodes ending an iteration. A
                    # compound condition (`while (a && b)`) gives the entry node several successors
                    # in the cycle, and in a loop tested at its bottom the latch is also the exit
                    # source. One marker per such node would split the loop into several iterations,
                    # which the duplication then copies once per end marker, and which
                    # __fix_loop_structures pairs up wrongly (deleting the loop body).
                    iteration_entry_points = sorted(iteration_entry_points, key=self.__pet_node_order)
                    iteration_exit_points = sorted(dict.fromkeys(iteration_exit_points), key=self.__pet_node_order)
                    ism = TGStartIterationNode(
                        iteration_entry_points[0].pet_node_id,
                        iteration_entry_points[0].level,
                        iteration_entry_points[0].position,
                        entry_node.pet_node_id,
                    )
                    # loop iterations will be duplicated later, which sets the loopstate ids
                    self.add_node(ism)
                    self.add_edge(entry_node, ism)
                    for itenp in iteration_entry_points:
                        self.graph.remove_edge(entry_node, itenp)
                        self.add_edge(ism, itenp)

                    iem = TGEndIterationNode(
                        iteration_exit_points[0].pet_node_id,
                        iteration_exit_points[0].level,
                        iteration_exit_points[0].position,
                        entry_node.pet_node_id,
                    )
                    iem_list: List[TGEndIterationNode] = [iem]
                    self.add_node(iem)
                    for itexp in iteration_exit_points:
                        self.add_edge(itexp, iem)

                    # redirect edge from entry -> end_loop to iteration_exit markers -> end_loop
                    self.graph.remove_edge(entry_node, lem)
                    for iem in iem_list:
                        self.add_edge(iem, lem)

                else:
                    logger.warning(
                        "NO entry_node and exit_node found for cycle: "
                        + str([(t[0].get_label(), t[1].get_label()) for t in cycle])
                    )
                    # crudely break the cycle by removing the edge back to the first encountered node
                    logger.warning(
                        "--> crudely broken cycle by removing edge: "
                        + str((cycle[-1][0].get_label(), cycle[-1][1].get_label()))
                    )
                    self.graph.remove_edge(cycle[-1][0], cycle[-1][1])
                    # try to minimize the "error" by connecting the end of the cycle to a successor of the "entry" node, if it is outside the cycle
                    outside_successor = None
                    for succ in self.get_successors(cycle[-1][0]):
                        if succ not in cycle_nodes:
                            outside_successor = succ
                            break
                    if outside_successor is not None:
                        self.add_edge(cycle[-1][1], outside_successor)
                        logger.warning(
                            "----> added new edge to outside successor: "
                            + str((cycle[-1][1].get_label(), outside_successor.get_label()))
                        )
                    else:
                        # if this is not possible, connect the exit to the function exit node to preserve the correct graph structure
                        descendants = self.get_descendants(function_node)
                        function_exit_nodes = [
                            d
                            for d in descendants
                            if type(d) is TGEndFunctionNode and d.pet_node_id == function_node.pet_node_id
                        ]
                        if len(function_exit_nodes) > 0:
                            self.add_edge(cycle[-1][1], function_exit_nodes[0])
                            logger.warning(
                                "----> added new edge to function exit node: "
                                + str((cycle[-1][1].get_label(), function_exit_nodes[0].get_label()))
                            )
                        else:
                            raise ValueError(
                                "Could neither determine outside loop successor nor function exit node for broken cycle: "
                                + str([(t[0].get_label(), t[1].get_label()) for t in cycle])
                            )

                    # progress search
                    if len(search_source_queue) > 0:
                        search_source = search_source_queue.popleft()
                    else:
                        break

    def __fix_loop_structures(self, plot_problematic_loops: bool = False) -> None:
        # in case a loop contains a branch to a non-iteration node (e.g. via "break"- statement), delete this edge and cleanup the graph
        logger.info("Fixing loop structures...")
        self.cus_deleted_by_early_exits = set()
        self.loops_with_cut_exits = dict()
        for function_node in progress(self.TGFunctionNode_pet_node_id_to_tg_node.values()):
            logger.info("--> " + function_node.get_label())
            modification_found = True
            while modification_found:
                modification_found = False
                descendants = self.get_descendants(function_node)
                # find problematic loops
                start_iteration_nodes = [d for d in descendants if isinstance(d, TGStartIterationNode)]
                end_iteration_nodes = [d for d in descendants if isinstance(d, TGEndIterationNode)]
                for sin in start_iteration_nodes:
                    for ein in end_iteration_nodes:
                        # the markers of one iteration belong to the same loop. (Their own pet node
                        # ids are the first and the last node of the iteration and differ in general.)
                        if sin.parent_loop_pet_node_id != ein.parent_loop_pet_node_id:
                            continue
                        # filter corresponding start and end iteration nodes
                        if not nx.has_path(self.graph, sin, ein):
                            continue
                        shortest_path = nx.shortest_path(self.graph, sin, ein)
                        if (
                            len(
                                [
                                    n
                                    for n in shortest_path
                                    if isinstance(n, TGStartIterationNode)
                                    and n.parent_loop_pet_node_id == sin.parent_loop_pet_node_id
                                ]
                            )
                            > 1
                        ):
                            # more than one iteration start node found
                            continue
                        if (
                            len(
                                [
                                    n
                                    for n in shortest_path
                                    if isinstance(n, TGEndIterationNode)
                                    and n.parent_loop_pet_node_id == ein.parent_loop_pet_node_id
                                ]
                            )
                            > 1
                        ):
                            # more than one iteration end node found
                            continue

                        iteration_nodes = self.__get_iteration_nodes(sin, ein)
                        # check iteration nodes for branches to outside the iteration
                        invalid_edges: List[(Tuple[TGNode, TGNode])] = []
                        for itn in iteration_nodes:
                            if itn == ein:
                                continue
                            for succ in self.get_successors(itn):
                                if succ not in iteration_nodes:
                                    invalid_edges.append((itn, succ))

                        if len(invalid_edges) == 0:
                            continue
                        # found problematic loop
                        warn("Invalid edges: " + str([(e[0].get_label(), e[1].get_label()) for e in invalid_edges]))

                        # show problematic loop
                        if plot_problematic_loops:
                            ax = plt.gca()  # type: ignore[attr-defined]
                            self.update_plot(
                                ax,
                                subgraph=nx.subgraph(self.graph, descendants),
                                highlight_nodes=[e[1] for e in invalid_edges],
                            )

                        # issue warningn and delete problematic edges
                        loop_position_string = (
                            ("line " + self.pet.node_at(sin.pet_node_id).start_position())
                            if sin.pet_node_id is not None
                            else ("CU ID " + str(sin.pet_node_id))
                        )
                        reason_position_string = ""

                        logger.warning(
                            "Found and fixing invalid loop structure in loop at "
                            + loop_position_string
                            + ". Reasons found at lines:"
                        )
                        for invalid_source in [e[0] for e in invalid_edges]:
                            logger.warning(
                                "--> "
                                + (
                                    self.pet.node_at(invalid_source.pet_node_id).start_position()
                                    if invalid_source.pet_node_id is not None
                                    else "NONE"
                                )
                            )
                        logger.warning(
                            "Typical reasons include break statements and similar. Treat results using this loop with caution."
                        )

                        # A call which does not return (exit(), abort(), a throw) ends the program from
                        # within the iteration, which is no reason against a parallel loop, while
                        # break, return and goto leave the loop.
                        early_exit_lines = [
                            str(self.pet.node_at(source.pet_node_id).start_position())
                            for source, target in invalid_edges
                            if source.pet_node_id is not None and not self.__ends_without_return(target)
                        ]
                        if len(early_exit_lines) > 0:
                            self.loops_with_cut_exits.setdefault(sin.parent_loop_pet_node_id, set()).update(
                                early_exit_lines
                            )
                        for invalid_edge_source, invalid_edge_target in invalid_edges:
                            if self.graph.has_edge(invalid_edge_source, invalid_edge_target):
                                self.graph.remove_edge(invalid_edge_source, invalid_edge_target)

                        # cleanup the graph by deleting nodes with no incoming edges
                        for _, invalid_edge_target in invalid_edges:
                            queue: Deque[TGNode] = deque([invalid_edge_target])
                            while len(queue) > 0:
                                current = queue.popleft()
                                if not self.graph.has_node(current):
                                    continue
                                predecessors = self.get_predecessors(current)
                                if len(predecessors) == 0:
                                    # mark successors for potential cleanup
                                    queue += [s for s in self.get_successors(current) if s not in queue]
                                    # delete current node
                                    logger.warning("---> deleting node: " + current.get_label())
                                    if type(current) is TGNode and current.pet_node_id is not None:
                                        self.cus_deleted_by_early_exits.add(current.pet_node_id)
                                    self.graph.remove_node(current)
                                    modification_found = True
                        if modification_found:
                            break
                    if modification_found:
                        break

    def __duplicate_loop_iterations(self, plot_progress: bool = False) -> None:
        logger.info("Duplicating loop iterations...")
        for function_node in progress(self.TGFunctionNode_pet_node_id_to_tg_node.values()):
            logger.info("--> " + function_node.get_label())
            added_copies: Set[TGNode] = set()  # do not allow the re-copying of copies
            already_considered: Set[TGNode] = set()  # do not allo the re-copying of nodes
            modification_found = True
            # plotting progress
            if plot_progress:
                original_descendants = self.get_descendants(function_node)
                self.update_plot(self.graph.subgraph(original_descendants))
                original_start_iteration_nodes = [
                    cast(TGNode, d) for d in original_descendants if isinstance(d, TGStartIterationNode)
                ]
                original_end_iteration_nodes = [
                    cast(TGNode, d) for d in original_descendants if isinstance(d, TGEndIterationNode)
                ]
                self.update_plot_node_color(original_start_iteration_nodes, color="orange")
                self.update_plot_node_color(original_end_iteration_nodes, color="orange")

            # retry duplication of loop iterations until each iteration in the function is followied by a duplicate
            # multiple tries are necessary, as every occurence of a loop needs to be duplicated
            while modification_found:
                modification_found = False
                logger.info("--> " + function_node.get_label())
                descendants = self.get_descendants(function_node)
                # plotting progress
                if plot_progress:
                    self.update_plot_node_color([n for n in original_descendants if n in already_considered], "green")

                start_iteration_nodes = [
                    d
                    for d in descendants
                    if isinstance(d, TGStartIterationNode) and d not in added_copies and d not in already_considered
                ]
                end_iteration_nodes = [
                    d
                    for d in descendants
                    if isinstance(d, TGEndIterationNode) and d not in added_copies and d not in already_considered
                ]

                # filter start_iteration_nodes to those, which have not already been duplicated
                filtered_start_iteration_nodes: List[TGStartIterationNode] = []
                for sin in start_iteration_nodes:
                    already_duplicated = False
                    for pred in self.get_predecessors(sin):
                        if (
                            isinstance(pred, TGEndIterationNode)
                            and pred.parent_loop_pet_node_id == sin.parent_loop_pet_node_id
                        ):
                            already_duplicated = True
                            break
                    if not already_duplicated:
                        filtered_start_iteration_nodes.append(sin)
                # filter end_iteration_nodes to those, which have not already been duplicated
                filtered_end_iteration_nodes: List[TGEndIterationNode] = []
                for ein in end_iteration_nodes:
                    already_duplicated = False
                    #                    print("EIN: ", ein.get_label(), ein)
                    #                    print("EIN SUCC: ", [n.get_label() for n in self.get_successors(ein)])
                    for succ in self.get_successors(ein):
                        if (
                            isinstance(succ, TGStartIterationNode)
                            and succ.parent_loop_pet_node_id == ein.parent_loop_pet_node_id
                        ):
                            already_duplicated = True
                            #                            print("--> Already duplicated")
                            break
                    if not already_duplicated:
                        filtered_end_iteration_nodes.append(ein)

                # pair each start with the end of its loop. Inner loops are duplicated first: the nodes
                # of a duplicated iteration are not considered again, and copies are never copied, so
                # an inner loop inside an outer iteration that is copied first would never be
                # duplicated (neither in the original nor in the copy). The order is made
                # deterministic, as get_descendants follows set iteration order.
                pairs: List[Tuple[TGStartIterationNode, TGEndIterationNode, Set[TGNode]]] = []
                for sin in sorted(filtered_start_iteration_nodes, key=self.__pet_node_order):
                    for ein in sorted(filtered_end_iteration_nodes, key=self.__pet_node_order):
                        # only consider pairs with equal corresponding pet_node_id's
                        if sin.parent_loop_pet_node_id != ein.parent_loop_pet_node_id:
                            continue
                        iteration_nodes = self.__get_iteration_nodes(sin, ein)
                        if len(iteration_nodes) == 0:
                            continue
                        pairs.append((sin, ein, iteration_nodes))
                        # one end per iteration (see __break_cycles)
                        break
                pending_starts = {sin for sin, _, _ in pairs}
                innermost = [
                    (sin, ein)
                    for sin, ein, iteration_nodes in pairs
                    if not any(other in iteration_nodes for other in pending_starts if other is not sin)
                ]
                if len(innermost) == 0:
                    # no innermost loop (malformed nesting): duplicate in the plain order
                    innermost = [(sin, ein) for sin, ein, _ in pairs]
                for sin, ein in innermost:
                    # duplicating a sibling loop may have changed the graph since the pairing
                    iteration_nodes = self.__get_iteration_nodes(sin, ein)
                    if len(iteration_nodes) == 0:
                        continue
                    # copy the iteration nodes and connect them to the original iteration
                    ein_successors = self.get_successors(ein)
                    for succ in ein_successors:
                        self.graph.remove_edge(ein, succ)
                    copied_nodes: Dict[TGNode, TGNode] = dict()

                    copied_nodes, copied_path, copied_iteration_entry, copied_iteration_exit = (
                        self.__copy_iteration_subgraph(copied_nodes, iteration_nodes, sin, ein)
                    )

                    # set loopstate_iterations_ids sucht that both iteration nodes react to different loopsate information during dependency creation
                    # print("sin.loopstate_iteration_ids: ", sin.loopstate_iteration_ids)
                    if sin.loopstate_iteration_ids is None:
                        sin.set_loopstate_iteration_ids([1])
                    if cast(TGStartIterationNode, copied_iteration_entry).loopstate_iteration_ids is None:
                        cast(TGStartIterationNode, copied_iteration_entry).set_loopstate_iteration_ids([0, 2])

                    self.add_edge(ein, copied_iteration_entry)
                    for succ in ein_successors:
                        self.add_edge(copied_iteration_exit, succ)
                    for copied_node in copied_nodes.values():
                        added_copies.add(copied_node)

                    for iteration_node in iteration_nodes:
                        already_considered.add(iteration_node)
                    modification_found = True

    def __assign_contexts(self) -> None:  # TODO: make the used graph parametric
        logger.info("Assigning contexts...")
        self.__assign_function_contexts()
        self.__assign_branching_contexts()
        #        self.__assign_parent_contexts_to_nodes()
        self.__assign_loop_contexts()
        self.__assign_work_contexts()
        self.__assign_inlined_function_contexts()

        self.__assign_parent_contexts_to_nodes()

    def __assign_function_contexts(self) -> None:
        logger.info("Assigning function contexts...")
        for function_node in progress(self.TGFunctionNode_pet_node_id_to_tg_node.values()):
            descendants = self.get_descendants(function_node)
            function_start_nodes = [n for n in descendants if isinstance(n, TGStartFunctionNode)]
            for fsn in function_start_nodes:
                function_context = FunctionContext(fsn.pet_node_id)
                function_context.add_node(fsn)
                fsn.register_created_context(function_context)
                #                for fsn_descendant in self.get_descendants(fsn):
                #                    function_context.add_node(fsn_descendant)
                self.contexts.append(function_context)

    def __assign_branching_contexts(self) -> None:
        logger.info("Assigning branching contexts...")
        # preparation
        logger.info("--> Selecting entry points...")
        start_branch_nodes: List[TGNode] = []
        start_branch_parent_nodes: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if isinstance(node, TGStartBranchNode):
                start_branch_nodes.append(node)
            if isinstance(node, TGStartBranchParentNode):
                start_branch_parent_nodes.append(node)

        # create individual branch context
        logger.info("--> Create branch contexts")
        for sbn in progress(start_branch_nodes):
            # create Context
            branch_context = BranchContext()
            sbn.register_created_context(branch_context)
            self.contexts.append(branch_context)

            if False:  # commented out due to high runtime without actual effect
                # DFS find nodes contained in the context
                queue: List[Tuple[TGNode, int]] = [(succ, 0) for succ in self.get_successors(sbn)]
                visited: Set[Tuple[TGNode, int]] = set()
                contained_nodes: Set[TGNode] = set()
                while len(queue) > 0:
                    current_node, current_level = queue.pop()
                    print("queue len: ", len(queue))
                    print("visited: len:", len(visited))
                    # stop search on this path, if a EndBranchNode is found and level is 0
                    if isinstance(current_node, TGEndBranchNode):
                        if current_level == 0:
                            # stop search along this path
                            continue
                        else:
                            # decrease level
                            current_level -= 1
                    # increase the level, if a StartBranchNode is encountered
                    if isinstance(current_node, TGStartBranchNode):
                        current_level += 1
                    # mark the node on the path as contained in the branch
                    contained_nodes.add(current_node)
                    # enqueue successors
                    for succ in self.get_successors(current_node):
                        queue_element = (succ, current_level)
                        if queue_element not in visited and queue_element not in queue:
                            queue.append(queue_element)
                            visited.add(queue_element)
                # register contained nodes in the context
            #            for contained_node in contained_nodes:
            #                branch_context.add_node(contained_node)

        # create branching parent contexts
        logger.info("--> Create branch parent contexts...")
        for sbpn in progress(start_branch_parent_nodes):
            branch_parent_context = BranchingParentContext()
            self.contexts.append(branch_parent_context)
            sbpn.created_context = branch_parent_context
            # get and register contained branch contexts
            for succ in self.get_successors(sbpn):
                # ensure correct structure
                if not isinstance(succ, TGStartBranchNode):
                    raise ValueError(
                        "InvalidGraphStructure: incorrect node type: "
                        + str(type(succ))
                        + " following a node of type "
                        + str(type(sbpn))
                        + " !"
                    )
                if succ.created_context is None:
                    raise ValueError(
                        "Field invalid: created_context of "
                        + str(type(succ))
                        + " node "
                        + succ.get_label()
                        + " is None!"
                    )
                succ.created_context.register_parent_context(branch_parent_context)
                branch_parent_context.add_contained_context(succ.created_context)

    def __assign_loop_contexts(self) -> None:
        logger.info("Assigning loop contexts...")

        for node in progress(self.graph.nodes):
            if not isinstance(node, TGStartLoopNode):
                continue

            # search corresponding loop end node
            loop_end_node: Optional[TGNode] = None
            queue: Deque[Tuple[TGNode, int]] = deque(
                [(node, -1)]
            )  # integer counts entered equivalent loops due to inlining
            visited: Set[TGNode] = {node}
            while len(queue) > 0:
                current, entered_equivalent_loops = queue.popleft()
                if isinstance(current, TGEndLoopNode) and (node.pet_node_id == current.pet_node_id):
                    if entered_equivalent_loops == 0:
                        loop_end_node = current
                        break
                    else:
                        entered_equivalent_loops -= 1
                if isinstance(current, TGStartLoopNode) and (node.pet_node_id == current.pet_node_id):
                    entered_equivalent_loops += 1
                for succ in self.get_successors(current):
                    if succ not in visited:
                        queue.append((succ, entered_equivalent_loops))
                        visited.add(succ)

            if loop_end_node is None:
                logger.warning("Could not determine loop end node for loop: " + node.get_label())
                #                plt.ioff()  # type: ignore[attr-defined]
                #                self.plot(highlight_nodes=[node])
                #                plt.pause(1)  # type: ignore[attr-defined]
                raise ValueError("Could not determine loop end node for loop: " + node.get_label())

            # search general loop nodes
            general_loop_nodes: set[TGNode] = {node, loop_end_node}
            shortest_loop_path = nx.shortest_path(self.graph, source=node, target=loop_end_node)
            for path_node in shortest_loop_path:
                general_loop_nodes.add(path_node)
                # add nodes from parent contexts to find nodes in branches within the loop body as well
                if len(path_node.parent_context) > 0:
                    for parent_ctx in path_node.parent_context:
                        if isinstance(parent_ctx, BranchingParentContext):
                            for n in parent_ctx.get_contained_nodes(inclusive=True):
                                general_loop_nodes.add(n)

            # search loop iteration starts
            iteration_starts: List[TGNode] = []
            for n in general_loop_nodes:
                if isinstance(n, TGStartIterationNode) and (n.parent_loop_pet_node_id == node.pet_node_id):
                    iteration_starts.append(n)

            # establish pairs between iteration start and end points
            valid_pairs: List[Tuple[TGStartIterationNode, TGEndIterationNode]] = []
            for it_start in iteration_starts:
                it_end: Optional[TGNode] = None
                it_queue: Deque[Tuple[TGNode, int]] = deque(
                    [(it_start, -1)]
                )  # integer counts entered equivalent loops due to inlining
                it_visited: Set[TGNode] = {it_start}
                while len(it_queue) > 0:
                    current, entered_equivalent_iterations = it_queue.popleft()
                    if isinstance(current, TGEndIterationNode) and (
                        cast(TGStartIterationNode, it_start).parent_loop_pet_node_id == current.parent_loop_pet_node_id
                    ):
                        if entered_equivalent_iterations == 0:
                            it_end = current
                            break
                        else:
                            entered_equivalent_iterations -= 1
                    if isinstance(current, TGStartIterationNode) and (
                        cast(TGStartIterationNode, it_start).parent_loop_pet_node_id == current.parent_loop_pet_node_id
                    ):
                        if entered_equivalent_iterations == -1:
                            entered_equivalent_iterations += 1
                        else:
                            raise ValueError("Invalid iteration structure found at node: " + current.get_label())
                    for succ in self.get_successors(current):
                        if succ not in it_visited:
                            it_queue.append((succ, entered_equivalent_iterations))
                            it_visited.add(succ)
                if it_end is not None:
                    valid_pairs.append((cast(TGStartIterationNode, it_start), cast(TGEndIterationNode, it_end)))

            # get iteration nodes for each pair
            pair_iteration_nodes: Dict[Tuple[TGStartIterationNode, TGEndIterationNode], List[TGNode]] = dict()
            for it_start, it_end in valid_pairs:
                tmp_iteration_nodes: set[TGNode] = {it_start, it_end}
                try:
                    shortest_iteration_path = nx.shortest_path(self.graph, source=it_start, target=it_end)
                except nx.NetworkXNoPath:
                    #                    plt.ioff()  # type: ignore[attr-defined]
                    #                    self.plot(highlight_nodes=[it_start, it_end])
                    #                    plt.pause(1)  # type: ignore[attr-defined]
                    warnings.warn("Got nx.NetworkXNoPath exception.")

                for path_node in shortest_iteration_path:
                    tmp_iteration_nodes.add(path_node)
                    # add nodes from parent contexts to find nodes in branches within the loop iteration as well
                    if len(path_node.parent_context) > 0:  # ignore cases where only the function-context is set
                        for parent_ctx in path_node.parent_context:
                            if isinstance(parent_ctx, BranchingParentContext):
                                for n in parent_ctx.get_contained_nodes(inclusive=True):
                                    tmp_iteration_nodes.add(n)
                    # add it_end to tmp_iteration_nodes
                    tmp_iteration_nodes.add(it_end)
                pair_iteration_nodes[(it_start, it_end)] = list(tmp_iteration_nodes)

            # create loop context
            loop_context = LoopParentContext(node.pet_node_id, node.loopstate_position)
            node.register_created_context(loop_context)
            #            for loop_node in general_loop_nodes:
            #                is_regular_loop_node = True
            #                for iteration_nodes in pair_iteration_nodes.values():
            #                    if loop_node in iteration_nodes:
            #                        is_regular_loop_node = False
            #                        break
            #                if is_regular_loop_node:
            #                    loop_context.add_node(loop_node)
            self.contexts.append(loop_context)

            # create iteration contexts
            for pair in pair_iteration_nodes:
                if pair[0].loopstate_iteration_ids is None:
                    warnings.warn(
                        "Applied fix: set previously unspecified loopstate iteration id of " + str(pair[0]) + "to [0]."
                    )
                    pair[0].loopstate_iteration_ids = [0]
                    # raise ValueError("TGStartIterationNode: loopstate iteration ids not set. Node: ", pair[0])
                iteration_context = IterationContext(loop_context, pair[0].loopstate_iteration_ids)
                pair[0].register_created_context(iteration_context)
                #                for iteration_node in pair_iteration_nodes[pair]:
                #                    iteration_context.add_node(iteration_node)
                loop_context.add_contained_context(iteration_context)
                self.contexts.append(iteration_context)

    def __assign_work_contexts(self) -> None:
        logger.info("Assigning work contexts to nodes...")

        for node in progress(self.graph.nodes):
            if not isinstance(node, TGStartWorkNode):
                continue
            # create a new work context
            work_context = WorkContext()
            node.register_created_context(work_context)
            self.contexts.append(work_context)

    def __assign_inlined_function_contexts(self) -> None:
        logger.info("Assigning inlined function contexts to nodes...")

        for node in progress(self.graph.nodes):
            if not isinstance(node, TGStartInlinedFunctionNode):
                continue
            # create a new inlined function context
            inlined_function_context = InlinedFunctionContext(call_instruction_id=node.call_instruction_id)
            node.register_created_context(inlined_function_context)
            self.contexts.append(inlined_function_context)

    def __assign_parent_contexts_to_nodes(self) -> None:
        # assigns each node the innermost context containing the node
        logger.info("Assigning parent contexts to nodes...")
        #        for ctx in progress(self.contexts):
        #            for node in ctx.get_contained_nodes(inclusive=False):
        #                node.add_parent_context(ctx)
        logger.info("--> classify entry points...")
        entry_points: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if len(self.get_predecessors(node)) == 0:
                entry_points.append(node)
        logger.info("DFS parsing entry points...")
        for entry_point in progress(entry_points):
            queue: Deque[Tuple[TGNode, Optional[Context]]] = deque()
            root_context = Context()
            # skip root node when initializing the queue
            if isinstance(entry_point, RootNode):
                for succ in self.get_successors(entry_point):
                    queue.append((succ, root_context))
            else:
                queue = deque([(entry_point, root_context)])
            already_enqueued: Set[Tuple[TGNode, Optional[Context]]] = set()
            while len(queue) > 0:
                current_node, current_parent_context = queue.popleft()
                # check if a new context is entered
                entered_context: Optional[Context] = None
                if (
                    isinstance(current_node, TGStartFunctionNode)
                    or isinstance(current_node, TGStartLoopNode)
                    or isinstance(current_node, TGStartIterationNode)
                    or isinstance(current_node, TGStartBranchParentNode)
                    or isinstance(current_node, TGStartBranchNode)
                    or isinstance(current_node, TGStartWorkNode)
                    or isinstance(current_node, TGStartInlinedFunctionNode)
                ):
                    entered_context = current_node.created_context

                # check if a context is exited
                exited_context: bool = False
                if (
                    isinstance(current_node, TGEndFunctionNode)
                    or isinstance(current_node, TGEndLoopNode)
                    or isinstance(current_node, TGEndIterationNode)
                    or isinstance(current_node, TGEndBranchParentNode)
                    or isinstance(current_node, TGEndBranchNode)
                    or isinstance(current_node, TGEndWorkNode)
                    or isinstance(current_node, TGEndInlinedFunctionNode)
                ):
                    exited_context = True

                if entered_context is not None:
                    if current_parent_context is not None:
                        entered_context.register_parent_context(current_parent_context)
                    current_parent_context = entered_context
                    current_parent_context.add_node(current_node)
                    current_node.add_parent_context(current_parent_context)
                elif exited_context:
                    if current_parent_context is not None:
                        current_parent_context.add_node(current_node)
                        current_node.add_parent_context(current_parent_context)
                        current_parent_context = current_parent_context.parent_context
                    else:
                        pass
                else:
                    # regular node found
                    if current_parent_context is not None:
                        current_parent_context.add_node(current_node)
                        current_node.add_parent_context(current_parent_context)
                    else:
                        pass
                # add successors to the queue
                for succ in self.get_successors(current_node):
                    queue_element = (succ, current_parent_context)
                    if queue_element not in already_enqueued:
                        queue.append(queue_element)
                        already_enqueued.add(queue_element)

    def __assign_node_levels(self) -> None:
        # assings levels to each node starting from the outer most context
        # this should allow a cheap check for "incoming" and "outgoing" dependencies
        warnings.warn("Not yet implemented!")

    def __assign_loopstate_positions_within_functions(self) -> None:
        """Assigns each loop the position of its iteration bucket within the "_loopstate" digits of the
        callpaths reported by the profiler, as listed in the profiler's loopstate_positions.txt. A loop
        the file does not list gets no position (None). Only for profiles without that file, the loops
        of a function are numbered in the order of their start lines, which is a guess.
        This function MUST BE EXECUTED BEFORE inlining function calls."""
        logger.info("Assigning Loop state positions within functions...")

        profiler_dir: Optional[str] = (
            None if self.dynamic_dependency_file is None else str(Path(self.dynamic_dependency_file).parent)
        )
        mapping = (
            None
            if profiler_dir is None
            else read_loopstate_positions(os.path.join(profiler_dir, LOOPSTATE_POSITIONS_FILE))
        )
        # only read for the line sorting fallback, to report functions whose positions are untrustworthy
        digit_counts: Optional[Dict[str, int]] = None
        if mapping is None:
            logger.warning(
                "No %s found: guessing the loopstate positions of loops from their start lines.",
                LOOPSTATE_POSITIONS_FILE,
            )

        entry_points: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if isinstance(node, TGFunctionNode):
                entry_points.append(node)
        logger.info("--> Assigning loop state ids")
        for entry_point in progress(entry_points):
            function_nodes = self.get_descendants(entry_point)
            loops = [n for n in function_nodes if isinstance(n, TGStartLoopNode)]
            if len(loops) == 0:
                continue
            function_name = self.pet.node_at(entry_point.pet_node_id).name
            if mapping is not None:
                assigned_loopstate_positions = self.__loopstate_positions_from_mapping(
                    function_name, loops, mapping.get(function_name, [])
                )
                for loop in loops:
                    loop.loopstate_position = assigned_loopstate_positions.get(loop.pet_node_id)
                self.__register_loopstate_positions(function_name, loops)
                continue

            # fallback: find all loops in function, sort them by location, and assign loopstate_positions.
            loops_pet_nodes = list(dict.fromkeys([n.get_pet_node(self.pet) for n in loops]))
            cleaned_loops_pet_nodes = [lpn for lpn in loops_pet_nodes if lpn is not None]
            sorted_loops_pet_nodes = sorted(cleaned_loops_pet_nodes, key=lambda x: x.start_line)
            # assign loopstate_positions to PET node ids
            next_unused_position = 0
            assigned_loopstate_positions = dict()
            for l_pet in sorted_loops_pet_nodes:
                if l_pet.id in assigned_loopstate_positions:
                    continue
                assigned_loopstate_positions[l_pet.id] = next_unused_position
                next_unused_position += 1
            if digit_counts is None:
                digit_counts = (
                    dict()
                    if profiler_dir is None
                    else read_loopstate_digit_counts(os.path.join(profiler_dir, "stateID_to_callpath_mapping.txt"))
                )
            if function_name in digit_counts and digit_counts[function_name] != next_unused_position:
                logger.warning(
                    "Loopstate positions of function %s are untrustworthy: %d loops, but %d loopstate digits.",
                    function_name,
                    next_unused_position,
                    digit_counts[function_name],
                )
            # assign loopstate positions to TGStartLoopNode's for later use
            for loop in loops:
                if loop.pet_node_id not in assigned_loopstate_positions:
                    raise KeyError("No entry in assigned_loopstate_positions for PET node id: " + str(loop.pet_node_id))
                loop.loopstate_position = assigned_loopstate_positions[loop.pet_node_id]
            self.__register_loopstate_positions(function_name, loops)

    def __register_loopstate_positions(self, function_name: str, loops: List[TGStartLoopNode]) -> None:
        """remembers which PET loop the loopstate positions of function_name stand for, see
        loop_pet_ids_by_loopstate_position"""
        for loop in loops:
            if loop.loopstate_position is not None and loop.pet_node_id is not None:
                self.loop_pet_ids_by_loopstate_position.setdefault((function_name, loop.loopstate_position), set()).add(
                    loop.pet_node_id
                )

    def __loopstate_positions_from_mapping(
        self, function_name: str, loops: List[TGStartLoopNode], entries: List[LoopstatePosition]
    ) -> Dict[PETNodeID, int]:
        """The loopstate positions of the given loops of function_name per loop entry node id, as listed
        in entries (the function's lines of loopstate_positions.txt). A loop is matched by its LoopNode
        (the PET parent of the loop's entry node) or, if the profiler did not know that node, by an
        unambiguous start location. Loops without a match are logged and left out."""
        by_loop_node: Dict[str, int] = {e.loop_node_id: e.position for e in entries if e.loop_node_id is not None}
        by_location: Dict[str, Set[int]] = dict()
        for e in entries:
            if e.start_location is not None:
                by_location.setdefault(e.start_location, set()).add(e.position)

        result: Dict[PETNodeID, int] = dict()
        for loop in loops:
            if loop.pet_node_id in result:
                continue
            entry_node = loop.get_pet_node(self.pet)
            candidates: List[PETNode] = []
            if entry_node is not None:
                # the entry node is a CU of the loop's header, a direct child of its LoopNode
                if isinstance(entry_node, LoopNode):
                    candidates.append(entry_node)
                for source, _, _ in in_edges(self.pet, entry_node.id, EdgeType.CHILD):
                    parent = self.pet.node_at(source)
                    if isinstance(parent, LoopNode):
                        candidates.append(parent)
            position: Optional[int] = None
            for candidate in candidates:
                if candidate.id in by_loop_node:
                    position = by_loop_node[candidate.id]
                    break
            if position is None:
                # the entry node's own location only as the last resort
                for candidate in candidates + ([] if entry_node is None else [entry_node]):
                    positions = by_location.get(str(candidate.start_position()), set())
                    if len(positions) == 1:
                        position = next(iter(positions))
                        break
            if position is None:
                logger.warning(
                    "Loop %s of function %s is not listed in %s: it gets no loopstate position.",
                    loop.pet_node_id,
                    function_name,
                    LOOPSTATE_POSITIONS_FILE,
                )
                continue
            result[loop.pet_node_id] = position
        return result

    def __calculate_context_successions(self) -> None:
        logger.info("Assigning context successions...")
        logger.info("--> classify entry points...")
        entry_points: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if self.graph.in_degree(node) == 0:
                entry_points.append(node)

        logger.info("--> DFS parsing entry points...")
        for entry_point in progress(entry_points):
            # initialize succession calculation
            # per path: the context that most recently ended at the current level - the one a
            # context entered next has to be registered behind - and the stack of the contexts the
            # path is currently inside, which is what makes that context available again once the
            # level is left. See ContextStack.
            queue: Deque[Tuple[TGNode, int, Optional[Context], Optional[ContextStack]]] = deque(
                [(entry_point, 0, None, None)]
            )
            already_enqueued: Set[Tuple[TGNode, int]] = set()
            while len(queue) > 0:
                current_node, current_level, preceding_context, open_contexts = queue.popleft()
                if current_level < 0:
                    # this path left more contexts than it entered, so there is no level left to
                    # register successors at
                    continue
                # check for entering new context level
                entered_context: Optional[Context] = None
                if (
                    isinstance(current_node, TGStartFunctionNode)
                    or isinstance(current_node, TGStartLoopNode)
                    or isinstance(current_node, TGStartIterationNode)
                    or isinstance(current_node, TGStartBranchParentNode)
                    or isinstance(current_node, TGStartBranchNode)
                    or isinstance(current_node, TGStartWorkNode)
                    or isinstance(current_node, TGStartInlinedFunctionNode)
                ):
                    entered_context = current_node.created_context
                if entered_context is not None:
                    # connect previous context to entered context as successor
                    if preceding_context is not None:
                        preceding_context.register_successor_context(entered_context)
                    # the body of the entered context is a new level, in which nothing has ended yet
                    open_contexts = ContextStack(entered_context, open_contexts)
                    preceding_context = None
                    # update current context level
                    current_level += 1

                # check for exiting context level
                exited_context: bool = False
                if (
                    isinstance(current_node, TGEndFunctionNode)
                    or isinstance(current_node, TGEndLoopNode)
                    or isinstance(current_node, TGEndIterationNode)
                    or isinstance(current_node, TGEndBranchParentNode)
                    or isinstance(current_node, TGEndBranchNode)
                    or isinstance(current_node, TGEndWorkNode)
                    or isinstance(current_node, TGEndInlinedFunctionNode)
                ):
                    exited_context = True
                if exited_context:
                    # update current context level
                    current_level -= 1
                    if open_contexts is not None:
                        # back at the level the left context was entered at, where it is now the
                        # context that most recently ended
                        preceding_context = open_contexts.innermost
                        open_contexts = open_contexts.enclosing

                # add successors to the queue
                for succ in self.graph.successors(current_node):
                    if (succ, current_level) not in already_enqueued:
                        queue.append((succ, current_level, preceding_context, open_contexts))
                        already_enqueued.add((succ, current_level))

    ## DEBUG
    #       plt.ioff()
    #       self.plot_context_graph()
    #       plt.pause(1)
    ## !DEBUG

    def __collect_all_contexts(self) -> List[Context]:
        """Returns every context reachable from self.contexts via any of the four relations, in a
        deterministic order. self.contexts only holds the contexts the __assign_*_contexts passes
        created themselves, so it is not necessarily complete."""
        collected: Set[Context] = set()
        queue: List[Context] = list(self.contexts)
        collected.update(queue)
        while len(queue) > 0:
            current = queue.pop()
            related: List[Optional[Context]] = [current.parent_context, current.successor, current.predecessor]
            related += list(current.contained_contexts)
            for ctx in related:
                if ctx is not None and ctx not in collected:
                    collected.add(ctx)
                    queue.append(ctx)
        return sorted(collected, key=lambda ctx: ctx.creation_index)

    def __describe_context(self, context: Context) -> str:
        """Identifies a context in a log message by its type and the source lines it covers."""
        scope = context.get_code_scope(self.pet)
        location = (scope[0] + ".." + scope[-1]) if len(scope) > 0 else "no source lines"
        return type(context).__name__ + " (" + location + ")"

    def __validate_context_structure(self) -> None:
        """Checks the structural invariants of the Context relations that __calculate_context_nesting
        and __calculate_context_successions build, and breaks cycles found in them.

        Every traversal of these relations - in Context itself, in the pattern detectors, and in
        ContextTaskGraph - assumes that containment forms a forest and that the successor chain is
        acyclic. None of the passes building them enforces that: they set parent_context /
        successor unconditionally, so the last write wins, and a node reached twice at the same
        nesting level via different paths can be linked into two different sequences. A cycle
        introduced that way is invisible until some traversal diverges, which surfaces as a
        RecursionError or a hang far away from its cause.

        Cycles are broken here (rather than raised) because a well-formed structure is what the
        rest of the pipeline needs, and because the results for the unaffected parts of the program
        stay valid. They are logged as errors, since they always indicate a defect in one of the
        passes above. Inconsistencies that cannot be repaired unambiguously - a containment or
        succession link that is only recorded on one of its two ends - are only counted and
        reported."""
        contexts = self.__collect_all_contexts()

        broken_containment_edges = self.__break_containment_cycles(contexts)
        broken_succession_links = self.__break_succession_cycles(contexts)
        self.__report_context_relation_inconsistencies(contexts)

        if broken_containment_edges > 0 or broken_succession_links > 0:
            logger.error(
                "Broke %d cyclic containment edge(s) and %d cyclic succession link(s) in the "
                "context structure. This indicates a defect in __calculate_context_nesting / "
                "__calculate_context_successions; results depending on the affected contexts "
                "are unreliable.",
                broken_containment_edges,
                broken_succession_links,
            )

    def __break_containment_cycles(self, contexts: List[Context]) -> int:
        """Detects cycles in the contained_contexts relation with an iterative depth-first search
        and removes the edge closing each of them. Returns the number of removed edges."""
        ON_STACK, FINISHED = 1, 2
        state: Dict[Context, int] = dict()
        removed = 0
        for root in progress(contexts, desc="Breaking containment cycles"):
            if root in state:
                continue
            state[root] = ON_STACK
            # (context, its not yet visited children); children are popped from the back
            stack: List[Tuple[Context, List[Context]]] = [(root, self.__sorted_contexts(root.contained_contexts))]
            while len(stack) > 0:
                current, remaining_children = stack[-1]
                if len(remaining_children) == 0:
                    state[current] = FINISHED
                    stack.pop()
                    continue
                child = remaining_children.pop()
                child_state = state.get(child, 0)
                if child_state == ON_STACK:
                    # back edge: child is an ancestor of current on the current search path
                    logger.error(
                        "Context %s contains %s, which is one of its own ancestors. Removing the "
                        "containment edge to keep the containment relation acyclic.",
                        self.__describe_context(current),
                        self.__describe_context(child),
                    )
                    current.contained_contexts.discard(child)
                    if child.parent_context is current:
                        child.parent_context = None
                    removed += 1
                elif child_state == 0:
                    state[child] = ON_STACK
                    stack.append((child, self.__sorted_contexts(child.contained_contexts)))
                # FINISHED children are reached via a second, non-cyclic path - harmless here
        return removed

    def __break_succession_cycles(self, contexts: List[Context]) -> int:
        """Detects cycles in the successor relation and clears the link closing each of them.
        Every context has at most one successor, so following the chain from each context and
        colouring the contexts on it visits every context once. Returns the number of cleared
        links."""
        ON_PATH, FINISHED = 1, 2
        state: Dict[Context, int] = dict()
        cleared = 0
        for context in progress(contexts, desc="Breaking succession cycles"):
            if context in state:
                continue
            path: List[Context] = []
            current: Optional[Context] = context
            while current is not None and current not in state:
                state[current] = ON_PATH
                path.append(current)
                current = current.successor
            if current is not None and state[current] == ON_PATH:
                # the chain ran back into a context of the path just walked
                closing_context = path[-1]
                logger.error(
                    "The successor chain starting at %s runs back into %s. Clearing the closing "
                    "link to keep the successor relation acyclic.",
                    self.__describe_context(closing_context),
                    self.__describe_context(current),
                )
                closing_context.successor = None
                if current.predecessor is closing_context:
                    current.predecessor = None
                cleared += 1
            for path_context in path:
                state[path_context] = FINISHED
        return cleared

    def __report_context_relation_inconsistencies(self, contexts: List[Context]) -> None:
        """Reports containment and succession links that are only recorded on one of their two
        ends. These are not repaired: which of the two ends is the correct one is not decidable
        here."""
        one_sided_containment = 0
        one_sided_succession = 0
        for context in progress(contexts, desc="Checking context relation consistency"):
            for child in context.contained_contexts:
                if child.parent_context is not context:
                    one_sided_containment += 1
            if context.parent_context is not None and context not in context.parent_context.contained_contexts:
                one_sided_containment += 1
            if context.successor is not None and context.successor.predecessor is not context:
                one_sided_succession += 1
            if context.predecessor is not None and context.predecessor.successor is not context:
                one_sided_succession += 1
        if one_sided_containment > 0 or one_sided_succession > 0:
            logger.warning(
                "Context structure contains %d one-sided containment and %d one-sided succession "
                "link(s) out of %d contexts. Traversals starting from either end of such a link "
                "see different structures.",
                one_sided_containment,
                one_sided_succession,
                len(contexts),
            )

    @staticmethod
    def __sorted_contexts(contexts: Set[Context]) -> List[Context]:
        """contained_contexts is a set, so it has to be ordered explicitly wherever the result
        depends on the iteration order."""
        return sorted(contexts, key=lambda ctx: ctx.creation_index)

    def __induction_variables(self, loop_ctx: LoopParentContext) -> Tuple[Optional[Set[str]], Optional[LineID]]:
        """(the loop indices of the loop's LoopNode, see PEGraphX.calculateLoopMetadata, or None if
        the loop has no LoopNode; the line of the loop's header)"""
        if loop_ctx.parent_loop is None or loop_ctx.parent_loop not in self.pet.g:
            return None, None
        entry = self.pet.node_at(loop_ctx.parent_loop)
        header_line = LineID(str(entry.file_id) + ":" + str(entry.start_line))
        loop_node = self.__loop_node_of_entry(loop_ctx.parent_loop)
        return (None if loop_node is None else set(loop_node.loop_indices)), header_line

    def __determine_loop_variables(self) -> None:
        """determine loop variables: the variables the loop header and the iterations exchange values
        of (RAW dependencies between them) which the loop itself advances. That is the case for an
        induction variable of the loop's LoopNode, and for a variable read and written on the line of
        the loop header (the increment of a for loop). A variable only written in the loop body and
        read in the condition, as in `while (x < n) x = ...;` or `while (v >= end[i]) i++;`, is no
        loop variable: its dependencies are carried by the loop, and exempting them would make such a
        loop look parallel."""
        logger.info("Determine loop variables...")
        logger.info("--> classify entry points...")
        entry_points: List[LoopParentContext] = []
        for node in progress(self.graph.nodes):
            if type(node.created_context) == LoopParentContext:
                entry_points.append(node.created_context)
        logger.info("--> determine loop variables...")
        for loop_ctx in progress(entry_points):
            loop_header_ctx = self.get_loop_header_context(loop_ctx)
            #            print("LOOP HEADER CTX:", loop_header_ctx)
            if loop_header_ctx is None:
                continue
            # identify loop variables by checking for RAW dependencies between loop body and loop header
            loop_iteration_ctxs = loop_ctx.get_contained_contexts(inclusive=True)
            loop_vars: List[Tuple[str, MemoryRegion]] = []
            #            print("LOOP IT CTXS: ", loop_iteration_ctxs)
            #            print("LOOP HEADER OUTDEPS: ", loop_header_ctx.outgoing_dependencies)
            #            print("LOOP HEADER INDEPS: ", loop_header_ctx.incoming_dependencies)
            for target_ctx, dep in loop_header_ctx.outgoing_dependencies:
                if dep is None or dep.etype != EdgeType.DATA:
                    continue
                # only consider RAW dependencies
                if dep.dtype != DepType.RAW:
                    continue
                if dep.var_name is None or dep.memory_region is None:
                    continue
                if target_ctx in loop_iteration_ctxs:
                    loop_vars.append((dep.var_name, dep.memory_region))

            for source_ctx, dep in loop_header_ctx.incoming_dependencies:
                if dep is None or dep.etype != EdgeType.DATA:
                    continue
                # only consider RAW dependencies
                if dep.dtype != DepType.RAW:
                    continue
                if dep.var_name is None or dep.memory_region is None:
                    continue
                if source_ctx in loop_iteration_ctxs:
                    loop_vars.append((dep.var_name, dep.memory_region))

            # remove duplicates
            loop_vars = list(dict.fromkeys(loop_vars))
            loop_indices, header_line = self.__induction_variables(loop_ctx)
            advanced_on_header_line: Set[Tuple[str, MemoryRegion]] = set()
            for _, dep in list(loop_header_ctx.outgoing_dependencies) + list(loop_header_ctx.incoming_dependencies):
                if (
                    dep is not None
                    and dep.dtype == DepType.RAW
                    and dep.var_name is not None
                    and dep.memory_region is not None
                    and header_line is not None
                    and dep.source_line == header_line
                    and dep.sink_line == header_line
                ):
                    advanced_on_header_line.add((dep.var_name, dep.memory_region))
            loop_vars = [
                v
                for v in loop_vars
                if (loop_indices is not None and v[0] in loop_indices) or v in advanced_on_header_line
            ]
            # save loop variables
            loop_ctx.loop_variables = loop_vars

    def __cleanup_loop_dependencies(self) -> None:
        """removed incorrectly added static dependencies between loop iterations using the loop variable."""
        logger.info("Cleaning loop dependencies...")
        logger.info("--> classify entry points...")
        entry_points: List[LoopParentContext] = []
        for node in progress(self.graph.nodes):
            if type(node.created_context) == LoopParentContext:
                entry_points.append(node.created_context)
        logger.info("--> cleaning loop dependencies")
        for loop_ctx in progress(entry_points):
            # get contexts by iterations
            iteration_ctxs = [
                c for c in loop_ctx.get_contained_contexts(inclusive=False) if type(c) == IterationContext
            ]
            iteration_contained_ctxs: Dict[IterationContext, Set[Context]] = dict()
            for it_ctx in iteration_ctxs:
                iteration_contained_ctxs[it_ctx] = it_ctx.get_contained_contexts(inclusive=True)
            # remove dependencies targeting loop variables between loop iterations
            for it_ctx_1 in iteration_ctxs:
                for it_ctx_2 in iteration_ctxs:
                    if it_ctx_1 == it_ctx_2:
                        continue
                    for it_1_node in iteration_contained_ctxs[it_ctx_1]:
                        # it_1_node and it_2_node are in different iterations of the same loop
                        # check static dependencies only
                        # check for dependencies between them using the loop variable
                        to_be_removed: List[Tuple[Context, Context, Dependency]] = []
                        for target_ctx, dep in it_1_node.outgoing_dependencies:
                            if dep is None or dep.etype != EdgeType.DATA:
                                continue
                            if dep.origin != DepOrigin.STATIC_ANALYSIS:
                                continue
                            if (dep.var_name, dep.memory_region) not in loop_ctx.loop_variables:
                                continue

                            if target_ctx in iteration_contained_ctxs[it_ctx_2]:
                                to_be_removed.append((it_1_node, target_ctx, dep))
                        # apply dependency deletions
                        for tpl in to_be_removed:
                            tpl[0].delete_outgoing_dependency(tpl[1], tpl[2])

    def __calculate_context_nesting(self) -> None:
        logger.info("Assigning context nestings...")
        logger.info("--> classify entry points...")

        entry_points: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if len(self.get_predecessors(node)) == 0:
                entry_points.append(node)

        logger.info("--> DFS parsing entry points...")
        for entry_point in progress(entry_points):

            # initialize the nesting calculation
            queue: Deque[Tuple[TGNode, Optional[Context]]] = deque([(entry_point, None)])
            already_enqueued: Set[Tuple[TGNode, Optional[Context]]] = {(entry_point, None)}
            while len(queue) > 0:
                current_node, current_context = queue.popleft()

                # check for entering a new contexts
                entered_context: Optional[Context] = None
                if (
                    isinstance(current_node, TGStartFunctionNode)
                    or isinstance(current_node, TGStartLoopNode)
                    or isinstance(current_node, TGStartIterationNode)
                    or isinstance(current_node, TGStartBranchParentNode)
                    or isinstance(current_node, TGStartBranchNode)
                    or isinstance(current_node, TGStartWorkNode)
                    or isinstance(current_node, TGStartInlinedFunctionNode)
                ):
                    entered_context = current_node.created_context

                # check for exiting a context
                exited_context: bool = False
                if (
                    isinstance(current_node, TGEndFunctionNode)
                    or isinstance(current_node, TGEndLoopNode)
                    or isinstance(current_node, TGEndIterationNode)
                    or isinstance(current_node, TGEndBranchParentNode)
                    or isinstance(current_node, TGEndBranchNode)
                    or isinstance(current_node, TGEndWorkNode)
                    or isinstance(current_node, TGEndInlinedFunctionNode)
                ):
                    exited_context = True

                # assert validity of the results
                if entered_context is not None and exited_context:
                    raise ValueError("Impossible result")

                # handle entering a context
                if entered_context is not None:
                    # register current_context as a parent of the entered context
                    if current_context is not None:
                        current_context.add_contained_context(entered_context)
                        entered_context.register_parent_context(current_context)
                    # update the current context
                    current_context = entered_context
                elif exited_context:
                    # update the current context
                    if current_context is None:
                        warnings.warn("Current context must not be None during processing!")
                        # plt.ioff()
                        # self.plot(highlight_nodes=[current_node])
                        raise ValueError("Current context must not be None during processing!")
                    # if current_context.parent_context is None:
                    #    raise ValueError("Parent context is unspecified. Exiting a context thus not possible!")
                    else:
                        # empty parent context can happen at the root level of the graph. All other cases are invalid.
                        if current_context.parent_context is None:
                            #                            print("TYPE: ", type(current_context))
                            if type(current_context) != Context:
                                raise ValueError(
                                    "Current.parent_context must not be None, as context must not be None during processing!"
                                )
                            continue
                        current_context = current_context.parent_context

                # add successors to the queue
                for succ in self.get_successors(current_node):
                    queue_element = (succ, current_context)
                    if queue_element not in already_enqueued:
                        queue.append(queue_element)
                        already_enqueued.add(queue_element)

    ### DEBGU
    #        plt.ioff()
    #        self.plot_context_graph()
    #        plt.pause(1)
    #        for ctx in self.contexts:
    #            print("parents: ", str([c.get_label() for c in ctx.parent_context]))
    #        import sys
    #        sys.exit(0)
    ### !DEBUG

    def __inline_function_calls(self) -> None:
        warnings.warn("Not yet implemented!")
        logger.info("Inlining function calls...")
        self.print_graph_statistics(self.graph, "pre inlining")
        # determine calling nodes
        calling_pet_nodes = [n.id for n in all_nodes(self.pet) if len(get_called_nodes(self.pet, n)) > 0]

        # inline functions calls starting from the root node
        # repeat the process until no modification is found anymore, i.e. no further functions calls need to be inlined
        # Tracking of the call path depth for "early termination", i.e. supporting recursion and cyclic calls
        call_path_limit = self.CALL_PATH_LIMIT
        call_path_depth = 0
        modification_found = True
        with progress(total=call_path_limit, desc="Callpath depth") as progress_bar:
            while modification_found:
                call_path_depth += 1
                if call_path_depth >= call_path_limit:
                    logger.info("Maximum call path depth of " + str(call_path_limit) + " reached.")
                    break
                modification_found = False
                descendants = self.get_descendants(self.root)
                calling_nodes: List[TGNode] = []
                for node in descendants:
                    if (
                        node.pet_node_id in calling_pet_nodes and type(node) == TGNode
                    ):  # check for type TGNode to exclude function calls etc.
                        calling_nodes.append(node)
                # filter calling nodes to such, which have not been inlined already
                filtered_calling_nodes: List[TGNode] = []
                for cn in calling_nodes:
                    already_inlined = False
                    for succ in self.get_successors(cn):
                        if isinstance(succ, TGStartInlinedFunctionNode):
                            # call already inlined
                            already_inlined = True
                            break
                    if not already_inlined:
                        filtered_calling_nodes.append(cn)

                for fcn in progress(filtered_calling_nodes, desc="Open calls"):
                    if fcn.pet_node_id is None:
                        continue
                    # duplicate inlined function body and insert it after the caller
                    caller = self.pet.node_at(fcn.pet_node_id)
                    called_functions_pet_node_ids = get_called_node_ids(self.pet, caller)
                    for cf_pet_node_id in called_functions_pet_node_ids:
                        call_instruction_id = get_call_instruction_id(caller, self.pet.node_at(cf_pet_node_id))
                        function_entry = self.TGFunctionNode_pet_node_id_to_tg_node[cf_pet_node_id]
                        inlined_entry, inlined_exit = self.__duplicate_inlined_function(
                            function_entry, fcn.pet_node_id, call_instruction_id
                        )
                        # connect edges
                        for succ in self.get_successors(fcn):
                            self.graph.remove_edge(fcn, succ)
                            self.add_edge(fcn, inlined_entry)
                            self.add_edge(inlined_exit, succ)
                        modification_found = True

                progress_bar.update()

                self.print_graph_statistics(self.graph, "post inlining")

    def __branching_dominator_trees(
        self, function_node: TGNode
    ) -> Tuple[Set[TGNode], Dict[TGNode, TGNode], Dict[Any, Any], object]:
        """(scope, idom, ipdom, virtual exit) of the control flow below function_node. The
        post-dominator tree is computed on the reversed graph with all sinks merged into one
        virtual exit, so post-dominance reduces to ordinary dominance from that exit."""
        scope: Set[TGNode] = set(self.get_descendants(function_node))
        scope.add(function_node)
        dom_graph = nx.MultiDiGraph()
        dom_graph.add_nodes_from(scope)
        for node in scope:
            for succ in self.get_successors(node):
                if succ in scope:
                    dom_graph.add_edge(node, succ)
        idom = nx.immediate_dominators(dom_graph, function_node)
        sinks = [node for node in scope if dom_graph.out_degree(node) == 0]
        pdom_graph = dom_graph.reverse(copy=True)
        virtual_exit = object()
        pdom_graph.add_node(virtual_exit)
        for sink in sinks:
            pdom_graph.add_edge(virtual_exit, sink)
        ipdom = nx.immediate_dominators(pdom_graph, virtual_exit)
        return scope, idom, ipdom, virtual_exit

    # nodes a short-circuit condition or a duplicated tail must not contain: loops stay single
    # copies (inlined calls, including their function markers, are fine)
    _NON_CONDITION_NODE_TYPES = (TGStartLoopNode, TGEndLoopNode, TGStartIterationNode, TGEndIterationNode)
    # at most this many nodes of a condition are treated as always evaluated
    _MAX_CHAINED_CONDITION_NODES = 200
    # at most this many nodes are copied for one side entry of a branch region
    _MAX_TAIL_DUPLICATION_NODES = 80

    def __split_branch_region_side_entries(self, function_node: TGNode) -> Tuple[int, int, int]:
        """Makes the branch regions (n, ipdom(n)) single-entry, so that the branching markers can
        nest. Returns (removed short-circuit edges, copied nodes, side entries left unresolved).

        Conditions with short-circuit operators and shared return blocks produce regions which are
        entered from the side: in `if (a && (b || c)) return 1; else return 0;` the block
        `return 1` is reached from b and from c, and `return 0` from a and from c, so neither the
        region of b nor the one of c is single-entry, and no placement of markers is properly
        nested. A side entry y of the region of n (a node of the region with a predecessor p
        outside of it) is resolved in one of two ways:

        - short-circuit edge: if p also reaches y through a few nodes without loops (the
          remaining parts of the condition), the edge p -> y is removed, so that `a && b` becomes
          the chain a -> b. The paths through the graph keep their nodes, except that these
          condition parts now count as always evaluated - an over-approximation of the executed
          code, which loses no dependency.
        - tail duplication: otherwise, if the nodes from y to the region's exit are few and
          contain no loop, y is split: a copy takes over the edges from outside and keeps
          the outgoing edges, and its successors become side entries in turn. Splitting does not
          change the paths through the graph. The copies are made before contexts exist, so a
          copied block becomes a second copy of its context, as copies of loop iterations do.

        Side entries matching neither are left as they are (the branching markers of their region
        may then not nest).

        The short-circuit test is plain reachability, so it also applies to other edges into a shared
        tail (a switch fallthrough, a goto). The code such an edge skipped then counts as executed on
        that path as well: contexts and their dependencies are unaffected, the exclusivity of the
        branch arms is not preserved."""
        removed_edges = 0
        copied = 0
        unresolved = 0
        # removing edges changes the dominator trees, so they are recomputed in rounds
        for _ in range(10):
            scope, idom, ipdom, virtual_exit = self.__branching_dominator_trees(function_node)
            modified = False
            unresolved = 0

            def dom_depth(node: TGNode) -> int:
                depth = 0
                current = node
                while current in idom and idom[current] != current:
                    current = idom[current]
                    depth += 1
                return depth

            branch_points = [node for node in scope if len([s for s in self.get_successors(node) if s in scope]) > 1]
            # innermost first, in a deterministic order
            branch_points.sort(key=lambda node: (-dom_depth(node), self.__pet_node_order(node)))
            for n in branch_points:
                m = ipdom.get(n)
                if m is None or m is virtual_exit or len(self.get_successors(n)) < 2:
                    continue
                region = self.__nodes_before(n, m)
                inside = region | {n}
                if all(all(pred in inside for pred in self.get_predecessors(node)) for node in region):
                    continue
                for node in self.__topological_order(region):
                    outside_preds = [pred for pred in self.get_predecessors(node) if pred not in inside]
                    for pred in outside_preds:
                        if self.__is_short_circuit_edge(pred, node):
                            while self.graph.has_edge(pred, node):
                                self.graph.remove_edge(pred, node)
                            removed_edges += 1
                            modified = True
                    outside_preds = [pred for pred in self.get_predecessors(node) if pred not in inside]
                    if len(outside_preds) == 0:
                        continue
                    tail = self.__nodes_before(node, m) | {node}
                    if len(tail) > self._MAX_TAIL_DUPLICATION_NODES or any(
                        isinstance(t, self._NON_CONDITION_NODE_TYPES) for t in tail
                    ):
                        unresolved += 1
                        logger.debug(
                            "Unresolved side entry of the branch region at "
                            + str(n.pet_node_id)
                            + ": "
                            + str(node.pet_node_id)
                            + " (tail of "
                            + str(len(tail))
                            + " nodes)"
                        )
                        continue
                    node_copy = copy.deepcopy(node)
                    self.add_node(node_copy)
                    self.__dict__.setdefault("tail_duplication_origins", {})[node_copy] = node
                    copied += 1
                    modified = True
                    for pred in outside_preds:
                        while self.graph.has_edge(pred, node):
                            self.graph.remove_edge(pred, node)
                            self.add_edge(pred, node_copy)
                    for succ in self.get_successors(node):
                        for _ in range(self.graph.number_of_edges(node, succ)):
                            self.add_edge(node_copy, succ)
            if not modified:
                break
        return removed_edges, copied, unresolved

    def __nodes_before(self, source: TGNode, stop: TGNode) -> Set[TGNode]:
        """Every node reachable from source (exclusive) without passing stop."""
        found: Set[TGNode] = set()
        queue: Deque[TGNode] = deque([source])
        while len(queue) > 0:
            current = queue.popleft()
            for succ in self.get_successors(current):
                if succ is not stop and succ not in found:
                    found.add(succ)
                    queue.append(succ)
        return found

    def __topological_order(self, nodes: Set[TGNode]) -> List[TGNode]:
        """nodes in a deterministic topological order of the edges among them."""
        in_degree = {node: len([p for p in self.get_predecessors(node) if p in nodes]) for node in nodes}
        ready = sorted([node for node, degree in in_degree.items() if degree == 0], key=self.__pet_node_order)
        order: List[TGNode] = []
        while len(ready) > 0:
            current = ready.pop(0)
            order.append(current)
            for succ in self.get_successors(current):
                if succ in in_degree:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        ready.append(succ)
        return order

    def __is_short_circuit_edge(self, source: TGNode, target: TGNode) -> bool:
        """True if source has another successor from which target is reached through at most
        _MAX_CHAINED_CONDITION_NODES nodes without loops (the remaining
        parts of a condition, possibly with inlined calls), so that source -> target is the short
        circuit of a condition."""
        queue: Deque[TGNode] = deque()
        seen: Set[TGNode] = set()
        for other in self.get_successors(source):
            if other is not target and not isinstance(other, self._NON_CONDITION_NODE_TYPES) and other not in seen:
                queue.append(other)
                seen.add(other)
        while len(queue) > 0:
            current = queue.popleft()
            for succ in self.get_successors(current):
                if succ is target:
                    return True
                if succ in seen or isinstance(succ, self._NON_CONDITION_NODE_TYPES):
                    continue
                if len(seen) >= self._MAX_CHAINED_CONDITION_NODES:
                    return False
                seen.add(succ)
                queue.append(succ)
        return False

    def __add_branching_nodes_for_function(self, function_node: TGNode) -> None:
        """Wraps every branch point (a node with more than one successor) together with its
        immediate post-dominator (the unique point where all of its arms are guaranteed to
        reconverge) in Start/EndBranchParent + per-arm Start/EndBranch markers.

        Using dominance/post-dominance instead of a purely local in/out-degree heuristic
        guarantees the inserted regions are properly nested (single-entry/single-exit). This
        matters because later context assignment relies on a simple stack-based enter/exit
        walk, which only produces a single, consistent enclosing context per node if the
        regions it walks are properly nested - a purely local degree-based heuristic can
        instead wrap unrelated, non-nested merge points (e.g. a loop's own exit converging
        with an internal break) into the same marker, which silently corrupts context
        assignment depending on graph traversal order.
        """
        removed, copies, unresolved = self.__split_branch_region_side_entries(function_node)
        if removed + copies + unresolved > 0:
            logger.info(
                "Branch regions of "
                + function_node.get_label()
                + ": removed "
                + str(removed)
                + " short-circuit edges, copied "
                + str(copies)
                + " nodes, left "
                + str(unresolved)
                + " side entries"
            )
        # per instance (the class attribute is only the default for an empty statistic)
        statistics: Dict[str, int] = self.__dict__.setdefault("branch_region_side_entry_statistics", {})
        for key, value in (("removed_edges", removed), ("copied_nodes", copies), ("unresolved", unresolved)):
            statistics[key] = statistics.get(key, 0) + value
        scope, idom, ipdom, virtual_exit = self.__branching_dominator_trees(function_node)

        def scoped_successors(node: TGNode) -> List[TGNode]:
            return [s for s in self.get_successors(node) if s in scope]

        region_owner: Dict[TGNode, TGNode] = {}

        def dom_depth(node: TGNode) -> int:
            depth = 0
            current = node
            while current in idom and idom[current] != current:
                current = idom[current]
                depth += 1
            return depth

        def dominates(ancestor: TGNode, node: TGNode) -> bool:
            # resolve synthetic wrapper nodes to the branch point they were created for, so
            # nesting composes correctly regardless of the order regions are processed in
            current = node
            while current in region_owner:
                current = region_owner[current]
            if current == ancestor:
                return True
            while current in idom and idom[current] != current:
                current = idom[current]
                if current == ancestor:
                    return True
            return False

        # process innermost (deepest) branch points first, so that by the time an
        # enclosing branch point is handled, anything it contains has already been wrapped
        branch_points = [node for node in scope if len(scoped_successors(node)) > 1]
        branch_points.sort(key=dom_depth, reverse=True)

        for n in branch_points:
            m = ipdom.get(n)
            if m is None or m is virtual_exit:
                # every arm of this branch reaches the function's end without reconverging
                # first - there is no internal merge point to close here
                continue

            # m can be a convergence point shared with another, non-nested branch (e.g. an
            # independent early exit that happens to reconverge at the same place). Check
            # up front whether n actually owns any of m's current predecessors: if none are
            # dominated by n, wrapping here would create an EndBranchParent with zero
            # predecessors - an orphaned node with no way to ever be entered, which later
            # crashes context nesting since it looks like a valid entry point starting
            # mid-context. Leave n entirely unwrapped in that case and let
            # __add_branching_nodes_fallback_cleanup, which is designed for exactly this
            # situation, wrap it unconditionally instead.
            claimed_preds = [pred for pred in self.get_predecessors(m) if dominates(n, pred)]
            if len(claimed_preds) == 0:
                continue

            start_branch_parent_node = TGStartBranchParentNode(n.pet_node_id, level=n.level, position=n.position)
            self.add_node(start_branch_parent_node)
            region_owner[start_branch_parent_node] = n
            for succ in list(self.get_successors(n)):
                self.graph.remove_edge(n, succ)
                self.add_edge(start_branch_parent_node, succ)
            self.add_edge(n, start_branch_parent_node)

            end_branch_parent_node = TGEndBranchParentNode(m.pet_node_id, level=m.level, position=m.position)
            self.add_node(end_branch_parent_node)
            region_owner[end_branch_parent_node] = n
            for pred in claimed_preds:
                # n trivially dominates itself, so n can be one of its own arms feeding
                # directly into m (e.g. an "if" with no "else"). claimed_preds was snapshotted
                # before the successor-rewiring loop above, which unconditionally retargets all
                # of n's own outgoing edges (including a direct n->m arm) to
                # start_branch_parent_node - so by now that's the live stand-in for n's own
                # contribution, not n itself. Removing (n, m) again would raise NetworkXError
                # (the edge is already gone) and abort this function's wrapping partway
                # through, leaving end_branch_parent_node behind with whatever predecessors
                # happened to be wired before the abort - possibly zero.
                actual_pred = start_branch_parent_node if pred == n else pred
                if not self.graph.has_edge(actual_pred, m):
                    continue
                self.graph.remove_edge(actual_pred, m)
                self.add_edge(actual_pred, end_branch_parent_node)
            self.add_edge(end_branch_parent_node, m)

            for succ in list(self.get_successors(start_branch_parent_node)):
                start_branch_node = TGStartBranchNode(
                    start_branch_parent_node.pet_node_id,
                    level=start_branch_parent_node.level,
                    position=start_branch_parent_node.position,
                )
                self.add_node(start_branch_node)
                region_owner[start_branch_node] = n
                self.graph.remove_edge(start_branch_parent_node, succ)
                self.add_edge(start_branch_parent_node, start_branch_node)
                self.add_edge(start_branch_node, succ)

            for pred in list(self.get_predecessors(end_branch_parent_node)):
                end_branch_node = TGEndBranchNode(
                    end_branch_parent_node.pet_node_id,
                    level=end_branch_parent_node.level,
                    position=end_branch_parent_node.position,
                )
                self.add_node(end_branch_node)
                region_owner[end_branch_node] = n
                self.graph.remove_edge(pred, end_branch_parent_node)
                self.add_edge(pred, end_branch_node)
                self.add_edge(end_branch_node, end_branch_parent_node)

    def __add_branching_nodes_fallback_cleanup(self) -> None:
        """Safety net for cases the dominance-based pass above cannot resolve on its own -
        chiefly, two independent (non-nested) branch points that happen to share the same
        merge point. That pass only lets a branch point claim predecessors of its merge that
        it actually dominates, so such siblings each keep their own EndBranchParent feeding
        directly into the shared merge node, and a function where dominance computation
        itself failed (see the try/except in __add_branching_nodes) is left entirely
        unwrapped. Wrap any residual multi-successor/multi-predecessor node the same way
        __add_branching_nodes used to unconditionally, so the graph-structure invariant
        checked right after this call always holds.
        """
        remaining_branch_parent_nodes = [
            n
            for n in self.graph.nodes
            if len(self.get_successors(n)) > 1 and not isinstance(n, TGStartBranchParentNode)
        ]
        remaining_merge_nodes = [
            n
            for n in self.graph.nodes
            if len(self.get_predecessors(n)) > 1 and not isinstance(n, TGEndBranchParentNode)
        ]
        if len(remaining_branch_parent_nodes) == 0 and len(remaining_merge_nodes) == 0:
            return
        logger.warning(
            "Dominance-based branching node insertion left "
            + str(len(remaining_branch_parent_nodes))
            + " unwrapped branch point(s) and "
            + str(len(remaining_merge_nodes))
            + " unwrapped merge point(s) (independent/non-nested control flow, or a function "
            + "dominance computation failed on). Falling back to unconditional wrapping for "
            + "these; results in this region may retain some run-to-run ordering variance."
        )

        start_branch_parent_nodes: List[TGNode] = []
        for bpn in remaining_branch_parent_nodes:
            start_branch_parent_node = TGStartBranchParentNode(bpn.pet_node_id, level=bpn.level, position=bpn.position)
            start_branch_parent_nodes.append(start_branch_parent_node)
            self.add_node(start_branch_parent_node)
            for succ in list(self.get_successors(bpn)):
                self.graph.remove_edge(bpn, succ)
                self.add_edge(start_branch_parent_node, succ)
            self.add_edge(bpn, start_branch_parent_node)

        end_branch_parent_nodes: List[TGNode] = []
        for mn in remaining_merge_nodes:
            end_branch_parent_node = TGEndBranchParentNode(mn.pet_node_id, level=mn.level, position=mn.position)
            end_branch_parent_nodes.append(end_branch_parent_node)
            self.add_node(end_branch_parent_node)
            for pred in list(self.get_predecessors(mn)):
                self.graph.remove_edge(pred, mn)
                self.add_edge(pred, end_branch_parent_node)
            self.add_edge(end_branch_parent_node, mn)

        for sbpn in start_branch_parent_nodes:
            for succ in list(self.get_successors(sbpn)):
                start_branch_node = TGStartBranchNode(sbpn.pet_node_id, level=sbpn.level, position=sbpn.position)
                self.add_node(start_branch_node)
                self.graph.remove_edge(sbpn, succ)
                self.add_edge(sbpn, start_branch_node)
                self.add_edge(start_branch_node, succ)

        for ebpn in end_branch_parent_nodes:
            for pred in list(self.get_predecessors(ebpn)):
                end_branch_node = TGEndBranchNode(ebpn.pet_node_id, level=ebpn.level, position=ebpn.position)
                self.add_node(end_branch_node)
                self.graph.remove_edge(pred, ebpn)
                self.add_edge(pred, end_branch_node)
                self.add_edge(end_branch_node, ebpn)

    def __add_branching_nodes(self) -> None:
        self.branch_region_side_entry_statistics = {"removed_edges": 0, "copied_nodes": 0, "unresolved": 0}
        self.tail_duplication_origins = dict()
        for function_node in progress(
            list(self.TGFunctionNode_pet_node_id_to_tg_node.values()), desc="Adding branching nodes per function"
        ):
            try:
                self.__add_branching_nodes_for_function(function_node)
            except nx.NetworkXError as e:
                logger.warning(
                    "Dominance-based branching node insertion failed for function "
                    + function_node.get_label()
                    + " ("
                    + str(e)
                    + "). Falling back to unconditional wrapping for its remaining branch/merge points."
                )
        self.__add_branching_nodes_fallback_cleanup()

        for node in progress(self.graph.nodes, desc="Validating node successors/predecessors"):
            succ_count = len(self.get_successors(node))
            pred_count = len(self.get_predecessors(node))
            if isinstance(node, TGEndBranchParentNode) and pred_count == 0:
                logger.error("Invalid graph structure: " + str(type(node)) + " has no predecessors!")
                #                plt.ioff()  # type: ignore[attr-defined]
                #                self.plot(highlight_nodes=[node])
                #                plt.pause(1)  # type: ignore[attr-defined]
                raise ValueError("Invalid graph structure!")
            if isinstance(node, TGStartBranchParentNode) and succ_count == 0:
                logger.error("Invalid graph structure: " + str(type(node)) + " has no successors!")
                #                plt.ioff()  # type: ignore[attr-defined]
                #                self.plot(highlight_nodes=[node])
                #                plt.pause(1)  # type: ignore[attr-defined]
                raise ValueError("Invalid graph structure!")
            if succ_count < 2 and pred_count < 2:
                continue
            if (succ_count >= 2) and (not isinstance(node, TGStartBranchParentNode)):
                logger.error("Invalid node type: " + str(type(node)) + " with " + str(succ_count) + " successors!")
                #                plt.ioff()  # type: ignore[attr-defined]
                #                self.plot(highlight_nodes=[node])
                #                plt.pause(1)  # type: ignore[attr-defined]
                raise ValueError("Invalid graph structure!")
            if (pred_count >= 2) and (not isinstance(node, TGEndBranchParentNode)):
                logger.error("Invalid node type: " + str(type(node)) + " with " + str(pred_count) + " predecessors!")
                #                plt.ioff()  # type: ignore[attr-defined]
                #                self.plot(highlight_nodes=[node])
                #                plt.pause(1)  # type: ignore[attr-defined]
                raise ValueError("Invalid graph structure!")

    def __add_work_nodes(self) -> None:
        logger.info("Adding work nodes...")
        work_nodes: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if type(node) == TGNode:
                work_nodes.append(node)

        logger.info("--> classify context entry nodes")
        visited: Set[TGNode] = set()
        context_entry_nodes: Set[TGNode] = set()
        for node in progress(work_nodes):
            if node in visited:
                continue

            # create a new context, if the predecessor of node is not a regular work node
            preds = self.get_predecessors(node)
            create_new_context = False
            if len(preds) > 1 or len(preds) == 0 or type(preds[0]) != TGNode or len(self.get_successors(preds[0])) > 1:
                create_new_context = True

            # create a new context if the node contains a function call
            if node.pet_node_id is not None:
                if len(out_edges(self.pet, node.pet_node_id, EdgeType.CALLSNODE)) > 0:
                    create_new_context = True

            # create a new context if a preceeding node contains a function call
            for pred in preds:
                if pred.pet_node_id is not None:
                    if len(out_edges(self.pet, pred.pet_node_id, EdgeType.CALLSNODE)) > 0:
                        create_new_context = True
                        break

            if not create_new_context:
                # node will be handled as part of another context
                visited.add(node)
                continue
            context_entry_nodes.add(node)

        logger.info("--> inserting work start and end nodes...")
        for node in progress(context_entry_nodes):
            # adding work start node
            start_work_node = TGStartWorkNode(node.pet_node_id, node.level, node.position)
            self.add_node(start_work_node)
            for pred in self.get_predecessors(node):
                self.graph.remove_edge(pred, node)
                self.add_edge(pred, start_work_node)
            self.add_edge(start_work_node, node)
            # find work exit.
            # __break_cycles has run by this point, so the successor chain is supposed to be
            # acyclic - but the walk must not depend on that: a single surviving cycle of
            # plain TGNodes would make it loop forever. The visited set bounds it to the
            # number of nodes in the graph.
            last_work_node = node
            visited_work_nodes: Set[TGNode] = {node}
            while True:
                successors = self.get_successors(last_work_node)
                if (
                    len(successors) == 0
                    or len(successors) > 1
                    or type(successors[0]) != TGNode
                    or successors[0] in context_entry_nodes
                ):
                    break
                if successors[0] in visited_work_nodes:
                    logger.warning(
                        "Cycle detected while searching for the work exit of "
                        + str(node)
                        + ". Ending the work region at "
                        + str(last_work_node)
                        + "."
                    )
                    break
                visited_work_nodes.add(successors[0])
                last_work_node = successors[0]
            # insert work end node after last_work_node
            successors = self.get_successors(last_work_node)
            for succ in successors:
                self.graph.remove_edge(last_work_node, succ)
            end_work_node = TGEndWorkNode(last_work_node.pet_node_id, last_work_node.level, last_work_node.position)
            self.add_node(end_work_node)
            self.add_edge(last_work_node, end_work_node)
            for succ in successors:
                self.add_edge(end_work_node, succ)

    def __duplicate_inlined_function(
        self, inlined_function: TGFunctionNode, inlining_pet_node_id: PETNodeID, call_instruction_id: Optional[int]
    ) -> Tuple[TGStartInlinedFunctionNode, TGEndInlinedFunctionNode]:

        # initialize entry and exit nodes
        entry = TGStartInlinedFunctionNode(inlining_pet_node_id, 0, 0, call_instruction_id)
        exit = TGEndInlinedFunctionNode(inlining_pet_node_id, 0, 0)
        self.add_node(entry)
        self.add_node(exit)

        copied_nodes: Dict[TGNode, TGNode] = dict()
        # copied in a deterministic order, which gives the copies deterministic creation indices
        function_body_nodes = sorted(
            self.get_descendants(inlined_function) + [inlined_function], key=self.__pet_node_order
        )
        # copy function body nodes
        for fbn in function_body_nodes:
            fbn_copy = copy.deepcopy(fbn)
            copied_nodes[fbn] = fbn_copy
            self.add_node(fbn_copy)
        # copy function body edges
        for fbn in function_body_nodes:
            for succ in self.get_successors(fbn):
                self.graph.add_edge(copied_nodes[fbn], copied_nodes[succ])

        # connect function body to entry and exit nodes
        self.add_edge(entry, copied_nodes[inlined_function])
        for fbn in function_body_nodes:
            if isinstance(fbn, TGEndFunctionNode) and fbn.pet_node_id == inlined_function.pet_node_id:
                self.add_edge(copied_nodes[fbn], exit)

        return entry, exit

    def __insert_pessimistic_data_dependencies(self) -> None:
        logger.info("Inserting pessimistic data dependencies (between all suitable nodes)...")

        # iterate over all edges in PET Graph
        for source, target, dependency_dict in progress(self.pet.g.edges(data=True)):
            dependency = cast(Dependency, dependency_dict["data"])
            # only consider DATA edges
            if dependency.etype != EdgeType.DATA:
                continue
            # ignore INIT edges
            if dependency.dtype == DepType.INIT:
                continue

            # find all pairs of TGNodes which qualify as source and / or targets of the dependency (Note: due to the duplication of iterations and function inlining, multiple occurrences are possible!)
            source_tg_nodes: List[TGNode] = []
            for node in self.graph.nodes:
                # search for regular nodes (i.e. CU nodes) with the given PET node id
                if type(node) == TGNode and node.pet_node_id is not None:
                    if node.pet_node_id == source:
                        source_tg_nodes.append(node)

            for source_tg in source_tg_nodes:
                # find target nodes for the dependency
                # collect all nodes with matching pet_node_id
                target_tg_nodes: Set[TGNode] = set()
                for node in self.graph.nodes:
                    if node.pet_node_id == target:
                        target_tg_nodes.add(node)

                # register dependency between each pair of source and target nodes
                for target_tg in list(target_tg_nodes):
                    # ignore dependencies within a single context
                    # if source_tg.parent_context == target_tg.parent_context:
                    #    continue
                    for source_parent_ctx in source_tg.parent_context:
                        for target_parent_ctx in target_tg.parent_context:
                            source_parent_ctx.register_outgoing_dependency(target_parent_ctx, dependency)

    def __insert_data_dependencies(self) -> None:
        logger.info("Inserting data dependencies...")

        # iterate over all edges in PET Graph
        for source, target, dependency_dict in progress(self.pet.g.edges(data=True)):
            dependency = cast(Dependency, dependency_dict["data"])
            # only consider DATA edges
            if dependency.etype != EdgeType.DATA:
                continue
            # ignore INIT edges
            if dependency.dtype == DepType.INIT:
                continue

            # find all pairs of TGNodes which qualify as source and / or targets of the dependency (Note: due to the duplication of iterations and function inlining, multiple occurrences are possible!)
            source_tg_nodes: List[TGNode] = []
            for node in self.graph.nodes:
                # search for regular nodes (i.e. CU nodes) with the given PET node id
                if type(node) == TGNode and node.pet_node_id is not None:
                    if node.pet_node_id == source:
                        source_tg_nodes.append(node)

            for source_tg in source_tg_nodes:
                # find target nodes for the dependency
                target_tg_nodes: Set[TGNode] = self.get_closest_predecessors_with_matching_pet_node_id(
                    source_tg,
                    target,
                    disallow_target_contexts=set(),
                    results_per_path=10,
                    # disallow_target_contexts=source_tg.parent_context
                )

                # register dependency between each pair of source and target nodes
                for target_tg in list(target_tg_nodes):
                    # ignore dependencies within a single context
                    if source_tg.parent_context == target_tg.parent_context:
                        continue
                    for source_parent_ctx in source_tg.parent_context:
                        for target_parent_ctx in target_tg.parent_context:
                            source_parent_ctx.register_outgoing_dependency(target_parent_ctx, dependency)

    @staticmethod
    def __line_of_location(location: str, instruction_id_to_line: Dict[str, str]) -> Optional[LineID]:
        """the file_id:line of a location in a dependency file, which is an instruction id or a
        file_id:line, or None if it has no line (e.g. '*')"""
        if ":" not in location:
            mapped = instruction_id_to_line.get(location)
            return LineID(mapped) if mapped is not None else None
        return LineID(":".join(location.split(":")[:2]))

    def __read_dependencies_from_files(
        self, dynamic_dependency_file: Optional[str], static_dependency_file: Optional[str]
    ) -> Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]]:
        """Reads data dependencies from files and returns them in a structured format.
        Format: {dep_type: {source_location: {source_state_id: {sink_location: {sink_state_id:  [var_info]}}}}}
        """

        deps: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]] = (
            dict()
        )  # {dep_type: {source_location: {source_state_id: {sink_location: {sink_state_id:  [var_info]}}}}}

        for idx, dependency_file in enumerate([dynamic_dependency_file, static_dependency_file]):
            if dependency_file is None or not os.path.exists(dependency_file):
                continue
            with open(dependency_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or len(line) == 0:
                        continue
                    if self.ignore_dependency_states:
                        # Drop the callpath state markers before any of them is interpreted below.
                        # Every source/sink then reads as NO_STATE: the dependencies stay dynamic, but
                        # are treated like the records without states (see
                        # __insert_data_dependencies_from_files).
                        line = STATE_MARKER_PATTERN.sub("", line)
                    # split and sanitize line
                    line_split = [elem for elem in line.split(" ") if len(elem) > 0]

                    source_location = line_split[0]
                    del line_split[0]

                    dep_is_dynamic_based_on_source = False

                    # unpack source
                    if "@" in source_location:
                        source_split = source_location.split("@")
                        source_location = source_split[0]
                        source_state_id = source_split[1]
                        dep_is_dynamic_based_on_source = True
                    else:
                        source_state_id = "NO_STATE"

                    # unpack lines
                    while len(line_split) >= 2:
                        current = line_split[0]
                        del line_split[0]

                        if current in ["BGN", "END"]:
                            # skip line
                            break
                        if current == "NOM":
                            # skip token
                            continue
                        # current is a dependency type
                        dep_type = current

                        # read dependency contents
                        dep_contents = line_split[0]
                        del line_split[0]

                        # unpack dep_contents
                        dep_contents_split = dep_contents.split("|")
                        sink_location = dep_contents_split[0]
                        var_info = dep_contents_split[1]

                        # unpack sink_location
                        dep_is_dynamic_based_on_sink = False
                        if "@" in sink_location:
                            sink_location_split = sink_location.split("@")
                            sink_location = sink_location_split[0]
                            sink_state_id = sink_location_split[1]
                            dep_is_dynamic_based_on_sink = True
                        else:
                            sink_state_id = "NO_STATE"

                        # prepend DYN or STAT to the dependency type to distinguish between dynamic and
                        # static dependencies. Every record of the dynamic dependency file was observed
                        # during profiling, whether or not it carries callpath states: the records of
                        # stack variables (hybrid analysis) carry none. Treated as static, they got the
                        # privatisation exemption of static dependencies in the do-all detection.
                        if idx == 0:
                            dep_type = "DYN_" + dep_type
                        else:
                            dep_type = "STAT_" + dep_type

                        # register dependency
                        if dep_type not in deps:
                            deps[dep_type] = dict()
                        if source_location not in deps[dep_type]:
                            deps[dep_type][source_location] = dict()
                        if source_state_id not in deps[dep_type][source_location]:
                            deps[dep_type][source_location][source_state_id] = dict()
                        if sink_location not in deps[dep_type][source_location][source_state_id]:
                            deps[dep_type][source_location][source_state_id][sink_location] = dict()
                        if sink_state_id not in deps[dep_type][source_location][source_state_id][sink_location]:
                            deps[dep_type][source_location][source_state_id][sink_location][sink_state_id] = list()
                        # prevent duplicates
                        if (
                            var_info
                            not in deps[dep_type][source_location][source_state_id][sink_location][sink_state_id]
                        ):
                            deps[dep_type][source_location][source_state_id][sink_location][sink_state_id].append(
                                var_info
                            )
        return deps

    def __apply_dependency_overwrites(
        self, dependencies: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]]
    ) -> Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]]:
        """Checks for more and less specific information in the dependencies.
        Applies overwrites if more specific information is found,
        E.g., if a dependency with a specific source state id exists in addition to one with no source state id.
        In such cases, it is assumed that the dependency with the specific source state id is more accurate and
        thus the dependency with no source state id is removed.
        The same applies for other, but similar cases.
        In step 1, unspecified cases are overwritten by fully and partially specified cases.
        In step 2, partially specified cases are overwritten by fully specified cases.
        Diffrent partially specified cases do not overwrite each other.
        Returns the updated dependencies.
        """

        # step 1: remove unspecified cases if more specific cases exist
        to_be_removed = []
        for dep_type, dep_type_deps in dependencies.items():
            for source_location, source_location_deps in dep_type_deps.items():
                for source_state_id, source_state_deps in source_location_deps.items():
                    for sink_location, sink_location_deps in source_state_deps.items():
                        for sink_state_id, var_infos in sink_location_deps.items():
                            # if the current dependency is at least partially specified, it will not be overwritten in step 1.
                            if source_state_id != "NO_STATE" or sink_state_id != "NO_STATE":
                                # at least partially specified
                                continue
                            # unspecified
                            # check for more specific source_state_id
                            if source_state_id == "NO_STATE":
                                for check_source_state_id, check_source_state_deps in source_location_deps.items():
                                    if check_source_state_id != "NO_STATE":
                                        # check if an entry for sink_state_id exists
                                        for (
                                            check_sink_location,
                                            check_sink_location_deps,
                                        ) in check_source_state_deps.items():
                                            if check_sink_location == sink_location:
                                                for (
                                                    check_sink_state_id,
                                                    check_var_infos,
                                                ) in check_sink_location_deps.items():
                                                    if (
                                                        sink_state_id == "NO_STATE"
                                                        and check_sink_state_id != "NO_STATE"
                                                    ) or (sink_state_id == check_sink_state_id):
                                                        # more specific sink_state_id exists. Mark current dependency for removal and skip to next dependency.
                                                        # DEBUG
                                                        print("step 1 overwrites: ")
                                                        print(
                                                            "-> original: ",
                                                            dep_type,
                                                            source_location,
                                                            source_state_id,
                                                            sink_location,
                                                            sink_state_id,
                                                        )
                                                        print(
                                                            "-> override: ",
                                                            dep_type,
                                                            source_location,
                                                            check_source_state_id,
                                                            sink_location,
                                                            check_sink_state_id,
                                                        )
                                                        # ! DEBUG
                                                        to_be_removed.append(
                                                            (
                                                                dep_type,
                                                                source_location,
                                                                source_state_id,
                                                                sink_location,
                                                                sink_state_id,
                                                            )
                                                        )
                                                        continue
                            # check for more specific sink_state_id
                            if sink_state_id == "NO_STATE":
                                for check_sink_state_id, check_var_infos in sink_location_deps.items():
                                    if check_sink_state_id != "NO_STATE":
                                        # more specific sink_state_id exists. Mark current dependency for removal and skip to next dependency.
                                        # DEBUG
                                        print("step 1 overwrites: ")
                                        print(
                                            "-> original: ",
                                            dep_type,
                                            source_location,
                                            source_state_id,
                                            sink_location,
                                            sink_state_id,
                                        )
                                        print(
                                            "-> override: ",
                                            dep_type,
                                            source_location,
                                            source_state_id,  # the overriding entry differs in its sink state only
                                            sink_location,
                                            check_sink_state_id,
                                        )
                                        # ! DEBUG
                                        to_be_removed.append(
                                            (dep_type, source_location, source_state_id, sink_location, sink_state_id)
                                        )
                                        continue
        # remove overwritten less specific dependencies
        for dep_type, source_location, source_state_id, sink_location, sink_state_id in to_be_removed:
            if (
                dep_type in dependencies
                and source_location in dependencies[dep_type]
                and source_state_id in dependencies[dep_type][source_location]
                and sink_location in dependencies[dep_type][source_location][source_state_id]
                and sink_state_id in dependencies[dep_type][source_location][source_state_id][sink_location]
            ):
                del dependencies[dep_type][source_location][source_state_id][sink_location][sink_state_id]
                # clean up empty dictionaries
                if len(dependencies[dep_type][source_location][source_state_id][sink_location]) == 0:
                    del dependencies[dep_type][source_location][source_state_id][sink_location]
                if len(dependencies[dep_type][source_location][source_state_id]) == 0:
                    del dependencies[dep_type][source_location][source_state_id]
                if len(dependencies[dep_type][source_location]) == 0:
                    del dependencies[dep_type][source_location]
                if len(dependencies[dep_type]) == 0:
                    del dependencies[dep_type]

        # step 2: remove partially specified cases if fully specified cases exist
        to_be_removed.clear()
        for dep_type, dep_type_deps in dependencies.items():
            for source_location, source_location_deps in dep_type_deps.items():
                for source_state_id, source_state_deps in source_location_deps.items():
                    for sink_location, sink_location_deps in source_state_deps.items():
                        for sink_state_id, var_infos in sink_location_deps.items():
                            # if the current dependency is fully specified, it will not be overwritten.
                            if source_state_id != "NO_STATE" and sink_state_id != "NO_STATE":
                                # fully specified
                                continue
                            # partially specified
                            # check for more specific source_state_id
                            if source_state_id == "NO_STATE":
                                for check_source_state_id, check_source_state_deps in source_location_deps.items():
                                    if check_source_state_id != "NO_STATE":
                                        # check if an entry for sink_state_id exists
                                        for (
                                            check_sink_location,
                                            check_sink_location_deps,
                                        ) in check_source_state_deps.items():
                                            if check_sink_location == sink_location:
                                                for (
                                                    check_sink_state_id,
                                                    check_var_infos,
                                                ) in check_sink_location_deps.items():
                                                    if sink_state_id == check_sink_state_id:
                                                        # more specific sink_state_id exists. Mark current dependency for removal and skip to next dependency.
                                                        # DEBUG
                                                        print("step 2 overwrites: ")
                                                        print(
                                                            "-> original: ",
                                                            dep_type,
                                                            source_location,
                                                            source_state_id,
                                                            sink_location,
                                                            sink_state_id,
                                                        )
                                                        print(
                                                            "-> override: ",
                                                            dep_type,
                                                            source_location,
                                                            check_source_state_id,
                                                            sink_location,
                                                            check_sink_state_id,
                                                        )
                                                        # ! DEBUG
                                                        to_be_removed.append(
                                                            (
                                                                dep_type,
                                                                source_location,
                                                                source_state_id,
                                                                sink_location,
                                                                sink_state_id,
                                                            )
                                                        )
                                                        continue
                            # check for more specific sink_state_id
                            if sink_state_id == "NO_STATE" and source_state_id != "NO_STATE":
                                for check_sink_state_id, check_var_infos in sink_location_deps.items():
                                    if check_sink_state_id != "NO_STATE":
                                        # more specific sink_state_id exists. Mark current dependency for removal and skip to next dependency.
                                        # DEBUG
                                        print("step 2 overwrites: ")
                                        print(
                                            "-> original: ",
                                            dep_type,
                                            source_location,
                                            source_state_id,
                                            sink_location,
                                            sink_state_id,
                                        )
                                        print(
                                            "-> override: ",
                                            dep_type,
                                            source_location,
                                            source_state_id,  # the overriding entry differs in its sink state only
                                            sink_location,
                                            check_sink_state_id,
                                        )
                                        # ! DEBUG
                                        to_be_removed.append(
                                            (dep_type, source_location, source_state_id, sink_location, sink_state_id)
                                        )
                                        continue
        # remove overwritten less specific dependencies
        for dep_type, source_location, source_state_id, sink_location, sink_state_id in to_be_removed:
            if (
                dep_type in dependencies
                and source_location in dependencies[dep_type]
                and source_state_id in dependencies[dep_type][source_location]
                and sink_location in dependencies[dep_type][source_location][source_state_id]
                and sink_state_id in dependencies[dep_type][source_location][source_state_id][sink_location]
            ):
                del dependencies[dep_type][source_location][source_state_id][sink_location][sink_state_id]
                # clean up empty dictionaries
                if len(dependencies[dep_type][source_location][source_state_id][sink_location]) == 0:
                    del dependencies[dep_type][source_location][source_state_id][sink_location]
                if len(dependencies[dep_type][source_location][source_state_id]) == 0:
                    del dependencies[dep_type][source_location][source_state_id]
                if len(dependencies[dep_type][source_location]) == 0:
                    del dependencies[dep_type][source_location]
                if len(dependencies[dep_type]) == 0:
                    del dependencies[dep_type]
        return dependencies

    def __get_state_mappings_from_file(self, dynamic_dependency_file: str) -> Dict[str, List[str]]:
        """Returns a dictionary mapping state ids to callpaths. Contained elements are filtered to only include these states which are used in dynamic_dependency_file."""
        warnings.warn(
            "TODO: stateID to callpath mapping might get really big. Implement this more scalable / resilient."
        )
        # collect used state ids from dynamic_dependency_file.
        # both source and sink state ids are looked up during dependency insertion
        # (see __insert_data_dependencies_from_files), so both have to be collected here.
        deps = self.__read_dependencies_from_files(dynamic_dependency_file, None)
        used_state_ids: Set[str] = set()
        for dep_type, dep_type_deps in deps.items():
            for source_location, source_location_deps in dep_type_deps.items():
                for source_state_id, source_state_deps in source_location_deps.items():
                    used_state_ids.add(source_state_id)
                    for sink_location, sink_location_deps in source_state_deps.items():
                        for sink_state_id, var_infos in sink_location_deps.items():
                            used_state_ids.add(sink_state_id)
        # print("SEEN_STATE_IDS: ", used_state_ids)
        # delete deps to free memory
        del deps

        state_mappings_file = os.path.join(Path(str(dynamic_dependency_file)).parent, "stateID_to_callpath_mapping.txt")
        if not os.path.exists(state_mappings_file):
            return dict()

        # The profiler writes the callpaths as a prefix tree, one node per line in the format
        # "<state_id> <parent_state_id> <label>" (see DiscoPoP::save_enumerated_paths). The root
        # node references itself as its parent and carries no callpath label. Lines are emitted in
        # nondeterministic order (the writer accumulates them via an OpenMP reduction), so the tree
        # has to be read in full before any callpath can be reconstructed.
        prefix_tree: Dict[str, Tuple[str, str]] = dict()  # {state_id: (parent_state_id, label)}
        with open(state_mappings_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or len(line) == 0:
                    continue
                line_split = [elem for elem in line.split(" ") if len(elem) > 0]
                if len(line_split) < 3:
                    continue
                state_id = line_split[0]
                parent_state_id = line_split[1]
                # labels are not supposed to contain spaces, join defensively.
                # they repeat heavily across states (function names, call markers), so intern them.
                label = sys.intern(" ".join(line_split[2:]))
                prefix_tree[state_id] = (parent_state_id, label)
        if len(prefix_tree) == 0:
            warnings.warn(
                "No callpaths could be read from " + state_mappings_file + ". "
                "Expected the prefix tree format '<state_id> <parent_state_id> <label>'. "
                "State ids will not be assigned, which suppresses data dependencies."
            )

        # resolved caches the callpaths of the visited states' ancestors, so states sharing a prefix
        # walk it only once. It is deliberately not merged into the returned dictionary, as that
        # would re-introduce the unused states which used_state_ids filters out.
        resolved: Dict[str, List[str]] = dict()

        def resolve(state_id: str) -> List[str]:
            """reconstructs the callpath of state_id, ordered from the root to the state itself."""
            # walk upwards until the root, an already resolved ancestor or an unknown state is hit
            pending: List[Tuple[str, str]] = []  # [(state_id, label)], ordered from state_id upwards
            visited: Set[str] = set()
            callpath: List[str] = []
            current = state_id
            hit_cycle = False
            while True:
                if current in visited:
                    # self reference / cycle in malformed input. the walk has to be cut here, and
                    # the cut lands wherever the walk happened to start, so the resulting callpath
                    # is specific to state_id and must not be cached for the states passed on the
                    # way (see below).
                    hit_cycle = True
                    break
                visited.add(current)
                if current in resolved:
                    callpath = resolved[current]
                    break
                if current not in prefix_tree:
                    # unknown ancestor (e.g. truncated mapping file). treat it as the root.
                    break
                parent_state_id, label = prefix_tree[current]
                if parent_state_id == current:
                    # the root references itself and carries no callpath label
                    break
                pending.append((current, label))
                current = parent_state_id
            # walk back down, caching the callpath of every state passed along the way. Callpaths
            # cut short by a cycle are not cached: caching them would hand a state the prefix of
            # whichever walk reached it first, making the result depend on the order in which the
            # states are resolved (used_state_ids is a set, so that order varies per process).
            for pending_state_id, pending_label in reversed(pending):
                callpath = callpath + [pending_label]
                if not hit_cycle:
                    resolved[pending_state_id] = callpath
            return callpath

        # create state_mappings_dict
        state_mappings_dict: Dict[str, List[str]] = dict()  # {stateID: callpath}
        for state_id in used_state_ids:
            if state_id not in prefix_tree:
                continue
            callpath = resolve(state_id)
            if len(callpath) == 0:
                # the root state does not describe a callpath
                continue
            state_mappings_dict[state_id] = callpath
        return state_mappings_dict

    # one frame of a callpath signature: (function name, call instruction id the function was entered
    # through (None for a root function), ((loop position, iteration ids), ...) of the active loops)
    _SignatureFrame = Tuple[str, Optional[int], Tuple[Tuple[int, Tuple[int, ...]], ...]]

    def __context_signature(
        self, ctx: Context, cache: Dict[Context, Optional[Tuple[_SignatureFrame, ...]]]
    ) -> Optional[Tuple[_SignatureFrame, ...]]:
        """The callpath a context lies on, read from its parent_context chain: the functions (entered
        through which call instruction) and, per function, the loop positions it lies inside of, with
        the iteration ids of the IterationContext the chain passes. A loop the chain enters without
        passing one of its iterations (the loop header) runs in every iteration bucket, so it gets
        the ids (0, 1, 2). None if the chain does not start at a FunctionContext (detached context)."""
        chain: List[Context] = []
        current: Optional[Context] = ctx
        while current is not None and current not in cache:
            chain.append(current)
            current = current.parent_context
            if len(chain) > 100000:
                # cyclic parent relation, see __break_containment_cycles
                return None
        signature: Optional[Tuple[TaskGraph._SignatureFrame, ...]] = () if current is None else cache[current]
        # remembers the call instruction of an InlinedFunctionContext until its FunctionContext
        pending_call: Optional[int] = None
        if current is not None and isinstance(current, InlinedFunctionContext):
            pending_call = current.call_instruction_id
        for element in reversed(chain):
            if signature is not None:
                if isinstance(element, FunctionContext):
                    if element.parent_function is None:
                        raise ValueError("parent_function is None!")
                    signature = signature + ((self.pet.node_at(element.parent_function).name, pending_call, ()),)
                    pending_call = None
                elif isinstance(element, InlinedFunctionContext):
                    pending_call = element.call_instruction_id
                elif type(element) is Context and element.parent_context is None:
                    # the root context, above the contexts of the functions
                    pass
                elif len(signature) == 0:
                    # the chain has to start at a function
                    signature = None
                elif isinstance(element, LoopParentContext) and element.loopstate_position is not None:
                    signature = self.__with_loop(signature, element.loopstate_position, (0, 1, 2))
                elif (
                    isinstance(element, IterationContext)
                    and isinstance(element.parent_context, LoopParentContext)
                    and element.parent_context.loopstate_position is not None
                ):
                    signature = self.__with_loop(
                        signature,
                        element.parent_context.loopstate_position,
                        tuple(sorted(element.loopstate_iteration_ids)),
                    )
            cache[element] = signature
        return signature

    @staticmethod
    def __with_loop(
        signature: Tuple[_SignatureFrame, ...], loopstate_position: int, ids: Tuple[int, ...]
    ) -> Tuple[_SignatureFrame, ...]:
        """signature, with the loop at loopstate_position of its innermost frame set to ids."""
        name, call, loops = signature[-1]
        updated = dict(loops)
        updated[loopstate_position] = ids
        return signature[:-1] + ((name, call, tuple(sorted(updated.items()))),)

    @staticmethod
    def _callpath_frames(callpath: List[str]) -> Optional[List[Tuple[str, Optional[int], Dict[int, int]]]]:
        """The frames of a profiler callpath: (function name, call instruction id it was entered
        through, {loop position: iteration bucket} of its active loops). Successive loopstate entries
        of a frame are transitions, the last one is the current state. None if the callpath is
        malformed (a loopstate of another function than the current frame's)."""
        frames: List[Tuple[str, Optional[int], Dict[int, int]]] = []
        pending_call: Optional[int] = None
        for entry in callpath:
            if entry.startswith("call_") and entry[5:].isdigit():
                pending_call = int(entry[5:])
                continue
            if "_loopstate" in entry:
                function_name, _, digits = entry.rpartition("_loopstate")
                if digits.isdigit():
                    if len(frames) == 0 or frames[-1][0] != function_name:
                        return None
                    frames[-1] = (
                        frames[-1][0],
                        frames[-1][1],
                        {position: int(digit) for position, digit in enumerate(digits) if digit in "012"},
                    )
                    continue
            frames.append((entry, pending_call, {}))
            pending_call = None
        return frames

    @staticmethod
    def __carried_frame_and_position(
        source_frames: List[Tuple[str, Optional[int], Dict[int, int]]],
        sink_frames: List[Tuple[str, Optional[int], Dict[int, int]]],
    ) -> Optional[Tuple[int, int]]:
        """(frame index counted from the outermost frame, loop position) of the loop a dependency
        between two callpath states crosses: the first loop, from the outermost frame on, which is
        active in both states with different iteration buckets. Different buckets mean different
        iterations; equal buckets are taken as the same iteration. None if the callpaths part
        before such a loop is found (different calls, or a loop active in only one of them).
        Both callpaths agree up to that frame, so the index is valid in both."""
        for index, ((name, call, buckets), (other_name, other_call, other_buckets)) in enumerate(
            zip(source_frames, sink_frames)
        ):
            if name != other_name or (index > 0 and call != other_call):
                return None
            for position in sorted(set(buckets) | set(other_buckets)):
                if position not in buckets or position not in other_buckets:
                    # a loop active in one of them only: the ends are not in one execution of it
                    return None
                if buckets[position] != other_buckets[position]:
                    return index, position
        return None

    def __loop_context_at(self, ctx: Context, function_name: str, loopstate_position: int) -> object:
        """The LoopParentContext on the chain of ctx for the loop at loopstate_position of the
        closest enclosing copy of function_name, or CARRIED_OUTSIDE if the chain does not reach
        that function (a standalone copy of a function) or the loop has no context there.

        The frame is found by its function rather than by counting frames: the profiler cuts the
        callpath at a recursive call, so a state of a recursive function stands for every recursion
        level, while the TaskGraph inlines several of them. A function occurs at most once on a
        callpath of the profiler, so the closest copy of it is the frame of the callpath."""
        current: Optional[Context] = ctx
        candidate: Optional[LoopParentContext] = None
        steps = 0
        while current is not None and steps < 100000:
            if isinstance(current, FunctionContext):
                if (
                    current.parent_function is not None
                    and self.pet.node_at(current.parent_function).name == function_name
                ):
                    return candidate if candidate is not None else CARRIED_OUTSIDE
                candidate = None
            elif (
                candidate is None
                and isinstance(current, LoopParentContext)
                and current.loopstate_position == loopstate_position
            ):
                # the innermost loop at that position of the frame (walking upwards, the loops of
                # a frame are found before its FunctionContext)
                candidate = current
            current = current.parent_context
            steps += 1
        return CARRIED_OUTSIDE

    # orders of the two instructions of a record without states, see __stateless_record_order
    _STATELESS_CARRIED = "carried"
    _STATELESS_FORWARD = "forward"

    @staticmethod
    def __stateless_record_order(later_location: str, earlier_location: str) -> Optional[str]:
        """How the instructions of a dynamic record without callpath states are ordered. The first
        column of a record is the later access, the second one the earlier access. Instruction ids
        are assigned in the order of the instructions in the function's basic block layout, which
        is the source order of the loop bodies (condition, body, increment). If the earlier access
        does not come before the later one in that order, the record has to cross iterations of a
        loop containing both (_STATELESS_CARRIED). Otherwise it is taken as a dependency within one
        iteration (_STATELESS_FORWARD); this misses a value carried over iterations past a write
        before the read that is not executed in every iteration (e.g. a conditional write). None if
        the ends are no instruction ids."""
        if not later_location.isdigit() or not earlier_location.isdigit():
            return None
        if int(earlier_location) >= int(later_location):
            return TaskGraph._STATELESS_CARRIED
        return TaskGraph._STATELESS_FORWARD

    @staticmethod
    def __common_loop(
        first: Context, second: Context, chain_cache: Dict[Context, List[Context]]
    ) -> Tuple[Optional[LoopParentContext], bool]:
        """(the innermost LoopParentContext containing both contexts, whether they lie in different
        iteration copies of it). A context in the loop's header lies in no iteration copy."""

        def chain(ctx: Context) -> List[Context]:
            cached = chain_cache.get(ctx)
            if cached is None:
                cached = []
                current: Optional[Context] = ctx
                while current is not None and len(cached) < 100000:
                    cached.append(current)
                    current = current.parent_context
                chain_cache[ctx] = cached
            return cached

        first_chain = chain(first)
        second_chain = chain(second)
        second_index = {ctx: index for index, ctx in enumerate(second_chain)}
        for first_position, ctx in enumerate(first_chain):
            if ctx not in second_index:
                continue
            # ctx is the closest common ancestor
            crosses = (
                isinstance(ctx, LoopParentContext)
                and first_position > 0
                and second_index[ctx] > 0
                and isinstance(first_chain[first_position - 1], IterationContext)
                and isinstance(second_chain[second_index[ctx] - 1], IterationContext)
            )
            for outer in first_chain[first_position:]:
                if isinstance(outer, LoopParentContext):
                    return outer, crosses
            return None, crosses
        return None, False

    def __loop_node_of_entry(self, entry: PETNodeID) -> Optional[LoopNode]:
        """the LoopNode of a loop, given by its entry CU (LoopParentContext.parent_loop), or None"""
        if entry is None or entry not in self.pet.g:
            return None
        node = self.pet.node_at(entry)
        if isinstance(node, LoopNode):
            return node
        for source, _, _ in in_edges(self.pet, node.id, EdgeType.CHILD):
            parent = self.pet.node_at(source)
            if isinstance(parent, LoopNode) and parent.file_id == node.file_id and parent.start_line == node.start_line:
                return parent
        return None

    @staticmethod
    def __file_and_line(line: Optional[LineID]) -> Optional[Tuple[int, int]]:
        if line is None or ":" not in line:
            return None
        file_id, _, line_number = str(line).partition(":")
        if not file_id.isdigit() or not line_number.isdigit():
            return None
        return int(file_id), int(line_number)

    def __innermost_loop_containing(self, first: Optional[LineID], second: Optional[LineID]) -> object:
        """the innermost LoopNode whose lines contain both lines, None if there is none, or
        _NO_LOOP_NODES if the PET has no LoopNodes at all (then the loop is taken from the contexts,
        see __stateless_carrying_loops)"""
        loops = self._loop_nodes_by_size
        if loops is None:
            loops = sorted(all_nodes(self.pet, type=LoopNode), key=lambda n: (n.end_line - n.start_line, str(n.id)))
            self._loop_nodes_by_size = loops
        if len(loops) == 0:
            return TaskGraph._NO_LOOP_NODES
        first_position = self.__file_and_line(first)
        second_position = self.__file_and_line(second)
        if first_position is None or second_position is None or first_position[0] != second_position[0]:
            return None
        for loop in loops:  # innermost first
            if int(loop.file_id) != first_position[0]:
                continue
            if (
                loop.start_line <= first_position[1] <= loop.end_line
                and loop.start_line <= second_position[1] <= loop.end_line
            ):
                return loop
        return None

    # see __innermost_loop_containing
    _NO_LOOP_NODES = object()
    # the LoopNodes of the PET, smallest first, see __innermost_loop_containing
    _loop_nodes_by_size: Optional[List[LoopNode]] = None

    def __stateless_carrying_loops(
        self, first: Context, second: Context, innermost_loop: object, chain_cache: Dict[Context, List[Context]]
    ) -> Optional[List[LoopParentContext]]:
        """The loops of the function frame of two contexts which a record without states between
        them can cross, innermost first: the copy of innermost_loop (see __innermost_loop_containing)
        containing both and the loops around it, up to the function. None if the contexts do not lie
        in one copy of innermost_loop. [] if no loop contains both ends."""
        self.__common_loop(first, second, chain_cache)  # fills the chains of both into chain_cache
        first_chain = chain_cache[first]
        second_members = set(chain_cache[second])
        common_index = next((i for i, ctx in enumerate(first_chain) if ctx in second_members), None)
        if common_index is None:
            return None
        loops: List[LoopParentContext] = []
        for ctx in first_chain[common_index:]:
            if isinstance(ctx, FunctionContext):
                break
            if isinstance(ctx, LoopParentContext):
                loops.append(ctx)
        if innermost_loop is TaskGraph._NO_LOOP_NODES:
            return loops
        if innermost_loop is None:
            return []
        if len(loops) == 0 or self.__loop_node_of_entry(loops[0].parent_loop) is not innermost_loop:
            return None
        return loops

    def __blamed_loops(
        self,
        carrying: List[LoopParentContext],
        var_name: str,
        memory_region: Optional[MemoryRegion],
        write_lines: Dict[Tuple[str, Optional[MemoryRegion]], Set[Tuple[int, int]]],
    ) -> List[LoopParentContext]:
        """The loops a record without states, carried by the loop carrying[0], is taken to cross:
        that loop, and the loops around it unless the variable is set again before the inner loop
        in every iteration of the outer one - it is an induction variable of the inner loop
        (initialized by the for statement), or it is written in the outer loop on a line before the
        inner loop. Without the states, which iterations of the outer loops the ends lie in is
        unknown, so the outer loops are blamed otherwise (e.g. `for i { for j { sum += a; } }`).
        A write executed only in some iterations is taken as one executed in all of them."""
        if len(carrying) == 0:
            return []
        blamed = [carrying[0]]
        for inner, outer in zip(carrying, carrying[1:]):
            inner_node = self.__loop_node_of_entry(inner.parent_loop)
            outer_node = self.__loop_node_of_entry(outer.parent_loop)
            if inner_node is not None and var_name in inner_node.loop_indices:
                break
            if (
                inner_node is not None
                and outer_node is not None
                and any(
                    file_id == int(inner_node.file_id) and outer_node.start_line <= line < inner_node.start_line
                    for file_id, line in write_lines.get((var_name, memory_region), set())
                )
            ):
                break
            blamed.append(outer)
        return blamed

    def __write_lines_of_variables(
        self,
        dependencies: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]],
        instruction_id_to_line: Dict[str, str],
    ) -> Dict[Tuple[str, Optional[MemoryRegion]], Set[Tuple[int, int]]]:
        """the (file id, line) pairs each variable of the dynamic records is written on"""
        result: Dict[Tuple[str, Optional[MemoryRegion]], Set[Tuple[int, int]]] = {}
        # which column of a record holds a write: (first, second), the first column being the later access
        writes_by_type = {
            "DYN_RAW": (False, True),
            "DYN_WAR": (True, False),
            "DYN_WAW": (True, True),
            "DYN_INIT": (True, False),
        }
        for dep_type, (first_writes, second_writes) in writes_by_type.items():
            for first_location, first_location_deps in dependencies.get(dep_type, {}).items():
                first_line = self.__file_and_line(self.__line_of_location(first_location, instruction_id_to_line))
                for first_state_deps in first_location_deps.values():
                    for second_location, second_location_deps in first_state_deps.items():
                        second_line = self.__file_and_line(
                            self.__line_of_location(second_location, instruction_id_to_line)
                        )
                        for var_infos in second_location_deps.values():
                            for var_info in var_infos:
                                key = (
                                    var_info.split("(")[0],
                                    MemoryRegion(var_info.split("(")[1].strip(")")) if "(" in var_info else None,
                                )
                                if first_writes and first_line is not None:
                                    result.setdefault(key, set()).add(first_line)
                                if second_writes and second_line is not None:
                                    result.setdefault(key, set()).add(second_line)
        return result

    @staticmethod
    def __contexts_matching_frames(
        index: Dict[
            Tuple[Tuple[str, Optional[int], Tuple[int, ...]], ...],
            List[Tuple[Context, Tuple[_SignatureFrame, ...]]],
        ],
        frames: List[Tuple[str, Optional[int], Dict[int, int]]],
    ) -> List[Context]:
        """The indexed contexts whose signature is frames: the same functions, call instructions
        and active loops, and iterations containing the bucket of every active loop."""
        key = tuple((name, call, tuple(sorted(buckets))) for name, call, buckets in frames)
        return [
            ctx
            for ctx, signature in index.get(key, [])
            if all(
                bucket in dict(loops)[position]
                for (_, _, buckets), (_, _, loops) in zip(frames, signature)
                for position, bucket in buckets.items()
            )
        ]

    def __assign_state_ids(self, dynamic_dependency_file: Optional[str]) -> None:
        """attaches the callpath states of the profiler to the contexts they describe.

        A state is attached to the FunctionContext (no loop of the innermost function active) or the
        IterationContext (of the innermost active loop) whose signature (see __context_signature)
        is the state's callpath: the same functions entered through the same call instructions, the
        same active loops, and iterations whose ids contain the state's iteration bucket of every
        active loop. The contexts are indexed by their signature once, so the result is independent
        of the order of the contexts and consistent with the consumers, which read the states along
        the parent_context chain (Context.get_state_ids)."""
        if dynamic_dependency_file is None:
            raise ValueError("Invalid Path!")
        state_mappings_dict = self.__get_state_mappings_from_file(dynamic_dependency_file)

        logger.info("Assigning state ids to nodes...")
        # {((function name, call id, active loop positions) per frame): [(context, its signature)]}
        index: Dict[
            Tuple[Tuple[str, Optional[int], Tuple[int, ...]], ...],
            List[Tuple[Context, Tuple[TaskGraph._SignatureFrame, ...]]],
        ] = {}
        signature_cache: Dict[Context, Optional[Tuple[TaskGraph._SignatureFrame, ...]]] = {}
        for ctx in self.__collect_all_contexts():
            if not isinstance(ctx, (FunctionContext, IterationContext)):
                continue
            signature = self.__context_signature(ctx, signature_cache)
            if signature is None or len(signature) == 0:
                continue
            if isinstance(ctx, IterationContext) and len(signature[-1][2]) == 0:
                # an iteration outside of every loop of its function: no loop state can describe it
                continue
            if isinstance(ctx, FunctionContext) and len(signature[-1][2]) != 0:
                continue
            key = tuple((name, call, tuple(position for position, _ in loops)) for name, call, loops in signature)
            index.setdefault(key, []).append((ctx, signature))

        observed = 0
        assigned = 0
        approximate = 0
        too_deep = 0
        ambiguous = 0
        self.approximately_assigned_state_ids = set()
        for state_id in sorted(state_mappings_dict, key=int):
            callpath = state_mappings_dict[state_id]
            # a callpath ending with a call element describes the call instruction itself
            if len(callpath) == 0 or (callpath[-1].startswith("call_") and callpath[-1][5:].isdigit()):
                continue
            frames = self._callpath_frames(callpath)
            if frames is None:
                continue
            observed += 1
            matches = self.__contexts_matching_frames(index, frames)
            if len(matches) == 0:
                if len(frames) - 1 >= self.CALL_PATH_LIMIT:  # more calls than inlined
                    too_deep += 1
                # fallback: the longest suffix of the callpath which starts at the standalone copy
                # of a function (the contexts of a function not inlined anywhere, i.e. "called from
                # somewhere"). Covers callpaths deeper than the inlining and calls whose inlined
                # copy is missing. The dependencies of the state then lose the distinction of the
                # outer calling contexts, which over-approximates them.
                for start in range(1, len(frames)):
                    name, _, buckets = frames[start]
                    matches = self.__contexts_matching_frames(index, [(name, None, buckets)] + frames[start + 1 :])
                    if len(matches) > 0:
                        break
                if len(matches) == 0:
                    continue
                approximate += 1
                self.approximately_assigned_state_ids.add(int(state_id))
            else:
                assigned += 1
            if len(matches) > 1:
                # two copies of one context: a structural error of the TaskGraph, or the copies of a
                # block reached through different paths of a short-circuit condition. Attaching the
                # state to all of them over-approximates the dependencies, which is the safe direction.
                ambiguous += 1
            for ctx in matches:
                ctx.state_ids.append(int(state_id))
        logger.info(
            "Assigned "
            + str(assigned)
            + " of "
            + str(observed)
            + " callpath states to contexts, "
            + str(approximate)
            + " more to the standalone copy of a function on their callpath ("
            + str(too_deep)
            + " unassigned states are deeper than the call inlining limit, "
            + str(ambiguous)
            + " states match several contexts)"
        )
        self.state_assignment_statistics = {
            "observed": observed,
            "assigned": assigned,
            "approximate": approximate,
            "too_deep": too_deep,
            "ambiguous": ambiguous,
        }

    #     def __old_assign_state_ids(self, dynamic_dependency_file: Optional[str]) -> None:
    #         """attaches state ids to Context nodes."""
    #         # read stateID to callpath mapping
    #         state_mappings_dict = self.__get_state_mappings_from_file(dynamic_dependency_file)
    #         print("state_mappings_dict: ")
    #         for state_id in state_mappings_dict:
    #             print("->", state_id, " -> ", state_mappings_dict[state_id])
    #
    #         # assign state id to task_graph nodes
    #         logger.info("Assigning state ids to nodes...")
    #         for state_id in progress(state_mappings_dict):
    #             print()
    #             print("Parsing state_id: ", state_id)
    #             # skip invalid states
    #             if (
    #                 len(state_mappings_dict[state_id]) > 0
    #                 and state_mappings_dict[state_id][-1].startswith("call_")
    #                 and state_mappings_dict[state_id][-1].split("call_")[1].isdigit()
    #             ):
    #                 # skip state ending with call
    #                 print("--> skip due to last element being a call.")
    #                 continue
    #             # search for first match along each path and set the state_id
    #             queue: List[Tuple[TGNode, list[str]]] = [
    #                 (self.root, state_mappings_dict[state_id])
    #             ]  # queue necessary to handle branching
    #             while len(queue) > 0:
    #                 current_node, remaining_path = queue.pop()
    #                 # cleanup remaining_path (remove leading call_<int> markers)
    #                 while (
    #                     len(remaining_path) > 0
    #                     and remaining_path[0].startswith("call_")
    #                     and remaining_path[0].split("call_")[1].isdigit()
    #                 ):
    #                     del remaining_path[0]
    #                 # cleanup remaining_path (compress multiple successive loopstates)
    #                 if len(remaining_path) > 0:
    #                     loopstate_indices: List[int] = []
    #                     for idx in range(0, len(remaining_path)):
    #                         if "_loopstate" in remaining_path[idx]:
    #                             loopstate_indices.append(idx)
    #                     to_be_removed: List[int] = []
    #                     for idx, val in enumerate(loopstate_indices):
    #                         if idx >= len(loopstate_indices) - 1:
    #                             continue
    #                         # check next registered loopstate info is a direct successor of the current one.
    #                         # if so, the current enty can be omitted
    #                         if val + 1 == loopstate_indices[idx + 1]:
    #                             to_be_removed.append(val)
    #                     for tbr in sorted(to_be_removed, reverse=True):
    #                         del remaining_path[tbr]
    #
    #                 print("candidate: ", current_node, "remaining path:", remaining_path)
    #
    #                 if len(remaining_path) == 0:
    #                     # end of search along this path
    #                     continue
    #
    #                 # check if current_node qualifies for a state hit.
    #                 is_candidate = isinstance(current_node, TGFunctionNode) or isinstance(
    #                     current_node, TGStartIterationNode
    #                 )
    #
    #                 if is_candidate:
    #                     # check for potential hit
    #                     print("remaining_path[0]: ", remaining_path)
    #                     if isinstance(current_node, TGFunctionNode):
    #                         # cleanup leading loopstate
    #                         while (
    #                             len(remaining_path) > 0
    #                             and "_loopstate" in remaining_path[0]
    #                             and remaining_path[0].split("_loopstate")[1].isdigit()
    #                         ):
    #                             del remaining_path[0]
    #
    #                         if len(remaining_path) == 0:
    #                             continue
    #
    #                         if cast(TGFunctionNode, current_node).get_pet_node(self.pet).name == remaining_path[0]:
    #                             # hit
    #                             del remaining_path[0]
    #                             if len(remaining_path) == 0:
    #                                 if current_node.state_id is not None:
    #                                     # keep longer path
    #                                     if len(state_mappings_dict[state_id]) > len(
    #                                         state_mappings_dict[current_node.state_id]
    #                                     ):
    #                                         pass
    #                                     else:
    #                                         print(
    #                                             "Skipped overwrite: "
    #                                             + str(current_node.state_id)
    #                                             + " with "
    #                                             + str(state_id)
    #                                         )
    #                                         continue
    #                                 current_node.state_id = state_id
    #                                 print("set state_id: ", state_id, " to node: ", current_node)
    #                                 # hit. stop search along this path
    #                                 continue
    #                         else:
    #                             # not a hit. stop search along this path.
    #                             warnings.warn(
    #                                 "WARN 0: State_id: "
    #                                 + str(state_id)
    #                                 + " could not be assigned to a node."
    #                                 #                                + "\nPath: "
    #                                 #                                + str(state_mappings_dict[state_id])
    #                             )
    #                             continue
    #                     elif isinstance(current_node, TGStartIterationNode):
    #                         if not "_loopstate" in remaining_path[0]:
    #                             # not a hit. stop search along this path.
    #                             warnings.warn(
    #                                 "WARN 1: State_id: "
    #                                 + str(state_id)
    #                                 + " could not be assigned to a node."
    #                                 #                                + "\nPath: "
    #                                 #                                + str(state_mappings_dict[state_id])
    #                             )
    #                             print("queue len: ", len(queue))
    #                             continue
    #                         else:
    #                             # check for matching loopstate id
    #                             # get current loopstate_info
    #                             loopstate_info = remaining_path[0].split("_loopstate")[1]
    #                             # get loopstate_position
    #                             print("parentCTX: ", cast(TGStartIterationNode, current_node).parent_context)
    #                             parent_ctxs = cast(TGStartIterationNode, current_node).parent_context
    #                             if len(parent_ctxs) == 0:
    #                                 continue
    #                             iter_ctx = cast(IterationContext, list(parent_ctxs)[0])
    #                             if iter_ctx.parent_context is None:
    #                                 continue
    #                             parent_loop_ctx = cast(LoopParentContext, iter_ctx.parent_context)
    #                             loopstate_position = parent_loop_ctx.loopstate_position
    #                             print("loopstate position: ", loopstate_position)
    #                             print(
    #                                 "loopstate iteration ids: ",
    #                                 cast(
    #                                     IterationContext, cast(TGStartIterationNode, current_node)
    #                                 ).loopstate_iteration_ids,
    #                             )
    #                             print("loopstate_info: ", loopstate_info)
    #                             # if loopstate_iteraton at the current index is 3, the loop should not be entered. Some mismatch occured
    #                             if loopstate_info[loopstate_position] == "3":
    #                                 # continue search with successors of current loop
    #                                 if parent_loop_ctx.successor is None:
    #                                     continue
    #                                 for succ_node in parent_loop_ctx.successor.contained_nodes:
    #                                     queue.append((succ_node, remaining_path))
    #                                 print("-> Skipped loop body due to loopstate 3")
    #                                 continue
    #
    #                             # find the IterationContext child of the parent_loop_ctx which matches the loopstate_iteration at the current index. Proceed processing there to skip previous iteration bodies.
    #                             if int(loopstate_info[loopstate_position]) in loopstate_indices:
    #                                 # iter_ctx targets current loopstate. nothing to do.
    #                                 pass
    #                             else:
    #                                 # check next loop iteration
    #                                 if iter_ctx.successor is not None:
    #                                     if isinstance(iter_ctx.successor, IterationContext):
    #                                         for succ_node in iter_ctx.successor.contained_nodes:
    #                                             queue.append((succ_node, remaining_path))
    #                                             continue
    #                                 # continue with successor of parent loop
    #                                 # continue search with successors of current loop
    #                                 if parent_loop_ctx.successor is None:
    #                                     continue
    #                                 for succ_node in parent_loop_ctx.successor.contained_nodes:
    #                                     queue.append((succ_node, remaining_path))
    #                                 print("-> Skipped loop body")
    #                                 continue
    #
    #                             #                                if isinstance(IterationContext)
    #                             #
    #                             #                                # search in children on parent_loop_ctx for matchin loopstate_index
    #                             #                                for child in parent_loop_ctx.get_contained_contexts():
    #                             #                                    if (
    #                             #                                        isinstance(child, IterationContext)
    #                             #                                        and int(loopstate_info[loopstate_position]) in child.loopstate_iteration_ids
    #                             #                                    ):
    #                             #                                        iter_ctx = child
    #                             #                                        break
    #                             # print("iterCTX: ", iter_ctx)
    #
    #                             # set state id
    #                             for n in iter_ctx.get_contained_nodes():
    #                                 if n.state_id is not None:
    #                                     # keep longer path
    #                                     if len(state_mappings_dict[state_id]) > len(state_mappings_dict[n.state_id]):
    #                                         pass
    #                                     else:
    #                                         print("Skipped overwrite: " + str(n.state_id) + " with " + str(state_id))
    #                                         continue
    #                                 n.state_id = state_id
    #                                 print("set state_id: ", state_id, " to node: ", n)
    #
    #                             # since loopstate encodes information on multiple entered loops, it may not be discarded by the processed TGStartIterationNode.
    #                             # successive TGFunctionNode encounters will cleanup leading loopstates in the remaining_path
    #
    #                 # continue search with successors
    #                 for succ in self.get_successors(current_node):
    #                     queue.append((succ, copy.deepcopy(remaining_path)))
    #         plt.ioff()
    #         self.plot()

    def __get_work_contexts_by_location_and_state_id(
        self,
        pet: PEGraphX,
        location: str,
        state_id: str,
        instructionID_mappings_dict: Dict[str, str],
        state_mappings_dict: Dict[str, List[str]],
        location_to_work_contexts: Dict[LineID, Set[WorkContext]],
        lookup_cache: Dict[Tuple[str, str], Set[Context]],
        state_ids_cache: Dict[Context, FrozenSet[int]],
        fallback: Optional["_ContextFallback"] = None,
    ) -> Set[Context]:
        """instructionID_mappings_dict is a mapping from instructionIDs to lineIDs. This should be removed in the long run, when instructionIDs become the default over lineIDs.
        state_mappings_dict is a mapping from stateIDs to callpaths.
        location_to_work_contexts is a reverse index {lineID: WorkContexts whose code scope contains it},
        built once per dependency-insertion pass (see __insert_data_dependencies_from_files).
        state_ids_cache memoizes get_state_ids per context for the duration of that pass.
        With a fallback, an end whose state no context at the location carries is not dropped but
        mapped approximately (see _ContextFallback.resolve)."""

        #        cache_key = (location, state_id)
        #        if cache_key in lookup_cache:
        #            return lookup_cache[cache_key]

        contexts: Set[Context] = set()
        requested_location = location
        # check if location is an instructionID. If so, convert it to a lineID using the mappings_dict.
        if ":" not in location:
            # location is an instruction id or something unspecified (e.g. '*').
            if location in instructionID_mappings_dict:
                location = instructionID_mappings_dict[location]

        # handle location, if it is a regular lineID in the format "file:line".
        if ":" in location:
            # location is in format "file:line".
            location_split = location.split(":")
            file_id = location_split[0]
            line_num = location_split[1]
            location_lineid = LineID(file_id + ":" + line_num)

            if location_lineid in location_to_work_contexts:
                contexts = set(location_to_work_contexts[location_lineid])

        # filter contexts for state_id compatibility
        # `contexts` already holds exactly the WorkContexts whose code scope contains `location`
        # (via the location_to_work_contexts spatial index), so only those need to be checked here.
        if state_id != "NO_STATE":
            target_state_id = int(state_id)
            # get_state_ids walks the ancestor chain of every context whose own state ids are
            # empty, and returns a list which is then scanned linearly. Both used to happen once
            # per candidate context per dependency; the state ids are assigned before dependencies
            # are inserted, so they are memoized as sets for the duration of the pass.
            filtered_contexts: Set[Context] = set()
            for ctx in contexts:
                cached_state_ids = state_ids_cache.get(ctx)
                if cached_state_ids is None:
                    cached_state_ids = frozenset(ctx.get_state_ids())
                    state_ids_cache[ctx] = cached_state_ids
                if target_state_id in cached_state_ids:
                    filtered_contexts.add(ctx)
            if len(filtered_contexts) == 0 and len(contexts) > 0 and fallback is not None:
                return fallback.resolve(requested_location, target_state_id, contexts)

            #            lookup_cache[cache_key] = filtered_contexts
            return filtered_contexts

        #        lookup_cache[cache_key] = contexts
        return contexts

    def __insert_data_dependencies_from_files(
        self, dynamic_dependency_file: Optional[str], static_dependency_file: Optional[str]
    ) -> None:
        """Load data dependencies from profiler output files and insert them into the graph."""

        logger.info(
            "Inserting data dependencies from files: "
            + "\n\t- "
            + str(dynamic_dependency_file)
            + "\n\t- "
            + str(static_dependency_file)
        )

        def debug_print_deps(
            deps: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]], indent: int = 0
        ) -> None:
            for dep_type, dep_type_deps in deps.items():
                print("DEP_TYPE: ", dep_type)
                for source_location, source_location_deps in dep_type_deps.items():
                    print("-> SOURCE LOCATION: ", source_location)
                    for source_state_id, source_state_deps in source_location_deps.items():
                        print("--> SOURCE STATE ID: ", source_state_id)
                        for sink_location, sink_location_deps in source_state_deps.items():
                            print("---> SINK LOCATION: ", sink_location)
                            for sink_state_id, var_infos in sink_location_deps.items():
                                print("----> SINK STATE ID: ", sink_state_id)
                                for var_info in var_infos:
                                    print("-----> VAR INFO: ", var_info)

        # collect data dependencies
        dependencies = self.__read_dependencies_from_files(dynamic_dependency_file, static_dependency_file)
        dependencies = self.__apply_dependency_overwrites(dependencies)

        # read instructionID to lineID mapping
        warnings.warn("TODO: update available data to use instructionIDs instead of lineIDs as the default.")
        mappings_dict: Dict[str, str] = dict()  # {instructionID: lineID}}
        mappings_file = os.path.join(Path(str(dynamic_dependency_file)).parent, "instructionID_to_lineID_mapping.txt")
        if os.path.exists(mappings_file):
            with open(mappings_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or len(line) == 0:
                        continue
                    line_split = [elem for elem in line.split(" ") if len(elem) > 0]
                    instruction_id = line_split[0]
                    line_id = line_split[1]
                    if line_id.startswith("*"):
                        continue
                    line_id_split = line_id.split(":")
                    file_id = line_id_split[0]
                    line_num = line_id_split[1]
                    column_num = line_id_split[2]
                    mappings_dict[instruction_id] = str(file_id) + ":" + str(line_num)

        # read stateID to callpath mapping
        if dynamic_dependency_file is None:
            raise ValueError("dynamic_dependency_file may not be None!")
        state_mappings_dict = self.__get_state_mappings_from_file(dynamic_dependency_file)

        # build spatial index: LineID -> Set[WorkContext]
        location_to_work_contexts: Dict[LineID, Set[WorkContext]] = {}
        for _ctx in self.contexts:
            if not isinstance(_ctx, WorkContext):
                continue
            for _line_id in _ctx.get_code_scope(self.pet):
                location_to_work_contexts.setdefault(_line_id, set()).add(_ctx)

        # cache for repeated (location, state_id) lookups
        _context_lookup_cache: Dict[Tuple[str, str], Set[Context]] = {}
        # see __get_work_contexts_by_location_and_state_id
        _state_ids_cache: Dict[Context, FrozenSet[int]] = {}
        # ends whose state no context at their location carries are mapped approximately
        context_fallback = _ContextFallback(self.__collect_all_contexts())

        # insert data dependencies into graph
        # ignores WAW dependencies, as they do not represent data flow and thus are not relevant for the TaskGraph.
        logger.info("--> Inserting data dependencies: ")
        # Everything derived from dep_type is invariant for the whole block below. It used to be
        # recomputed for every (source context, target context, variable) triple.
        #
        # The two caches below hold values which are a function of a single context, but which
        # used to be recomputed per pair of contexts - and, for the ancestors, per variable.
        # Sampling the thread stacks of this pass showed most of its time inside
        # get_closest_function_ancestor and get_ancestor_contexts. They are valid for the
        # duration of this pass: inserting dependencies does not change the containment relation.
        closest_function_ancestor_cache: Dict[Context, Optional[Context]] = {}
        iteration_ancestors_cache: Dict[Context, List[Context]] = {}

        # callpath frames per state, and the loop crossed per pair of states (see __carried_frame_and_position)
        frames_cache: Dict[str, Optional[List[Tuple[str, Optional[int], Dict[int, int]]]]] = {}
        carried_cache: Dict[Tuple[str, str], Optional[Tuple[int, int]]] = {}

        # parent chains, for the records without states (see __common_loop)
        chain_cache: Dict[Context, List[Context]] = {}
        # the lines each variable is written on, for the records without states (see __blamed_loops)
        write_lines = self.__write_lines_of_variables(dependencies, mappings_dict)

        # lines only covered by code the cuts deleted (early exits, exception unwind paths): the
        # records observed there have no context, which is reported below
        deleted_lines: Set[Optional[LineID]] = set()
        for deleted_cu in self.cus_deleted_by_early_exits | self.cus_deleted_by_exception_unwinding:
            if deleted_cu is None:
                continue
            deleted_node = self.pet.node_at(deleted_cu)
            for line_number in range(deleted_node.start_line, deleted_node.end_line + 1):
                deleted_line = LineID(str(deleted_node.file_id) + ":" + str(line_number))
                if deleted_line not in location_to_work_contexts:
                    deleted_lines.add(deleted_line)
        self.records_on_deleted_lines = 0
        deleted_line_examples: List[str] = []

        def state_frames(state_id: str) -> Optional[List[Tuple[str, Optional[int], Dict[int, int]]]]:
            if state_id not in frames_cache:
                callpath = state_mappings_dict.get(state_id)
                frames_cache[state_id] = self._callpath_frames(callpath) if callpath is not None else None
            return frames_cache[state_id]

        def _is_approximate(location: str, state_id: str) -> bool:
            return state_id.isdigit() and (location, int(state_id)) in context_fallback.approximate

        def closest_function_ancestor(ctx: Context) -> Optional[Context]:
            if ctx not in closest_function_ancestor_cache:
                closest_function_ancestor_cache[ctx] = ctx.get_closest_function_ancestor()
            return closest_function_ancestor_cache[ctx]

        def ancestors_from_closest_iteration(ctx: Context) -> List[Context]:
            """the context's ancestors, pruned to start at the closest enclosing iteration context"""
            cached = iteration_ancestors_cache.get(ctx)
            if cached is None:
                cached = ctx.get_ancestor_contexts()
                while len(cached) > 0 and not isinstance(cached[0], IterationContext):
                    del cached[0]
                iteration_ancestors_cache[ctx] = cached
            return cached

        for dep_type, dep_type_deps in progress(dependencies.items(), desc="Dependency types"):
            is_static_dep_type = dep_type.startswith("STAT_")
            # remove the DYN_ or STAT_ prefix from dep_type to get the actual dependency type
            clean_dep_type = dep_type.replace("STAT_" if is_static_dep_type else "DYN_", "")
            dep_type_enum_obj = DepType[clean_dep_type] if clean_dep_type in DepType.__members__ else None
            # ignore WAW and INIT, as there is no data flow. Nothing below registers anything for
            # them, so the whole dependency type is skipped here - the check used to sit at the
            # innermost level, once the ancestry of every pair of contexts had been computed.
            if dep_type_enum_obj == DepType.WAW or dep_type_enum_obj == DepType.INIT:
                continue

            for source_location, source_location_deps in progress(
                dep_type_deps.items(), desc="Source locations", leave=False
            ):
                # The line of each end, kept on the dependency to explain the decisions based on it
                # (see PatternDecisions). The first column of a dependency file line is the sink of
                # the dependency in the sense of Dependency.sink_line, so the names are swapped
                # relative to the ones used here. Resolved once per location.
                dependency_sink_line = self.__line_of_location(source_location, mappings_dict)
                for source_state_id, source_state_deps in source_location_deps.items():
                    # find source and target contexts based on locations and state ids
                    # only work contexts can be source or target of data dependencies
                    source_contexts = self.__get_work_contexts_by_location_and_state_id(
                        self.pet,
                        source_location,
                        source_state_id,
                        mappings_dict,
                        state_mappings_dict,
                        location_to_work_contexts,
                        _context_lookup_cache,
                        _state_ids_cache,
                        context_fallback,
                    )
                    source_is_approximate = _is_approximate(source_location, source_state_id)
                    for sink_location, sink_location_deps in source_state_deps.items():
                        dependency_source_line = self.__line_of_location(sink_location, mappings_dict)
                        for sink_state_id, var_infos in sink_location_deps.items():
                            # find source and target contexts based on locations and state ids
                            # only work contexts can be source or target of data dependencies
                            target_contexts = self.__get_work_contexts_by_location_and_state_id(
                                self.pet,
                                sink_location,
                                sink_state_id,
                                mappings_dict,
                                state_mappings_dict,
                                location_to_work_contexts,
                                _context_lookup_cache,
                                _state_ids_cache,
                                context_fallback,
                            )
                            approximate_context = source_is_approximate or _is_approximate(sink_location, sink_state_id)
                            # the variable name and the memory region depend on the entry alone,
                            # but used to be parsed again for every pair of contexts
                            parsed_var_infos: List[Tuple[str, Optional[MemoryRegion]]] = [
                                (
                                    var_info if "(" not in var_info else var_info.split("(")[0],
                                    None if "(" not in var_info else MemoryRegion(var_info.split("(")[1].strip(")")),
                                )
                                for var_info in var_infos
                            ]

                            if not is_static_dep_type:
                                for executed_line in (dependency_sink_line, dependency_source_line):
                                    if executed_line is not None:
                                        self.lines_with_dynamic_records.add(executed_line)
                            if dependency_sink_line in deleted_lines or dependency_source_line in deleted_lines:
                                if not is_static_dep_type:
                                    self.records_on_deleted_lines += 1
                                    if len(deleted_line_examples) < 5:
                                        deleted_line_examples.append(
                                            str(dependency_sink_line) + " <- " + str(dependency_source_line)
                                        )

                            def make_dependency(
                                var_name: str,
                                memory_region: Optional[MemoryRegion],
                                origin: DepOrigin,
                                carried_by_loop: Optional[object] = None,
                                carried_by_pet_loops: Optional[FrozenSet[str]] = None,
                            ) -> Dependency:
                                dependency = Dependency(type=EdgeType.DATA)
                                dependency.dtype = dep_type_enum_obj
                                dependency.var_name = var_name
                                dependency.memory_region = memory_region
                                dependency.origin = origin
                                dependency.source_line = dependency_source_line
                                dependency.sink_line = dependency_sink_line
                                dependency.approximate_context = approximate_context
                                dependency.carried_by_loop = carried_by_loop
                                dependency.carried_by_pet_loops = carried_by_pet_loops
                                return dependency

                            # Records of the dynamic file without states on both ends (stack variables,
                            # recorded by the hybrid analysis, or --ignore-dependency-states): which
                            # iterations they cross is read from the order of their instructions, see
                            # __stateless_record_order. Without instruction ids (an older profiler
                            # format) that order is unknown, and they are treated like static ones.
                            stateless_order: Optional[str] = None
                            if not is_static_dep_type and source_state_id == "NO_STATE" == sink_state_id:
                                stateless_order = self.__stateless_record_order(source_location, sink_location)

                            # handle static and dynamic dependencies separately
                            if is_static_dep_type or (
                                source_state_id == "NO_STATE" == sink_state_id and stateless_order is None
                            ):
                                # static dependencies must not leave the current function scope
                                # source and target have to share a parent function context.
                                # TODO (or consider other branches)
                                for source_ctx in source_contexts:
                                    # check for shared closest function parent
                                    source_closest_fn = closest_function_ancestor(source_ctx)
                                    if source_closest_fn is None:
                                        # no shared parent function context can exist
                                        continue
                                    for target_ctx in target_contexts:
                                        if source_ctx == target_ctx:
                                            continue
                                        if closest_function_ancestor(target_ctx) != source_closest_fn:
                                            # closest parent function contexts are not equal.
                                            # static dependencies are only valid within a functions scope.
                                            continue
                                        for var_name, memory_region in parsed_var_infos:
                                            source_ctx.register_outgoing_dependency(
                                                target_ctx,
                                                make_dependency(var_name, memory_region, DepOrigin.STATIC_ANALYSIS),
                                            )
                            elif stateless_order is not None:
                                # a variable of the stack frame: both ends lie in the same call, and only
                                # the loops of that call can carry it
                                innermost_loop = (
                                    self.__innermost_loop_containing(dependency_sink_line, dependency_source_line)
                                    if stateless_order == self._STATELESS_CARRIED
                                    else None
                                )
                                for source_ctx in source_contexts:
                                    source_closest_fn = closest_function_ancestor(source_ctx)
                                    if source_closest_fn is None:
                                        continue
                                    for target_ctx in target_contexts:
                                        if closest_function_ancestor(target_ctx) != source_closest_fn:
                                            continue
                                        if stateless_order == self._STATELESS_FORWARD:
                                            # the earlier access comes first in the code: taken as a
                                            # dependency within one iteration (see __stateless_record_order)
                                            _, crosses_iterations = self.__common_loop(
                                                source_ctx, target_ctx, chain_cache
                                            )
                                            if source_ctx == target_ctx or crosses_iterations:
                                                continue
                                            for var_name, memory_region in parsed_var_infos:
                                                source_ctx.register_outgoing_dependency(
                                                    target_ctx,
                                                    make_dependency(
                                                        var_name, memory_region, DepOrigin.DYNAMIC_ANALYSIS
                                                    ),
                                                )
                                            continue
                                        # the earlier access comes later in the code: the dependency
                                        # crosses iterations of the innermost loop containing both ends
                                        carrying = self.__stateless_carrying_loops(
                                            source_ctx, target_ctx, innermost_loop, chain_cache
                                        )
                                        if carrying is None or (len(carrying) == 0 and source_ctx == target_ctx):
                                            # the contexts do not lie in one execution of that loop: the
                                            # location of an end only matches a context of another CU
                                            # on its line (e.g. the initialization of a for loop)
                                            continue
                                        for var_name, memory_region in parsed_var_infos:
                                            blamed = self.__blamed_loops(carrying, var_name, memory_region, write_lines)
                                            source_ctx.register_outgoing_dependency(
                                                target_ctx,
                                                make_dependency(
                                                    var_name,
                                                    memory_region,
                                                    DepOrigin.DYNAMIC_ANALYSIS,
                                                    blamed[0] if len(blamed) > 0 else None,
                                                    (
                                                        frozenset(str(loop.parent_loop) for loop in blamed)
                                                        if len(blamed) > 0
                                                        else None
                                                    ),
                                                ),
                                            )
                            else:
                                # dynamic dependencies are allowed to leave the current function
                                # register dependencies between all pairs of source and target contexts
                                #
                                # prevent false positive dependencies in case of same iterations by checking for same ancestors
                                # TODO: add states to contexts to allow a more robust search in __get_work_contexts_by_location_and_state_id
                                # TODO: The fact the following condition is necessary is a result of incorrect behavior of __get_work_contexts_by_location_and_state_id, which should be fixed!
                                same_state = source_state_id == sink_state_id
                                carried: Optional[Tuple[int, int]] = None
                                source_frames = state_frames(source_state_id) if source_state_id.isdigit() else None
                                sink_frames = state_frames(sink_state_id) if sink_state_id.isdigit() else None
                                if not same_state and source_frames is not None and sink_frames is not None:
                                    carried_key = (source_state_id, sink_state_id)
                                    if carried_key not in carried_cache:
                                        carried_cache[carried_key] = self.__carried_frame_and_position(
                                            source_frames, sink_frames
                                        )
                                    carried = carried_cache[carried_key]
                                carried_function: Optional[str] = None
                                carried_pet_loop: Optional[PETNodeID] = None
                                if carried is not None and source_frames is not None:
                                    # the PET loop follows from the states alone, also for an end
                                    # mapped to a standalone copy or approximately
                                    carried_function = source_frames[carried[0]][0]
                                    pet_loops = self.loop_pet_ids_by_loopstate_position.get(
                                        (carried_function, carried[1]), set()
                                    )
                                    if len(pet_loops) == 1:
                                        carried_pet_loop = next(iter(pet_loops))
                                sink_is_approximate = _is_approximate(sink_location, sink_state_id)
                                for source_ctx in source_contexts:
                                    source_ancs = ancestors_from_closest_iteration(source_ctx) if same_state else []
                                    # the loop context is looked up from an end mapped exactly: an
                                    # approximately mapped end may not lie on its state's callpath
                                    source_carried_by_loop: Optional[object] = (
                                        self.__loop_context_at(source_ctx, carried_function, carried[1])
                                        if carried is not None
                                        and carried_function is not None
                                        and not source_is_approximate
                                        else None
                                    )
                                    for target_ctx in target_contexts:
                                        carried_by_loop = source_carried_by_loop
                                        if (
                                            carried_by_loop is None
                                            and carried is not None
                                            and carried_function is not None
                                            and not sink_is_approximate
                                        ):
                                            carried_by_loop = self.__loop_context_at(
                                                target_ctx, carried_function, carried[1]
                                            )
                                        pet_loop = carried_pet_loop
                                        if pet_loop is None and isinstance(carried_by_loop, LoopParentContext):
                                            pet_loop = carried_by_loop.parent_loop
                                        if source_ctx == target_ctx and pet_loop is None:
                                            # (a dependency between the iterations with the buckets 0
                                            # and 2 of a loop has both ends in its copy [0, 2]; it is
                                            # kept, as it tells the loop it crosses)
                                            continue
                                        if same_state:
                                            # both pruned to their closest iteration context, so that
                                            # source and target are required to be in the same iteration
                                            if source_ancs != ancestors_from_closest_iteration(target_ctx):
                                                continue
                                        for var_name, memory_region in parsed_var_infos:
                                            source_ctx.register_outgoing_dependency(
                                                target_ctx,
                                                make_dependency(
                                                    var_name,
                                                    memory_region,
                                                    DepOrigin.DYNAMIC_ANALYSIS,
                                                    carried_by_loop,
                                                    None if pet_loop is None else frozenset([str(pet_loop)]),
                                                ),
                                            )

        if self.records_on_deleted_lines > 0:
            logger.warning(
                "%d dynamic dependency records have an end on a line of code deleted by cutting early exits "
                "or exception unwind paths (e.g. %s); they are not part of the TaskGraph.",
                self.records_on_deleted_lines,
                ", ".join(deleted_line_examples),
            )
        logger.info(
            "Mapped "
            + str(len(context_fallback.approximate))
            + " dependency ends without a context carrying their state approximately ("
            + str(context_fallback.scoped)
            + " within the scope of their state, "
            + str(context_fallback.location_only)
            + " by location only)"
        )
        self.approximate_dependency_end_statistics = {
            "ends": len(context_fallback.approximate),
            "scoped": context_fallback.scoped,
            "location_only": context_fallback.location_only,
        }
        logger.info(
            "Inserting data dependencies from files: "
            + str(dynamic_dependency_file)
            + ", "
            + str(static_dependency_file)
            + " completed."
        )

    def map_dynamic_dependency_records(self) -> List[MappedDependencyRecord]:
        """All dynamic RAW/WAR/WAW/INIT records of the dependency files, with their ends mapped to work contexts.

        Used by the side effect export (discopop_explorer.side_effects.export). Reads the files
        again instead of reusing state of __insert_data_dependencies_from_files, so that the
        TaskGraph and therefore pattern detection are not affected by the export. The mapping is
        the one of __insert_data_dependencies_from_files: the same context lookup and the same
        same-state rule, but without its approximate fallback (_ContextFallback): an end whose state no
        context at its location carries stays unmapped here, so that the side effect analysis reports
        it as such instead of attributing it to a calling context it may not belong to. The returned
        pairs are therefore the exactly attributed subset of the edges registered for RAW and WAR (and
        of those it would register for WAW), without the dependencies of a context on itself. INIT
        records have no other end; only their first-column end is mapped. Records with an end without
        a state are skipped (they cannot be attributed to a calling context), as are static ones.
        """
        dependencies = self.__read_dependencies_from_files(self.dynamic_dependency_file, self.static_dependency_file)
        dependencies = self.__apply_dependency_overwrites(dependencies)

        mappings_dict: Dict[str, str] = dict()  # {instructionID: lineID}
        mappings_file = os.path.join(
            Path(str(self.dynamic_dependency_file)).parent, "instructionID_to_lineID_mapping.txt"
        )
        if os.path.exists(mappings_file):
            with open(mappings_file, "r") as f:
                for line in f:
                    line_split = line.split()
                    if len(line_split) < 2 or line_split[0].startswith("#") or line_split[1].startswith("*"):
                        continue
                    line_id_split = line_split[1].split(":")
                    mappings_dict[line_split[0]] = line_id_split[0] + ":" + line_id_split[1]
        state_mappings_dict = (
            self.__get_state_mappings_from_file(self.dynamic_dependency_file)
            if self.dynamic_dependency_file is not None
            else {}
        )

        location_to_work_contexts: Dict[LineID, Set[WorkContext]] = {}
        for ctx in self.contexts:
            if isinstance(ctx, WorkContext):
                for line_id in ctx.get_code_scope(self.pet):
                    location_to_work_contexts.setdefault(line_id, set()).add(ctx)
        lookup_cache: Dict[Tuple[str, str], Set[Context]] = {}
        state_ids_cache: Dict[Context, FrozenSet[int]] = {}
        iteration_ancestors_cache: Dict[Context, List[Context]] = {}

        def contexts_of(location: str, state_id: str) -> List[Context]:
            found = self.__get_work_contexts_by_location_and_state_id(
                self.pet,
                location,
                state_id,
                mappings_dict,
                state_mappings_dict,
                location_to_work_contexts,
                lookup_cache,
                state_ids_cache,
            )
            return sorted(found, key=lambda c: c.creation_index)

        def ancestors_from_closest_iteration(ctx: Context) -> List[Context]:
            # same pruning as in __insert_data_dependencies_from_files
            cached = iteration_ancestors_cache.get(ctx)
            if cached is None:
                cached = ctx.get_ancestor_contexts()
                while len(cached) > 0 and not isinstance(cached[0], IterationContext):
                    del cached[0]
                iteration_ancestors_cache[ctx] = cached
            return cached

        records: List[MappedDependencyRecord] = []
        for dep_type, dep_type_deps in dependencies.items():
            if not dep_type.startswith("DYN_"):
                continue
            clean_dep_type = dep_type[len("DYN_") :]
            if clean_dep_type not in ("RAW", "WAR", "WAW", "INIT"):
                continue
            for first_location, first_location_deps in dep_type_deps.items():
                if not first_location.isdigit():
                    # not an instruction id: data of an older profiler format
                    continue
                first_line = self.__line_of_location(first_location, mappings_dict)
                for first_state_id, first_state_deps in first_location_deps.items():
                    if first_state_id == "NO_STATE":
                        continue
                    first_contexts = contexts_of(first_location, first_state_id)
                    for other_location, other_location_deps in first_state_deps.items():
                        for other_state_id, var_infos in other_location_deps.items():
                            var_names = list(dict.fromkeys(v.split("(")[0] for v in var_infos))
                            if clean_dep_type == "INIT":
                                for var_name in var_names:
                                    records.append(
                                        MappedDependencyRecord(
                                            "INIT",
                                            var_name,
                                            (int(first_location), int(first_state_id), first_line),
                                            None,
                                            [],
                                            first_contexts,
                                            [],
                                        )
                                    )
                                continue
                            if other_state_id == "NO_STATE" or not other_location.isdigit():
                                continue
                            other_line = self.__line_of_location(other_location, mappings_dict)
                            other_contexts = contexts_of(other_location, other_state_id)
                            same_state = first_state_id == other_state_id
                            pairs: List[Tuple[Context, Context]] = []
                            for first_ctx in first_contexts:
                                first_ancs = ancestors_from_closest_iteration(first_ctx) if same_state else []
                                for other_ctx in other_contexts:
                                    if first_ctx == other_ctx:
                                        continue
                                    if same_state and first_ancs != ancestors_from_closest_iteration(other_ctx):
                                        continue
                                    pairs.append((first_ctx, other_ctx))
                            for var_name in var_names:
                                records.append(
                                    MappedDependencyRecord(
                                        clean_dep_type,
                                        var_name,
                                        (int(first_location), int(first_state_id), first_line),
                                        (int(other_location), int(other_state_id), other_line),
                                        pairs,
                                        first_contexts,
                                        other_contexts,
                                    )
                                )
        return records

    def __validate_data_dependencies(self) -> None:
        self.__validate_data_dependencies_using_initializations()
        self.__validate_data_dependencies_using_metadata()

    def __validate_data_dependencies_using_initializations(self) -> None:
        logger.info("Validating data dependencies using initializations...")
        invalid_deps: List[Tuple[Context, Context, Dependency]] = []

        self.__print_context_statistics("Pre validation")

        logger.info("--> checking contexts...")
        for ctx in progress(self.contexts):
            # calculate initialized variables per context
            initialized_vars: Set[Tuple[str, Optional[MemoryRegion]]] = set()
            for node in ctx.get_contained_nodes():
                if node.pet_node_id is None:
                    continue
                pet_node = self.pet.node_at(node.pet_node_id)
                in_data_edges = in_edges(self.pet, node.pet_node_id, EdgeType.DATA)
                incoming_init_deps = [e[2] for e in in_data_edges if e[2].dtype == DepType.INIT]
                for dep in incoming_init_deps:
                    if dep.var_name is None:
                        continue
                    initialized_vars.add((dep.var_name, dep.memory_region))

            print("CTX: ", ctx)
            print("--> inits: ", [str(t) for t in initialized_vars])
            print()
            initialized_var_names = [v[0] for v in initialized_vars]
            initialized_var_memregs = [v[1] for v in initialized_vars]

            # check outgoing dependencies to predecessors against inits
            preceeding_contexts = ctx.get_preceeding_contexts()
            for target_ctx, dep in ctx.outgoing_dependencies:
                if target_ctx not in preceeding_contexts:
                    continue
                # target_ctx is preceeding ctx
                # check if dep is covered by a initialization. If so, the dependency can be ignored as it is a hallucination
                if dep.memory_region is not None and dep.memory_region in initialized_var_memregs:
                    invalid_deps.append((ctx, target_ctx, dep))
                    continue
                if dep.var_name in initialized_var_names:
                    invalid_deps.append((ctx, target_ctx, dep))
                    continue

        for source_ctx, target_ctx, dep in invalid_deps:
            tpl = (target_ctx, dep)
            if tpl in source_ctx.outgoing_dependencies:
                print("REMOVING: ", dep.var_name, dep.sink_line, dep.source_line)
                source_ctx.outgoing_dependencies.remove(tpl)

        self.__print_context_statistics("Post validation")

    def __validate_data_dependencies_using_metadata(self) -> None:
        logger.info("Validating data dependencies using existing metadata...")
        invalid_deps: List[Tuple[Context, Context, Dependency]] = []
        valid_deps: Set[Tuple[Context, Context, Dependency]] = set()
        for source_ctx in progress(self.contexts):
            source_call_stack: Optional[List[Context]] = None  # only calculate, if it is required
            for target_ctx, dep in source_ctx.outgoing_dependencies:
                # check if metadata exists
                if (
                    dep.metadata_inter_call_dep is None
                    or dep.metadata_intra_call_dep is None
                    or dep.metadata_inter_iteration_dep is None
                    or dep.metadata_intra_iteration_dep is None
                ):
                    # no metadata exists
                    continue
                # check if any list is non-empty, i.e., if a check is actually required
                if (
                    len(dep.metadata_source_ancestors) == 0
                    and len(dep.metadata_sink_ancestors) == 0
                    and len(dep.metadata_inter_call_dep) == 0
                    and len(dep.metadata_intra_call_dep) == 0
                    and len(dep.metadata_inter_iteration_dep) == 0
                    and len(dep.metadata_intra_iteration_dep) == 0
                ):
                    # all lists are empty. no check required.
                    continue
                # calculate callstacks for validation
                if source_call_stack is None:
                    source_call_stack = get_context_call_stack(source_ctx)
                target_call_stack = get_context_call_stack(target_ctx)
                # get LineIDs from callstacks
                converted_source_call_stack = convert_callstacks_to_lineIDs(self.pet, source_call_stack)
                converted_target_call_stack = convert_callstacks_to_lineIDs(self.pet, target_call_stack)

                skip_further_checks = False

                # validate source ancestors
                if (not skip_further_checks) and len(dep.metadata_sink_ancestors) > 0:
                    filtered_source_call_stack = [
                        elem[1] for elem in converted_source_call_stack if elem[0] != CallStackElementType.ITERATION
                    ]

                    for entry in dep.metadata_sink_ancestors:
                        if entry not in filtered_source_call_stack:
                            logger.warning(
                                "found source-ancestor mismatch: "
                                + entry
                                + ". Keep dependency to err on the safe side."
                            )
                            # following checks would not target the current dependency. Keep the dependency to err on the safe side.
                            skip_further_checks = True
                            break

                # validate sink ancestors
                if (not skip_further_checks) and len(dep.metadata_source_ancestors) > 0:
                    filtered_target_call_stack = [
                        elem[1] for elem in converted_target_call_stack if elem[0] != CallStackElementType.ITERATION
                    ]
                    for entry in dep.metadata_source_ancestors:
                        if entry not in filtered_target_call_stack:
                            logger.warning(
                                "found sink-ancestor mismatch: " + entry + ". Keep dependency to err on the safe side."
                            )
                            # following checks would not target the current dependency. Keep the dependency to err on the safe side.
                            skip_further_checks = True
                            break

                if skip_further_checks:
                    continue

                dependency_valid = True

                # validate intra-call relation
                if dependency_valid and len(dep.metadata_intra_call_dep) > 0:
                    # check for exact same parent function
                    overlapping_stack_elements = [elem for elem in source_call_stack if elem in target_call_stack]
                    converted_overlapping_stack_elements = convert_callstacks_to_lineIDs(
                        self.pet, overlapping_stack_elements
                    )
                    filtered_conv_ov_stack_elements = [
                        elem[1]
                        for elem in converted_overlapping_stack_elements
                        if elem[0] == CallStackElementType.FUNCTION
                    ]
                    for entry in dep.metadata_intra_call_dep:
                        if entry not in filtered_conv_ov_stack_elements:
                            logger.warning("found intra-call mismatch: " + entry)
                            dependency_valid = False
                            break

                # validate inter-call relation
                if dependency_valid and len(dep.metadata_inter_call_dep) > 0:
                    # check for differenct parent nodes of the same function
                    source_call_stack_function_filtered = [
                        elem for elem in source_call_stack if isinstance(elem, FunctionContext)
                    ]
                    target_call_stack_function_filtered = [
                        elem for elem in target_call_stack if isinstance(elem, FunctionContext)
                    ]
                    disjoint_function_nodes = [
                        elem
                        for elem in source_call_stack_function_filtered
                        if elem not in target_call_stack_function_filtered
                    ]
                    converted_disjoint_function_nodes = convert_callstacks_to_lineIDs(
                        self.pet, cast(List[Context], disjoint_function_nodes)
                    )
                    unpacked_converted_disjoint_function_nodes = [elem[1] for elem in converted_disjoint_function_nodes]
                    #                    print("CDFN: ", str(converted_disjoint_function_nodes))
                    for entry in dep.metadata_inter_call_dep:
                        if entry not in unpacked_converted_disjoint_function_nodes:
                            logger.warning("found inter-call mismatch: " + entry)
                            dependency_valid = False
                            break

                # validate intra-iteration relation
                if dependency_valid and len(dep.metadata_intra_iteration_dep) > 0:
                    # check for equal iteration node
                    overlapping_stack_elements = [elem for elem in source_call_stack if elem in target_call_stack]
                    converted_overlapping_stack_elements = convert_callstacks_to_lineIDs(
                        self.pet, overlapping_stack_elements
                    )
                    iteration_filtered_conv_ov_stack_elements = [
                        elem[1]
                        for elem in converted_overlapping_stack_elements
                        if elem[0] == CallStackElementType.ITERATION
                    ]
                    loop_filtered_conv_ov_stack_elements = [
                        elem[1] for elem in converted_overlapping_stack_elements if elem[0] == CallStackElementType.LOOP
                    ]

                    for entry in dep.metadata_intra_iteration_dep:
                        if entry not in loop_filtered_conv_ov_stack_elements:
                            # source and target not in the same loop.
                            continue
                        if entry not in iteration_filtered_conv_ov_stack_elements:
                            logger.warning("found intra-iteration mismatch: " + entry)
                            dependency_valid = False
                            break

                # validate inter-iteration relation
                if dependency_valid and len(dep.metadata_inter_iteration_dep) > 0:
                    # check for differing iteration node
                    source_call_stack_iteration_filtered = [
                        elem for elem in source_call_stack if isinstance(elem, IterationContext)
                    ]
                    target_call_stack_iteration_filtered = [
                        elem for elem in target_call_stack if isinstance(elem, IterationContext)
                    ]
                    source_disjoint_iteration_nodes = [
                        elem
                        for elem in source_call_stack_iteration_filtered
                        if elem not in target_call_stack_iteration_filtered
                    ]
                    target_disjoint_iteration_nodes = [
                        elem
                        for elem in target_call_stack_iteration_filtered
                        if elem not in source_call_stack_iteration_filtered
                    ]

                    source_disjoint_iteration_parent_loops = [
                        elem.belongs_to_context for elem in source_disjoint_iteration_nodes
                    ]
                    target_disjoint_iteration_parent_loops = [
                        elem.belongs_to_context for elem in target_disjoint_iteration_nodes
                    ]
                    overlapping_parent_loops = [
                        elem
                        for elem in source_disjoint_iteration_parent_loops
                        if elem in target_disjoint_iteration_parent_loops
                    ]
                    converted_overlapping_loop_nodes = convert_callstacks_to_lineIDs(self.pet, overlapping_parent_loops)
                    filtered_conv_ov_loop_nodes = [elem[1] for elem in converted_overlapping_loop_nodes]

                    for entry in dep.metadata_inter_iteration_dep:
                        if entry not in filtered_conv_ov_loop_nodes:
                            logger.warning("found inter-iteration mismatch: " + entry)
                            dependency_valid = False
                            break

                # mark dependency invalid, if required
                if not dependency_valid:
                    invalid_deps.append((source_ctx, target_ctx, dep))
                else:
                    valid_deps.add((source_ctx, target_ctx, dep))

        self.__print_context_statistics("Pre validation")

        # remove invalid dependencies)
        invalid_deps = [entry for entry in invalid_deps if entry not in valid_deps]
        for source_ctx, target_ctx, dep in invalid_deps:
            tpl = (target_ctx, dep)
            if tpl in source_ctx.outgoing_dependencies:
                source_ctx.outgoing_dependencies.remove(tpl)

        self.__print_context_statistics("Post validation")

    def __print_context_statistics(self, label: str = "") -> None:
        # prepare context dependency count
        ctx_dep_count = 0
        for ctx in self.contexts:
            ctx_dep_count += len(ctx.outgoing_dependencies)
        # print to console
        logger.info("####################")
        logger.info("# Context statistics: " + label)
        logger.info("# Context count: " + str(len(self.contexts)))
        logger.info("# Context deps:  " + str(ctx_dep_count))
        logger.info("####################")

    def __get_iteration_nodes(
        self, iteration_entry: TGStartIterationNode, iteration_exit: TGEndIterationNode
    ) -> Set[TGNode]:
        queue: Deque[TGNode] = deque([iteration_entry])
        visited: Set[TGNode] = set()
        iteration_nodes: Set[TGNode] = set()
        while len(queue) > 0:
            current_source = queue.popleft()
            visited.add(current_source)
            if nx.has_path(self.graph, current_source, iteration_exit):
                iteration_nodes.add(current_source)

            # do not consider successors of iteration end node
            if current_source == iteration_exit:
                continue
            # add successors of regular iteration nodes to the queue
            for succ in self.get_successors(current_source):
                if succ in queue or succ in visited:
                    continue
                queue.append(succ)
        return iteration_nodes

    def __validate_graph_structure(self) -> None:
        """Checks invariant 4 (see INVARIANTS.md): once __break_cycles and
        __duplicate_loop_iterations have run, every function's control flow must be acyclic - loops
        are unrolled into two linear iterations rather than kept as back edges. A remaining cycle
        means one of those passes gave up on it; __break_cycles does so silently when it cannot
        derive a loop header and its crude fallback runs out of search sources.

        Every later pass assumes acyclicity and none of them re-checks it, so the failures a
        remaining cycle causes surface far from here and look unrelated: dominance-based region
        wrapping is unsound, the context-nesting stack machine assigns whichever enclosing context
        a path happens to arrive with, and __calculate_context_successions does not terminate at
        all if the cycle's context entries and exits do not balance - it keys its traversal on
        (node, level), and each lap around such a cycle shifts the level by the imbalance, so every
        lap is a state it has not seen yet. That one presents as unbounded memory growth minutes
        later, which is what makes finding the cause from the symptom so expensive.

        Reported rather than raised: the results for the functions containing the cycle are
        unreliable either way, but the rest of the program is unaffected, and raising here would
        stop projects that currently produce (partially) usable suggestions. Turn the summary into
        a raise if a hard failure is preferred."""
        logger.info("Validating graph structure...")
        cyclic_components = [
            component for component in nx.strongly_connected_components(self.graph) if len(component) > 1
        ]
        self_loops = list(nx.selfloop_edges(self.graph))
        if len(cyclic_components) == 0 and len(self_loops) == 0:
            return

        enclosing_functions = self.__map_nodes_to_enclosing_functions()
        for source, _ in self_loops:
            logger.error(
                "Node %s in %s has an edge to itself.",
                source.get_label(),
                enclosing_functions.get(source, DETACHED_REGION),
            )
        detached = 0
        for component in cyclic_components:
            logger.error(self.__describe_cyclic_component(component, enclosing_functions))
            if all(node not in enclosing_functions for node in component):
                detached += 1

        logger.error(
            "%d cyclic region(s) and %d self-loop(s) remain in the control flow after cycle "
            "breaking and loop unrolling, violating invariant 4 (INVARIANTS.md). Results "
            "depending on the affected code are unreliable, and context succession calculation "
            "does not terminate at all on a cyclic region whose context entries and exits do not "
            "balance.",
            len(cyclic_components),
            len(self_loops),
        )
        if detached > 0:
            logger.error(
                "%d of those cyclic region(s) are not reachable from any function entry node, "
                "which is why they are still here: __break_cycles searches for cycles with "
                "nx.find_cycle(source=<function node>) and therefore cannot see them. Whatever "
                "detached them - it removes edges to break cycles and rewires predecessors - is "
                "the place to look, not the cycle breaking itself.",
                detached,
            )

    def __map_nodes_to_enclosing_functions(self) -> Dict[TGNode, str]:
        """Maps each node to the label of the first TGFunctionNode it is reachable from. Only built
        once a cycle has actually been found, since it costs one traversal per function."""
        enclosing: Dict[TGNode, str] = dict()
        for function_node in self.TGFunctionNode_pet_node_id_to_tg_node.values():
            for node in self.get_descendants(function_node):
                enclosing.setdefault(node, function_node.get_label())
        return enclosing

    def __describe_cyclic_component(self, component: Set[TGNode], enclosing_functions: Dict[TGNode, str]) -> str:
        """Names the function a cyclic region belongs to and reports the property that decides
        whether __calculate_context_successions can terminate on it: whether one lap around it
        enters as many contexts as it leaves."""
        functions = sorted({enclosing_functions.get(node, DETACHED_REGION) for node in component})
        description = "Cyclic control flow in " + ", ".join(functions) + ": %d nodes" % len(component)
        try:
            cycle = nx.find_cycle(self.graph.subgraph(component), orientation="original")
        except nx.NetworkXNoCycle:  # pragma: no cover - a component of size > 1 always has one
            return description
        entered = sum(1 for source, *_ in cycle if source.created_context is not None)
        left = sum(1 for source, *_ in cycle if self.__is_context_exit(source))
        description += ", example cycle of %d edges entering %d and leaving %d contexts" % (
            len(cycle),
            entered,
            left,
        )
        if entered != left:
            description += " (unbalanced by %d per lap - context succession calculation cannot terminate here)" % (
                entered - left
            )
        description += ": " + " -> ".join(source.get_label() for source, *_ in cycle[:8])
        if len(cycle) > 8:
            description += " -> ..."
        return description

    @staticmethod
    def __is_context_exit(node: TGNode) -> bool:
        return isinstance(
            node,
            (
                TGEndFunctionNode,
                TGEndLoopNode,
                TGEndIterationNode,
                TGEndBranchParentNode,
                TGEndBranchNode,
                TGEndWorkNode,
                TGEndInlinedFunctionNode,
            ),
        )

    def get_successors(self, node: Optional[TGNode]) -> List[TGNode]:
        if node is None:
            return []
        successors = list(dict.fromkeys(t for s, t in self.graph.out_edges(node)))
        ## DEBUG
        #        if node.get_label() == "3:34" and len(successors) > 1:
        #            print("SUCCESSORS: ", str([c.get_label() for c in successors]))
        #            plt.ioff()
        #            self.plot(highlight_nodes=[node] + successors)
        #            plt.pause(1)
        ## !DEBUG
        return successors

    def get_predecessors(self, node: Optional[TGNode]) -> List[TGNode]:
        if node is None:
            return []
        predecessors = list(dict.fromkeys(s for s, t in self.graph.in_edges(node)))
        return predecessors

    def get_closest_predecessors_with_matching_pet_node_id(
        self,
        node: Optional[TGNode],
        pet_node_id: PETNodeID,
        disallow_target_contexts: Set[Context],
        results_per_path: int = 1,
    ) -> Set[TGNode]:
        """Returns the predecessors with pet_node_id for each path starting from node in a set."""
        if node is None:
            return set()
        queue: List[Tuple[TGNode, int]] = [(n, results_per_path) for n in self.get_predecessors(node)]
        visited: Set[TGNode] = set(self.get_predecessors(node))
        result: Set[TGNode] = set()
        while len(queue) > 0:
            current_node, remaining_results_on_path = queue.pop()
            if current_node.pet_node_id == pet_node_id and type(current_node) == TGNode:
                if len(current_node.parent_context.intersection(disallow_target_contexts)) == 0:
                    # no overlap with disallowed contexts
                    result.add(current_node)
                    remaining_results_on_path -= 1
                    if remaining_results_on_path == 0:
                        # stop search on this path
                        continue
            for pred in self.get_predecessors(current_node):
                if pred not in visited:
                    visited.add(pred)
                    queue.append((pred, remaining_results_on_path))
        return result

    def get_descendants(self, node: TGNode) -> List[TGNode]:
        return list(nx.descendants(self.graph, node))

    def get_ancestors(self, node: TGNode) -> List[TGNode]:
        return list(nx.ancestors(self.graph, node))

    def is_ancestor(self, src_node: TGNode, tgt_node: TGNode) -> bool:
        """returns True, if tgt_node is an ancestor of src_node."""
        return tgt_node in self.get_ancestors(src_node)

    def print_graph_statistics(self, graph: Graph, label: str = "") -> None:
        cleaned_label = "" if len(label) == 0 else "(" + label + ")"
        logger.info("### Graph Statisticts " + cleaned_label + " ###")
        logger.info("--> Nodes: " + str(len(graph.nodes)))
        logger.info("--> Edges: " + str(len(graph.edges)))
        # logger.info("--> longest path length: " + str(nx.dag_longest_path_length(graph)))
        logger.info("#########################")

    def __copy_iteration_subgraph(
        self,
        copied_nodes: Dict[TGNode, TGNode],
        iteration_nodes: Set[TGNode],
        iteration_entry: TGNode,
        iteration_exit: TGNode,
    ) -> Tuple[Dict[TGNode, TGNode], List[TGNode], TGNode, TGNode]:
        if len(iteration_nodes) == 0:
            raise ValueError("Empty set of iteration nodes not supported as an argument!")
        copied_iteration_nodes: List[TGNode] = []
        # copy nodes
        for node in iteration_nodes:
            if node not in copied_nodes:
                node_copy = copy.deepcopy(node)
                self.add_node(node_copy)
                copied_nodes[node] = node_copy
            copied_iteration_nodes.append(copied_nodes[node])
        # copy edges

        for source in [
            n for n in iteration_nodes if n != iteration_exit
        ]:  # do not copy outgoing edges of the path exit
            for succ in self.get_successors(source):
                try:
                    self.add_edge(copied_nodes[source], copied_nodes[succ])
                except KeyError:
                    # plt.ioff()
                    # self.plot(highlight_nodes=[source, succ])
                    warnings.warn(
                        "could not draw edge between "
                        + source.get_label()
                        + " and "
                        + succ.get_label()
                        + " due to a KeyError"
                    )

        return copied_nodes, copied_iteration_nodes, copied_nodes[iteration_entry], copied_nodes[iteration_exit]

    def get_loop_header_context(self, loop: LoopParentContext) -> Optional[WorkContext]:
        candidates: List[WorkContext] = []
        for ctx_1 in loop.contained_contexts:
            if not type(ctx_1) == WorkContext:
                continue
            # find a context ctx_1 without predecessor, i.e, the entry into the loops body, thus the loop header
            is_loop_header = True
            for ctx_2 in loop.contained_contexts:
                if ctx_1 == ctx_2:
                    continue
                if ctx_1 == ctx_2.successor:
                    is_loop_header = False
                    break
            if not is_loop_header:
                continue
            else:
                return ctx_1
        return None
