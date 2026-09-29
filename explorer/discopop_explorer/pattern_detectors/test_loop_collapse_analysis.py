# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Unit tests for the identification of collapsible do-all loop nests.

The pet graphs built here mirror the structure a real loop nest produces. For

    for (i = ...)          // loop node, lines 10-100
      for (j = ...)        // loop node, lines 11-99
        body;

the outer loop node has five children: its entry CU and its increment CU (both on the loop's header
line), the inner loop's initialization CU (on the inner loop's header line), the CU closing the
loop body (on the outer loop's last line), and the inner loop node itself. A statement between the
two loops shows up as an additional child CU on a line of its own, which is what distinguishes a
perfect from an imperfect nest.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple, Union

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.loop_collapse_analysis import identify_collapsible_loop_nests
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]

# variable name used as the loop variable of the loop at each nesting level
LOOP_VARIABLE_NAMES = ["i", "j", "k"]


class _AstHelperWithKnownVars(ASTPatternDetectionHelper):
    """An AST helper which reports a fixed set of variables as being in scope everywhere, so that
    the scope filtering can be exercised without loading a real AST."""

    def __init__(self, known_vars: Sequence[str]) -> None:
        super().__init__()
        self._known_vars = list(known_vars)

    def is_ast_loaded(self) -> bool:
        return True

    def get_variables_at_location(
        self, file_id: Union[int, str], line: int, column: Optional[int] = None
    ) -> list[tuple[str, Optional[str]]]:
        return [(name, "int") for name in self._known_vars]


def _build_loop_nest(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    depth: int,
    work_between_loops_at_levels: Sequence[int] = (),
    additional_nested_loop_at_levels: Sequence[int] = (),
) -> Tuple[PEGraphX, TaskGraph, List[NodeID]]:
    """Builds `depth` nested loops and returns the pet graph, a task graph registering a
    LoopParentContext per loop, and the entry CU id of each loop, outermost first.

    work_between_loops_at_levels: levels whose loop body gets an extra CU representing a statement
        next to the nested loop, which makes the nesting imperfect.
    additional_nested_loop_at_levels: levels which get a second nested loop, so that the level
        encloses more than one loop.
    """
    nodes: List[Node] = []
    edges: List[Tuple[str, str, Union[EdgeType, Any]]] = []
    next_node_id = [1]

    def new_node(node_type: NodeType, start_line: int, end_line: int, name: str = "cu") -> Node:
        node = make_node(f"1:{next_node_id[0]}", node_type, name=name, start_line=start_line, end_line=end_line)
        next_node_id[0] += 1
        nodes.append(node)
        return node

    function_node = make_node("0:0", NodeType.FUNC, name="main", start_line=1, end_line=200)
    nodes.append(function_node)

    entry_cu_ids: List[NodeID] = []

    def build_level(level: int, parent_id: str) -> None:
        # the loop of each level is indented by one line at the top and at the bottom
        loop_start = 10 + level
        loop_end = 100 - level
        loop_node = new_node(NodeType.LOOP, loop_start, loop_end, name=f"loop_{level}")
        edges.append((parent_id, loop_node.id, EdgeType.CHILD))

        # entry CU, on the loop's header line
        entry_cu = new_node(NodeType.CU, loop_start, loop_start)
        edges.append((loop_node.id, entry_cu.id, EdgeType.CHILD))
        entry_cu_ids.append(entry_cu.id)

        is_innermost = level == depth - 1
        if is_innermost:
            # the innermost loop body performs the actual work
            body_cu = new_node(NodeType.CU, 50, 50)
            edges.append((loop_node.id, body_cu.id, EdgeType.CHILD))
        else:
            # initialization CU of the nested loop, on the nested loop's header line
            nested_init_cu = new_node(NodeType.CU, loop_start + 1, loop_start + 1)
            edges.append((loop_node.id, nested_init_cu.id, EdgeType.CHILD))

            if level in work_between_loops_at_levels:
                # a statement next to the nested loop, on a line of its own
                work_cu = new_node(NodeType.CU, 50, 50)
                edges.append((loop_node.id, work_cu.id, EdgeType.CHILD))

            build_level(level + 1, loop_node.id)

            if level in additional_nested_loop_at_levels:
                sibling_loop = new_node(NodeType.LOOP, loop_start + 1, loop_end - 1, name=f"loop_{level}_sibling")
                edges.append((loop_node.id, sibling_loop.id, EdgeType.CHILD))
                sibling_entry_cu = new_node(NodeType.CU, loop_start + 1, loop_start + 1)
                edges.append((sibling_loop.id, sibling_entry_cu.id, EdgeType.CHILD))

            # CU closing the loop body, on the loop's last line
            closing_cu = new_node(NodeType.CU, loop_end, loop_end)
            edges.append((loop_node.id, closing_cu.id, EdgeType.CHILD))

        # increment CU, on the loop's header line
        increment_cu = new_node(NodeType.CU, loop_start, loop_start)
        edges.append((loop_node.id, increment_cu.id, EdgeType.CHILD))

    build_level(0, function_node.id)
    pet = build_pet_graph(nodes, edges)

    tg_nodes = []
    for level, entry_cu_id in enumerate(entry_cu_ids):
        loop_ctx = LoopParentContext(parent_loop=entry_cu_id)
        loop_ctx.loop_variables = [(LOOP_VARIABLE_NAMES[level], MemoryRegion(str(level)))]
        tg_node = make_tg_node(entry_cu_id, level=level, position=0)
        tg_node.register_created_context(loop_ctx)
        tg_nodes.append(tg_node)
    tg = build_task_graph(pet, tg_nodes)

    return pet, tg, entry_cu_ids


def _make_doall(
    pet: PEGraphX,
    node_id: NodeID,
    first_private: Sequence[str] = (),
    private: Sequence[str] = (),
    last_private: Sequence[str] = (),
    shared: Sequence[str] = (),
) -> DoAllInfo:
    """Creates a do-all pattern for the given loop entry CU with the given data sharing clauses."""
    pattern = DoAllInfo(pet, pet.node_at(node_id))
    pattern.first_private = _to_variables(first_private)
    pattern.private = _to_variables(private)
    pattern.last_private = _to_variables(last_private)
    pattern.shared = _to_variables(shared)
    pattern.reduction = []
    pattern.pattern_tag = pattern.get_tag()
    return pattern


def _to_variables(names: Sequence[str]) -> List[Variable]:
    return [Variable(type="int", name=VarName(name), defLine="1:1") for name in names]


def _clause_names(variables: Sequence[Variable]) -> List[str]:
    return sorted([str(v.name) for v in variables])


def test_clean_two_level_nest_yields_a_single_collapse_level_two_pattern(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0]),
        _make_doall(pet, entry_cu_ids[1]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    assert len(collapsed) == 1
    assert collapsed[0].collapse_level == 2
    # the collapsed pattern is based on the outer loop, as that is where the pragma goes
    assert collapsed[0].node_id == entry_cu_ids[0]


def test_associated_loop_variables_are_removed_from_all_clauses(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """The loop variables of every collapsed loop become the iteration variables of the collapsed
    construct. They are private to it implicitly and are not allowed in a data sharing clause, so
    the inner loop's `firstprivate(i)` must not survive the merge."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0], first_private=["nk", "nj", "ni"], private=["j", "k"], shared=["A", "B", "E"]),
        _make_doall(pet, entry_cu_ids[1], first_private=["nk", "nj", "i"], private=["k"], shared=["A", "B", "E"]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    assert len(collapsed) == 1
    assert _clause_names(collapsed[0].first_private) == ["ni", "nj", "nk"]
    assert _clause_names(collapsed[0].private) == ["k"]
    assert _clause_names(collapsed[0].shared) == ["A", "B", "E"]
    assert _clause_names(collapsed[0].last_private) == []


def test_clause_precedence_is_applied_when_merging_clauses(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A variable classified differently by the two loops must end up in exactly one clause."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0], private=["x", "y"]),
        _make_doall(pet, entry_cu_ids[1], shared=["x"], first_private=["y"]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    assert len(collapsed) == 1
    # shared wins over private, firstprivate wins over private
    assert _clause_names(collapsed[0].shared) == ["x"]
    assert _clause_names(collapsed[0].first_private) == ["y"]
    assert _clause_names(collapsed[0].private) == []


def test_variables_out_of_scope_at_the_outer_loop_are_dropped(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """A variable declared inside the outer loop body cannot appear in a clause of a pragma placed
    in front of the outer loop, so it must be filtered out when the AST tells us it is not in
    scope there."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0], shared=["global_array"]),
        _make_doall(pet, entry_cu_ids[1], private=["declared_in_outer_body"], shared=["global_array"]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, _AstHelperWithKnownVars(["global_array"]), patterns)

    assert len(collapsed) == 1
    assert _clause_names(collapsed[0].shared) == ["global_array"]
    assert _clause_names(collapsed[0].private) == []


def test_work_between_the_loops_prevents_collapse(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """The loops are not perfectly nested, so collapsing them would execute the statement between
    them a different number of times."""
    pet, tg, entry_cu_ids = _build_loop_nest(
        make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2, work_between_loops_at_levels=[0]
    )
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0]),
        _make_doall(pet, entry_cu_ids[1]),
    ]

    assert identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns) == []


def test_more_than_one_nested_loop_prevents_collapse(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    pet, tg, entry_cu_ids = _build_loop_nest(
        make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2, additional_nested_loop_at_levels=[0]
    )
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0]),
        _make_doall(pet, entry_cu_ids[1]),
    ]

    assert identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns) == []


def test_nested_loop_without_a_doall_pattern_prevents_collapse(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Only loops which have been identified as do-all loops may be collapsed."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [_make_doall(pet, entry_cu_ids[0])]

    assert identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns) == []


def test_outer_loop_without_a_doall_pattern_prevents_collapse(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [_make_doall(pet, entry_cu_ids[1])]

    assert identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns) == []


def test_nested_reduction_loop_prevents_collapse(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Collapsing changes which iterations share the reduction target, so a loop which carries a
    reduction must not be folded into a nest. The same loop being reported as a do-all as well
    does not make it collapsible."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    reduction = ReductionInfo(pet, pet.node_at(entry_cu_ids[1]), reduction=_to_variables(["sum"]))
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0]),
        _make_doall(pet, entry_cu_ids[1]),
        reduction,
    ]

    assert identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns) == []


def test_clean_three_level_nest_yields_every_reachable_collapse_level(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Collapsing may be applied repeatedly to build deeper nests. Every depth is a valid
    alternative, so the outermost loop yields both a two and a three level collapse, and the
    middle loop yields a two level collapse of its own."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=3)
    patterns: List[DoAllInfo | ReductionInfo] = [_make_doall(pet, node_id) for node_id in entry_cu_ids]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    assert sorted([(p.node_id, p.collapse_level) for p in collapsed]) == sorted(
        [
            (entry_cu_ids[0], 2),
            (entry_cu_ids[0], 3),
            (entry_cu_ids[1], 2),
        ]
    )


def test_three_level_collapse_merges_the_clauses_of_all_involved_loops(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=3)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0], shared=["a"], private=["j", "k"]),
        _make_doall(pet, entry_cu_ids[1], shared=["b"], first_private=["i"]),
        _make_doall(pet, entry_cu_ids[2], shared=["c"], first_private=["i", "j"]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    three_level = [p for p in collapsed if p.collapse_level == 3]
    assert len(three_level) == 1
    # all three loop variables are associated with the collapsed construct and drop out
    assert _clause_names(three_level[0].shared) == ["a", "b", "c"]
    assert _clause_names(three_level[0].first_private) == []
    assert _clause_names(three_level[0].private) == []


def test_collapsed_pattern_records_the_patterns_it_was_derived_from(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Applying a collapse pattern excludes applying the patterns of the loops it folded in, so
    the relation has to be recorded for downstream consumers."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    outer = _make_doall(pet, entry_cu_ids[0])
    inner = _make_doall(pet, entry_cu_ids[1])
    patterns: List[DoAllInfo | ReductionInfo] = [outer, inner]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    assert len(collapsed) == 1
    assert collapsed[0].collapsed_pattern_ids == [outer.pattern_id, inner.pattern_id]
    # the patterns it was derived from are kept as alternatives
    assert collapsed[0].pattern_id not in [outer.pattern_id, inner.pattern_id]


def test_collapse_level_distinguishes_the_pattern_tags(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """The two collapses reported for the outermost loop of a three level nest carry identical
    clauses here, so only the collapse level keeps their tags apart. Equal tags would make one of
    them get dropped as a duplicate."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=3)
    patterns: List[DoAllInfo | ReductionInfo] = [_make_doall(pet, node_id) for node_id in entry_cu_ids]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)

    tags = [p.pattern_tag for p in collapsed]
    assert len(set(tags)) == len(tags)


def test_collapsed_patterns_are_not_collapsed_again(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
) -> None:
    """Deeper nests are built by extending the chain of loops, not by folding an already collapsed
    pattern into another one, which would count the same loop twice."""
    pet, tg, entry_cu_ids = _build_loop_nest(make_node, build_pet_graph, build_task_graph, make_tg_node, depth=2)
    patterns: List[DoAllInfo | ReductionInfo] = [
        _make_doall(pet, entry_cu_ids[0]),
        _make_doall(pet, entry_cu_ids[1]),
    ]

    collapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns)
    # feeding the results back in must not report any additional nest
    recollapsed = identify_collapsible_loop_nests(tg, ASTPatternDetectionHelper(), patterns + list(collapsed))

    assert [(p.node_id, p.collapse_level) for p in recollapsed] == [(p.node_id, p.collapse_level) for p in collapsed]
