# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of parse_cu, which turns a node of Data.xml into a PET node, and of the parsing of dependency records."""

from __future__ import annotations

from typing import Optional, cast

import pytest
from lxml import objectify  # type: ignore

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.utilities.PEGraphConstruction.PEGraphConstructionUtilities import parse_cu, parse_dependency
from discopop_explorer.utilities.PEGraphConstruction.classes.DependenceItem import DependenceItem
from discopop_explorer.utilities.PEGraphConstruction.parser import _split_location


def _cu(
    starts_at: str, ends_at: str, instruction_lines: str, instruction_ids: Optional[str] = "17,18"
) -> objectify.ObjectifiedElement:
    count = len([entry for entry in instruction_lines.split(",") if entry != ""])
    ids = "" if instruction_ids is None else f'<instructionIDs count="0">{instruction_ids}</instructionIDs>'
    return objectify.fromstring(
        f"""<Node id="1:575" type="0" name="" startsAtLine = "{starts_at}" endsAtLine = "{ends_at}">
        <childrenNodes></childrenNodes>
        <BasicBlockID>land.end</BasicBlockID>
        <instructionsCount>2</instructionsCount>
        <instructionLines count="{count}">{instruction_lines}</instructionLines>
        {ids}
        <returnInstructions count="0"></returnInstructions>
        <successors></successors>
        <localVariables></localVariables>
        <globalVariables></globalVariables>
        <callsNode></callsNode>
        </Node>"""
    )


def test_an_instruction_without_a_line_does_not_extend_the_cu_to_the_start_of_its_file() -> None:
    """lulesh-init.cc: the phi of a short-circuit condition in loop 442 has line 0, so the CU spanned
    the lines 0-483 and its context in the loop covered the code before the loop. The static
    dependencies between lines before the loop then looked like ones between its iterations."""
    node = parse_cu(_cu("1:0", "1:483", "1:0,1:483"))

    assert (node.start_line, node.end_line) == (483, 483)


def test_a_cu_with_known_lines_keeps_its_start() -> None:
    node = parse_cu(_cu("1:480", "1:483", "1:480,1:483"))

    assert (node.start_line, node.end_line) == (480, 483)


def test_a_cu_without_any_known_line_starts_at_its_end() -> None:
    node = parse_cu(_cu("1:0", "1:7", "1:0"))

    assert (node.start_line, node.end_line) == (7, 7)


def test_the_instructions_of_a_cu_are_kept_in_program_order() -> None:
    assert cast(CUNode, parse_cu(_cu("1:480", "1:483", "1:480,1:483", "851,849,850"))).instruction_ids == [
        851,
        849,
        850,
    ]
    assert cast(CUNode, parse_cu(_cu("1:480", "1:480", "1:480", ""))).instruction_ids == []


def test_a_cu_without_instruction_ids_is_rejected_as_output_of_an_older_profiler() -> None:
    with pytest.raises(ValueError, match="older profiler"):
        parse_cu(_cu("1:480", "1:483", "1:480,1:483", None))


def test_the_ends_of_a_dependency_record_keep_their_instruction_ids_and_states() -> None:
    mapping = {"98": "1:22", "100": "1:22"}
    assert _split_location("100@31", mapping) == (100, "31", "1:22")
    assert _split_location("98", mapping) == (98, None, "1:22")
    assert _split_location("*", mapping) == (None, None, "*")
    assert _split_location("1:22", mapping) == (None, None, "1:22")

    dependency = parse_dependency(DependenceItem("1:22", "1:22", "WAR", "g_caught", "7", False, 98, 100, "31", "31"))
    assert (dependency.source_instruction_id, dependency.sink_instruction_id) == (98, 100)
    assert (dependency.source_state_id, dependency.sink_state_id) == ("31", "31")
