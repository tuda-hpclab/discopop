# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from collections import deque
from io import TextIOWrapper
from typing import Deque, List, cast, TextIO

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes
from discopop_explorer.utilities.PEGraphConstruction.parser import parse_inputs


def __collect_children_ids(pet: PEGraphX, parent_id: NodeID, children_ids: List[NodeID]) -> List[NodeID]:
    if parent_id in children_ids:
        # this id has already been processed. No need to go through it again
        return children_ids
    children_ids.append(parent_id)
    children_ids = list(dict.fromkeys(children_ids))
    # collect all of its children
    for child_node in direct_children_or_called_nodes(pet, pet.node_at(parent_id)):
        children_ids += __collect_children_ids(pet, child_node.id, children_ids)
        children_ids = list(dict.fromkeys(children_ids))
    return children_ids


def __recursive_call_inside_loop(pet: PEGraphX, recursive_function_call: str) -> bool:
    """checks if the given recursive function call occurs in any loop body.
    :param pet: PET Graph
    :param recursive_function_call: string representation of a recursive function call, extracted from cu-xml
    :return: True, if recursive call inside any loop body. False otherwise."""
    for tmp_cu in all_nodes(pet, LoopNode):
        if __line_contained_in_region(
            LineID(recursive_function_call.split(" ")[-1].replace(",", "")),
            tmp_cu.start_position(),
            tmp_cu.end_position(),
        ):
            return True
    return False


def __recursive_function_called_multiple_times_inside_function(pet: PEGraphX, recursive_function_call: str) -> bool:
    """checks if the given recursive function is called multiple times from within a functions body
    :param pet: PET Graph
    :param recursive_function_call: string representation of a recursive function call, extracted from cu-xml
    :return: True, if multiple calls exists. False otherwise."""
    for tmp_func_cu in all_nodes(pet, FunctionNode):
        # 1. get parent function of recursive function call
        if not __line_contained_in_region(
            LineID(recursive_function_call.split(" ")[-1].replace(",", "")),
            tmp_func_cu.start_position(),
            tmp_func_cu.end_position(),
        ):
            continue
        # recursive function call contained in tmp_func_cu
        # 2. check if multiple calls to recursive function exist in tmp_func_cus body
        # by listing cu nodes in function body.
        # get cu's inside function by traversing child edges
        queue: Deque[Node] = deque([tmp_func_cu])
        contained_cus: List[Node] = []
        while len(queue) > 0:
            cur_cu = queue.popleft()
            if __line_contained_in_region(
                cur_cu.start_position(), tmp_func_cu.start_position(), tmp_func_cu.end_position()
            ) and __line_contained_in_region(
                cur_cu.end_position(), tmp_func_cu.start_position(), tmp_func_cu.end_position()
            ):
                # cur_cu contained in tmp_func_cu's scope
                if cur_cu not in contained_cus:
                    contained_cus.append(cur_cu)
                # append cur_cu children to queue
                for child_edge in out_edges(pet, cur_cu.id, [EdgeType.CHILD, EdgeType.CALLSNODE]):
                    child_cu = pet.node_at(child_edge[1])
                    if child_cu not in queue and child_cu not in contained_cus:
                        queue.append(child_cu)
        # get recursive function calls from contained_cus
        rec_calls: List[str] = []
        for tmp_cu in contained_cus:
            rec_calls += tmp_cu.recursive_function_calls
        # remove None and prune rec_calls to called function names only
        rec_calls = [e for e in rec_calls if e is not None]
        rec_calls = [e.split(" ")[0] for e in rec_calls]
        # check if recursive_function_call occurs at least twice
        if rec_calls.count(recursive_function_call.split(" ")[0]) > 1:
            return True
    return False


def __output_dependencies_of_type(
    pet: PEGraphX,
    child_id: NodeID,
    children_ids: List[NodeID],
    output_file: TextIO,
    dep_type: DepType,
    dep_identifier: str,
) -> None:
    """check for and output dependencies of the given type
    :param pet: PET Graph
    :param child_id: specific node id, taken from children_ids
    :param children_ids: list of children node id's of a given node.
    :param output_file: file to be written
    :param dep_type: type of dependency to be handled
    :param dep_identifier: identifier corresponding to the given dep_type (|RAW|, |WAR|, |WAW|)
    """
    for dep in in_edges(pet, child_id, EdgeType.DATA):
        if dep[2].dtype is not dep_type:
            continue
        if dep[2].source_line is None or dep[2].var_name is None or dep[2].sink_line is None:
            continue
        # check if the CUid of the dep exists in children_ids
        if dep[0] in children_ids:
            # CUid found in children_ids. So print the line numbers of this dependence
            output_file.write(
                cast(str, dep[2].sink_line)
                + dep_identifier
                + cast(str, dep[2].source_line)
                + "|"
                + dep[2].var_name
                + ","
            )


def __search_recursive_calls(pet: PEGraphX, output_file: TextIOWrapper, node: Node) -> None:
    if not isinstance(node, CUNode):
        return
    for recursive_function_call in node.recursive_function_calls:
        if recursive_function_call is None:
            continue
        # check if recursive function call occurs inside loop (check if line contained in lines of any loop cu)
        contained_in_loop = __recursive_call_inside_loop(pet, recursive_function_call)
        # check if recursive function call is called multiple times
        called_multiple_times = __recursive_function_called_multiple_times_inside_function(pet, recursive_function_call)

        # check if recursive function is called inside loop or multiple times
        if not (contained_in_loop or called_multiple_times):
            continue

        output_file.write(recursive_function_call + " ")

        children_ids: List[NodeID] = []
        # Output RAW deps. First collect all children IDs of currently called
        # function. Then go through the CU type nodes in them and record all deps
        # that are on the cus in this list.
        children_ids = __collect_children_ids(pet, node.id, children_ids)

        for child_id in children_ids:
            # node type is not cu so goto next node
            if not isinstance(pet.node_at(child_id), CUNode):
                continue
            __output_dependencies_of_type(pet, child_id, children_ids, output_file, DepType.RAW, "|RAW|")
            __output_dependencies_of_type(pet, child_id, children_ids, output_file, DepType.WAR, "|WAR|")
            __output_dependencies_of_type(pet, child_id, children_ids, output_file, DepType.WAW, "|WAW|")

        output_file.write("\n")


def cu_instantiation_input_cpp(pet: PEGraphX, output_file: str) -> None:
    """translation of CUInstantiationInput.cpp, previously contained in discopop-analyzer/analyzer/src.
    Wrapper to gather information on recursive function calls for CU Instantiation.
    :param pet: PET Graph
    :param output_file: Path to storage location of generated Data_CUInst.txt"""
    with open(output_file, "w+") as data_cu_inst_file:
        for node in all_nodes(
            pet,
        ):
            __search_recursive_calls(pet, data_cu_inst_file, node)


def wrapper(cu_xml: str, dep_file: str, loop_counter_file: str, reduction_file: str, output_file: str) -> None:
    """Wrapper to generate the Data_CUInst.txt file, required for the generation of CUInstResult.txt"""
    # 1. generate PET Graph
    pet = PEGraphX.from_parsed_input(*parse_inputs(cu_xml, dep_file, loop_counter_file, reduction_file))  # type: ignore
    # 2. Generate Data_CUInst.txt
    cu_instantiation_input_cpp(pet, output_file)


def __line_contained_in_region(test_line: LineID, start_line: LineID, end_line: LineID) -> bool:
    """check if test_line is contained in [startLine, endLine].
    Return True if so. False else.
    :param test_line: <fileID>:<line>
    :param start_line: <fileID>:<line>
    :param end_line: <fileID>:<line>
    :return: bool
    """
    test_line_file_id = int(test_line.split(":")[0])
    test_line_line = int(test_line.split(":")[1])
    start_line_file_id = int(start_line.split(":")[0])
    start_line_line = int(start_line.split(":")[1])
    end_line_file_id = int(end_line.split(":")[0])
    end_line_line = int(end_line.split(":")[1])
    if (
        test_line_file_id == start_line_file_id == end_line_file_id
        and start_line_line <= test_line_line <= end_line_line
    ):
        return True
    return False
