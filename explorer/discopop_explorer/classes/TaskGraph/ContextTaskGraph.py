# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
from collections import deque
from typing import Deque, Dict, List, Optional, Set, Tuple, cast
import warnings
from matplotlib import pyplot as plt
import networkx as nx  # type: ignore
from matplotlib.axes import Axes
from networkx import Graph

from discopop_explorer.classes.ContextTaskGraph.classes.edges import (
    CTGEdgeInfo,
    CTGEdgeType,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_edges.partial_transitive_reduction import (
    partial_transitive_reduction,
)
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_edges.break_triangles import (
    break_triangles,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_nodes.merge_only_childs_with_parents import (
    merge_only_childs_with_parents,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_nodes.replace_trivial_branched_region import (
    replace_trivial_branched_region,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_nodes.replace_trivial_task_region import (
    replace_trivial_task_region,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.inflate_nodes.split_taskable_control_sequence import (
    split_taskable_control_sequence,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_nodes.trivial_control_sequence_simplification import (
    trivial_control_sequence_simplification,
)
from discopop_explorer.classes.ContextTaskGraph.modifications.remove_nodes.merge_only_childs_without_successors_with_parents import (
    merge_only_childs_without_successors_with_parents,
)
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import (
    BranchingParentContext,
)
from discopop_explorer.classes.TaskGraph.Contexts.BranchContext import BranchContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import (
    InlinedFunctionContext,
)
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import (
    TaskParentContext,
)
from discopop_explorer.classes.TaskGraph.Contexts.TaskEndContext import TaskEndContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import (
    LoopParentContext,
)
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import (
    IterationContext,
)
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph

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

import matplotlib.lines as mlines
import plotille  # type: ignore

from discopop_explorer.classes.ContextTaskGraph.modifications.computationally_expensive.transitive_reduction import (
    transitive_reduction,
)
from discopop_library.StatusReporting.console import progress, stage

logger = logging.getLogger("Explorer")


class ContextTaskGraph(Plottable, object):  # type: ignore[misc]
    pet: PEGraphX
    task_graph: TaskGraph
    graph: nx.DiGraph
    edge_information: Dict[Context, Dict[Context, List[CTGEdgeInfo]]] = dict()
    imaginary_replacement_edges: Dict[Context, List[Context]] = dict()
    inverse_imaginary_replacement_edges: Dict[Context, List[Context]] = dict()

    def __init__(self, task_graph: TaskGraph, visualizer: Visualizer | None = None) -> None:
        super().__init__(visualizer)

        self.pet = task_graph.pet
        self.task_graph = task_graph
        self.graph = nx.MultiDiGraph()
        # start processing
        with stage("Constructing ContextTaskGraph"):
            self.__construct_from_task_graph()

    def __construct_from_task_graph(self) -> None:
        """convert the given task graph to a ContextTaskGraph for Task detection. The created graph will be used to determine Forks, Barriers, and Tasks."""
        for ctx in progress(self.task_graph.contexts, desc="Adding context nodes"):
            self.add_node(ctx)

        # add edges based on task graph successors
        for tg_node in self.task_graph.graph.nodes:
            if tg_node.created_context is None:
                continue
            successor_contexts: List[Context] = []
            queue = self.task_graph.get_successors(tg_node)
            visited_tg_nodes: Set[TGNode] = set(queue)
            while len(queue) > 0:
                current = queue.pop()
                if current.created_context is not None:
                    successor_contexts.append(current.created_context)
                    continue
                for nd in self.task_graph.get_successors(current):
                    if nd not in visited_tg_nodes:
                        visited_tg_nodes.add(nd)
                        queue.append(nd)
            for succ_ctx in successor_contexts:
                self.add_edge(
                    tg_node.created_context,
                    succ_ctx,
                    edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL),
                )

        # Extract branched sections
        if False:
            raw_branching_contexts: Deque[Context] = deque()
            for node in self.graph.nodes():
                if isinstance(node, BranchingParentContext):
                    raw_branching_contexts.append(node)

            finished_branching_context: List[Context] = []
            replacements: Dict[Context, Context] = dict()
            while len(raw_branching_contexts) > 0:
                current_branching_context = raw_branching_contexts.popleft()
                # skip, if current_branching_context contains branching contexts
                contained_contexts = current_branching_context.get_contained_contexts(inclusive=True)
                contains_branched_section = (
                    len(
                        [
                            ctx
                            for ctx in contained_contexts
                            if isinstance(ctx, BranchingParentContext) and (ctx not in finished_branching_context)
                        ]
                    )
                    > 0
                )
                if contains_branched_section:
                    raw_branching_contexts.append(current_branching_context)
                    continue
                # found trivial branching context
                replacement_node = WorkContext()
                self.add_node(replacement_node)
                if current_branching_context.parent_context is not None:
                    replacement_node.parent_context = current_branching_context.parent_context
                    replacement_node.parent_context.add_contained_context(replacement_node)

                # redirect edges to replacement_node
                outside_predecessors = self.get_predecessors(current_branching_context)
                for pred in outside_predecessors:
                    self.graph.remove_edge(pred, current_branching_context)
                    self.add_edge(
                        pred,
                        replacement_node,
                        edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL),
                    )
                for node in contained_contexts:
                    for succ in self.get_successors(node):
                        if succ not in contained_contexts:
                            #            outside_successors.add(succ)
                            self.graph.remove_edge(node, succ)
                            self.add_edge(
                                replacement_node,
                                succ,
                                edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL),
                            )
                # register replacements
                for node in contained_contexts:
                    replacements[node] = replacement_node

                finished_branching_context.append(current_branching_context)
                # register non-existing dashed edge for plotting purposes only
                if replacement_node not in self.imaginary_replacement_edges:
                    self.imaginary_replacement_edges[replacement_node] = []
                if current_branching_context not in self.inverse_imaginary_replacement_edges:
                    self.inverse_imaginary_replacement_edges[current_branching_context] = []
                self.imaginary_replacement_edges[replacement_node].append(current_branching_context)
                self.inverse_imaginary_replacement_edges[current_branching_context].append(replacement_node)

        # reconnect graph by:
        #  - removing successor edges
        #  - add contains edges ignoring BranchParents as targets
        #  - removing outgoing edges from BranchParents, saving imaginary connection
        #  - enforce a single landing pad per entry point

        # TEST
        #  - calculate connected components
        #  - find entry point for each component
        #  - find replacement node for each component
        #  - add intra-component dependency edges
        #  - add inter-component dependency edges (to and from replacement nodes)

        # Save successor edges
        saved_successors: Dict[Context, List[Context]] = dict()
        for node in self.graph.nodes:
            saved_successors[node] = self.get_successors(node)

        # remove successor edges
        # self.graph.clear_edges()

        # add contains edges ignoring BranchParents as targets
        for ctx in self.graph.nodes:
            for contained_ctx in cast(Context, ctx).get_contained_contexts(inclusive=False):
                if isinstance(contained_ctx, BranchingParentContext):
                    continue
                self.add_edge(ctx, contained_ctx, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

        # remove outgoing edges from BranchParent, saving imaginary connection
        if False:
            for node in self.graph.nodes:
                if isinstance(node, BranchingParentContext):
                    for succ in self.get_successors(node):
                        self.graph.remove_edge(node, succ)
                        if node not in self.imaginary_replacement_edges:
                            self.imaginary_replacement_edges[node] = []
                        if succ not in self.inverse_imaginary_replacement_edges:
                            self.inverse_imaginary_replacement_edges[succ] = []
                        self.imaginary_replacement_edges[node].append(succ)
                        self.inverse_imaginary_replacement_edges[succ].append(node)

        # enforce a single landing pad per entry point
        entry_points: List[Context] = []
        for ctx in self.graph.nodes:
            if len(self.get_predecessors(ctx)) == 0:
                entry_points.append(ctx)
        for entry in entry_points:
            exit_points: List[Context] = []
            for node in nx.descendants(self.graph, entry):
                if len(self.get_successors(node)) == 0:
                    exit_points.append(node)
            if len(exit_points) > 1:
                landing_pad = WorkContext()
                self.graph.add_node(landing_pad)
                for exit in exit_points:
                    self.graph.add_edge(exit, landing_pad)

        # TEST
        #  - calculate connected components
        # Note: connected_components is a generator!
        connected_components = nx.weakly_connected_components(self.graph)

        #  - find entry point for each component
        component_entry_points: Dict[Tuple[Context, ...], Context] = dict()
        for comp in connected_components:
            for ctx in comp:
                if len(self.get_predecessors(ctx)) == 0:
                    component_entry_points[tuple(comp)] = ctx
                    break
        #  - find replacement nodes for each component
        component_replacements_dict: Dict[Tuple[Context, ...], List[Context]] = dict()
        for comp in component_entry_points:
            entry_point = component_entry_points[comp]
            component_replacements: List[Context] = []
            replacement_candidates: Deque[Context] = deque([entry_point])
            visited: List[Context] = []
            while len(replacement_candidates) > 0:
                candidate = replacement_candidates.popleft()
                visited.append(candidate)

                # check if candidate is instance of WorkNode and not a trivial solution
                if isinstance(candidate, WorkContext):
                    if candidate == entry_point:
                        # trivial solution, ignore, if another solution is possible
                        if candidate in self.inverse_imaginary_replacement_edges:
                            replacement_candidates += [
                                c
                                for c in self.inverse_imaginary_replacement_edges[candidate]
                                if c not in replacement_candidates and c not in visited
                            ]
                    else:
                        # found replacement node
                        component_replacements.append(candidate)
                else:
                    # continue searching for replacement node if possible
                    if candidate in self.inverse_imaginary_replacement_edges:

                        replacement_candidates += [
                            c
                            for c in self.inverse_imaginary_replacement_edges[candidate]
                            if c not in replacement_candidates and c not in visited
                        ]
                    else:
                        # no further step upwards possible. Use the current solution
                        pass
            component_replacements_dict[comp] = list(dict.fromkeys(component_replacements))

        # calculate inverse component dictionary
        inverse_component_dict: Dict[Context, Tuple[Context, ...]] = dict()
        for comp in component_replacements_dict:
            for ctx in comp:
                inverse_component_dict[ctx] = comp

        #  - add intra-component dependency edges
        for ctx in progress(self.graph.nodes):
            ctx_parent_component = inverse_component_dict[ctx]
            for sink_ctx, dep in ctx.outgoing_dependencies:
                sink_ctx_parent_component = inverse_component_dict[sink_ctx]
                if ctx_parent_component != sink_ctx_parent_component:
                    # not an intra-component dependency
                    continue
                # intra-component dependency
                self.add_edge(sink_ctx, ctx, edge_info=CTGEdgeInfo(CTGEdgeType.DATA, dep_obj=dep))
                # print("ADDED Intra component dependency: ", dep.sink_line, dep.source_line, dep.dtype, dep.var_name)

        #  - add inter-component dependency edges (to and from replacement nodes)
        logger.debug("--> Add inter-component dependency edges (inward)")
        for ctx in progress(self.graph.nodes):
            ctx_parent_component = inverse_component_dict[ctx]
            for sink_ctx, dep in ctx.outgoing_dependencies:
                sink_ctx_parent_component = inverse_component_dict[sink_ctx]
                if sink_ctx_parent_component == ctx_parent_component:
                    # intra-component dependency
                    continue
                # inter-component dependency
                # check if sink_ctx_parent_component is a parent of ctx_parent_component
                sink_is_parent_of: Optional[Context] = None
                # copy: the dict entry must not be consumed by the walk, it is read again for
                # every other ctx. Visited set: the replacement relation is not guaranteed to be
                # acyclic, and "not in candidates" alone only rejects duplicates that are still
                # queued, so an already-processed candidate could be re-enqueued forever.
                candidates = list(component_replacements_dict[ctx_parent_component])
                visited_candidates: Set[Context] = set(candidates)
                while len(candidates) > 0:
                    current_candidate = candidates.pop(0)
                    if inverse_component_dict[current_candidate] == sink_ctx_parent_component:
                        # sink_ctx_parent_component is a parent of ctx_parent_component
                        sink_is_parent_of = current_candidate
                        break
                    for c in component_replacements_dict[inverse_component_dict[current_candidate]]:
                        if c not in visited_candidates:
                            visited_candidates.add(c)
                            candidates.append(c)

                if sink_is_parent_of is not None:
                    # inward dependency found
                    self.add_edge(
                        sink_ctx,
                        sink_is_parent_of,
                        edge_info=CTGEdgeInfo(CTGEdgeType.DATA, dep_obj=dep),
                    )

        logger.debug("--> Add inter-component dependency edges (outward)")
        for ctx in progress(self.graph.nodes):
            ctx_parent_component = inverse_component_dict[ctx]
            for sink_ctx, dep in ctx.outgoing_dependencies:
                sink_ctx_parent_component = inverse_component_dict[sink_ctx]
                if sink_ctx_parent_component == ctx_parent_component:
                    # intra-component dependency
                    continue
                # inter-component dependency
                # check if ctx_parent_component is a parent of sink_ctx_parent_component
                source_is_parent_of: Optional[Context] = None
                # see the inward walk above for why this copies and tracks visited candidates
                candidates = list(component_replacements_dict[sink_ctx_parent_component])
                visited_candidates = set(candidates)
                while len(candidates) > 0:
                    current_candidate = candidates.pop(0)
                    if inverse_component_dict[current_candidate] == ctx_parent_component:
                        # ctx_parent_component is a parent of sink_ctx_parent_component
                        source_is_parent_of = current_candidate
                        break
                    for c in component_replacements_dict[inverse_component_dict[current_candidate]]:
                        if c not in visited_candidates:
                            visited_candidates.add(c)
                            candidates.append(c)

                if source_is_parent_of is not None:
                    # outward dependency found
                    self.add_edge(
                        sink_is_parent_of,
                        sink_ctx,
                        edge_info=CTGEdgeInfo(CTGEdgeType.DATA, dep_obj=dep),
                    )  # TODO CHECK!
                    logger.debug("ADDED OUTWARD DEPENDENCY")

        # add contained edges. absence of all successor edges might allow searching for parallelism
        if True:
            logger.info("--> Add contained edges...")
            for ctx in progress(self.task_graph.contexts):
                for sink_ctx in ctx.get_contained_contexts():
                    # check if sink_ctx is an entry to a successor sequence
                    if sink_ctx.predecessor is None:
                        self.add_edge(ctx, sink_ctx, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

        return

        # filling the structure with successor edges
        targets: Set[Context] = set()
        for source in saved_successors:
            for target in saved_successors[source]:
                if len(self.get_predecessors(target)) == 0:
                    targets.add(target)

        for source in saved_successors:
            for target in saved_successors[source]:
                if target not in targets:
                    continue
                self.add_edge(source, target, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

        return

        logger.info("--> Add dependencies on called functions...")
        for ctx in progress(self.task_graph.contexts):
            for sink_ctx in ctx.get_contained_contexts():
                if isinstance(sink_ctx, InlinedFunctionContext):
                    self.add_edge(ctx, sink_ctx, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

        # TODO Branching durch WORK knoten ersetzen. Branches individuell analysieren
        logger.info("--> Add dependencies to force synchronization at exit nodes via synthetic landing pads...")
        required_synthetic_landing_pads: List[List[Context]] = []
        for ctx in progress(self.graph.nodes):
            # filter for entry nodes
            ## TODO: REMOVE THE INSTANCE CHECKS, make sure the graph structure is correct!
            if len(self.get_predecessors(ctx)) != 0 or not (
                isinstance(ctx, WorkContext) or isinstance(ctx, FunctionContext)
            ):
                continue
            # found entry node
            # get descendants without successors, aka leaf nodes
            leaf_nodes: List[Context] = []
            for desc in nx.descendants(self.graph, ctx):
                if len(self.get_successors(desc)) != 0:
                    continue
                # found leaf node
                leaf_nodes.append(desc)
            # register a synthetic landing pad for later creation
            if len(leaf_nodes) > 1:
                required_synthetic_landing_pads.append(leaf_nodes)
        # create synthetic landing pads
        for leaf_nodes in required_synthetic_landing_pads:
            landing_pad = WorkContext()
            self.add_node(landing_pad)
            for leaf in leaf_nodes:
                self.add_edge(leaf, landing_pad, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))
            logger.info("----> Added synthetic landing pad")

    #        # DEBUG - TO BE REMOVED
    #        cleaning_found = True
    #        while cleaning_found:
    #            cleaning_found = False
    #            for node in self.graph.nodes:
    #                if len(self.get_predecessors(node)) == 0 and not (isinstance(node, WorkContext) or isinstance(node, FunctionContext)):
    #                    self.graph.remove_node(node)
    #                    cleaning_found = True
    #                    break
    #        # !DEBUG

    def simplify_graph(self) -> List[TaskParentContext]:
        """Execute the simplification pipeline.
        Inner iteration are cheap, local analysis steps.
        Outer iterations are expensive, path based analysis steps.
        Returns a list of identified TaskParentContexts
        """
        identified_tasks: List[TaskParentContext] = []

        statistics_current_step = 0
        statistics_time_series_x_values: List[int] = [statistics_current_step]
        statistics_time_series_node_count: List[int] = [len(self.graph.nodes)]
        statistics_time_series_edge_count: List[int] = [len(self.graph.edges)]
        statistics_time_series_outer_epoch_markers: List[int] = []
        statistics_time_series_inner_epoch_markers: List[int] = []
        statistics_current_step += 1

        # TODO: measure execution time and size differences per executed simplification step. Plot both in the Terminal.
        # TODO: plot total time impact of each applied simplification step as well as average.
        # TODO: consider plot of graph statistics over time (nodes, edges, depth?)
        # TODO: Consider adding a plot for the distrbution of found patterns over time / simplification step.
        # TODO: Consider plotting online statistics (especially interesting for larger software)
        self.__print_graph_statistics("Pre simplification")

        # Safety bound on the fixpoint iteration. Every simplification step is supposed to make
        # the graph strictly smaller, which bounds the number of productive iterations by the
        # initial size - but split_taskable_control_sequence *adds* nodes, and the steps interact,
        # so that is an assumption about six mutually recursive passes rather than something the
        # code enforces. If two steps ever start undoing each other, this turns a silent hang into
        # a warning plus a usable (if less reduced) result.
        iteration_budget = max(1000, len(self.graph.nodes) + len(self.graph.edges))
        budget_exhausted = False

        outer_modification_applied = True
        while outer_modification_applied and not budget_exhausted:
            outer_modification_applied = False

            inner_modification_applied = True
            while inner_modification_applied and not budget_exhausted:
                inner_modification_applied = False

                iteration_budget -= 1
                if iteration_budget <= 0:
                    logger.warning(
                        "ContextTaskGraph simplification did not reach a fixpoint within its "
                        "iteration budget and was stopped early. The simplification steps are "
                        "likely undoing each other. Continuing with the partially simplified "
                        "graph (%d nodes, %d edges).",
                        len(self.graph.nodes),
                        len(self.graph.edges),
                    )
                    budget_exhausted = True
                    break

                if True:
                    # note: THIS IS A WORK IN PROGRESS, NOT SURE IT IS BENEFICIAL!
                    # split control sequences into tasks
                    stcs_res, identified_tasks = split_taskable_control_sequence(self, identified_tasks)
                    if stcs_res:
                        self.__print_graph_statistics("Post split taskable work sequence")
                    else:
                        logger.debug("No effect: split taskable work sequence")
                    inner_modification_applied = inner_modification_applied or stcs_res
                    statistics_time_series_x_values.append(statistics_current_step)
                    statistics_current_step += 1
                    statistics_time_series_node_count.append(len(self.graph.nodes))
                    statistics_time_series_edge_count.append(len(self.graph.edges))

                    # todo: replace trivial task region with CombinedContext
                    if True:
                        rttr_res = replace_trivial_task_region(self)
                        if rttr_res:
                            self.__print_graph_statistics("Post replace trivial task region")
                        else:
                            logger.debug("No effect: replace trivial task region")
                        inner_modification_applied = inner_modification_applied or rttr_res
                        statistics_time_series_x_values.append(statistics_current_step)
                        statistics_current_step += 1
                        statistics_time_series_node_count.append(len(self.graph.nodes))
                        statistics_time_series_edge_count.append(len(self.graph.edges))

                # todo: replace "trivial" BranchParent with CombinedContext (trivial: both branches consist of exaclty one node)

                # merge only-childs without successors with parents
                # Note: this is not really effective and leads to a lot more iterations
                if False:
                    mocwos_res = merge_only_childs_without_successors_with_parents(self)
                    if mocwos_res:
                        self.__print_graph_statistics(
                            "Post merge only-childs without successors with parents", color="yellow"
                        )
                    else:
                        logger.debug("No effect: merge only-childs without successors with parents")
                    inner_modification_applied = inner_modification_applied or mocwos_res
                    statistics_time_series_x_values.append(statistics_current_step)
                    statistics_current_step += 1
                    statistics_time_series_node_count.append(len(self.graph.nodes))
                    statistics_time_series_edge_count.append(len(self.graph.edges))

                # todo: non-trivial sequence combination (latter node has incoming dependencies)

                # todo: redirect incoming CONTROL edges of tasks to taskParent? CHECK THIS

                if True:
                    css_res = trivial_control_sequence_simplification(self)
                    if css_res:
                        self.__print_graph_statistics(
                            "Post trivial_control sequence simplification",
                        )
                    else:
                        logger.debug("No effect: trivial_control sequence simplification")
                    inner_modification_applied = inner_modification_applied or css_res
                    statistics_time_series_x_values.append(statistics_current_step)
                    statistics_current_step += 1
                    statistics_time_series_node_count.append(len(self.graph.nodes))
                    statistics_time_series_edge_count.append(len(self.graph.edges))

                if True:
                    bt_res = break_triangles(self)
                    if bt_res:
                        self.__print_graph_statistics("Post break triangles")
                    else:
                        logger.debug("No effect: break triangles")
                    inner_modification_applied = inner_modification_applied or bt_res
                    statistics_time_series_x_values.append(statistics_current_step)
                    statistics_current_step += 1
                    statistics_time_series_node_count.append(len(self.graph.nodes))
                    statistics_time_series_edge_count.append(len(self.graph.edges))

                if True:
                    rtbr_res = replace_trivial_branched_region(self)
                    if rtbr_res:
                        self.__print_graph_statistics("Post replace trivial branched regions")
                    else:
                        logger.debug("No effect: replace trivial branched regions")
                    inner_modification_applied = inner_modification_applied or rtbr_res
                    statistics_time_series_x_values.append(statistics_current_step)
                    statistics_current_step += 1
                    statistics_time_series_node_count.append(len(self.graph.nodes))
                    statistics_time_series_edge_count.append(len(self.graph.edges))

                # add inner epoch marker to plot
                statistics_time_series_inner_epoch_markers.append(statistics_current_step)

            if inner_modification_applied:
                outer_modification_applied = True

            # todo: implement removal of all redundant edges. This is mainly for evaluation purposes.
            # Not sure if it will stay active, maybe as a step after stalled iterations.
            # Problem: full transitive reduction is quite costly.
            if False:
                rre_res = transitive_reduction(self)
                if rre_res:
                    self.__print_graph_statistics("Post remove redundant edges")
                else:
                    logger.debug("No effect: remove redundant edges")
                outer_modification_applied = outer_modification_applied or rre_res
                statistics_time_series_x_values.append(statistics_current_step)
                statistics_current_step += 1
                statistics_time_series_node_count.append(len(self.graph.nodes))
                statistics_time_series_edge_count.append(len(self.graph.edges))

            if True:
                ptr_res = partial_transitive_reduction(self)
                if ptr_res:
                    self.__print_graph_statistics("Post partial transitive reduction")
                else:
                    logger.debug("No effect: partial transitive reduction")
                outer_modification_applied = outer_modification_applied or ptr_res
                statistics_time_series_x_values.append(statistics_current_step)
                statistics_current_step += 1
                statistics_time_series_node_count.append(len(self.graph.nodes))
                statistics_time_series_edge_count.append(len(self.graph.edges))

            # merge only-childs with successors with parents
            if True:
                moc_res = merge_only_childs_with_parents(self)
                if moc_res:
                    self.__print_graph_statistics("Post merge only-childs with parents")
                else:
                    logger.debug("No effect: merge only-childs with parents")
                outer_modification_applied = outer_modification_applied or moc_res
                statistics_time_series_x_values.append(statistics_current_step)
                statistics_current_step += 1
                statistics_time_series_node_count.append(len(self.graph.nodes))
                statistics_time_series_edge_count.append(len(self.graph.edges))

            # add epoch marker to plot
            statistics_time_series_outer_epoch_markers.append(statistics_current_step)

        self.__print_graph_statistics("Post simplification")

        # OLD IMPLEMENTATION. BREAK TRIANGLES IS SIMPLER AND MORE ELEGANT
        # self.__replace_triangles()

        self.__plot_time_series(
            statistics_time_series_x_values,
            statistics_time_series_node_count,
            statistics_time_series_edge_count,
            statistics_time_series_outer_epoch_markers,
            statistics_time_series_inner_epoch_markers,
        )

        return identified_tasks

    def __plot_time_series(
        self,
        time_series_x_values: List[int],
        time_series_node_counts: List[int],
        time_series_edge_counts: List[int],
        time_series_outer_epoch_markers: List[int],
        time_series_inner_epoch_markers: List[int],
    ) -> None:
        if (
            len(time_series_x_values) == 0
            or len(time_series_node_counts) == 0
            or len(time_series_edge_counts) == 0
            or len(time_series_outer_epoch_markers) == 0
            or len(time_series_inner_epoch_markers) == 0
        ):
            logger.warning("Invalid arguments given to ContextTaskGraph.__plot_time_series. Skipping.")
            return

        fig = plotille.Figure()
        fig.height = 30
        fig.width = 60
        fig.x_label = "Simplification step"
        fig.y_label = "Count"
        # add time series
        fig.plot(
            time_series_x_values,
            time_series_node_counts,
            interp="linear",
            lc="green",
            label="Nodes",
        )
        fig.plot(
            time_series_x_values,
            time_series_edge_counts,
            interp="linear",
            lc="yellow",
            label="Edges",
        )
        # add outer epoch markers
        max_x_val = max(time_series_x_values)
        for outer_epoch_marker in time_series_outer_epoch_markers:
            if outer_epoch_marker > max_x_val:
                outer_epoch_marker = max_x_val
            fig.axvline(x=outer_epoch_marker / max_x_val, ymin=0, ymax=1, lc="blue")
        # add inner epoch markers
        for inner_epoch_marker in time_series_inner_epoch_markers:
            if inner_epoch_marker > max_x_val:
                inner_epoch_marker = max_x_val
            fig.axvline(x=inner_epoch_marker / max_x_val, ymin=0, ymax=1)
        print(fig.show(legend=True))

    def __print_graph_statistics(self, label: str = "") -> None:
        logger.debug(f"Graph statistics ({label}): {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")

    def get_predecessors(self, node: Optional[Context]) -> List[Context]:
        if node is None:
            return []
        predecessors = list(dict.fromkeys(s for s, t in self.graph.in_edges(node)))
        return predecessors

    def get_successors(self, node: Optional[Context]) -> List[Context]:
        if node is None:
            return []
        successors = list(dict.fromkeys(t for s, t in self.graph.out_edges(node)))
        return successors

    def plot(self, highlight_nodes: Optional[List[Context]] = None) -> None:
        import tkinter as tk
        import numpy as np
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # type: ignore
        from matplotlib.figure import Figure

        root = tk.Tk()
        root.title("Context Task Graph")

        def close_window() -> None:
            root.quit()
            root.destroy()

        frame1 = tk.Frame(root)
        fig1 = Figure()  # Figure(figsize=(5, 4))

        ax1 = fig1.add_subplot(111)
        ax1.set_title("Context Task Graph")
        canvas1 = FigureCanvasTkAgg(fig1, master=frame1)
        canvas1.draw()
        canvas1.get_tk_widget().grid(row=0, sticky="nsew")
        toolbar1 = NavigationToolbar2Tk(canvas1, pack_toolbar=False)  # , root)
        toolbar1.update()
        toolbar1.grid(row=1)
        frame1.grid(column=0, row=0, sticky="nswe")

        self.update_plot(ax1, highlight_nodes)
        print("Waiting for user to close the Window...")
        # ---- start main loop
        root.protocol("WM_DELETE_WINDOW", close_window)
        root.mainloop()
        # plt.show()

    def update_plot(self, axis: Axes, highlight_nodes: Optional[List[Context]] = None) -> None:
        logger.info("Plotting...")

        logger.info("---> generating layout...")
        # positions = nx.nx_pydot.pydot_layout(self.graph, prog="sfdp")  # prog="dot")
        positions = nx.nx_pydot.pydot_layout(self.graph, prog="dot")
        # positions = self.quick_layout(self.graph)
        logger.info("--->    Done.")

        # draw regular nodes
        if highlight_nodes is None:
            nx.draw_networkx_nodes(self.graph, positions, ax=axis)
        else:
            nx.draw_networkx_nodes(
                self.graph,
                positions,
                nodelist=[n for n in self.graph.nodes() if n not in highlight_nodes],
                ax=axis,
            )
        # draw highlighted nodes
        if highlight_nodes is not None:
            nx.draw_networkx_nodes(
                self.graph,
                positions,
                nodelist=highlight_nodes,
                node_color="red",
                ax=axis,
            )
        # draw control edges
        tmp_graph = self.graph
        edgelist: List[Tuple[Context, Context]] = []
        for source, target in [(s, t) for s, t in self.graph.edges()]:
            edge_info = self.get_edge_info(source, target)
            is_control_edge = (
                True if len([info for info in edge_info if info.type == CTGEdgeType.CONTROL]) > 0 else False
            )
            is_data_edge = True if len([info for info in edge_info if info.type == CTGEdgeType.DATA]) > 0 else False
            if is_control_edge and not is_data_edge:
                tmp_graph.add_edge(source, target)
                edgelist.append((source, target))
        nx.draw_networkx_edges(tmp_graph, positions, edgelist=edgelist, edge_color="black", ax=axis)
        for tpl in edgelist:
            tmp_graph.remove_edge(tpl[0], tpl[1])
        # draw data edges
        edgelist.clear()
        for source, target in [(s, t) for s, t in self.graph.edges()]:
            edge_info = self.get_edge_info(source, target)
            is_control_edge = (
                True if len([info for info in edge_info if info.type == CTGEdgeType.CONTROL]) > 0 else False
            )
            is_data_edge = True if len([info for info in edge_info if info.type == CTGEdgeType.DATA]) > 0 else False
            if is_data_edge and not is_control_edge:
                tmp_graph.add_edge(source, target)
                edgelist.append((source, target))
        nx.draw_networkx_edges(
            tmp_graph,
            positions,
            edgelist=edgelist,
            edge_color="red",
            ax=axis,
            connectionstyle="arc3,rad=0.2",
        )
        for tpl in edgelist:
            tmp_graph.remove_edge(tpl[0], tpl[1])
        # draw combined control and data edges
        edgelist.clear()
        for source, target in [(s, t) for s, t in self.graph.edges()]:
            edge_info = self.get_edge_info(source, target)
            is_control_edge = (
                True if len([info for info in edge_info if info.type == CTGEdgeType.CONTROL]) > 0 else False
            )
            is_data_edge = True if len([info for info in edge_info if info.type == CTGEdgeType.DATA]) > 0 else False
            if is_data_edge and is_control_edge:
                tmp_graph.add_edge(source, target)
                edgelist.append((source, target))
        nx.draw_networkx_edges(
            tmp_graph,
            positions,
            edgelist=edgelist,
            edge_color="blue",
            ax=axis,
            connectionstyle="arc3,rad=0.2",
        )
        for tpl in edgelist:
            tmp_graph.remove_edge(tpl[0], tpl[1])

        # draw imaginary edges
        edgelist.clear()
        for source in self.imaginary_replacement_edges:
            for target in self.imaginary_replacement_edges[source]:
                tmp_graph.add_edge(source, target)
                edgelist.append((source, target))
        try:
            nx.draw_networkx_edges(tmp_graph, positions, edgelist=edgelist, edge_color="green", ax=axis)
        except KeyError:
            logger.info("KeyError during plotting of imaginary replacement edges. Skipping.")
            pass
        for source in self.imaginary_replacement_edges:
            for target in self.imaginary_replacement_edges[source]:
                tmp_graph.remove_edge(source, target)

        # get node labels
        labels = {}
        for node in self.graph.nodes():
            labels[node] = node.get_label()
        try:
            nx.draw_networkx_labels(self.graph, positions, labels, font_size=7, ax=axis)
        except KeyError:
            logger.info("KeyError during plotting node labels. Skipping.")
            pass

        # define legend
        black_line = mlines.Line2D([], [], color="black", markersize=15, label="control")  # marker='*',
        red_line = mlines.Line2D([], [], color="red", markersize=15, label="data")  # marker='*',
        blue_line = mlines.Line2D([], [], color="blue", markersize=15, label="control + data")  # marker='*',
        green_line = mlines.Line2D(
            [],
            [],
            color="green",  # marker='*',
            markersize=15,
            label="imaginary replacement edges",
        )

        axis.legend(
            loc="upper left", handles=[black_line, red_line, blue_line, green_line]
        )  # labels=["control", "data", "control + data", "imaginary"], labelcolor=["black", "red", "blue", "green"], )

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
                positions[current_node] = (
                    float(current_position),
                    float(-current_level),
                )

                out_edges = graph.out_edges(current_node)

                for _, target in out_edges:
                    queue.append((target, current_level + 1))
        return positions

    def add_node(self, node: Context) -> None:
        self.graph.add_node(node)

    def add_edge(
        self,
        source: Optional[Context],
        target: Optional[Context],
        edge_info: CTGEdgeInfo,
    ) -> None:
        if source is None or target is None:
            return
        # disallow duplicate edges
        if not self.graph.has_edge(source, target):
            self.graph.add_edge(source, target)

        # attach edge_info to the edge
        if source not in self.edge_information:
            self.edge_information[source] = dict()
        if target not in self.edge_information[source]:
            self.edge_information[source][target] = []
        if edge_info not in self.edge_information[source][target]:
            self.edge_information[source][target].append(edge_info)

    def get_edge_info(self, source: Context, target: Context) -> List[CTGEdgeInfo]:
        if source not in self.edge_information:
            return []
        if target not in self.edge_information[source]:
            return []
        return self.edge_information[source][target]
