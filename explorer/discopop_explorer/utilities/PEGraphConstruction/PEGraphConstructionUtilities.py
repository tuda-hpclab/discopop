# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import List, Union

from lxml.objectify import ObjectifiedElement  # type: ignore

from discopop_explorer.classes.PEGraph.CUNode import CUNode

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.utilities.PEGraphConstruction.classes.DependenceItem import DependenceItem
from discopop_explorer.classes.variable import Variable
from discopop_explorer.utilities.PEGraphConstruction.ParserUtilities import parse_id


def parse_dependency(dep: DependenceItem) -> Dependency:
    d = Dependency(EdgeType.DATA)
    d.source_line = dep.source
    d.sink_line = dep.sink
    # check for intra-iteration dependencies
    if "_II_" in dep.type:
        d.intra_iteration = True
        # get intra_iteration_level
        d.intra_iteration_level = int(dep.type[dep.type.rindex("_") + 1 :])
        d.dtype = DepType[dep.type[: dep.type.index("_")]]  # remove _II_x tag
    else:
        d.dtype = DepType[dep.type]
    d.var_name = dep.var_name
    d.memory_region = dep.memory_region
    d.is_gep_result_dependency = dep.is_gep_result_dependency
    d.source_instruction_id = dep.source_instruction_id
    d.sink_instruction_id = dep.sink_instruction_id
    d.source_state_id = dep.source_state_id
    d.sink_state_id = dep.sink_state_id

    return d


def parse_cu(node: ObjectifiedElement) -> Node:
    node_id = node.get("id")
    node_type = NodeType(int(node.get("type")))

    n: Node
    # CU Node
    if node_type == NodeType.CU:
        n = CUNode(node_id)
        if hasattr(node.localVariables, "local"):
            n.local_vars = [
                Variable(v.get("type"), v.text, v.get("defLine"), v.get("accessMode"), 0)
                for v in node.localVariables.local
            ]
        if hasattr(node.globalVariables, "global"):
            n.global_vars = [
                Variable(v.get("type"), v.text, v.get("defLine"), v.get("accessMode"), 0)
                for v in getattr(node.globalVariables, "global")
            ]
        if hasattr(node, "BasicBlockID"):
            n.basic_block_id = getattr(node, "BasicBlockID").text
        if hasattr(node, "returnInstructions"):
            n.return_instructions_count = int(getattr(node, "returnInstructions").get("count"))
        if hasattr(node.callsNode, "nodeCalled"):
            n.node_calls = [
                {"cuid": v.text, "atLine": v.get("atLine"), "callInstId": v.get("callInstId")}
                for v in getattr(node.callsNode, "nodeCalled")
                if v.get("atLine") is not None
            ]
        if hasattr(node, "callsNode") and hasattr(node.callsNode, "recursiveFunctionCall"):
            n.recursive_function_calls = [n.text for n in node.callsNode.recursiveFunctionCall]
        if hasattr(node, "performsFileIO"):
            n.performs_file_io = True if int(getattr(node, "performsFileIO")) == 1 else False
        n.instructions_count = int(getattr(node, "instructionsCount"))
        if not hasattr(node, "instructionIDs"):
            raise ValueError(f"CU {node_id} of Data.xml lists no instructionIDs: it was created by an older profiler")
        n.instruction_ids = [int(i) for i in str(node.instructionIDs.text or "").split(",") if i]

    # FUNC or DUMMY NODE
    elif node_type == NodeType.DUMMY or node_type == NodeType.FUNC:
        dummy_or_func: Union[DummyNode, FunctionNode]
        if node_type == NodeType.DUMMY:
            dummy_or_func = DummyNode(node_id)
        else:
            dummy_or_func = FunctionNode(node_id)
        if hasattr(node, "funcArguments") and hasattr(node.funcArguments, "arg"):
            dummy_or_func.args = [
                Variable(v.get("type"), v.text, v.get("defLine"), "", 0) for v in node.funcArguments.arg
            ]
        n = dummy_or_func

    # LOOP Node
    elif node_type == NodeType.LOOP:
        n = LoopNode(node_id)
    else:
        assert False, "invalid NodeType"

    _, n.start_line = parse_id(node.get("startsAtLine"))
    _, n.end_line = parse_id(node.get("endsAtLine"))
    if node_type == NodeType.CU and n.start_line == 0:
        # an instruction without a source location (e.g. the phi of a short-circuit condition)
        # makes the profiler report line 0 as the start of the CU, which would then span every
        # line of its file up to its end - and contain the code before it, e.g. the code before
        # the loop around it
        n.start_line = _first_known_instruction_line(node, n.end_line)
    n.name = node.get("name")

    return n


def _first_known_instruction_line(node: ObjectifiedElement, end_line: int) -> int:
    """the smallest line other than 0 among the instruction lines of a CU node, or end_line"""
    lines: List[int] = []
    if hasattr(node, "instructionLines") and node.instructionLines.text is not None:
        for entry in str(node.instructionLines.text).split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            try:
                line = int(entry.split(":")[1])
            except ValueError:
                continue
            if line != 0:
                lines.append(line)
    return min(lines) if len(lines) > 0 else end_line
