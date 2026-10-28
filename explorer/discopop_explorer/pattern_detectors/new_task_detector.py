# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
from typing import Dict, List, Optional, Set, Tuple
import warnings

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.patterns.TaskParallelismInfo import (
    ParallelRegionInfo,
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.task_dataflow import (
    analyze_task_group,
    clauses_of_dependences,
    after_dependences_of_instructions,
    function_of,
)
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
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
    # identify non-immediate successive contexts with no dependencies between them, such that asynchronous execution is
    # possible
    logger.info("--> Identifying dependent tasking... TODO")
    logger.info("--> Identifying multi-dependent tasking... TODO")
    logger.info("--> Identifying loop tasking... TODO")
    logger.info("--> Identifying recursive tasking... TODO?")

    return result


def show_all_plots(context_task_graph: ContextTaskGraph, highlight_nodes: Optional[Set[Context]] = None) -> None:
    if not context_task_graph.plottable():
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

        context_task_graph.task_graph.new_plot_context_debug_graph(context_task_graph.create_plottable("Main graph"))

    def on_filter(filter_text: str) -> None:
        logger.debug("Filter text: " + filter_text)

        # Extra processing here

    context_task_graph.clear_visualizer()
    context_task_graph.set_filter_callback(on_filter)
    draw_plots()
    context_task_graph.run_visualizer()


def _cus_of_task(ctg: ContextTaskGraph, task: Context) -> List[CUNode]:
    """The CUs a task consists of, including those of the contexts it contains."""
    cus: List[CUNode] = []
    for node in task.get_contained_nodes(inclusive=True):
        pet_node = node.get_pet_node(ctg.pet)
        if isinstance(pet_node, CUNode):
            cus.append(pet_node)
    return cus


def _is_valid_task_body(ctg: ContextTaskGraph, task: Context) -> bool:
    """Whether the CUs of a task can be the body of an OpenMP task. A task is rejected if

    - it does no work: its CUs access no variable and call nothing, e.g. a ``return`` or the jump over an ``else``
      branch (``fft_twiddle_gen``, ``bots_get_params``), or
    - it is not a region with a single exit: its CUs lead to more than one CU outside of the task, i.e. it ends in a
      conditional branch whose targets are not part of the task. The condition of ``if (verbose) fprintf(...)`` or
      an operand of ``a || b`` is no task of its own, and what follows it depends on the condition.

    A task without CUs (no information) is accepted.

    Note: the checks could also be made in ``split_taskable_control_sequence``, so that the ContextTaskGraph would
    not create these groups at all. This needs the CUs of CombinedContexts there and is therefore not done yet; the
    task detection filters after the simplification instead.
    """
    cus = _cus_of_task(ctg, task)
    if len(cus) == 0:
        return True
    if not any(cu.local_vars or cu.global_vars or cu.node_calls or cu.recursive_function_calls for cu in cus):
        return False
    task_cu_ids = {cu.id for cu in cus}
    exits = {
        target
        for cu in cus
        for _, target, _ in out_edges(ctg.pet, cu.id, EdgeType.SUCCESSOR)
        if target not in task_cu_ids
    }
    return len(exits) <= 1


def _record_data_flow(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    task_patterns: List[TaskParallelismInfo],
    region: ParallelRegionInfo,
) -> None:
    """Dependences between the tasks, what the code after the region depends on and the data sharing of the tasks."""
    flow = analyze_task_group(pet, tasks, task_lines)
    ids = [t.pattern_id for t in task_patterns]
    region.task_dependences = [
        {"from_task": ids[d.from_task], "to_task": ids[d.to_task], "variable": d.variable, "kind": d.kind}
        for d in flow.dependences
    ]
    region.after_dependences = [
        {"task": ids[a.task], "variable": a.variable, "kind": a.kind, "line": a.line} for a in flow.after
    ]
    for index, (task, sharing) in enumerate(zip(task_patterns, flow.sharing)):
        task.shared, task.private, task.first_private = sharing.shared, sharing.private, sharing.first_private
        task.in_dep, task.out_dep, task.in_out_dep = clauses_of_dependences(flow.dependences, index)


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

        if tpc.parent_context is None:
            continue
        tpc_parent_pet_node = tpc.parent_context.get_first_pet_node(ctg.pet)
        if tpc_parent_pet_node is None:
            continue
        # the lines of the instructions of the contexts; a context that holds none keeps the range of its nodes.
        # The parent only bounds the tasks: its jumps (the closing brace) belong to it, unlike to the tasks.
        parent_scopes = ctg.pet.get_line_ids_of_instructions(
            tpc.parent_context.get_instruction_scope(ctg.pet, inclusive=False)
        ) or tpc.parent_context.get_code_scope(ctg.pet, inclusive=False)
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
        task_lines: List[Tuple[int, int, int]] = []
        parallel_region_start: Optional[int] = None
        parallel_region_end: Optional[int] = None

        # tasks that cannot be the body of a task are dropped; fewer than two tasks are no parallelism
        valid_tasks = [task for task in tpc.registered_tasks if _is_valid_task_body(ctg, task)]
        if len(valid_tasks) < 2:
            continue

        for task in valid_tasks:
            task_scopes: List[LineID] = []
            task_scopes += ctg.pet.get_statement_line_ids_of_instructions(
                task.get_instruction_scope(ctg.pet, inclusive=True)
            ) or task.get_code_scope(ctg.pet, inclusive=True)
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
            task_lines.append((parent_scope_file_id, task_scope_min, task_scope_max))
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
            )  # LineID(str(tpc_parent_pet_node.file_id) + ":" + str(task_scope_max))
            tpi.instruction_ids = task.get_instruction_scope(ctg.pet, inclusive=True)
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

        _record_data_flow(ctg.pet, valid_tasks, task_lines, pattern_objects, parallel_region_pattern)

        patterns.append(parallel_region_pattern)
        # close task group
        task_group_num += 1

    return patterns


def _hotspot_functions(
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
) -> Optional[Set[Tuple[int, str]]]:
    """(file id, name) of the functions classified as hotspot. None, if there is no hotspot information."""
    if not hotspots:
        return None
    return {
        (file_id, name)
        for entries in hotspots.values()
        for file_id, _, node_type, name, _ in entries
        if node_type == HotspotNodeType.FUNCTION
    }


def identify_loop_tasking(
    pet: PEGraphX,
    do_all_patterns: List[DoAllInfo],
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    first_task_group: int,
) -> List[PatternInfo]:
    """Loops whose iterations are independent (do-all) and whose body calls a function that is a hotspot are suggested
    as one task per iteration, e.g. the recursive calls in the loop of ``fft_aux`` (omp-tasks: ``task`` on the call
    and a ``taskwait`` after the loop). Without hotspot information, every call qualifies. The tasks are created
    inside the loop and have to be joined after it; the parallel region belongs to the caller.
    The loop is not a task candidate itself if its body does not call anything: do-all is the better suggestion then.
    """
    patterns: List[PatternInfo] = []
    hotspot_functions = _hotspot_functions(hotspots)
    # instruction id of a call -> the function it calls
    callees: Dict[int, Node] = dict()
    for cu in all_nodes(pet, CUNode):
        for call in cu.node_calls:
            if call.get("callInstId") is not None and call["cuid"] in pet.g:
                callees[int(call["callInstId"])] = pet.node_at(NodeID(call["cuid"]))

    task_group_num = first_task_group
    for do_all in do_all_patterns:
        called = [
            callees[i]
            for i in do_all.instruction_ids
            if i in callees
            and (hotspot_functions is None or (callees[i].file_id, callees[i].name) in hotspot_functions)
        ]
        if len(called) == 0:
            continue
        loop_node = pet.node_at(NodeID(do_all.node_id))
        loop_line = str(loop_node.start_position())
        lines = [
            int(line.split(":")[1])
            for line in pet.get_statement_line_ids_of_instructions(do_all.instruction_ids)
            if int(line.split(":")[0]) == loop_node.file_id
        ]
        # the body: the lines of the loop without its header
        body_lines = [line for line in lines if line != loop_node.start_line] or lines
        if len(body_lines) == 0:
            continue
        task = TaskParallelismInfo(loop_node, TPIType.TASK, ["#pragma omp task"], str(min(body_lines)), [], [], [])
        task.region_end_line = str(max(body_lines))
        task.task_group.append(task_group_num)
        task.instruction_ids = list(do_all.instruction_ids)
        task.loop_start_line = loop_line
        task.standalone_pattern = False
        task.applicable_pattern = False
        # per iteration, the loop's own data sharing (do-all); the loop is one task for what the code after it needs
        task.shared = sorted({v.name for v in do_all.shared})
        task.private = sorted({v.name for v in do_all.private})
        task.first_private = sorted({v.name for v in do_all.first_private})
        function = function_of(pet, loop_node)
        after = (
            after_dependences_of_instructions(pet, do_all.instruction_ids, loop_node.file_id, max(body_lines), function)
            if function is not None
            else []
        )
        # what the code after the loop reads is shared: the task writes it, and the code after the loop needs it
        for needed in sorted({a.variable for a in after if a.kind == "RAW"}):
            task.private = [v for v in task.private if v != needed]
            task.first_private = [v for v in task.first_private if v != needed]
            if needed not in task.shared:
                task.shared = sorted(task.shared + [needed])
        region = ParallelRegionInfo(
            loop_node,
            TPIType.PARALLELREGION,
            loop_node.start_line,
            max(body_lines),
            task_group=[task_group_num],
            contained_tasks=[task],
        )
        region.loop_start_line = loop_line
        region.after_dependences = [
            {"task": task.pattern_id, "variable": a.variable, "kind": a.kind, "line": a.line} for a in after
        ]
        patterns += [task, region]
        task_group_num += 1
    return patterns
