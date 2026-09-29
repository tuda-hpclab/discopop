# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.MWType import MWType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.utilities.PEGraphConstruction.ParserUtilities import parse_id


# TODO make the Node class abstract
class Node:
    # properties of every Node
    id: NodeID
    file_id: int
    node_id: int
    start_line: int
    end_line: int
    type: NodeType
    name: str
    parent_function_id: Optional[NodeID] = (
        None  # metadata to speedup some calculations (TODO FunctionNodes have themselves as parent)
    )
    workload: Optional[int] = None

    # properties of CU Nodes
    node_calls: List[Dict[str, str]] = []
    recursive_function_calls: List[str] = []

    # properties related to pattern analysis
    reduction: bool = False
    do_all: bool = False
    geometric_decomposition: bool = False
    pipeline: float = -1
    tp_contains_task: bool = False
    tp_contains_taskwait: bool = False
    tp_omittable: bool = False
    mw_type = MWType.FORK

    def __init__(self, node_id: NodeID):
        self.id = node_id
        self.file_id, self.node_id = parse_id(node_id)

    #    @classmethod
    #    def from_kwargs(cls, node_id: NodeID, **kwargs) -> Node:
    #        node = cls(node_id)
    #        for key, value in kwargs.items():
    #            setattr(node, key, value)
    #        return node

    def start_position(self) -> LineID:
        """Start position file_id:line
        e.g. 23:45

        :return:
        """

        return LineID(f"{self.file_id}:{self.start_line}")

    def end_position(self) -> LineID:
        """End position file_id:line
        e.g. 23:45

        :return:
        """
        return LineID(f"{self.file_id}:{self.end_line}")

    def contains_line(self, other_line: str) -> bool:
        if other_line == "GlobalVar" or other_line == "LineNotFound":
            return False
        if not ":" in other_line:
            return False
        other_file_id = int(other_line.split(":")[0])
        other_line_num = int(other_line.split(":")[1])
        if other_file_id != self.file_id:
            return False
        if other_line_num >= self.start_line and other_line_num <= self.end_line:
            return True
        return False

    def get_contained_line_ids(self) -> List[LineID]:
        result: List[LineID] = []
        for i in range(self.start_line, self.end_line + 1):
            result.append(LineID(str(self.file_id) + ":" + str(i)))
        return result

    def __str__(self) -> str:
        return self.id

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Node) and other.file_id == self.file_id and other.node_id == self.node_id

    def __hash__(self) -> int:
        return hash(self.id)
