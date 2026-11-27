# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of TaskGraph.__header_controlled_variables: variables advanced on the line of the loop header
(e.g. `++it`) and written nowhere else in the loop are loop variables."""

from __future__ import annotations

from typing import List, Optional, Tuple

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType

HEADER = LineID("1:10")
BODY = LineID("1:11")
BEFORE = LineID("1:5")
VAR = ("it", MemoryRegion("M1"))


def _dep(dtype: DepType, source_line: LineID, sink_line: LineID, var: Tuple[str, MemoryRegion] = VAR) -> Dependency:
    dep = Dependency(EdgeType.DATA)
    dep.dtype = dtype
    dep.var_name = var[0]
    dep.memory_region = var[1]
    dep.source_line = source_line
    dep.sink_line = sink_line
    return dep


class _Loop:
    """a loop context with a header context and a body context, which are contained in it"""

    def __init__(self) -> None:
        self.loop = LoopParentContext(NodeID("1:2"))
        self.header = Context()
        self.body = Context()
        self.outside = Context()
        self.iteration_ctxs = {self.header, self.body}

    def add(self, source: Context, sink: Context, dep: Dependency) -> None:
        source.register_outgoing_dependency(sink, dep)

    def with_header_control(self) -> "_Loop":
        self.add(self.header, self.header, _dep(DepType.RAW, HEADER, HEADER))
        self.add(self.header, self.body, _dep(DepType.RAW, HEADER, BODY))
        return self

    def result(self, header_line: Optional[LineID] = HEADER) -> List[Tuple[str, MemoryRegion]]:
        # a private static method, under its mangled name
        header_controlled = TaskGraph._TaskGraph__header_controlled_variables  # type: ignore[attr-defined]
        result: List[Tuple[str, MemoryRegion]] = header_controlled(self.loop, self.iteration_ctxs, header_line)
        return result


def test_variable_advanced_on_the_header_line_is_returned() -> None:
    assert _Loop().with_header_control().result() == [VAR]


def test_raw_with_body_writer_disqualifies() -> None:
    loop = _Loop().with_header_control()
    loop.add(loop.body, loop.header, _dep(DepType.RAW, BODY, HEADER))
    assert loop.result() == []


def test_war_with_body_writer_disqualifies() -> None:
    loop = _Loop().with_header_control()
    loop.add(loop.header, loop.body, _dep(DepType.WAR, HEADER, BODY))
    assert loop.result() == []


def test_writer_outside_the_loop_does_not_disqualify() -> None:
    loop = _Loop().with_header_control()
    loop.add(loop.outside, loop.header, _dep(DepType.RAW, BEFORE, HEADER))
    loop.add(loop.outside, loop.header, _dep(DepType.WAW, BEFORE, HEADER))
    assert loop.result() == [VAR]


def test_missing_header_line_yields_no_variables() -> None:
    assert _Loop().with_header_control().result(header_line=None) == []


def test_variable_written_in_body_and_read_in_header_is_no_loop_variable() -> None:
    # while (x < n) x = ...;
    loop = _Loop()
    loop.add(loop.body, loop.header, _dep(DepType.RAW, BODY, HEADER))
    assert loop.result() == []


def test_a_body_write_under_another_name_disqualifies() -> None:
    # library code writing the iterator's memory under its own variable name
    loop = _Loop().with_header_control()
    loop.add(loop.body, loop.header, _dep(DepType.WAW, BODY, HEADER, ("this1", VAR[1])))
    assert loop.result() == []
