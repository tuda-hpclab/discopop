# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of the data flow of a group of tasks, with the shape of fib: ``x = fib(n - 1); y = fib(n - 2);`` on the
lines 31 and 32 and ``return x + y;`` on line 34."""

from types import SimpleNamespace

import pytest
from typing import Any, List, Set, Tuple

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.utilities.PEGraphConstruction.parser import instructionToCUIdMap
from discopop_explorer.pattern_detectors.task_dataflow import (
    AfterDependence,
    TaskDependence,
    after_dependences_of_instructions,
    analyze_task_group,
    classify_variable,
    clauses_of_dependences,
    instructions_with_callees,
)


class _Ctx:
    def __init__(self, variables: List[Variable] | None = None) -> None:
        self.variables = variables or []
        self.outgoing_dependencies: Set[Tuple[Any, Dependency]] = set()
        self.incoming_dependencies: Set[Tuple[Any, Dependency]] = set()
        self.successive: Set[Any] = set()

    def get_contained_nodes(self, inclusive: bool = False) -> List[Any]:
        node = SimpleNamespace(local_vars=self.variables, global_vars=[])
        return [SimpleNamespace(get_pet_node=lambda pet: node)]

    def get_first_pet_node(self, pet: Any) -> None:
        return None  # no PET node: the writes of callees are tested on their own

    def get_contained_contexts(self, inclusive: bool = False) -> Set[Any]:
        return set()

    def get_successive_contexts(self) -> Set[Any]:
        return self.successive


def _depends(later: _Ctx, earlier: _Ctx, variable: str, kind: DepType, sink_instruction: int = 9) -> None:
    """``later`` is the sink, the later access: the edge of a context points from the sink to the source."""
    dependence = Dependency(EdgeType.DATA)
    dependence.dtype, dependence.var_name, dependence.sink_instruction_id = kind, variable, sink_instruction
    later.outgoing_dependencies.add((earlier, dependence))
    earlier.incoming_dependencies.add((later, dependence))


def _pet(lines: dict[int, str]) -> Any:
    return SimpleNamespace(
        get_line_ids_of_instructions=lambda ids: [lines[i] for i in ids if i in lines],
    )


def _var(name: str, def_line: str, mode: str) -> Variable:
    return Variable("ptr", VarName(name), def_line, mode)


def _analyze(pet: Any, tasks: List[_Ctx]) -> Any:
    return analyze_task_group(pet, tasks, LINES)  # type: ignore[arg-type]


def _fib_tasks() -> Tuple[_Ctx, _Ctx, _Ctx]:
    first = _Ctx([_var("n", "3:26", "R"), _var("x", "3:28", "W")])
    second = _Ctx([_var("n", "3:26", "R"), _var("y", "3:28", "W")])
    after = _Ctx([_var("x", "3:28", "R"), _var("y", "3:28", "R")])
    first.successive = second.successive = {after}
    return first, second, after


LINES = [(3, 31, 31), (3, 32, 32)]


def test_the_code_after_a_group_that_reads_what_the_tasks_wrote_is_reported_with_its_line() -> None:
    first, second, after = _fib_tasks()
    _depends(after, first, "x", DepType.RAW, 40)
    _depends(after, second, "y", DepType.RAW, 41)
    flow = _analyze(_pet({40: "3:34", 41: "3:34"}), [first, second])
    assert flow.after == [AfterDependence(0, "x", "RAW", "3:34"), AfterDependence(1, "y", "RAW", "3:34")]
    assert flow.dependences == []


def test_the_first_line_after_the_group_is_reported() -> None:
    first, second, after = _fib_tasks()
    _depends(after, first, "x", DepType.RAW, 40)
    _depends(after, first, "x", DepType.RAW, 41)
    flow = _analyze(_pet({40: "3:36", 41: "3:34"}), [first, second])
    assert flow.after == [AfterDependence(0, "x", "RAW", "3:34")]


def test_a_dependence_between_two_tasks_has_the_earlier_task_as_its_source() -> None:
    first, second, _ = _fib_tasks()
    _depends(second, first, "a", DepType.RAW)
    flow = _analyze(_pet({}), [first, second])
    assert flow.dependences == [TaskDependence(0, 1, "a", "RAW")]
    assert clauses_of_dependences(flow.dependences, 0) == ([], ["a"], [])
    assert clauses_of_dependences(flow.dependences, 1) == (["a"], [], [])


def test_a_war_between_tasks_makes_the_earlier_a_reader_and_the_later_a_writer() -> None:
    dependences = [TaskDependence(0, 1, "a", "WAR")]
    assert clauses_of_dependences(dependences, 0) == (["a"], [], [])
    assert clauses_of_dependences(dependences, 1) == ([], ["a"], [])


def test_a_variable_that_is_in_and_out_of_a_task_is_in_out() -> None:
    dependences = [TaskDependence(0, 1, "a", "RAW"), TaskDependence(1, 2, "a", "RAW")]
    assert clauses_of_dependences(dependences, 1) == ([], [], ["a"])


def test_other_kinds_of_dependences_are_not_registered() -> None:
    first, second, _ = _fib_tasks()
    _depends(second, first, "a", DepType.INIT)
    assert _analyze(_pet({}), [first, second]).dependences == []


def test_the_data_sharing_of_the_fib_tasks() -> None:
    first, second, after = _fib_tasks()
    _depends(after, first, "x", DepType.RAW, 40)
    _depends(after, second, "y", DepType.RAW, 41)
    flow = _analyze(_pet({40: "3:34", 41: "3:34"}), [first, second])
    assert flow.sharing[0].shared == ["x"] and flow.sharing[0].first_private == ["n"]
    assert flow.sharing[1].shared == ["y"] and flow.sharing[1].first_private == ["n"]


def test_a_variable_declared_in_the_task_is_private_unless_the_code_after_needs_it() -> None:
    first, second, after = _fib_tasks()
    first.variables = [_var("tmp", "3:31", "RW"), _var("res", "3:31", "W")]
    _depends(after, first, "res", DepType.RAW)
    flow = _analyze(_pet({9: "3:34"}), [first, second])
    assert flow.sharing[0].private == ["tmp"]
    assert flow.sharing[0].shared == ["res"]


def test_global_variables_and_variables_written_by_a_sibling_are_shared() -> None:
    first = _Ctx([_var("g", "GlobalVar", "R"), _var("a", "3:20", "R")])
    second = _Ctx([_var("a", "3:20", "W")])
    flow = _analyze(_pet({}), [first, second])
    assert flow.sharing[0].shared == ["a", "g"]


def test_classify_variable() -> None:
    assert classify_variable(True, False, False, False, False, False) == "first_private"
    assert classify_variable(True, False, False, True, False, False) == "shared"
    assert classify_variable(True, True, False, False, False, False) == "shared"
    assert classify_variable(True, False, True, False, False, False) == "private"
    assert classify_variable(False, False, False, False, False, False) is None


def test_what_a_callee_writes_through_a_pointer_is_read_after_the_task(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    """``put(&a, k);`` on line 15 (instruction 5), ``*out = f(n)`` in the callee (store 20), ``return a`` on line 17."""
    caller = make_node("3:10", node_calls=[{"cuid": "3:99", "atLine": "3:15", "callInstId": "5"}], instruction_ids=[5])
    # the code after the task reads a itself (line 17) and calls a function that reads b (line 20)
    reader = make_node(
        "3:11", node_calls=[{"cuid": "3:98", "atLine": "3:20", "callInstId": "11"}], instruction_ids=[9, 11]
    )
    function = make_node("3:1", NodeType.FUNC, end_line=30)
    put = make_node("3:99", NodeType.FUNC)
    put_body = make_node("3:50", instruction_ids=[20, 21])
    show = make_node("3:98", NodeType.FUNC)
    show_body = make_node("3:60", instruction_ids=[30])
    reads = []
    for variable, sink in (("a", 9), ("b", 30)):
        dependence = Dependency(EdgeType.DATA)
        dependence.dtype, dependence.var_name = DepType.RAW, variable
        dependence.source_instruction_id, dependence.sink_instruction_id = 20, sink
        reads.append((reader.id if sink == 9 else show_body.id, put_body.id, dependence))
    pet = build_pet_graph(
        [caller, reader, function, put, put_body, show, show_body],
        [
            (function.id, caller.id, EdgeType.CHILD),
            (function.id, reader.id, EdgeType.CHILD),
            (put.id, put_body.id, EdgeType.CHILD),
            (show.id, show_body.id, EdgeType.CHILD),
        ]
        + reads,
    )
    pet.instruction_lines = {"5": "3:15", "20": "3:10", "9": "3:17", "11": "3:20", "30": "3:40"}
    for instruction, cu in ((5, caller), (20, put_body), (9, reader), (11, reader), (30, show_body)):
        monkeypatch.setitem(instructionToCUIdMap, instruction, cu.id)
    assert instructions_with_callees(pet, [5]) == {5, 20, 21}
    found = after_dependences_of_instructions(pet, [5], 3, 15, function)
    assert [(a.variable, a.kind, a.line) for a in found] == [("a", "RAW", "3:17"), ("b", "RAW", "3:20")]
    assert after_dependences_of_instructions(pet, [5], 3, 17, function)[0].line == "3:20"  # only what follows

    # a task that calls its own function reaches the code around it: no result
    recursive = make_node(
        "3:12", node_calls=[{"cuid": "3:1", "atLine": "3:16", "callInstId": "6"}], instruction_ids=[6]
    )
    pet.g.add_node(recursive.id, data=recursive)
    pet.g.add_edge(function.id, recursive.id, data=Dependency(EdgeType.CHILD))
    monkeypatch.setitem(instructionToCUIdMap, 6, recursive.id)
    assert after_dependences_of_instructions(pet, [6], 3, 16, function) == []
