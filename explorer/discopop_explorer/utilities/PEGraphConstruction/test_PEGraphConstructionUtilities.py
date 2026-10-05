# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of parse_cu, which turns a node of Data.xml into a PET node."""

from __future__ import annotations

from lxml import objectify  # type: ignore

from discopop_explorer.utilities.PEGraphConstruction.PEGraphConstructionUtilities import parse_cu


def _cu(starts_at: str, ends_at: str, instruction_lines: str) -> objectify.ObjectifiedElement:
    count = len([entry for entry in instruction_lines.split(",") if entry != ""])
    return objectify.fromstring(
        f"""<Node id="1:575" type="0" name="" startsAtLine = "{starts_at}" endsAtLine = "{ends_at}">
        <childrenNodes></childrenNodes>
        <BasicBlockID>land.end</BasicBlockID>
        <instructionsCount>2</instructionsCount>
        <instructionLines count="{count}">{instruction_lines}</instructionLines>
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
