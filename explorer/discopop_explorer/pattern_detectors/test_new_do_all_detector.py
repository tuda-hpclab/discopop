# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Any, Callable, Tuple

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.pattern_detectors.new_do_all_detector import (
    detect_doall_sharing_clauses,
    identify_simple_doall_and_reduction,
)
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _build_two_iteration_loop(
    make_node: MakeNode, build_pet_graph: BuildPetGraph, build_task_graph: Any, make_tg_node: Any, **pet_kwargs: Any
) -> Tuple[TaskGraph, Node, LoopParentContext, WorkContext, WorkContext]:
    """Builds a minimal PEGraphX (main -> loop -> body_cu) plus a TaskGraph whose
    loop TGNode has a LoopParentContext containing two IterationContexts, each
    wrapping a WorkContext for one dynamic execution of `body_cu`."""
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    body_cu = make_node("1:3", NodeType.CU, name="body", start_line=6, end_line=6)
    pet = build_pet_graph(
        [main, loop, body_cu],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, body_cu.id, EdgeType.CHILD)],
        **pet_kwargs,
    )

    loop_ctx = LoopParentContext(parent_loop=loop.id)
    iter1 = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[0])
    iter2 = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[1])
    loop_ctx.add_contained_context(iter1)
    loop_ctx.add_contained_context(iter2)
    iter1.register_parent_context(loop_ctx)
    iter2.register_parent_context(loop_ctx)

    work1 = WorkContext()
    work2 = WorkContext()
    work1.add_node(make_tg_node(body_cu.id, level=1, position=0))
    work2.add_node(make_tg_node(body_cu.id, level=1, position=1))
    iter1.add_contained_context(work1)
    iter2.add_contained_context(work2)
    work1.register_parent_context(iter1)
    work2.register_parent_context(iter2)

    tg_loop = make_tg_node(loop.id, level=0, position=0)
    tg_loop.register_created_context(loop_ctx)
    tg = build_task_graph(pet, [tg_loop])

    return tg, loop, loop_ctx, work1, work2


def test_identify_simple_doall_detected_without_inter_iteration_dependencies(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert len(patterns) == 1
    assert isinstance(patterns[0], DoAllInfo)
    assert patterns[0].node_id == loop.id


def test_identify_simple_doall_allows_war_dependency_between_iterations(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A WAR dependency between iterations is explicitly documented as non-critical
    (privatizable), unlike RAW/WAW, and must not prevent the do-all suggestion."""
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.WAR
    dep.var_name = "x"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert len(patterns) == 1
    assert isinstance(patterns[0], DoAllInfo)


def test_identify_simple_doall_prevented_by_dynamic_cross_iteration_dependency(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "x"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert patterns == []


def test_identify_simple_doall_allows_dependency_on_loop_variable(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "i"
    dep.memory_region = "M_I"  # type: ignore[assignment]
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    loop_ctx.loop_variables = [("i", "M_I")]  # type: ignore[list-item]
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert len(patterns) == 1
    assert isinstance(patterns[0], DoAllInfo)


def test_identify_simple_reduction_dependency_currently_only_prevents_doall(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Characterizes current (likely unintended) behavior: the reduction-detection branch in
    identify_simple_doall_and_reduction checks `red_var_dict["loop_line"] in
    node.created_context.get_code_scope(tg.pet)`, but get_code_scope() is called without
    inclusive=True, so it only looks at nodes added directly to the LoopParentContext via
    add_node(). No code path in the codebase ever calls add_node() on a LoopParentContext
    (the one call site that would, in TaskGraph.py's __assign_contexts, is commented out) --
    so get_code_scope() is always [], the "loop_line in scope" check always fails, and
    is_reduction_dependency can never become True. A dependency shaped like a reduction
    therefore isn't converted into a ReductionInfo suggestion here; since it also isn't a
    recognized loop variable, it just falls through to preventing the do-all suggestion
    entirely, exactly like an ordinary cross-iteration dependency would.
    """
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node,
        build_pet_graph,
        build_task_graph,
        make_tg_node,
        reduction_vars=[
            {
                "loop_line": "1:6",
                "name": "sum",
                "operation": "+",
                "reduction_line": "1:6",
            }
        ],
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "sum"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert patterns == []


def _build_reduction_loop(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    reduction_vars: Any,
) -> Any:
    """A two-iteration loop whose reduction branch is actually reachable.

    _build_two_iteration_loop adds no node to the LoopParentContext, so its code scope is empty
    and the "loop_line in loop scope" test can never succeed. Adding the loop's own node gives
    the context the loop's lines (1:5 - 1:10), which is what a reduction entry for this loop has
    to be found in.
    """
    tg, loop, loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node, reduction_vars=reduction_vars
    )
    loop_ctx.add_node(make_tg_node(loop.id, level=0, position=0))
    return tg, loop, loop_ctx, work1, work2


def test_reduction_operation_comes_from_the_matching_entry(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """The operation must be the one reported for the variable which the dependency matched.

    It used to be read from the last entry of pet.reduction_vars regardless of which entry
    matched, so every reduction of a project was labelled with the operation of whichever one
    happened to be listed last in reduction.txt. On rodinia's kmeans that turned the "delta +=
    1.0" accumulation into reduction(max:delta), because an unrelated maximum was listed last.
    """
    tg, loop, loop_ctx, work1, work2 = _build_reduction_loop(
        make_node,
        build_pet_graph,
        build_task_graph,
        make_tg_node,
        reduction_vars=[
            {"loop_line": "1:6", "name": "sum", "operation": "+", "reduction_line": "1:6"},
            # listed last, belongs to a different loop and variable: the trap
            {"loop_line": "1:20", "name": "peak", "operation": ">", "reduction_line": "1:21"},
        ],
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "sum"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))

    reductions = [p for p in patterns if isinstance(p, ReductionInfo)]
    assert len(reductions) == 1
    assert [(v.operation, str(v.name)) for v in reductions[0].reduction] == [("+", "sum")]


def test_reduction_operation_translates_comparisons_to_min_and_max(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A genuine maximum still has to be reported as one, from its own entry."""
    tg, loop, loop_ctx, work1, work2 = _build_reduction_loop(
        make_node,
        build_pet_graph,
        build_task_graph,
        make_tg_node,
        reduction_vars=[
            {"loop_line": "1:6", "name": "peak", "operation": ">", "reduction_line": "1:6"},
            {"loop_line": "1:20", "name": "sum", "operation": "+", "reduction_line": "1:21"},
        ],
    )
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "peak"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))

    reductions = [p for p in patterns if isinstance(p, ReductionInfo)]
    assert len(reductions) == 1
    assert [(v.operation, str(v.name)) for v in reductions[0].reduction] == [("max", "peak")]


def test_identify_simple_doall_allows_static_dependency_first_written_inside_loop(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A cross-iteration dependency whose origin is static analysis (as opposed to dynamic
    analysis) gets a "second chance": unlike a dynamic-analysis dependency, it does not
    immediately break do-all detection, and is instead only re-checked against variables
    that are first written inside the loop body. Here "x" is first written (an INIT
    dependency on the body CU itself), so the static dependency must not prevent the
    do-all suggestion."""
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    body_cu = make_node("1:3", NodeType.CU, name="body", start_line=6, end_line=6)
    init_dep = Dependency(EdgeType.DATA)
    init_dep.dtype = DepType.INIT
    init_dep.var_name = "x"
    pet = build_pet_graph(
        [main, loop, body_cu],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, body_cu.id, EdgeType.CHILD),
            (body_cu.id, body_cu.id, init_dep),
        ],
    )

    loop_ctx = LoopParentContext(parent_loop=loop.id)
    iter1 = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[0])
    iter2 = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[1])
    loop_ctx.add_contained_context(iter1)
    loop_ctx.add_contained_context(iter2)
    iter1.register_parent_context(loop_ctx)
    iter2.register_parent_context(loop_ctx)

    work1 = WorkContext()
    work2 = WorkContext()
    work1.add_node(make_tg_node(body_cu.id, level=1, position=0))
    work2.add_node(make_tg_node(body_cu.id, level=1, position=1))
    iter1.add_contained_context(work1)
    iter2.add_contained_context(work2)
    work1.register_parent_context(iter1)
    work2.register_parent_context(iter2)

    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "x"
    dep.origin = DepOrigin.STATIC_ANALYSIS
    work1.register_outgoing_dependency(work2, dep)

    tg_loop = make_tg_node(loop.id, level=0, position=0)
    tg_loop.register_created_context(loop_ctx)
    tg = build_task_graph(pet, [tg_loop])

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert len(patterns) == 1
    assert isinstance(patterns[0], DoAllInfo)


def test_identify_simple_doall_skips_loops_with_fewer_than_two_iterations(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    pet = build_pet_graph([main, loop], [(main.id, loop.id, EdgeType.CHILD)])

    loop_ctx = LoopParentContext(parent_loop=loop.id)
    tg_loop = make_tg_node(loop.id)
    tg_loop.register_created_context(loop_ctx)
    tg = build_task_graph(pet, [tg_loop])

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert patterns == []


def test_identify_simple_doall_skips_loop_with_exactly_one_iteration(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A single-iteration loop has no other iteration to compare against, so it can never
    be shown to be free of cross-iteration dependencies; the "< 2" check must reject it
    just like the zero-iteration case."""
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    body_cu = make_node("1:3", NodeType.CU, name="body", start_line=6, end_line=6)
    pet = build_pet_graph(
        [main, loop, body_cu],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, body_cu.id, EdgeType.CHILD)],
    )

    loop_ctx = LoopParentContext(parent_loop=loop.id)
    iter1 = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[0])
    loop_ctx.add_contained_context(iter1)
    iter1.register_parent_context(loop_ctx)

    work1 = WorkContext()
    work1.add_node(make_tg_node(body_cu.id, level=1, position=0))
    iter1.add_contained_context(work1)
    work1.register_parent_context(iter1)

    tg_loop = make_tg_node(loop.id, level=0, position=0)
    tg_loop.register_created_context(loop_ctx)
    tg = build_task_graph(pet, [tg_loop])

    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet))
    assert patterns == []


class _StubASTHelper(ASTPatternDetectionHelper):
    """An ASTPatternDetectionHelper answering from canned data instead of a loaded AST.

    detect_doall_sharing_clauses asks it three things about the loop's source location: which
    variables are in scope, which of those are of pointer/reference type, and which have their
    own storage assigned inside the loop.
    """

    def __init__(self, in_scope: dict[str, str], assigned_in_loop: frozenset[str] = frozenset()) -> None:
        super().__init__()
        self._in_scope = in_scope
        self._assigned_in_loop = assigned_in_loop

    def get_variables_at_location(
        self, file_id: int | str, line: int, column: int | None = None
    ) -> list[tuple[str, str | None]]:
        return [(name, type_str) for name, type_str in self._in_scope.items()]

    def get_variables_assigned_in_loop_at(self, file_id: int | str, line: int) -> frozenset[str]:
        return self._assigned_in_loop


def _build_pointer_reaim_loop(
    make_node: MakeNode, build_pet_graph: BuildPetGraph, build_task_graph: Any, make_tg_node: Any
) -> Tuple[PEGraphX, LoopParentContext, Node, Node]:
    """Builds the dependency shape a re-aimed pointer produces.

    Two CUs make up each iteration's sequence.  The first initializes ``rA`` (``rA = &rv[i]``),
    the second reads through it (``rA[i].v``), and that read's RAW dependency points at a CU
    outside the loop - the code that filled the array back in the caller.  Because the profiler
    names an indirect access after the pointer it went through, both dependencies carry the name
    ``rA``, which is what makes the pointer look like incoming shared state.
    """
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=10, end_line=20)
    init_cu = make_node("1:3", NodeType.CU, name="init", start_line=11, end_line=11)
    use_cu = make_node("1:4", NodeType.CU, name="use", start_line=12, end_line=12)
    outside_cu = make_node("1:5", NodeType.CU, name="outside", start_line=2, end_line=2)

    init_dep = Dependency(EdgeType.DATA)
    init_dep.dtype = DepType.INIT
    init_dep.var_name = "rA"
    init_dep.origin = DepOrigin.DYNAMIC_ANALYSIS

    read_dep = Dependency(EdgeType.DATA)
    read_dep.dtype = DepType.RAW
    read_dep.var_name = "rA"
    read_dep.origin = DepOrigin.DYNAMIC_ANALYSIS

    pet = build_pet_graph(
        [main, loop, init_cu, use_cu, outside_cu],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, init_cu.id, EdgeType.CHILD),
            (loop.id, use_cu.id, EdgeType.CHILD),
            (main.id, outside_cu.id, EdgeType.CHILD),
            (init_cu.id, init_cu.id, init_dep),
            (use_cu.id, outside_cu.id, read_dep),
        ],
    )

    loop_ctx = LoopParentContext(parent_loop=loop.id)
    for iteration_id in (0, 1):
        iteration = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[iteration_id])
        loop_ctx.add_contained_context(iteration)
        iteration.register_parent_context(loop_ctx)
        work = WorkContext()
        work.add_node(make_tg_node(init_cu.id, level=1, position=2 * iteration_id))
        work.add_node(make_tg_node(use_cu.id, level=1, position=2 * iteration_id + 1))
        iteration.add_contained_context(work)
        work.register_parent_context(iteration)

    return pet, loop_ctx, loop, outside_cu


def _classify(pet: PEGraphX, loop_ctx: LoopParentContext, loop: Node, ast_helper: ASTPatternDetectionHelper) -> Any:
    return detect_doall_sharing_clauses(
        pet,
        ast_helper,
        DataEdgeIndex(pet),
        loop.id,
        [ctx for ctx in loop_ctx.get_contained_contexts(inclusive=False) if isinstance(ctx, IterationContext)],
        loop_ctx.get_contained_contexts(inclusive=True),
        set(),
        {},
    )


def test_pointer_reaimed_in_the_loop_is_private_not_shared(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
) -> None:
    """A pointer assigned inside the loop must be private: sharing it races on the pointer.

    Its incoming RAW dependency describes the memory it is aimed at, not its own value - it
    cannot describe its own value, since it is written before it is read in every iteration.
    """
    pet, loop_ctx, loop, _ = _build_pointer_reaim_loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    ast_helper = _StubASTHelper({"rA": "FOUR_VECTOR *"}, assigned_in_loop=frozenset({"rA"}))

    firstprivate, private, lastprivate, shared, _firstwritten, _init = _classify(pet, loop_ctx, loop, ast_helper)

    assert private == {"rA"}
    assert shared == set()
    assert firstprivate == set()
    assert lastprivate == set()


def test_pointer_only_read_in_the_loop_stays_shared(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
) -> None:
    """The same dependencies, but nothing assigns the pointer itself inside the loop - as for a
    base pointer indexed with ``A[i] = ...``. Privatizing that would break it, so it stays shared.
    """
    pet, loop_ctx, loop, _ = _build_pointer_reaim_loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    ast_helper = _StubASTHelper({"rA": "FOUR_VECTOR *"}, assigned_in_loop=frozenset())

    _firstprivate, private, _lastprivate, shared, _firstwritten, _init = _classify(pet, loop_ctx, loop, ast_helper)

    assert shared == {"rA"}
    assert private == set()
