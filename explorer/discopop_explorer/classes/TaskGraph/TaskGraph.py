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
from typing import Any, Deque, Dict, FrozenSet, List, Optional, Set, Tuple, Union, cast
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
from discopop_explorer.classes.PEGraph.Dependency import Dependency

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
    from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees
except (ImportError, ModuleNotFoundError):

    class Plottable:  # type: ignore[no-redef]
        def __init__(self, visualizer: object = None) -> None:
            pass

        def plottable(self) -> bool:
            return False

    Visualizer = object  # type: ignore[assignment, misc]
    ViewableCanvasWithTrees = object  # type: ignore[assignment, misc]

logger = logging.getLogger("Explorer")

# how __validate_graph_structure refers to code that no function entry node reaches any more
DETACHED_REGION = "a region not reachable from any function entry node"

# callpath state markers ("<line_id>@<state_id>") as emitted by the profiler into
# dynamic_dependencies.txt. Removing them is what --ignore-dependency-states does.
STATE_MARKER_PATTERN = re.compile(r"@\d+")


# Aliases
TGConstructionQueueElement = Tuple[Optional[TGNode], Union[PETNode, VisitorMarker]]  # (Predecessor, current element)


class TaskGraph(Plottable, object):  # type: ignore[misc]
    pet: PEGraphX
    graph: nx.MultiDiGraph
    # class-level default so instances created without __init__ (e.g. the test
    # fixtures, which bypass it) still read as "states are interpreted"
    ignore_dependency_states: bool = False
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

    def new_plot_context_debug_graph(self, canvas: ViewableCanvasWithTrees) -> None:
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

        canvas.build_trees(ctx_graph)

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

                    # add iteration entry markings between entry_node and iteration_entry_points
                    ism_list: List[TGStartIterationNode] = []

                    for itenp in iteration_entry_points:
                        self.graph.remove_edge(entry_node, itenp)
                        ism = TGStartIterationNode(
                            itenp.pet_node_id, itenp.level, itenp.position, entry_node.pet_node_id
                        )
                        # ism.loopstate_iteration_ids = [
                        #   0
                        # ]  # loop iterations will be duplicated later. loopstate_ids will be overwritten / set then.

                        ism_list.append(ism)
                        self.add_node(ism)
                        self.add_edge(entry_node, ism)
                        self.add_edge(ism, itenp)

                    # add iteration exit markings after iteration_exit_points
                    iem_list: List[TGEndIterationNode] = []
                    for itexp in iteration_exit_points:
                        iem = TGEndIterationNode(itexp.pet_node_id, itexp.level, itexp.position, entry_node.pet_node_id)
                        iem_list.append(iem)
                        self.add_node(iem)
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
                        if sin.pet_node_id != ein.pet_node_id:
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
                                    if (n.pet_node_id == sin.pet_node_id) and isinstance(n, TGStartIterationNode)
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
                                    if (n.pet_node_id == ein.pet_node_id) and isinstance(n, TGEndIterationNode)
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

                # find corresponding end iteration node for each start
                for sin in filtered_start_iteration_nodes:
                    #                    print("SIN: ", sin.get_label())
                    for ein in filtered_end_iteration_nodes:
                        #                        print("EIN: ", ein.get_label())
                        # only consider pairs with equal corresponding pet_node_id's
                        if sin.parent_loop_pet_node_id != ein.parent_loop_pet_node_id:
                            continue

                        # get iteration nodes
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
        """Assigns loopstate positions to loops within functions in their order of occurrence in the source code.
        This function MUST BE EXECUTED BEFORE inlining function calls."""
        logger.info("Assigning Loop state positions within functions...")

        entry_points: List[TGNode] = []
        for node in progress(self.graph.nodes):
            if isinstance(node, TGFunctionNode):
                entry_points.append(node)
        logger.info("--> Assigning loop state ids")
        for entry_point in progress(entry_points):
            # loop state position corresponds to the position of the iteration count for the specific loop within the "_loopstate"-information in the callpaths reported by the profiler
            # find all loops in function, sort them by location, and assign loopstate_positions.
            function_nodes = self.get_descendants(entry_point)
            loops = [n for n in function_nodes if isinstance(n, TGStartLoopNode)]
            loops_pet_nodes = list(dict.fromkeys([n.get_pet_node(self.pet) for n in loops]))
            cleaned_loops_pet_nodes = [lpn for lpn in loops_pet_nodes if lpn is not None]
            sorted_loops_pet_nodes = sorted(cleaned_loops_pet_nodes, key=lambda x: x.start_line)
            # assign loopstate_positions to PET node ids
            next_unused_position = 0
            assigned_loopstate_positions: Dict[PETNodeID, int] = dict()
            for l_pet in sorted_loops_pet_nodes:
                if l_pet.id in assigned_loopstate_positions:
                    continue
                assigned_loopstate_positions[l_pet.id] = next_unused_position
                next_unused_position += 1
            # assign loopstate positions to TGStartLoopNode's for later use
            for loop in loops:
                if loop.pet_node_id not in assigned_loopstate_positions:
                    raise KeyError("No entry in assigned_loopstate_positions for PET node id: " + str(loop.pet_node_id))
                loop.loopstate_position = assigned_loopstate_positions[loop.pet_node_id]

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

    def __determine_loop_variables(self) -> None:
        """determine loop variables."""
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
        call_path_limit = 6
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
        scope: Set[TGNode] = set(self.get_descendants(function_node))
        scope.add(function_node)

        def scoped_successors(node: TGNode) -> List[TGNode]:
            return [s for s in self.get_successors(node) if s in scope]

        # forward dominator tree
        dom_graph = nx.MultiDiGraph()
        dom_graph.add_nodes_from(scope)
        for node in scope:
            for succ in scoped_successors(node):
                dom_graph.add_edge(node, succ)
        idom = nx.immediate_dominators(dom_graph, function_node)

        # immediate post-dominator tree: reverse the graph and merge all sinks into one
        # virtual exit, so post-dominance reduces to ordinary dominance from that exit
        sinks = [node for node in scope if len(scoped_successors(node)) == 0]
        pdom_graph = dom_graph.reverse(copy=True)
        virtual_exit = object()
        pdom_graph.add_node(virtual_exit)
        for sink in sinks:
            pdom_graph.add_edge(virtual_exit, sink)
        ipdom = nx.immediate_dominators(pdom_graph, virtual_exit)

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
        function_body_nodes = self.get_descendants(inlined_function) + [inlined_function]
        # copy function body nodes
        for fbn in function_body_nodes:
            fbn_copy = copy.deepcopy(fbn)
            copied_nodes[fbn] = fbn_copy
            self.graph.add_node(fbn_copy)
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
                        # Every source/sink then reads as NO_STATE, which also reclassifies the
                        # affected dependencies from DYN_* to STAT_*.
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

                        # prepend DYN or STAT to the dependency type to distinguish between dynamic and static dependencies
                        if dep_is_dynamic_based_on_source or dep_is_dynamic_based_on_sink:
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
                                            check_source_state_id,
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
                                            check_source_state_id,
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

    def __assign_state_ids(self, dynamic_dependency_file: Optional[str]) -> None:
        """attaches state ids to Context nodes."""
        # read stateID to callpath mapping. States are filtered for observed states in dynamic dependency file to compress map slightly
        if dynamic_dependency_file is None:
            raise ValueError("Invalid Path!")
        state_mappings_dict = self.__get_state_mappings_from_file(dynamic_dependency_file)
        #        print("state_mappings_dict: ")
        #        for state_id in state_mappings_dict:
        #            print("->", state_id, " -> ", state_mappings_dict[state_id])

        def recursive_assignment(
            state_id: int,
            callstate: Tuple[str, ...],
            ctx: Context,
            memo: Dict[Tuple[int, Tuple[str, ...]], bool],
        ) -> bool:
            """assigns state_id to the matching states.
            Returns True, if state_id was assigned to at least one Context.
            Returns False otherwise.

            Results are memoized per state_id search on (context identity, incoming callstate).
            The function is deterministic in that pair, and its only side effect (appending
            state_id to matching contexts) is fully determined by it, so revisiting a cached pair
            would merely re-append the identical state_id to the identical contexts. Memoization
            therefore preserves the exact set of (context -> state_id) assignments while collapsing
            the otherwise exponential re-traversal of shared subtrees (contexts are reachable both
            directly via a parent's contained_contexts and via successor chains)."""
            # memoize on the INCOMING callstate (before any in-function rewriting below), keyed by
            # context identity. Different callstates reaching the same context are distinct keys.
            memo_key = (id(ctx), callstate)
            if memo_key in memo:
                return memo[memo_key]
            result = compute_assignment(state_id, callstate, ctx, memo)
            memo[memo_key] = result
            return result

        def compute_assignment(
            state_id: int,
            callstate: Tuple[str, ...],
            ctx: Context,
            memo: Dict[Tuple[int, Tuple[str, ...]], bool],
        ) -> bool:
            if len(callstate) == 0:
                return False

            if isinstance(ctx, FunctionContext):
                if "_loopstate" in callstate[0]:
                    # remove leading loopstate entries
                    callstate = tuple(
                        v for v in callstate if not ("_loopstate" in v and v.split("_loopstate")[1].isdigit())
                    )

                if ctx.parent_function is None:
                    raise ValueError("parent_function is None!")

                if len(callstate) > 0 and self.pet.node_at(ctx.parent_function).name == callstate[0]:
                    # HIT
                    callstate = callstate[1:]
                else:
                    # MISS
                    return False
            elif isinstance(ctx, IterationContext):
                if "_loopstate" in callstate[0]:
                    # check for matching loopstate id
                    # get current loopstate_info
                    loopstate_info = callstate[0].split("_loopstate")[1]
                    # check if parent is LoopParentContext. if not, MISS
                    if not isinstance(ctx.parent_context, LoopParentContext):
                        return False
                    # get loopstate_position
                    parent_loop_ctx = ctx.parent_context
                    loopstate_position = parent_loop_ctx.loopstate_position
                    if loopstate_position is None:
                        raise ValueError("loopstate position is None")
                    #                    logger.debug("loopstate_info: " + loopstate_info)
                    #                    logger.debug("loopstate_position: " + str(loopstate_position))

                    if (
                        loopstate_position + 1 <= len(loopstate_info)
                        and int(loopstate_info[loopstate_position]) in ctx.loopstate_iteration_ids
                    ):
                        # HIT LOOPSTATE
                        # replace iteration id with processed marker "4"
                        new_head = (
                            callstate[0][: callstate[0].index("_loopstate") + len("_loopstate") + loopstate_position]
                            + "4"
                            + callstate[0][
                                callstate[0].index("_loopstate") + 1 + loopstate_position + len("_loopstate") :
                            ]
                        )
                        callstate = (new_head,) + callstate[1:]
                        # check if search along this path is finished
                        if (
                            len(callstate) == 1
                            and "0" not in callstate[0].split("_loopstate")[1]
                            and "1" not in callstate[0].split("_loopstate")[1]
                            and "2" not in callstate[0].split("_loopstate")[1]
                        ):
                            # trigger setting of state id
                            callstate = callstate[1:]
                    else:
                        # missed loop state. continue search with successors
                        pass
                else:
                    # MISS (invalid)
                    return False
            elif isinstance(ctx, InlinedFunctionContext):
                if callstate[0].startswith("call_") and callstate[0][5:].isdigit():
                    # check for matching CallInstruction ID
                    call_instruction_id = int(callstate[0][5:])
                    #                    print(
                    #                        "FOUND InlinedFunctionContext "
                    #                        + str(ctx)
                    #                        + " at current callstate: "
                    #                        + str(callstate)
                    #                        + " with callInstID: "
                    #                        + str(ctx.call_instruction_id)
                    #                    )
                    if call_instruction_id == ctx.call_instruction_id:
                        # HIT CALL
                        callstate = callstate[1:]
                    else:
                        # MISS (invalid)
                        return False
                else:
                    # MISS (invalid)
                    return False

            # set state_id if necessary
            if len(callstate) == 0:
                ctx.state_ids.append(state_id)
                logger.debug("ADD state_id:" + str(state_id) + " to ctx: " + str(ctx))
                return True

            # continue assignment with children
            ret_val = False
            for child in ctx.get_contained_contexts():
                ret_val = ret_val or recursive_assignment(state_id, callstate, child, memo)
            # continue assignment with successors

            if ctx.successor is not None:

                ret_val = ret_val or recursive_assignment(state_id, callstate, ctx.successor, memo)
            return ret_val

        # assign state id to task_graph nodes
        logger.info("Assigning state ids to nodes...")
        # entry points are independent of the processed state; compute them once.
        entry_points: List[Context] = [c for c in self.contexts if isinstance(c, FunctionContext)]
        for state_id in progress(state_mappings_dict):
            #            print()
            #            print("Parsing state_id: ", state_id)
            #            print("CallState: ", state_mappings_dict[state_id])
            smd_entry = state_mappings_dict[state_id]
            # skip callstate ending with call element
            if (
                len(state_mappings_dict[state_id]) > 0
                and smd_entry[-1].startswith("call_")
                and smd_entry[-1].split("call_")[1].isdigit()
            ):
                #                print("skipping due to call at the end.")
                continue
            # cleanup callstate (shallow copy suffices: entries are immutable strings)
            callstate = list(smd_entry)
            #            # cleanup callstate (remove call_<int> markers)
            #            to_be_removed: List[int] = []
            #            for idx in range(0, len(callstate)):
            #                if callstate[idx].startswith("call_") and callstate[idx].split("call_")[1].isdigit():
            #                    to_be_removed.append(idx)
            #            for idx in sorted(to_be_removed, reverse=True):
            #                del callstate[idx]
            # cleanup callstate (compress multiple successive loopstates)
            if len(callstate) > 0:
                loopstate_indices: List[int] = []
                for idx in range(0, len(callstate)):
                    if "_loopstate" in callstate[idx]:
                        loopstate_indices.append(idx)
                to_be_removed: List[int] = []
                for idx, val in enumerate(loopstate_indices):
                    if idx >= len(loopstate_indices) - 1:
                        continue
                    # check next registered loopstate info is a direct successor of the current one.
                    # if so, the current enty can be omitted
                    if val + 1 == loopstate_indices[idx + 1]:
                        to_be_removed.append(val)
                for tbr in sorted(to_be_removed, reverse=True):
                    del callstate[tbr]

            #            print("Clean CallState: ", callstate)
            callstate_tuple: Tuple[str, ...] = tuple(callstate)
            # memoize (context, incoming callstate) -> result within this state's search only.
            # See recursive_assignment for why this preserves the assignment side effects.
            memo: Dict[Tuple[int, Tuple[str, ...]], bool] = {}
            could_be_assigned: bool = False
            for entry_point in entry_points:
                could_be_assigned = could_be_assigned or recursive_assignment(
                    int(state_id), callstate_tuple, entry_point, memo
                )

    #            if not could_be_assigned:
    #                print("-> Not assigned!")

    #        ax = self.create_plot("Context Graph")
    #        self.plot_context_graph(ax)
    #        self.run_visualizer()

    #        import sys
    #        sys.exit(0)

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
    ) -> Set[Context]:
        """instructionID_mappings_dict is a mapping from instructionIDs to lineIDs. This should be removed in the long run, when instructionIDs become the default over lineIDs.
        state_mappings_dict is a mapping from stateIDs to callpaths.
        location_to_work_contexts is a reverse index {lineID: WorkContexts whose code scope contains it},
        built once per dependency-insertion pass (see __insert_data_dependencies_from_files).
        state_ids_cache memoizes get_state_ids per context for the duration of that pass."""

        #        cache_key = (location, state_id)
        #        if cache_key in lookup_cache:
        #            return lookup_cache[cache_key]

        contexts: Set[Context] = set()
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
            dep_origin = DepOrigin.STATIC_ANALYSIS if is_static_dep_type else DepOrigin.DYNAMIC_ANALYSIS

            for source_location, source_location_deps in progress(
                dep_type_deps.items(), desc="Source locations", leave=False
            ):
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
                    )
                    for sink_location, sink_location_deps in source_state_deps.items():
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
                            )
                            # the variable name and the memory region depend on the entry alone,
                            # but used to be parsed again for every pair of contexts
                            parsed_var_infos: List[Tuple[str, Optional[MemoryRegion]]] = [
                                (
                                    var_info if "(" not in var_info else var_info.split("(")[0],
                                    None if "(" not in var_info else MemoryRegion(var_info.split("(")[1].strip(")")),
                                )
                                for var_info in var_infos
                            ]

                            # handle static and dynamic dependencies separately
                            if is_static_dep_type:
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
                                            # print("SKIPPING POTENTIAL DEP: ", dep_type, var_infos)
                                            continue
                                        target_closest_fn = closest_function_ancestor(target_ctx)
                                        if target_closest_fn is None:
                                            # no shared parent function context can exist
                                            continue
                                        if source_closest_fn != target_closest_fn:
                                            # closest parent function contexts are not equal.
                                            # static dependencies are only valid within a functions scope.
                                            continue

                                        for var_name, memory_region in parsed_var_infos:
                                            dependency = Dependency(type=EdgeType.DATA)
                                            dependency.dtype = dep_type_enum_obj
                                            dependency.var_name = var_name
                                            dependency.memory_region = memory_region
                                            dependency.origin = dep_origin

                                            source_ctx.register_outgoing_dependency(target_ctx, dependency)
                            else:
                                # dynamic dependencies are allowed to leave the current function
                                # register dependencies between all pairs of source and target contexts
                                #
                                # prevent false positive dependencies in case of same iterations by checking for same ancestors
                                # TODO: add states to contexts to allow a more robust search in __get_work_contexts_by_location_and_state_id
                                # TODO: The fact the following condition is necessary is a result of incorrect behavior of __get_work_contexts_by_location_and_state_id, which should be fixed!
                                same_state = source_state_id == sink_state_id
                                for source_ctx in source_contexts:
                                    source_ancs = ancestors_from_closest_iteration(source_ctx) if same_state else []
                                    for target_ctx in target_contexts:
                                        if source_ctx == target_ctx:
                                            continue
                                        if same_state:
                                            # both pruned to their closest iteration context, so that
                                            # source and target are required to be in the same iteration
                                            if source_ancs != ancestors_from_closest_iteration(target_ctx):
                                                continue
                                        for var_name, memory_region in parsed_var_infos:
                                            dependency = Dependency(type=EdgeType.DATA)
                                            dependency.dtype = dep_type_enum_obj
                                            dependency.var_name = var_name
                                            dependency.memory_region = memory_region
                                            dependency.origin = dep_origin

                                            if dependency.var_name == "error":
                                                print(
                                                    "REGISTER DEP: ",
                                                    source_ctx,
                                                    target_ctx,
                                                    dependency.dtype,
                                                    dependency.source_line,
                                                    dependency.sink_line,
                                                    dependency.var_name,
                                                )
                                                print("source: ", source_ctx)
                                                print("source_ancs: ", source_ctx.get_ancestor_contexts())
                                                print("sink: ", target_ctx)
                                                print("sink ancs:", target_ctx.get_ancestor_contexts())
                                                print("source_state: ", source_state_id)
                                                print("sink_state: ", sink_state_id)
                                                print("source_location: ", source_location)
                                                print("sink_location: ", sink_location)
                                                print("source_states: ", source_ctx.get_state_ids())
                                                print("sink_states: ", target_ctx.get_state_ids())
                                                print()
                                            source_ctx.register_outgoing_dependency(target_ctx, dependency)

        logger.info(
            "Inserting data dependencies from files: "
            + str(dynamic_dependency_file)
            + ", "
            + str(static_dependency_file)
            + " completed."
        )

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
