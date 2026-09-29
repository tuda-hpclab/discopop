# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import os
from typing import Any, List

from lxml import objectify, etree  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import line_contained_in_region


def cu_xml_preprocessing(cu_xml: str) -> str:
    """Execute CU XML Preprocessing.
    Returns file name of modified cu xml file.
    :param cu_xml: path to the xml file
    :return: file name of modified cu xml file.
    """
    xml_fd = open(cu_xml)
    xml_content = ""
    for line in xml_fd.readlines():
        if not (line.rstrip().endswith("</Nodes>") or line.rstrip().endswith("<Nodes>")):
            xml_content = xml_content + line

    xml_content = "<Nodes>{0}</Nodes>".format(xml_content)

    parsed_cu = objectify.fromstring(xml_content)

    iterate_over_cus = True  # used to enable re-starting
    self_added_node_ids: List[str] = []
    while iterate_over_cus:
        used_node_ids = []
        for node in parsed_cu.Node:
            used_node_ids.append(node.get("id"))

        for node in parsed_cu.Node:
            inner_iteration = True
            remaining_recursive_call_in_parent = False
            while inner_iteration:
                used_node_ids = list(dict.fromkeys(used_node_ids + self_added_node_ids))

                if node.get("type") == "0":  # iterate over CU nodes
                    # find CU nodes with > 1 recursiveFunctionCalls in own code region
                    if (
                        __preprocessor_cu_contains_at_least_two_recursive_calls(node)
                        or remaining_recursive_call_in_parent
                    ):
                        remaining_recursive_call_in_parent = False
                        # Preprocessor Step 1
                        tmp_cn_entry = None  # (recursiveFunctionCall, nodeCalled)
                        for cne_idx, calls_node_entry in enumerate(node.callsNode):
                            # get first matching entry of node.callsNode
                            try:
                                for rc_idx, rec_call in enumerate(calls_node_entry.recursiveFunctionCall):
                                    rec_call_line = calls_node_entry.nodeCalled[rc_idx].get("atLine")
                                    if str(rec_call_line) in str(rec_call):
                                        tmp_cn_entry = (
                                            rec_call,
                                            calls_node_entry.nodeCalled[rc_idx],
                                        )
                                        break
                            except AttributeError:
                                continue
                        if tmp_cn_entry is None:
                            raise Exception("no matching entries for callsNode found!")

                        parent = node
                        tmp_cn_entry[0].getparent().remove(tmp_cn_entry[0])
                        tmp_cn_entry[1].getparent().remove(tmp_cn_entry[1])
                        parent_copy = copy.copy(parent)
                        parsed_cu.insert(parsed_cu.index(parent), parent_copy)

                        # Preprocessor Step 2 - generate cu id for new element
                        __generate_new_cu_id(parent, parent_copy, used_node_ids, self_added_node_ids)

                        # Preprocessor Step 3
                        parent_copy.callsNode.clear()
                        parent_copy.callsNode.append(tmp_cn_entry[1])
                        parent_copy.callsNode.append(tmp_cn_entry[0])

                        parent_copy.successors.clear()
                        etree.SubElement(parent_copy.successors, "CU")
                        parent_copy.successors.CU._setText(parent.get("id"))

                        # delete childrenNodes-entry from parent
                        tmp_cu_id = tmp_cn_entry[1].text
                        parent.childrenNodes._setText(parent.childrenNodes.text.replace(tmp_cu_id + ",", ""))
                        parent.childrenNodes._setText(parent.childrenNodes.text.replace(tmp_cu_id, ""))

                        # set parent_copy.childrenNodes
                        __set_parent_copy_childrennodes(parent_copy)

                        # Preprocessor Step 4
                        # __remove_overlapping_start_and_end_lines(parent_copy, parent.instructionLines)
                        # __remove_overlapping_start_and_end_lines(parent_copy, parent.readPhaseLines)
                        # __remove_overlapping_start_and_end_lines(parent_copy, parent.writePhaseLines)

                        separator_line = parent.get("startsAtLine")
                        # select smallest recursive function call line >= separator_line + 1
                        parent_new_start_line = None
                        potential_lines = []
                        for tmp1 in parent.callsNode:
                            try:
                                for tmp2 in tmp1.nodeCalled:
                                    try:
                                        potential_lines.append(tmp2.get("atLine"))
                                        pass
                                    except AttributeError:
                                        pass
                            except AttributeError:
                                pass
                        for tmp in potential_lines:
                            if tmp == "":
                                continue
                            if int(tmp[tmp.find(":") + 1 :]) >= int(separator_line[separator_line.find(":") + 1 :]) + 1:
                                if parent_new_start_line is None:
                                    parent_new_start_line = tmp
                                    continue
                                # select smallest instruction line
                                if int(tmp[tmp.find(":") + 1 :]) < int(
                                    parent_new_start_line[parent_new_start_line.find(":") + 1 :]
                                ):
                                    parent_new_start_line = tmp
                        if not potential_lines or (potential_lines and not parent_new_start_line):
                            parent_new_start_line = str(separator_line[: separator_line.index(":")])
                            parent_new_start_line += ":"
                            parent_new_start_line += str(int(separator_line[separator_line.index(":") + 1 :]) + 1)

                        parent.set("startsAtLine", parent_new_start_line)
                        parent_copy.set("endsAtLine", separator_line)

                        # update instruction/readPhase/writePhase lines
                        # __filter_rwi_lines(parent_copy, parent_copy.instructionLines)
                        # __filter_rwi_lines(parent_copy, parent_copy.readPhaseLines)
                        # __filter_rwi_lines(parent_copy, parent_copy.writePhaseLines)

                        # insert separator line to parent_copys instruction,
                        # read and writePhaseLines if not already present
                        # __insert_separator_line(parent_copy, parent_copy.instructionLines)
                        # __insert_separator_line(parent_copy, parent_copy.readPhaseLines)
                        # __insert_separator_line(parent_copy, parent_copy.writePhaseLines)

                        # insert all lines contained in parent to instruction, read and writePhaseLines
                        # __insert_missing_rwi_lines(parent, parent.instructionLines)
                        # __insert_missing_rwi_lines(parent, parent.readPhaseLines)
                        # __insert_missing_rwi_lines(parent, parent.writePhaseLines)

                        # remove returnInstructions if they are not part of the cus anymore
                        __remove_unnecessary_return_instructions(parent_copy)
                        __remove_unnecessary_return_instructions(parent)

                        # add parent.id to parent_function.childrenNodes
                        __add_parent_id_to_children(parsed_cu, parent)

                        # Preprocessor Step 5 (looping)
                        parent_further_cn_entry = None
                        for cne_idx, calls_node_entry in enumerate(parent.callsNode):
                            # get first matching entry of node.callsNode
                            try:
                                for rc_idx, rec_call in enumerate(calls_node_entry.recursiveFunctionCall):
                                    rec_call_line = calls_node_entry.nodeCalled[rc_idx].get("atLine")
                                    if str(rec_call_line) in str(rec_call):
                                        parent_further_cn_entry = (
                                            rec_call,
                                            calls_node_entry.nodeCalled[rc_idx],
                                        )
                                        break
                            except AttributeError:
                                continue
                        if parent_further_cn_entry is None:
                            # parent has no further recursive call, restart outer loop
                            inner_iteration = False
                            continue
                        else:
                            # parent still has recursive calls
                            inner_iteration = True
                            node = parent
                            remaining_recursive_call_in_parent = True
                            continue
                    else:
                        inner_iteration = False
                        continue
                else:
                    # node not of type CU, go to next node
                    inner_iteration = False
                    continue

        iterate_over_cus = False  # disable restarting, preprocessing finished

    # print modified Data.xml to file
    modified_cu_xml = cu_xml.replace(".xml", "-preprocessed.xml")
    if os.path.exists(modified_cu_xml):
        os.remove(modified_cu_xml)
    f = open(modified_cu_xml, "w+")
    f.write(etree.tostring(parsed_cu, pretty_print=True).decode("utf-8"))
    f.close()
    return modified_cu_xml


def __generate_new_cu_id(parent: Any, parent_copy: Any, used_node_ids: Any, self_added_node_ids: Any) -> None:
    """Generate the next free CU id and assign it to the parent CU.
    :param parent: parent CU, id will be updated
    :param parent_copy: copy of parent CU (newly created CU)
    :param used_node_ids: list of used cu node id's
    :param self_added_node_ids: list of added node id's"""
    # get next free id for specific tmp_file_id
    parent_copy_id = parent_copy.get("id")
    tmp_file_id = parent_copy_id[: parent_copy_id.index(":")]
    tmp_used_ids = [int(s[s.index(":") + 1 :]) for s in used_node_ids if s.startswith(tmp_file_id + ":")]
    next_free_id = max(tmp_used_ids) + 1
    incremented_id = tmp_file_id + ":" + str(next_free_id)
    parent.set("id", incremented_id)
    self_added_node_ids.append(incremented_id)


def __set_parent_copy_childrennodes(parent_copy: Any) -> None:
    """Adds cu nodes called by parent_copy to the childrenNodes list of parent_copy, if not already contained.
    :param parent_copy: cu node to be updated"""
    parent_copy.childrenNodes._setText("")
    for cne_idx, calls_node_entry in enumerate(parent_copy.callsNode):
        try:
            for node_call in calls_node_entry.nodeCalled:
                try:
                    if node_call.text not in parent_copy.childrenNodes.text:
                        parent_copy.childrenNodes._setText(parent_copy.childrenNodes.text + "," + node_call.text)
                        if parent_copy.childrenNodes.text.startswith(","):
                            parent_copy.childrenNodes._setText(parent_copy.childrenNodes.text[1:])
                        if parent_copy.childrenNodes.text.endswith(","):
                            parent_copy.childrenNodes._setText(parent_copy.childrenNodes.text[:-1])
                        continue
                except AttributeError as e1:
                    print(e1)
                    continue
        except AttributeError as e2:
            print(e2)
            continue


def __remove_overlapping_start_and_end_lines(parent_copy: Any, target_list: Any) -> None:
    """Removes the first line of parent_copy from parent´s readPhaseLines, writePhaseLines or instructionLines.
    As a result, start and end Lines of both nodes do not overlap anymore.
    :param parent_copy: copy of parent node (newly added node)
    :param target_list: eiter readPhaseLines, writePhaseLines or instructionLines of parent
    """
    try:
        if parent_copy.callsNode.nodeCalled.get("atLine") in target_list.text:
            target_list._setText(target_list.text.replace(parent_copy.callsNode.nodeCalled.get("atLine") + ",", ""))
            target_list._setText(target_list.text.replace(parent_copy.callsNode.nodeCalled.get("atLine"), ""))
            target_list.set("count", str(int(target_list.get("count")) - 1))
    except TypeError:
        target_list._setText(parent_copy.callsNode.nodeCalled.get("atLine"))
        target_list.set("count", "1")


def __filter_rwi_lines(parent_copy: Any, target_list: Any) -> None:
    """Removes entries from instructionLines, readPhaseLines and writePhraseLines of parent_copy if their value is not
    between parent_copy.startsAtLine and parent_copy.endsAtLine.
    :param parent_copy: cu node to be filtered
    :param target_list: eiter readPhaseLines, writePhaseLines or instructionLines of parent_copy"""
    try:
        for tmp_line in target_list.text.split(","):
            if not line_contained_in_region(tmp_line, parent_copy.get("startsAtLine"), parent_copy.get("endsAtLine")):
                target_list._setText(target_list.text.replace(tmp_line + ",", ""))
                target_list._setText(target_list.text.replace(tmp_line, ""))
                if target_list.text.endswith(","):
                    target_list._setText(target_list.text[:-1])
                target_list.set("count", str(int(target_list.get("count")) - 1))
    except AttributeError:
        pass


def __insert_separator_line(parent_copy: Any, target_list: Any) -> None:
    """Insert separator line to parent_copys instruction, read and writePhaseLines if not already present
    :param parent_copy: cu node to be updated
    :param target_list: eiter readPhaseLines, writePhaseLines or instructionLines of parent_copy"""
    try:
        if not parent_copy.get("endsAtLine") in target_list.text:
            target_list._setText(target_list.text + "," + parent_copy.get("endsAtLine"))
            if target_list.text.startswith(","):
                target_list._setText(target_list.text[1:])
            target_list.set("count", str(int(target_list.get("count")) + 1))
    except TypeError:
        target_list._setText(parent_copy.get("endsAtLine"))
        target_list.set("count", "1")
    target_list._setText(target_list.text.replace(",,", ","))


def __insert_missing_rwi_lines(parent: Any, target_list: Any) -> None:
    """Insert all lines contained in parent to instruction, read and writePhaseLines
    :param parent: cu node to be updated
    :param target_list: eiter readPhaseLines, writePhaseLines or instructionLines of parent"""
    cur_line = parent.get("startsAtLine")
    while line_contained_in_region(cur_line, parent.get("startsAtLine"), parent.get("endsAtLine")):
        if cur_line not in target_list.text:
            target_list._setText(cur_line + "," + target_list.text)
            if target_list.text.endswith(","):
                target_list._setText(target_list.text[:-1])
            target_list.set("count", str(int(target_list.get("count")) + 1))
        # increment cur_line by one
        cur_line = cur_line[0 : cur_line.rfind(":") + 1] + str(int(cur_line[cur_line.rfind(":") + 1 :]) + 1)
        continue
    target_list._setText(target_list.text.replace(",,", ","))


def __remove_unnecessary_return_instructions(target: Any) -> None:
    """Remove returnInstructions if they are not part of target cu anymore.
    :param target: cu to be checked"""
    if int(target.returnInstructions.get("count")) != 0:
        entries = target.returnInstructions.text.split(",")
        new_entries = []
        for entry in entries:
            if line_contained_in_region(entry, target.get("startsAtLine"), target.get("endsAtLine")):
                new_entries.append(entry)
        target.returnInstructions._setText(",".join(new_entries))
        target.returnInstructions.set("count", str(len(new_entries)))


def __add_parent_id_to_children(parsed_cu: Any, parent: Any) -> None:
    """ "Add parent.id to parent_function.childrenNodes
    :param: parsed_cu: parsed contents of cu_xml file
    :param parent: cu node to be added to parent_function's children
    """
    parent_function = None
    for tmp_node in parsed_cu.Node:
        if tmp_node.get("type") == "1":
            if line_contained_in_region(
                parent.get("startsAtLine"), tmp_node.get("startsAtLine"), tmp_node.get("endsAtLine")
            ):
                if line_contained_in_region(
                    parent.get("endsAtLine"),
                    tmp_node.get("startsAtLine"),
                    tmp_node.get("endsAtLine"),
                ):
                    parent_function = tmp_node
                    break
    if parent_function is None:
        print("No parent function found for cu node: ", parent.get("id"), ". Ignoring.")
    else:
        parent_function.childrenNodes._setText(parent_function.childrenNodes.text + "," + parent.get("id"))
        if parent_function.childrenNodes.text.startswith(","):
            parent_function.childrenNodes._setText(parent_function.childrenNodes.text[1:])


def __preprocessor_cu_contains_at_least_two_recursive_calls(node: Any) -> bool:
    """Check if >= 2 recursive function calls are contained in a cu's code region.
    Returns True, if so.
    Returns False, else.
    :param node: CUNode
    :return: bool
    """
    starts_at_line = node.get("startsAtLine").split(":")
    ends_at_line = node.get("endsAtLine").split(":")
    file_id = starts_at_line[0]
    if file_id != ends_at_line[0]:
        raise Exception("error in Data.xml: FileIds of startsAtLine and endsAtLine not matching!")
    starts_at_line = starts_at_line[1]
    ends_at_line = ends_at_line[1]

    # count contained recursive Function calls
    contained_recursive_calls = 0
    for calls_node_entry in node.callsNode:
        try:
            for i in calls_node_entry.recursiveFunctionCall:
                rec_func_calls = [s for s in str(i).split(",") if len(s) > 0]
                if len(rec_func_calls) != 0:
                    for rec_func_call in rec_func_calls:
                        rec_func_call = rec_func_call.split(" ")[1]
                        rfc_file_id = rec_func_call.split(":")[0]
                        rfc_line = rec_func_call.split(":")[1]
                        # test if recursiveFunctionCall is inside CU region
                        if rfc_file_id == file_id and starts_at_line <= rfc_line <= ends_at_line:
                            contained_recursive_calls += 1
        except AttributeError:
            pass
    if contained_recursive_calls >= 2:
        return True
    return False


def check_loop_scopes(pet: PEGraphX) -> None:
    """Checks if the scope of loop CUs matches these of their children. Corrects the scope of the loop CU
    (expand only) if necessary
    :param pet: PET graph"""
    for loop_cu in all_nodes(pet, LoopNode):
        for child in direct_children_or_called_nodes(pet, loop_cu):
            if not line_contained_in_region(child.start_position(), loop_cu.start_position(), loop_cu.end_position()):
                # expand loop_cu start_position upwards
                if child.start_line < loop_cu.start_line and loop_cu.file_id == child.file_id:
                    loop_cu.start_line = child.start_line
            if not line_contained_in_region(child.end_position(), loop_cu.start_position(), loop_cu.end_position()):
                # expand loop_cu end_position downwards
                if child.end_line > loop_cu.end_line and loop_cu.file_id == child.file_id:
                    loop_cu.end_line = child.end_line
