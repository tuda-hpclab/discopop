# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import warnings

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
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
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.task_cursor_loops import LoopTaskSource
from discopop_explorer.pattern_detectors.task_dataflow import (
    AfterDependence,
    analyze_task_group,
    clauses_of_dependences,
    after_dependences_of_instructions,
    function_of,
    instructions_with_callees,
)
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.StatusReporting.console import stage

try:
    from discopop_gui.Visualizers.Base import Base as Visualizer
except (ImportError, ModuleNotFoundError):
    Visualizer = object  # type: ignore[assignment, misc]

logger = logging.getLogger("Explorer").getChild("Tasking")


def run_detection(
    pet: PEGraphX,
    task_graph: TaskGraph,
    visualizer: Visualizer | None,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> List[PatternInfo]:
    logger.info("Starting task detection...")
    result: List[PatternInfo] = []

    context_task_graph = ContextTaskGraph(task_graph, visualizer)
    with stage("Simplifying ContextTaskGraph"):
        simplification_result = context_task_graph.simplify_graph()

    # result += identify_simple_taskloop(pet, task_graph)
    result += identify_simple_tasking(
        context_task_graph, simplification_result, observed_dependences(task_graph), ast_helper
    )
    if visualizer:
        show_all_plots(context_task_graph)

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


def _after_record(task_id: int, dependence: AfterDependence) -> Dict[str, Any]:
    """An entry of ``after_dependences`` of a region (patterns.json). ``line`` is None and ``at_return`` true if the
    reader is outside of the function (the join is before the function returns); ``variable`` is a name of the scope
    of the function, or empty if there is none."""
    return {
        "task": task_id,
        "variable": dependence.variable,
        "kind": dependence.kind,
        "line": dependence.line,
        "at_return": dependence.at_return,
    }


def _record_data_flow(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    task_patterns: List[TaskParallelismInfo],
    region: ParallelRegionInfo,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> None:
    """Dependences between the tasks, what the code after the region depends on and the data sharing of the tasks."""
    flow = analyze_task_group(pet, tasks, task_lines, ast_helper)
    ids = [t.pattern_id for t in task_patterns]
    region.task_dependences = [
        {"from_task": ids[d.from_task], "to_task": ids[d.to_task], "variable": d.variable, "kind": d.kind}
        for d in flow.dependences
    ]
    region.after_dependences = [_after_record(ids[a.task], a) for a in flow.after]
    for index, (task, sharing) in enumerate(zip(task_patterns, flow.sharing)):
        task.shared, task.private, task.first_private = sharing.shared, sharing.private, sharing.first_private
        task.reduction = sharing.reduction
        task.in_dep, task.out_dep, task.in_out_dep = clauses_of_dependences(flow.dependences, index)


def observed_dependences(task_graph: TaskGraph) -> Set[Tuple[int, int]]:
    """``(earlier instruction, later instruction)`` of every RAW and WAR registered on a context of the task graph that
    is not carried by a loop, in any copy of the code the graph holds.

    The task graph holds a copy of a function per call and per level of a recursion, and the profile's dependences
    reach only some of them (the call paths of a recursive function stand for all of its levels). The instructions are
    those of the program, the same in every copy: a dependence found in one copy is one of the code of all of them."""
    found: Set[Tuple[int, int]] = set()
    for context in task_graph.contexts:
        for _, dependence in context.outgoing_dependencies:
            if dependence is None or dependence.dtype not in (DepType.RAW, DepType.WAR):
                continue
            if dependence.carried_by_loop is not None or dependence.carried_by_pet_loops is not None:
                continue
            if dependence.source_instruction_id is None or dependence.sink_instruction_id is None:
                continue
            found.add((dependence.source_instruction_id, dependence.sink_instruction_id))
    return found


def _neighbours_depend(pet: PEGraphX, tasks: List[TaskParallelismInfo], observed: Set[Tuple[int, int]]) -> bool:
    """Whether a task reads or overwrites what the task before it accessed, in itself or in the functions it calls.
    Such tasks are no parallelism. The instructions both reach (the same function called by both, e.g. a recursion)
    tell nothing."""
    executed = [instructions_with_callees(pet, task.instruction_ids) for task in tasks]
    for earlier, later in zip(executed, executed[1:]):
        common = earlier & later
        if any((a, b) in observed for a in earlier - common for b in later - common):
            return True
    return False


def identify_simple_tasking(
    ctg: ContextTaskGraph,
    simplification_results: List[TaskParentContext],
    observed: Optional[Set[Tuple[int, int]]] = None,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> List[PatternInfo]:
    """Analyzes the results of the graph simplification and create simple tasking patterns.

    ``observed`` are the instruction pairs of the dependences of the program (``observed_dependences``): a group
    whose neighbouring tasks depend on each other in any copy of the code is dropped. The simplification found it
    in the copy it looked at, which may be one the profile's dependences did not reach."""
    patterns: List[PatternInfo] = []
    logger.info("Extracting task suggestions from graph simplification results")

    def get_file_id(lid: LineID) -> int:
        return int(lid.split(":")[0])

    def get_line_num(lid: LineID) -> int:
        return int(lid.split(":")[1])

    task_group_num = 0
    # a recursive function is inlined once per level, which gives one copy of a group per context instance; a group
    # is reported once per (parent node, line ranges and instructions of its tasks)
    seen_groups: Set[Tuple[NodeID, Tuple[Tuple[int, int, Tuple[int, ...]], ...]]] = set()

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
        if observed is not None and _neighbours_depend(ctg.pet, pattern_objects, observed):
            continue
        group_key = (
            tpc_parent_pet_node.id,
            tuple((lines[1], lines[2], tuple(tpi.instruction_ids)) for lines, tpi in zip(task_lines, pattern_objects)),
        )
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
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

        _record_data_flow(ctg.pet, valid_tasks, task_lines, pattern_objects, parallel_region_pattern, ast_helper)

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


def _guard_lines(pet: PEGraphX, instruction_ids: List[int], cu_of: Dict[int, CUNode]) -> Set[int]:
    """Lines of the instructions that only evaluate a condition, e.g. ``if (BENCH[i] != NULL)`` guarding a task: no
    CU on the line calls anything, at least one ends in a conditional branch (more than one successor), and the others
    do nothing (no variable; the jump of ``if.end``). The condition is no part of the code of the task."""
    cus_of_line: Dict[int, Set[Optional[CUNode]]] = dict()
    for instruction in instruction_ids:
        for line_id in pet.get_line_ids_of_instructions([instruction]):
            cus_of_line.setdefault(int(line_id.split(":")[1]), set()).add(cu_of.get(instruction))
    guards: Set[int] = set()
    for line, cus in cus_of_line.items():
        if None in cus or any(cu.node_calls or cu.recursive_function_calls for cu in cus if cu is not None):
            continue
        branching = [
            cu is not None and len({target for _, target, _ in out_edges(pet, cu.id, EdgeType.SUCCESSOR)}) > 1
            for cu in cus
        ]
        idle = [cu is not None and not cu.local_vars and not cu.global_vars for cu in cus]
        if any(branching) and all(b or i for b, i in zip(branching, idle)):
            guards.add(line)
    return guards


def _loop_index_names(pet: PEGraphX, header_lines: Set[str], cus: List[CUNode]) -> Set[str]:
    """The variables that are the index of a loop with one of the header lines: they depend on themselves (RAW) in the
    line of the header (``jj++``)."""
    return {
        str(dependence.var_name)
        for cu in cus
        for _, _, dependence in out_edges(pet, cu.id, EdgeType.DATA)
        if dependence.dtype == DepType.RAW
        and dependence.var_name is not None
        and dependence.sink_line == dependence.source_line
        and dependence.source_line in header_lines
    }


def identify_loop_tasking(
    pet: PEGraphX,
    do_all_patterns: Sequence[LoopTaskSource],
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    first_task_group: int,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> List[PatternInfo]:
    """Loops whose iterations are independent (do-all) and whose body calls a function that is a hotspot are suggested
    as one task per iteration, e.g. the recursive calls in the loop of ``fft_aux`` (omp-tasks: ``task`` on the call
    and a ``taskwait`` after the loop). Without hotspot information, every call qualifies. The tasks are created
    inside the loop and have to be joined after it; the parallel region belongs to the caller.
    The loop is not a task candidate itself if its body does not call anything: do-all is the better suggestion then.

    The task and the region cover the statement the task executes: not the header of the loop and not the conditions
    that only guard the call. Loops of a nest that give the same statement are one suggestion, for the innermost
    loop (one task per iteration of the nest, as in omp-tasks).
    """
    patterns: List[PatternInfo] = []
    hotspot_functions = _hotspot_functions(hotspots)
    # instruction id of a call -> the function it calls
    callees: Dict[int, Node] = dict()
    cu_of: Dict[int, CUNode] = dict()
    for cu in all_nodes(pet, CUNode):
        for instruction in cu.instruction_ids:
            cu_of[instruction] = cu
        for call in cu.node_calls:
            if call.get("callInstId") is not None and call["cuid"] in pet.g:
                callees[int(call["callInstId"])] = pet.node_at(NodeID(call["cuid"]))

    loop_headers = {(loop.file_id, loop.start_line) for loop in all_nodes(pet, LoopNode)}

    # the candidates: the do-all loop, its node and the lines of the statement of its task
    candidates: List[Tuple[LoopTaskSource, Node, List[int], Set[int]]] = []
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
        lines = [
            int(line.split(":")[1])
            for line in pet.get_statement_line_ids_of_instructions(do_all.instruction_ids)
            if int(line.split(":")[0]) == loop_node.file_id
        ]
        # the body: the lines of the loop without its header and without the conditions that only guard the task
        guards = _guard_lines(pet, do_all.instruction_ids, cu_of)
        # the header of the loop and those of the loops in it
        header_lines = {loop_node.start_line} | {line for line in lines if (loop_node.file_id, line) in loop_headers}
        body_lines = [line for line in lines if line not in header_lines] or [
            line for line in lines if line != loop_node.start_line
        ]
        body_lines = body_lines or lines
        body_lines = [line for line in body_lines if line not in guards] or body_lines
        if len(body_lines) == 0:
            continue
        candidates.append((do_all, loop_node, body_lines, header_lines))

    # loops of a nest with the same statement: the innermost one (fewest instructions) is the suggestion
    innermost: Dict[Tuple[int, int, int], LoopTaskSource] = dict()
    for do_all, loop_node, body_lines, header_lines in candidates:
        key = (loop_node.file_id, min(body_lines), max(body_lines))
        known = innermost.get(key)
        if known is None or len(do_all.instruction_ids) < len(known.instruction_ids):
            innermost[key] = do_all

    task_group_num = first_task_group
    for do_all, loop_node, body_lines, header_lines in candidates:
        if innermost[(loop_node.file_id, min(body_lines), max(body_lines))] is not do_all:
            continue
        loop_line = str(loop_node.start_position())
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
        task.reduction = sorted({f"{v.operation or '?'}:{v.name}" for v in do_all.reduction})
        task.last_private = sorted({v.name for v in do_all.last_private})
        function = function_of(pet, loop_node)
        after = (
            after_dependences_of_instructions(
                pet,
                do_all.instruction_ids,
                loop_node.file_id,
                max(body_lines),
                function,
                ast_helper=ast_helper,
                task_first_line=min(body_lines),
            )
            if function is not None
            else []
        )
        # what the code after the loop reads is shared: the task writes it, and the code after the loop needs it.
        # Not what the caller of the function reads (``at_return``): that is the memory a pointer parameter points to,
        # the parameter itself stays what the do-all loop made of it (a read-only pointer is firstprivate).
        # A reduced variable keeps its clause, which is how it is shared. A last private one is shared as well, and
        # listed in last_private as a hint: the value of the last iteration has to be the one that remains.
        special = {v.name for v in do_all.reduction}
        # The cursor of a loop (while (v) { f(v); v = v->next; }) is firstprivate: the task gets the pointer by value,
        # the update stays in the creating thread. A dependence the names of the join map to it is one on what it
        # points to.
        cursors = set(getattr(do_all, "cursors", []))
        for needed in sorted(
            {a.variable for a in after if a.kind == "RAW" and not a.at_return and a.variable} - special - cursors
        ):
            task.private = [v for v in task.private if v != needed]
            task.first_private = [v for v in task.first_private if v != needed]
            if needed not in task.shared:
                task.shared = sorted(task.shared + [needed])
        task.shared = [v for v in task.shared if v not in special]
        task.private = [v for v in task.private if v not in special]
        task.first_private = [v for v in task.first_private if v not in special]
        # what the task gets by value (firstprivate, the index of the loop) can be written by the code after the loop
        # while the task runs: that write does not have to wait for the task
        task_cus = [cu_of[i] for i in do_all.instruction_ids if i in cu_of]
        by_value = set(task.first_private) | _loop_index_names(
            pet, {f"{loop_node.file_id}:{line}" for line in header_lines}, task_cus
        )
        after = [a for a in after if not (a.kind == "WAR" and a.variable in by_value)]
        region = ParallelRegionInfo(
            loop_node,
            TPIType.PARALLELREGION,
            min(body_lines),
            max(body_lines),
            task_group=[task_group_num],
            contained_tasks=[task],
        )
        region.loop_start_line = loop_line
        # the pattern's node may be the first CU of the loop instead of the loop: take the end of the loop itself
        loop_ends = [
            loop.end_line
            for loop in all_nodes(pet, LoopNode)
            if loop.file_id == loop_node.file_id and loop.start_line == loop_node.start_line
        ]
        if len(loop_ends) > 0:
            region.loop_end_line = f"{loop_node.file_id}:{max(loop_ends)}"
        region.after_dependences = [_after_record(task.pattern_id, a) for a in after]
        patterns += [task, region]
        task_group_num += 1
    return patterns
