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
from typing import Any, List, Set, Tuple

import pytest

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
    _output_dependences,
    after_dependences_of_instructions,
    analyze_task_group,
    classify_variable,
    clauses_of_dependences,
    variables_of_instructions,
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

    def get_instruction_scope(self, pet: Any, inclusive: bool = False) -> List[int]:
        return []

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


def test_a_variable_that_several_tasks_accumulate_into_is_a_reduction_not_shared() -> None:
    first = _Ctx([_var("sum", "3:20", "RW")])
    second = _Ctx([_var("sum", "3:20", "RW")])
    flow = _analyze(_pet({}), [first, second])
    assert [(s.shared, s.reduction) for s in flow.sharing] == [([], ["?:sum"]), ([], ["?:sum"])]


def test_the_operation_of_a_reduction_comes_from_the_reduction_entry_on_a_line_of_the_task() -> None:
    first = _Ctx([_var("sum", "3:20", "RW")])
    second = _Ctx([_var("sum", "3:20", "RW")])
    pet = _pet({})
    pet.reduction_vars = [{"name": "sum", "reduction_line": "3:32", "loop_line": "3:30", "operation": "+"}]
    flow = _analyze(pet, [first, second])
    # the entry lies on the line of the second task (32) only: the first one does not know the operation
    assert flow.sharing[0].reduction == ["?:sum"]
    assert flow.sharing[1].reduction == ["+:sum"]


def test_a_variable_that_one_task_writes_and_another_only_reads_is_no_reduction() -> None:
    first = _Ctx([_var("a", "3:20", "RW")])
    second = _Ctx([_var("a", "3:20", "R")])
    flow = _analyze(_pet({}), [first, second])
    assert flow.sharing[0].reduction == [] and flow.sharing[0].shared == ["a"]
    assert flow.sharing[1].reduction == [] and flow.sharing[1].first_private == []
    assert flow.sharing[1].shared == ["a"]


def test_a_variable_whose_write_is_known_from_a_dependence_only_is_written() -> None:
    """The CU of ``sum += f(k)`` can list ``sum`` as read only; the RAW from the task to the code after it shows the
    write."""
    first, second, after = _fib_tasks()
    first.variables = [_var("sum", "3:20", "R")]
    _depends(after, first, "sum", DepType.RAW, 40)
    flow = _analyze(_pet({40: "3:34"}), [first, second])
    assert flow.sharing[0].shared == ["sum"] and flow.sharing[0].first_private == []


def test_a_waw_dependence_makes_both_tasks_outs() -> None:
    dependences = [TaskDependence(0, 1, "d", "WAW")]
    assert clauses_of_dependences(dependences, 0) == ([], ["d"], [])
    assert clauses_of_dependences(dependences, 1) == ([], ["d"], [])


def test_output_dependences_between_tasks_are_read_from_the_instructions_of_the_tasks(
    make_node: Any, build_pet_graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``d = f(k);`` (store 5) in the first task, ``d = f(n);`` (store 6) in the second: a WAW from 5 to 6, which is
    not registered on contexts. A WAW inside a task and one to the code after the tasks are no dependences between
    the tasks."""
    first_cu = make_node("3:10", instruction_ids=[5, 7])
    second_cu = make_node("3:11", instruction_ids=[6])
    edges = []
    for source, sink, variable in ((5, 6, "d"), (5, 7, "e")):
        dependence = Dependency(EdgeType.DATA)
        dependence.dtype, dependence.var_name = DepType.WAW, variable
        dependence.source_instruction_id, dependence.sink_instruction_id = source, sink
        edges.append((second_cu.id if sink == 6 else first_cu.id, first_cu.id, dependence))
    pet = build_pet_graph([first_cu, second_cu], edges)
    for instruction, cu in ((5, first_cu), (7, first_cu), (6, second_cu)):
        monkeypatch.setitem(instructionToCUIdMap, instruction, cu.id)
    assert _output_dependences(pet, [{5, 7}, {6}]) == [TaskDependence(0, 1, "d", "WAW")]


def test_classify_variable() -> None:
    assert classify_variable(True, False, False, False, False, False) == "first_private"
    assert classify_variable(True, False, False, True, False, False) == "shared"
    assert classify_variable(True, True, False, False, False, False) == "shared"
    assert classify_variable(True, False, True, False, False, False) == "private"
    assert classify_variable(False, False, False, False, False, False) is None
    assert classify_variable(True, True, False, False, True, False, True) == "reduction"
    assert classify_variable(True, True, True, False, True, False, True) == "private"


def _recursive_function(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any, passed: List[str]
) -> Tuple[Any, Any]:
    """``void f(int *out, int *in)`` (header line 1) with the task ``f(&x, ...)`` on line 15 (instruction 5, its CU
    accesses the variables ``passed``), a store through ``out`` on line 3 (instruction 20, the base case), a header
    store (instruction 2) and the code after the task: line 17 reads ``x`` and ``out``, line 18 reads ``in``."""
    function = make_node(
        "3:1",
        NodeType.FUNC,
        end_line=30,
        args=[Variable("ptr", VarName("out"), "1", "RW"), Variable("ptr", VarName("in"), "1", "RW")],
    )
    header = make_node("3:10", instruction_ids=[2], start_line=1)
    base = make_node("3:11", instruction_ids=[20], start_line=3)
    call = make_node(
        "3:12",
        node_calls=[{"cuid": "3:1", "atLine": "3:15", "callInstId": "5"}],
        instruction_ids=[5],
        local_vars=[Variable("ptr", VarName(name), "3:2", "R") for name in passed],
        global_vars=[],
    )
    reader = make_node("3:13", instruction_ids=[9, 10], start_line=17)
    edges: List[Any] = [(function.id, cu.id, EdgeType.CHILD) for cu in (header, base, call, reader)]
    for source, sink, variable in ((20, 9, "x"), (20, 9, "out"), (20, 10, "in"), (2, 9, "h")):
        dependence = Dependency(EdgeType.DATA)
        dependence.dtype, dependence.var_name = DepType.RAW, variable
        dependence.source_instruction_id, dependence.sink_instruction_id = source, sink
        edges.append((reader.id, header.id if source == 2 else base.id, dependence))
    pet = build_pet_graph([function, header, base, call, reader], edges)
    pet.instruction_lines = {"2": "3:1", "20": "3:3", "5": "3:15", "9": "3:17", "10": "3:18"}
    for instruction, cu in ((2, header), (20, base), (5, call), (9, reader), (10, reader)):
        monkeypatch.setitem(instructionToCUIdMap, instruction, cu.id)
    return pet, function


def test_the_join_of_a_recursive_task_is_found_without_the_states_of_the_recursion_levels(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    """The base case of the recursion (instruction 20) writes through ``out``, which the caller passed as ``&x``: the
    read of ``x`` on line 17 is a join. The header store of the parameters (instruction 2) never reaches the caller,
    and a parameter that the task does not pass on (``in``) is only read in the frame of its own level."""
    pet, function = _recursive_function(monkeypatch, make_node, build_pet_graph, passed=["out"])
    found = after_dependences_of_instructions(pet, [5], 3, 15, function)
    assert [(a.variable, a.kind, a.line) for a in found] == [("out", "RAW", "3:17"), ("x", "RAW", "3:17")]


def test_a_parameter_the_recursive_task_does_not_pass_on_is_no_join(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    pet, function = _recursive_function(monkeypatch, make_node, build_pet_graph, passed=[])
    found = after_dependences_of_instructions(pet, [5], 3, 15, function)
    assert [(a.variable, a.kind, a.line) for a in found] == [("x", "RAW", "3:17")]


def test_variables_of_instructions(monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any) -> None:
    pet, _ = _recursive_function(monkeypatch, make_node, build_pet_graph, passed=["out", "k"])
    assert variables_of_instructions(pet, [5]) == {"out", "k"}
    assert variables_of_instructions(pet, [2]) == set()
    assert variables_of_instructions(pet, [999]) == set()
