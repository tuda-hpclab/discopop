# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the instruction ids a pattern reports for the nodes it covers."""

from typing import Any

from discopop_explorer.classes.patterns.PatternInfo import instruction_ids_of
from discopop_explorer.enums.NodeType import NodeType


def test_the_instruction_ids_of_cus_are_listed_once_in_the_order_of_the_nodes(make_node: Any) -> None:
    first = make_node("1:1", NodeType.CU, instruction_ids=[3, 4])
    loop = make_node("1:2", NodeType.LOOP)
    second = make_node("1:3", NodeType.CU, instruction_ids=[5, 4])

    assert instruction_ids_of([first, loop, second]) == [3, 4, 5]
    assert instruction_ids_of([]) == []
