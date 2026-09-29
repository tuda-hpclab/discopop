# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
import threading
from typing import List, Optional, Set, Tuple, cast
import warnings

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Loops.TGStartLoopNode import TGStartLoopNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    ParallelRegionInfo,
    TPIType,
    TaskParallelismInfo,
)
from discopop_library.StatusReporting.console import stage

try:
    from discopop_gui.Visualizers.Base import Base as Visualizer
except (ImportError, ModuleNotFoundError):
    Visualizer = object  # type: ignore[assignment, misc]

logger = logging.getLogger("Explorer").getChild("Tasking")


def run_detection(pet: PEGraphX, task_graph: TaskGraph, visualizer: Visualizer | None) -> List[PatternInfo]:
    logger.info("Starting task detection...")
    result: List[PatternInfo] = []

    context_task_graph = ContextTaskGraph(task_graph, visualizer)
    with stage("Simplifying ContextTaskGraph"):
        simplification_result = context_task_graph.simplify_graph()

    # result += identify_simple_taskloop(pet, task_graph)
    result += identify_simple_tasking(context_task_graph, simplification_result)
    if visualizer:
        show_all_plots(context_task_graph)

    # identify immediate successive contexts with no dependencies between them
    logger.info("--> Identify tasking with data sharing clauses ... TODO")
    logger.info("--> Identifying simple asynchronous tasking ... TODO")
    # identify non-immediate successive contexts with no dependencies between them, such that asynchronous execution is possible
    logger.info("--> Identifying dependent tasking... TODO")
    logger.info("--> Identifying multi-dependent tasking... TODO")
    logger.info("--> Identifying loop tasking... TODO")
    logger.info("--> Identifying recursive tasking... TODO?")

    return result


def show_all_plots(context_task_graph: ContextTaskGraph, highlight_nodes: Optional[Set[Context]] = None) -> None:
    if context_task_graph.plottable() == False:
        return

    def draw_plots() -> None:
        # [ax1, ax2, ax3, ax4] = context_task_graph.create_multi_plot(
        #     "Graphs",
        #     ["Task Graph", "Task graph (context graph)", "Task graph (context debug graph)", "Context task graph"],
        #     2,
        #     2,
        # )

        # print("Plotting task graph...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.update_plot(ax1)

        # print("Plotting task graph (context graph)...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.plot_context_graph(ax2)

        # print("Plotting task graph (context debug graph)...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.plot_context_debug_graph(ax3)

        # print("Plotting context task graph...")
        # context_task_graph.update_plot(
        #     ax4, highlight_nodes=list(highlight_nodes) if highlight_nodes is not None else None
        # )

        # ax1 = context_task_graph.create_plot("Task Graph")
        # ax2 = context_task_graph.create_plot("Task graph (context graph)")
        # ax3 = context_task_graph.create_plot("Task graph (context debug graph)")
        # ax4 = context_task_graph.create_plot("Context task graph")

        # print("Plotting separate task graph...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.update_plot(ax1)

        # print("Plotting separate task graph (context graph)...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.plot_context_graph(ax2)

        # print("Plotting separate task graph (context debug graph)...")
        # if len(context_task_graph.task_graph.graph.nodes()) < 500:
        #     context_task_graph.task_graph.plot_context_debug_graph(ax3)

        # print("Plotting separate context task graph...")
        # context_task_graph.update_plot(
        #     ax4, highlight_nodes=list(highlight_nodes) if highlight_nodes is not None else None
        # )

        context_task_graph.task_graph.new_plot_context_debug_graph(
            context_task_graph.create_plottable_canvas("Main graph")
        )

    def on_filter(filter_text: str) -> None:
        logger.debug("Filter text: " + filter_text)

        # Extra processing here

    context_task_graph.clear_visualizer()
    context_task_graph.set_filter_callback(on_filter)
    draw_plots()
    context_task_graph.run_visualizer()


def identify_simple_tasking(
    ctg: ContextTaskGraph, simplification_results: List[TaskParentContext]
) -> List[PatternInfo]:
    """Analyzes the results of the graph simplification and create simple tasking patterns."""
    patterns: List[PatternInfo] = []
    logger.info("Extracting task suggestions from graph simplification results")

    def get_file_id(lid: LineID) -> int:
        return int(lid.split(":")[0])

    def get_line_num(lid: LineID) -> int:
        return int(lid.split(":")[1])

    task_group_num = 0

    for tpc in simplification_results:

        from discopop_explorer.pattern_detectors.task_parallelism.classes import TPIType

        if tpc.parent_context is None:
            continue
        tpc_parent_pet_node = tpc.parent_context.get_first_pet_node(ctg.pet)
        if tpc_parent_pet_node is None:
            continue
        parent_scopes = tpc.parent_context.get_code_scope(ctg.pet, inclusive=False)
        parent_scope_file_id = tpc_parent_pet_node.file_id
        parent_scope_lines = [get_line_num(s) for s in parent_scopes]
        parent_scopes_min_line = min(parent_scope_lines)
        parent_scopes_max_line = max(parent_scope_lines)

        # parent_scope_start_line
        # print("TPC")
        # print("parent scopes: ", parent_scopes)
        # print("parent scopes file id:", parent_scope_file_id)
        # print("parent scopes min line: ", parent_scopes_min_line)
        # print("parent scopes max line: ", parent_scopes_max_line)

        # TODO: filter scopes by relevant file id.
        # TODO determine task scopes properly
        # TODO create PatternInfo representing the identified tasks
        # TODO: check if data sharing clauses are required
        invalid = False
        pattern_objects: List[TaskParallelismInfo] = []
        parallel_region_start: Optional[int] = None
        parallel_region_end: Optional[int] = None

        for task in tpc.registered_tasks:
            task_scopes: List[LineID] = []
            task_scopes += task.get_code_scope(ctg.pet, inclusive=True)
            task_scopes = list(dict.fromkeys(task_scopes))
            #            task_scope_file_id = task_pet_node.file_id
            task_scope_line_nums = [get_line_num(ts) for ts in task_scopes if get_file_id(ts) == parent_scope_file_id]
            filtered_task_scope_line_nums = [
                n for n in task_scope_line_nums if n >= parent_scopes_min_line and n <= parent_scopes_max_line
            ]
            if len(filtered_task_scope_line_nums) == 0:
                warnings.warn(
                    "Empty task scope. Skipping Task suggestion. Parent scope: "
                    + str(parent_scope_file_id)
                    + ":"
                    + str(parent_scopes_min_line)
                    + " - "
                    + str(parent_scopes_max_line)
                )
                invalid = True
                break
            task_scope_min = min(filtered_task_scope_line_nums)
            task_scope_max = max(filtered_task_scope_line_nums)
            # update parallel region
            if parallel_region_start is None:
                parallel_region_start = task_scope_min
            if parallel_region_end is None:
                parallel_region_end = task_scope_max
            if parallel_region_start > task_scope_min:
                parallel_region_start = task_scope_min
            if parallel_region_end < task_scope_max:
                parallel_region_end = task_scope_max
            fp: List[str] = []
            p: List[str] = []
            s: List[str] = []
            tpi = TaskParallelismInfo(
                tpc_parent_pet_node,
                TPIType.TASK,
                ["#pragma omp task"],
                str(task_scope_min),  # LineID(str(tpc_parent_pet_node.file_id) + ":" + str(task_scope_min)),
                fp,
                p,
                s,
            )
            tpi.task_group.append(task_group_num)
            tpi.region_end_line = str(
                task_scope_max
            )  #  LineID(str(tpc_parent_pet_node.file_id) + ":" + str(task_scope_max))
            tpi.standalone_pattern = False
            tpi.applicable_pattern = False
            pattern_objects.append(tpi)

        if invalid:
            continue
        # register found patterns
        for tpi in pattern_objects:
            patterns.append(tpi)

        if parallel_region_start is None or parallel_region_end is None:
            continue

        parallel_region_pattern = ParallelRegionInfo(
            tpc_parent_pet_node,
            TPIType.PARALLELREGION,
            parallel_region_start,  # LineID(str(parent_scope_file_id) + ":" + str(parallel_region_start)),
            parallel_region_end,  # LineID(str(parent_scope_file_id) + ":" + str(parallel_region_end)),
            task_group=[task_group_num],
            contained_tasks=pattern_objects,
        )

        patterns.append(parallel_region_pattern)
        # close task group
        task_group_num += 1

    return patterns
