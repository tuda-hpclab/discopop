# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The entry calls of recursive task groups (calls into the recursion from outside of it)."""

from typing import Any, Dict, List, Tuple

from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.task_recursion import CallStructure


def _call(callee: str, line: int, instruction: int) -> Dict[str, str]:
    return {"cuid": callee, "atLine": f"3:{line}", "callInstId": str(instruction)}


def _program(make_node: Any, build_pet_graph: Any, calls: Dict[str, List[Dict[str, str]]]) -> Tuple[Any, CallStructure]:
    """Functions "3:<n>" with one CU "3:<n>1" each, which holds the calls given by function id."""
    nodes = []
    for function_id, node_calls in calls.items():
        function = make_node(function_id, NodeType.FUNC, name="f" + function_id)
        cu = make_node(function_id + "1", NodeType.CU, node_calls=node_calls)
        cu.parent_function_id = function.id
        nodes += [function, cu]
    pet = build_pet_graph(nodes)
    return pet, CallStructure(pet)


def test_the_call_from_a_function_outside_of_the_recursion_is_the_entry(make_node: Any, build_pet_graph: Any) -> None:
    # fib (3:5) calls itself with instructions 6 and 7; main (3:1) calls it at line 13
    pet, calls = _program(
        make_node,
        build_pet_graph,
        {"3:5": [_call("3:5", 6, 6), _call("3:5", 7, 7)], "3:1": [_call("3:5", 13, 20)]},
    )
    assert calls.entry_call_lines(pet.node_at("3:5"), [6, 7]) == ["3:13"]


def test_tasks_that_do_not_reach_their_function_are_no_recursion(make_node: Any, build_pet_graph: Any) -> None:
    pet, calls = _program(
        make_node, build_pet_graph, {"3:5": [_call("3:9", 6, 6)], "3:9": [], "3:1": [_call("3:5", 13, 20)]}
    )
    assert calls.entry_call_lines(pet.node_at("3:5"), [6]) is None


def test_a_mutual_recursion_is_found_and_only_calls_from_outside_of_it_are_entries(
    make_node: Any, build_pet_graph: Any
) -> None:
    # a (3:5) calls b (3:6) in its task, b calls a again; main calls a at lines 30 and 31, b calls a at line 12
    pet, calls = _program(
        make_node,
        build_pet_graph,
        {
            "3:5": [_call("3:6", 6, 6)],
            "3:6": [_call("3:5", 12, 12)],
            "3:1": [_call("3:5", 31, 21), _call("3:5", 30, 20)],
        },
    )
    assert calls.entry_call_lines(pet.node_at("3:5"), [6]) == ["3:30", "3:31"]


def test_a_recursion_without_an_outside_call_has_no_entry(make_node: Any, build_pet_graph: Any) -> None:
    pet, calls = _program(make_node, build_pet_graph, {"3:5": [_call("3:5", 6, 6)]})
    assert calls.entry_call_lines(pet.node_at("3:5"), [6]) == []


def test_a_group_in_a_recursive_function_counts_even_if_its_tasks_do_not_recurse(
    make_node: Any, build_pet_graph: Any
) -> None:
    # f (3:5) has tasks calling work (3:9, instructions 6 and 7) and calls itself outside of them (instruction 8)
    pet, calls = _program(
        make_node,
        build_pet_graph,
        {
            "3:5": [_call("3:9", 6, 6), _call("3:9", 7, 7), _call("3:5", 8, 8)],
            "3:9": [],
            "3:1": [_call("3:5", 13, 20)],
        },
    )
    assert calls.entry_call_lines(pet.node_at("3:5"), [6, 7]) == ["3:13"]
