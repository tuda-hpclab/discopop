# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of what the code after a task depends on when a callee writes through a pointer
(``after_dependences_of_instructions``): the line of the reader in the function, the join before the function returns
when the reader is outside, and the names (the scope of the function that holds the task)."""

from typing import Any, List, Optional, Sequence, Tuple

import pytest

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.task_dataflow import (
    AfterDependence,
    after_dependences_of_instructions,
    instructions_with_callees,
)
from discopop_explorer.utilities.PEGraphConstruction.parser import instructionToCUIdMap


class _Program:
    """The PET of ``put(res, k);`` on line 15 (the task: CU 3:10, instruction 5) in the function 3:1 (lines 1-30).

    - the callee ``put`` (3:99) stores through its pointer with the instruction 20 (CU 3:50, also 21),
    - the code after the task (CU 3:11) reads on line 17 (instruction 9) and calls ``show`` on line 20 (instruction 11),
      whose body (3:60) reads with instruction 30,
    - ``main`` (CU 3:70) reads with instruction 40 on line 60, outside of the function."""

    def __init__(
        self,
        make_node: Any,
        build_pet_graph: Any,
        monkeypatch: pytest.MonkeyPatch,
        dependences: Sequence[Tuple[int, int, str, DepType, Optional[str]]],
        params: Sequence[Variable] = (),
        task_vars: Sequence[Variable] = (),
        reader_vars: Sequence[Variable] = (),
        global_vars: Sequence[Variable] = (),
    ) -> None:
        """``dependences``: (earlier instruction, later instruction, variable, kind, state of the earlier access)."""
        self.caller = make_node(
            "3:10",
            node_calls=[{"cuid": "3:99", "atLine": "3:15", "callInstId": "5"}],
            instruction_ids=[5],
            local_vars=list(task_vars),
        )
        reader = make_node(
            "3:11",
            node_calls=[{"cuid": "3:98", "atLine": "3:20", "callInstId": "11"}],
            instruction_ids=[9, 11],
            local_vars=list(reader_vars),
        )
        self.function = make_node("3:1", NodeType.FUNC, end_line=30)
        self.function.args = list(params)
        put_body = make_node("3:50", instruction_ids=[20, 21], global_vars=list(global_vars))
        show_body = make_node("3:60", instruction_ids=[30])
        main = make_node("3:2", NodeType.FUNC, end_line=90)
        main_body = make_node("3:70", instruction_ids=[40])
        owners = {20: put_body, 21: put_body, 30: show_body, 9: reader, 11: reader, 40: main_body, 5: self.caller}
        edges = []
        for source, sink, variable, kind, state in dependences:
            dependence = Dependency(EdgeType.DATA)
            dependence.dtype, dependence.var_name = kind, variable
            dependence.source_instruction_id, dependence.sink_instruction_id = source, sink
            dependence.source_state_id = state
            edges.append((owners[sink].id, owners[source].id, dependence))
        self.pet = build_pet_graph(
            [
                self.caller,
                reader,
                self.function,
                make_node("3:99", NodeType.FUNC),
                put_body,
                make_node("3:98", NodeType.FUNC),
                show_body,
                main,
                main_body,
            ],
            [
                (self.function.id, self.caller.id, EdgeType.CHILD),
                (self.function.id, reader.id, EdgeType.CHILD),
                ("3:99", put_body.id, EdgeType.CHILD),
                ("3:98", show_body.id, EdgeType.CHILD),
                (main.id, main_body.id, EdgeType.CHILD),
            ]
            + edges,
        )
        self.pet.instruction_lines = {"5": "3:15", "20": "3:10", "9": "3:17", "11": "3:20", "30": "3:40", "40": "3:60"}
        for instruction, cu in owners.items():
            monkeypatch.setitem(instructionToCUIdMap, instruction, cu.id)

    def after(self, **kwargs: Any) -> List[AfterDependence]:
        return after_dependences_of_instructions(self.pet, [5], 3, 15, self.function, **kwargs)


def _ptr(name: str) -> Variable:
    return Variable("ptr", VarName(name), "3:1", "R")


def _global(name: str) -> Variable:
    return Variable("i32", VarName(name), "GlobalVar", "W")


def _summary(found: List[AfterDependence]) -> List[Tuple[str, str, Optional[str], bool]]:
    return [(a.variable, a.kind, a.line, a.at_return) for a in found]


def test_what_a_callee_writes_through_a_pointer_is_read_after_the_task(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    """``a`` is read on line 17 by the function itself, ``p`` is the name of the callee ``show`` that reads the result
    on line 20: the function knows it as ``b``, which the task and the call line have in common."""
    program = _Program(
        make_node,
        build_pet_graph,
        monkeypatch,
        [(20, 9, "a", DepType.RAW, None), (20, 30, "p", DepType.RAW, None)],
        task_vars=[_ptr("b")],
        reader_vars=[_ptr("a"), _ptr("b")],
    )
    assert instructions_with_callees(program.pet, [5]) == {5, 20, 21}
    assert _summary(program.after()) == [("a", "RAW", "3:17", False), ("b", "RAW", "3:20", False)]
    assert program.after(task=3)[0].task == 3
    assert after_dependences_of_instructions(program.pet, [5], 3, 17, program.function)[0].line == "3:20"  # after it


def test_a_task_that_calls_its_own_function_reports_the_dependences_of_the_whole_function(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    program = _Program(make_node, build_pet_graph, monkeypatch, [(20, 9, "a", DepType.RAW, None)])
    recursive = make_node(
        "3:12", node_calls=[{"cuid": "3:1", "atLine": "3:16", "callInstId": "6"}], instruction_ids=[6]
    )
    program.pet.g.add_node(recursive.id, data=recursive)
    program.pet.g.add_edge(program.function.id, recursive.id, data=Dependency(EdgeType.CHILD))
    monkeypatch.setitem(instructionToCUIdMap, 6, recursive.id)
    # the callpath states are cut at the recursive call, so the code of the function counts as the task's work (an
    # over-approximation, see _written_by_recursive_task): the read after the task is found
    found = after_dependences_of_instructions(program.pet, [6], 3, 16, program.function)
    assert [(a.variable, a.kind, a.line, a.at_return) for a in found] == [("a", "RAW", "3:17", False)]


def test_a_read_in_the_caller_is_a_join_before_the_function_returns_named_by_the_pointer_parameter(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    """``main`` reads what ``put`` stored (``x`` there); the function knows the memory as its parameter ``res``, which
    the task passes on, not as ``k`` (not a pointer), ``other`` (not used by the task) or ``x`` (no name of the
    function)."""
    program = _Program(
        make_node,
        build_pet_graph,
        monkeypatch,
        [(20, 40, "x", DepType.RAW, None)],
        params=[_ptr("res"), Variable("i32", VarName("k"), "3:1", "R"), _ptr("other")],
        task_vars=[_ptr("res"), _ptr("k")],
    )
    assert _summary(program.after()) == [("res", "RAW", None, True)]


def test_a_read_in_the_caller_without_a_pointer_parameter_is_reported_without_a_name(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    program = _Program(make_node, build_pet_graph, monkeypatch, [(20, 40, "x", DepType.RAW, None)])
    assert _summary(program.after()) == [("", "RAW", None, True)]


def test_a_global_keeps_its_name_and_a_later_write_is_no_join_before_the_return(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    program = _Program(
        make_node,
        build_pet_graph,
        monkeypatch,
        [(20, 40, "g", DepType.RAW, None), (20, 40, "h", DepType.WAR, None)],
        global_vars=[_global("g")],
    )
    assert _summary(program.after()) == [("g", "RAW", None, True)]


def test_a_read_by_another_task_of_the_group_is_no_join_before_the_return(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    program = _Program(make_node, build_pet_graph, monkeypatch, [(20, 40, "x", DepType.RAW, None)])
    assert program.after(group_instructions={40}) == []


def test_the_callpath_state_tells_which_task_wrote_when_the_tasks_share_the_callee(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    """The state 25 is ``put`` called by the instruction 5 (this task), the state 31 ``put`` called by the instruction 6
    (a sibling task): both write with the instruction 20."""
    program = _Program(
        make_node,
        build_pet_graph,
        monkeypatch,
        [(20, 40, "ga", DepType.RAW, "25"), (20, 40, "gb", DepType.RAW, "31")],
        global_vars=[_global("ga"), _global("gb")],
    )
    assert _summary(program.after()) == [("ga", "RAW", None, True), ("gb", "RAW", None, True)]  # no states known
    program.pet.callpath_tree = {
        "22": ("1", "h"),
        "24": ("22", "call_5"),
        "25": ("24", "put"),
        "23": ("22", "call_6"),
        "31": ("23", "put"),
    }
    assert _summary(program.after()) == [("ga", "RAW", None, True)]


class _Ast:
    """The AST of a function in which ``a`` is only passed by address: the profiler never sees it accessed."""

    def get_variables_at_location(self, file_id: int, line: int) -> List[Tuple[str, Optional[str]]]:
        return [("a", "int"), ("n", "int")]

    def get_referenced_names(self, file_id: int, first: int, last: int) -> frozenset[str]:
        if first <= 15 <= last:
            return frozenset({"a", "put"})
        return frozenset({"a", "show"}) if first <= 20 <= last else frozenset()


def test_the_ast_names_the_variables_that_are_only_passed_by_address(
    monkeypatch: pytest.MonkeyPatch, make_node: Any, build_pet_graph: Any
) -> None:
    program = _Program(make_node, build_pet_graph, monkeypatch, [(20, 30, "p", DepType.RAW, None)])
    assert _summary(program.after()) == [("", "RAW", "3:20", False)]
    found = program.after(ast_helper=_Ast(), task_first_line=15, task_last_line=15)
    assert _summary(found) == [("a", "RAW", "3:20", False)]
