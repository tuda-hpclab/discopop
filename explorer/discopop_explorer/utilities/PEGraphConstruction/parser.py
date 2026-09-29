# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from io import TextIOWrapper
import os
import re
import warnings
from collections import defaultdict
from os.path import abspath, dirname
from typing import Any, Dict, List, Optional, Tuple

from lxml import objectify  # type: ignore
from lxml.objectify import ObjectifiedElement  # type: ignore

from discopop_explorer.utilities.PEGraphConstruction.classes.DependenceItem import DependenceItem
from discopop_explorer.utilities.PEGraphConstruction.classes.LoopData import LoopData

# Map to record which line belongs to read set of nodes. LID -> NodeIds
readlineToCUIdMap = defaultdict(set)  # type: ignore
# Map to record which line belongs to write set of nodes. LID -> NodeIds
writelineToCUIdMap = defaultdict(set)  # type: ignore
# Map to record which line belongs to set of nodes. LID -> NodeIds
lineToCUIdMap = defaultdict(set)  # type: ignore


def __parse_xml_input(xml_fd: TextIOWrapper) -> Dict[str, ObjectifiedElement]:
    lines = []
    for line in xml_fd:
        stripped = line.rstrip()
        if not (stripped.endswith("</Nodes>") or stripped.endswith("<Nodes>")):
            lines.append(line)

    xml_content = "<Nodes>{0}</Nodes>".format("".join(lines))

    parsed_cu = objectify.fromstring(xml_content)
    cu_dict = dict()
    for node in parsed_cu.Node:
        node.childrenNodes = str(node.childrenNodes).split(",") if node.childrenNodes else []
        if node.get("type") == "0":
            for instruction_id in str(node.writePhaseLines).split(","):
                writelineToCUIdMap[instruction_id].add(node.get("id"))
            for instruction_id in str(node.readPhaseLines).split(","):
                readlineToCUIdMap[instruction_id].add(node.get("id"))
            # add call lines to read lines for cases where reads happen inside the function arguments
            if "callsNode" in dir(node):
                if "nodeCalled" in dir(node.callsNode):
                    for idx, i in enumerate(node.callsNode.nodeCalled):
                        call_at_line = node.callsNode.nodeCalled[idx].get("atLine")
                        if call_at_line not in readlineToCUIdMap:
                            readlineToCUIdMap[call_at_line] = set()
                        readlineToCUIdMap[call_at_line].add(node.get("id"))

        if node.get("id") in cu_dict:
            # entry exists already! merge the two entries
            pass
        else:
            cu_dict[node.get("id")] = node

    return cu_dict


def __map_dummy_nodes(cu_dict: Dict[str, ObjectifiedElement]) -> Dict[str, ObjectifiedElement]:
    dummy_node_args_to_id_map = defaultdict(list)
    func_node_args_to_id_map = dict()
    dummy_to_func_ids_map = dict()
    for node_id, node in cu_dict.items():
        if node.get("type") == "3" or node.get("type") == "1":
            key = node.get("name")
            if "arg" in dir(node.funcArguments):
                for i in node.funcArguments.arg:
                    key = key + i.get("type")
            if node.get("type") == "3":
                dummy_node_args_to_id_map[key].append(node_id)
            else:
                func_node_args_to_id_map[key] = node_id

    # iterate over all real functions
    for func in func_node_args_to_id_map:
        if func in dummy_node_args_to_id_map:
            for dummyID in dummy_node_args_to_id_map[func]:
                dummy_to_func_ids_map[dummyID] = func_node_args_to_id_map[func]
                cu_dict.pop(dummyID)

    # now go through all the nodes and update the mapped dummies to real funcs
    for node_id, node in cu_dict.items():
        # check dummy in all the children nodes
        if "childrenNodes" in dir(node):
            for child_idx, child in enumerate(node.childrenNodes):
                if child in dummy_to_func_ids_map:
                    cu_dict[node_id].childrenNodes[child_idx]._setText(dummy_to_func_ids_map[child])

            # Also do the same in callLineToFunctionMap
            if "callsNode" in dir(node):
                for idx, i in enumerate(node.callsNode.nodeCalled):
                    # atLine = i.get("atLine")
                    # callInstId = i.get("callInstId")
                    if i in dummy_to_func_ids_map:
                        cu_dict[node_id].callsNode.nodeCalled[idx]._setText(dummy_to_func_ids_map[i])

    return cu_dict


def __parse_dep_file(dep_fd: TextIOWrapper, output_path: str) -> Tuple[List[DependenceItem], List[LoopData]]:
    dependencies_list: List[DependenceItem] = []
    loop_data_list: List[LoopData] = []

    # read dependency metadata
    metadata_exists: bool = False
    dependency_metadata_lines = []
    if os.path.exists(os.path.join(output_path, "dependency_metadata.txt")):
        with open(os.path.join(output_path, "dependency_metadata.txt"), "r") as dep_metadata_fd:
            dependency_metadata_lines = dep_metadata_fd.readlines()
        metadata_exists = True
    dependency_metadata: Dict[Tuple[Any, Any, Any, Any, Any], List[str]] = dict()
    for line in dependency_metadata_lines:
        line = line.replace("\n", "")
        split_line = line.split(" ")
        if split_line[0].startswith("#"):
            continue
        type = split_line[0]
        sink = split_line[1]
        source = split_line[2]
        var = split_line[3]
        AAvar = split_line[4]
        line_metadata = " ".join(
            [split_line[5], split_line[6], split_line[7], split_line[8], split_line[9], split_line[10]]
        )  # IAC, IAI, IEC, IEI, SINK_ANC, SOURCE_ANC)
        key_tuple = sink, source, type, var, AAvar
        if key_tuple not in dependency_metadata:
            dependency_metadata[key_tuple] = []
        dependency_metadata[key_tuple].append(line_metadata)

    # read static dependencies
    static_dependency_lines = []
    if not os.path.exists(os.path.join(output_path, "static_dependencies.txt")):
        pass
    else:
        with open(os.path.join(output_path, "static_dependencies.txt"), "r") as static_dep_fd:
            static_dependency_lines = static_dep_fd.readlines()

    # load instruction to lineID mapping for backwards compatibility
    instruction_to_lineID_mapping: Dict[str, str] = dict()
    if os.path.exists(os.path.join(output_path, "instructionID_to_lineID_mapping.txt")):
        with open(os.path.join(output_path, "instructionID_to_lineID_mapping.txt"), "r") as f:
            for line in f.readlines():
                line = line.replace("\n", "")
                if line.startswith("#") or len(line) == 0:
                    continue
                split_line = line.split(" ")
                instruction_id = split_line[0]
                line_id = split_line[1]
                if line_id.startswith("*"):
                    continue
                line_id_split = line_id.split(":")
                file_id = line_id_split[0]
                line_num = line_id_split[1]
                column_num = line_id_split[2]
                instruction_to_lineID_mapping[instruction_id] = str(file_id) + ":" + str(line_num)

    for line in dep_fd.readlines() + static_dependency_lines:
        dep_fields = line.split()
        if dep_fields[1] == "BGN" and dep_fields[2] == "loop":
            line_id = dep_fields[0]
            total_iteration_count = int(dep_fields[3])
            entry_count = int(dep_fields[4])
            average_iteration_count = int(dep_fields[5])
            maximum_iteration_count = int(dep_fields[6])
            loop_data_list.append(
                LoopData(
                    line_id,
                    total_iteration_count,
                    entry_count,
                    average_iteration_count,
                    maximum_iteration_count,
                )
            )
        if len(dep_fields) < 4 or dep_fields[1] != "NOM":
            continue

        sink = dep_fields[0]
        # pairwise iteration over dependencies source
        for dep_pair in list(zip(dep_fields[2:], dep_fields[3:]))[::2]:
            type = dep_pair[0]
            source_fields = dep_pair[1].split("|")
            var_str = "" if len(source_fields) == 1 else source_fields[1]
            var_name = ""
            aa_var_name = ""
            metadata: Optional[List[str]] = [] if metadata_exists else None
            if len(var_str) > 0:
                if "(" in var_str:
                    split_var_str = var_str.split("(")
                    var_name = split_var_str[0]
                    aa_var_name = split_var_str[1][
                        : split_var_str[1].index(")")
                    ]  # name of the allocated variable which is accessed, i.e. variable name after anti aliasing
                else:
                    # compatibility with results created without alias analysis
                    var_name = var_str
            # retrieve metadata
            key_tuple = sink, source_fields[0], type, var_name, aa_var_name
            if key_tuple in dependency_metadata:
                metadata = dependency_metadata[key_tuple]

            # check if the dependency originates from the result of a GEP instruction
            is_gep_result_dependency = False
            if var_name.startswith("GEPRESULT_"):
                var_name = var_name.replace("GEPRESULT_", "")
                is_gep_result_dependency = True

            # convert instruction ids to lineIds for backwards compatibility
            source = source_fields[0]
            if ":" not in sink:
                if "@" in sink:
                    sink = sink[: sink.index("@")]  # remove state information
                if sink in instruction_to_lineID_mapping:
                    sink = instruction_to_lineID_mapping[sink]
            if ":" not in source:
                if "@" in source:
                    source = source[: source.index("@")]  # remove state information
                if source in instruction_to_lineID_mapping:
                    source = instruction_to_lineID_mapping[source]

            # register dependencies
            if metadata is None:
                dependencies_list.append(
                    DependenceItem(sink, source, type, var_name, aa_var_name, is_gep_result_dependency, None)
                )
                continue

            if len(metadata) == 0:
                dependencies_list.append(
                    DependenceItem(sink, source, type, var_name, aa_var_name, is_gep_result_dependency, "")
                )
            else:
                for md_set in metadata:
                    dependencies_list.append(
                        DependenceItem(sink, source, type, var_name, aa_var_name, is_gep_result_dependency, md_set)
                    )

    return dependencies_list, loop_data_list


def parse_inputs(
    cu_file: str, dependencies_file_path: str, reduction_file: str, file_mapping: str
) -> Tuple[Dict[str, ObjectifiedElement], List[DependenceItem], Dict[str, LoopData], Optional[List[Dict[str, str]]]]:
    with open(cu_file) as f:
        cu_dict = __parse_xml_input(f)
    cu_dict = __map_dummy_nodes(cu_dict)

    with open(dependencies_file_path) as f:
        dependencies, loop_info = __parse_dep_file(f, dirname(abspath(cu_file)))

    loop_data = {loop.line_id: loop for loop in loop_info}

    fmap_file = open(file_mapping)
    fmap_lines = fmap_file.read().splitlines()
    fmap_file.close()

    if os.path.exists(reduction_file):
        reduction_vars = []

        # parse reduction variables
        with open(reduction_file) as f:
            content = f.readlines()
        for line in content:
            if is_reduction(line, fmap_lines, file_mapping):
                line = line.replace("\n", "")
                s = line.split(" ")
                var = {
                    "loop_line": f"{s[3]}:{s[8]}",
                    "name": s[17],
                    "reduction_line": f"{s[3]}:{s[13]}",
                    "operation": s[21],
                }
                reduction_vars.append(var)
    else:
        reduction_vars = None

    return cu_dict, dependencies, loop_data, reduction_vars


def is_reduction(reduction_line: str, fmap_lines: List[str], file_mapping: str) -> bool:
    rex = re.compile("FileID : ([0-9]*) Loop Line Number : [0-9]* Reduction Line Number : ([0-9]*) ")
    if not rex:
        return False
    res = rex.search(reduction_line)
    if res is None:
        return False
    file_id = int(res.group(1))
    file_line = int(res.group(2))

    filepath = get_filepath(file_id, fmap_lines, file_mapping)
    if not os.path.exists(filepath):
        return False
    src_file = open(filepath)
    src_lines = src_file.read().splitlines()
    src_file.close()

    return possible_reduction(file_line, src_lines)


def possible_reduction(line: int, src_lines: List[str]) -> bool:
    assert line > 0 and line <= len(src_lines), "invalid src line"
    src_line = src_lines[line - 1]
    while not ";" in src_line:
        line = line + 1
        if line > len(src_lines):
            return False
        src_line = src_line + " " + src_lines[line - 1]

    pos = src_line.find("=")
    if pos == -1:
        return True

    bracket_a = src_line[0:pos].find("[")
    if bracket_a == -1:
        return True
    bracket_b = src_line[0:pos].rfind("]")
    assert bracket_b != -1

    rex_search_res = re.search(r"([A-Za-z0-9_]+)\[", src_line[0 : (bracket_a + 1)])
    if not rex_search_res:
        return True

    array_name = rex_search_res[1]
    array_index = src_line[(bracket_a + 1) : bracket_b]

    array_indices = find_array_indices(array_name, src_line[pos : len(src_line)])
    for index in array_indices:
        if index == array_index:
            return False

    return True


def get_filepath(file_id: int, fmap_lines: List[str], file_mapping: str) -> str:
    assert file_id > 0 and file_id <= len(fmap_lines), "invalid file id"
    line = fmap_lines[file_id - 1]
    tokens = line.split(sep="\t")
    if tokens[1].startswith(".."):
        return os.path.dirname(file_mapping) + "/" + tokens[1]
    else:
        return tokens[1]


def get_enclosed_str(data: str) -> str:
    num_open_brackets = 1
    for i in range(0, len(data)):
        if data[i] == "[":
            num_open_brackets = num_open_brackets + 1
        elif data[i] == "]":
            num_open_brackets = num_open_brackets - 1
            if num_open_brackets == 0:
                return data[0:i]
    raise ValueError("No enclosed str found!")


def find_array_indices(array_name: str, src_line: str) -> List[str]:
    indices: List[str] = []
    uses = list(re.finditer(array_name, src_line))
    for use in uses:
        if src_line[use.end()] == "[":
            indices.append(get_enclosed_str(src_line[(use.end() + 1) : len(src_line)]))
        else:
            indices.append("")

    return indices
