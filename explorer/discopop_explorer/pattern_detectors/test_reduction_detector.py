# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Callable, List, Sequence, Tuple, Union, cast

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.reduction_detector import (
    __check_for_problematic_function_argument_access,
    __detect_reduction,
    __get_called_functions,
    __get_parent_loops,
)

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _loop(node: Node) -> LoopNode:
    return cast(LoopNode, node)


# --- __get_parent_loops ---------------------------------------------------------
#
# NOTE: reduction_detector's __get_parent_loops is a near-duplicate of
# do_all_detector's (both files' own docstrings say "duplicates exists:
# do_all_detector <-> reduction_detector !"), but they are NOT identical:
# do_all_detector's version filters `if p != root_loop.id` before returning,
# this one does not. Since the BFS always starts at root_loop.id and appends
# it to `parents` (it is itself a LoopNode), the loop's own start position is
# always included in its own "parent loops" here. These tests characterize
# that as-shipped behavior rather than assume the do_all_detector variant.


def test_get_parent_loops_includes_the_loop_itself(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop", start_line=1)
    pet = build_pet_graph([loop])
    assert __get_parent_loops(pet, _loop(loop)) == [loop.start_position()]


def test_get_parent_loops_includes_both_the_loop_and_its_ancestor(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    outer = make_node("1:1", NodeType.LOOP, name="outer", start_line=1)
    inner = make_node("1:2", NodeType.LOOP, name="inner", start_line=2)
    pet = build_pet_graph([outer, inner], [(outer.id, inner.id, EdgeType.CHILD)])
    assert set(__get_parent_loops(pet, _loop(inner))) == {outer.start_position(), inner.start_position()}


def test_get_parent_loops_empty_only_for_a_non_loop_root(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    # root_loop is always itself a LoopNode in real usage; this documents that a
    # FunctionNode root (which the type signature disallows, but nothing enforces
    # at runtime) is correctly excluded from the result.
    main = make_node("1:1", NodeType.FUNC, name="main")
    pet = build_pet_graph([main])
    assert __get_parent_loops(pet, cast(LoopNode, main)) == []


def test_get_parent_loops_follows_calls_node_edges(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    outer = make_node("1:1", NodeType.LOOP, name="outer", start_line=1)
    caller_cu = make_node("1:2", NodeType.CU, name="caller_cu")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    inner = make_node("2:2", NodeType.LOOP, name="inner", start_line=2)
    pet = build_pet_graph(
        [outer, caller_cu, helper, inner],
        [
            (outer.id, caller_cu.id, EdgeType.CHILD),
            (caller_cu.id, helper.id, EdgeType.CALLSNODE),
            (helper.id, inner.id, EdgeType.CHILD),
        ],
    )
    assert set(__get_parent_loops(pet, _loop(inner))) == {outer.start_position(), inner.start_position()}


# --- __get_called_functions -----------------------------------------------------


def test_get_called_functions_collects_direct_call(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    pet = build_pet_graph(
        [loop, cu, helper],
        [(loop.id, cu.id, EdgeType.CHILD), (cu.id, helper.id, EdgeType.CALLSNODE)],
    )
    assert __get_called_functions(pet, _loop(loop)) == [helper.start_position()]


def test_get_called_functions_empty_when_nothing_called(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([loop, cu], [(loop.id, cu.id, EdgeType.CHILD)])
    assert __get_called_functions(pet, _loop(loop)) == []


# --- __check_for_problematic_function_argument_access ---------------------------


def test_problematic_function_argument_access_true_for_shared_pointer_arg(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[Variable("int*", VarName("p"), "1:1")])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "p"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is True


def test_problematic_function_argument_access_false_for_non_pointer_arg(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[Variable("int", VarName("x"), "1:1")])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "x"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is False


def test_problematic_function_argument_access_false_when_var_is_not_an_argument(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "not_an_arg"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is False


# --- __detect_reduction / __check_loop_dependencies ------------------------------


DepEdge = Tuple[str, str, Union[EdgeType, Dependency]]


def _sum_reduction_pet(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    deps: Sequence[DepEdge] = (),
    declare_reduction_var: bool = True,
) -> Tuple[PEGraphX, Node, Node, Node]:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node(
        "1:3", NodeType.CU, name="cu1", start_line=6, end_line=6, local_vars=[Variable("int", VarName("sum"), "1:1")]
    )
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    reduction_vars = [{"loop_line": loop.start_position(), "name": "sum"}] if declare_reduction_var else None
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
        ]
        + list(deps),
        reduction_vars=reduction_vars,
    )
    return pet, loop, cu1, cu2


def test_detect_reduction_false_without_a_declared_reduction_variable(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, loop, cu1, cu2 = _sum_reduction_pet(make_node, build_pet_graph, declare_reduction_var=False)
    assert __detect_reduction(pet, _loop(loop)) is False


def test_detect_reduction_true_for_declared_reduction_variable_without_dependencies(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, loop, cu1, cu2 = _sum_reduction_pet(make_node, build_pet_graph)
    assert __detect_reduction(pet, _loop(loop)) is True


def test_detect_reduction_false_for_raw_on_reduction_var_between_different_cus(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    # _sum_reduction_pet always places cu1 at "1:3" and cu2 at "1:4"
    raw = Dependency(EdgeType.DATA)
    raw.dtype = DepType.RAW
    raw.var_name = "sum"
    pet, loop, cu1, cu2 = _sum_reduction_pet(make_node, build_pet_graph, deps=[("1:3", "1:4", raw)])
    # a RAW on the reduction variable between two *different* CUs violates the
    # read-compute-write pattern a reduction relies on.
    assert __detect_reduction(pet, _loop(loop)) is False


def test_detect_reduction_true_for_raw_on_reduction_var_within_the_same_cu(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    raw_self = Dependency(EdgeType.DATA)
    raw_self.dtype = DepType.RAW
    raw_self.var_name = "sum"
    pet, loop, cu1, cu2 = _sum_reduction_pet(make_node, build_pet_graph, deps=[("1:3", "1:3", raw_self)])
    # a self-dependency (source == target) is exactly the accumulation pattern
    # (e.g. "sum += x[i]") a reduction is meant to allow.
    assert __detect_reduction(pet, _loop(loop)) is True


def test_detect_reduction_false_for_raw_on_non_reduction_variable_between_different_cus(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    # a RAW on a variable that is *not* the declared reduction variable ("sum") is handled
    # by a separate branch of __check_loop_dependencies: with no dependency metadata and
    # not an intra-iteration dependency, it must still block the reduction suggestion.
    raw = Dependency(EdgeType.DATA)
    raw.dtype = DepType.RAW
    raw.var_name = "y"
    raw.memory_region = "M2"  # type: ignore[assignment]
    war = Dependency(EdgeType.DATA)
    war.dtype = DepType.WAR
    war.var_name = "y"
    war.memory_region = "M2"  # type: ignore[assignment]
    war.sink_line = LineID("1:7")
    pet, loop, cu1, cu2 = _sum_reduction_pet(
        make_node, build_pet_graph, deps=[("1:3", "1:4", raw), ("1:4", "1:3", war)]
    )
    assert __detect_reduction(pet, _loop(loop)) is False
