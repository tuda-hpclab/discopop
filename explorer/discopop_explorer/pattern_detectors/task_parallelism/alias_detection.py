# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import pathlib
import re
import subprocess
from typing import Dict, List, Optional, Match, cast, Any

from lxml import objectify  # type: ignore


def __prune_statement(stmt_copy: str, statement: str, var_name: str, var_type: str) -> Optional[List[str]]:
    """splits a statement and performs multiple alias analyses if necessary (more than one '=' contained
    in the given statement).
    :param stmt_copy: cleaned copy of the target statement
    :param statement: statement to check for new alias definition
    :param var_name: target variable name
    :param var_type: type of the variable
    :return: List containing found aliases"""
    if stmt_copy.count(",") == 0:
        return None
    indices = [i for i, x in enumerate(stmt_copy) if x == ","]
    indices = indices + [len(stmt_copy)]
    aliases: List[str] = []
    for idx, index in enumerate(indices):
        if idx == 0:
            stmt = statement[: indices[idx]]
        elif idx == len(indices) - 1:
            stmt = statement[indices[idx - 1] + 1 : index + 1]
        else:
            stmt = statement[indices[idx - 1] + 1 : indices[idx]]
        tmp = __get_alias_from_statement(var_name, var_type, stmt)
        if tmp is not None:
            aliases += tmp
    if len(aliases) == 0:
        return None
    return aliases


def __check_obvious_pointer_type(var_name: str, rhs: str) -> bool:
    """Checks conditions for obvious pointer types.
    :param var_name: target variable name
    :param rhs: right hand side string to be analyzed
    :return: True, of None should be returned by __get_alias_statement. False, otherwise.
    """
    # var_name has index access?
    if rhs.index(var_name) + len(var_name) < len(rhs) and rhs[rhs.index(var_name) + len(var_name)] == "[":
        return True
    # '*' prior to var_name?
    if rhs.index(var_name) - 1 >= 0 and rhs[rhs.index(var_name) - 1] == "*":
        return True
    # '*' and '(' prior, no ')' prior to var_name?
    if (
        rhs.index(var_name) - 2 >= 0
        and rhs[rhs.index(var_name) - 2] == "*"
        and rhs[rhs.index(var_name) - 1] == "("
        and ")" not in rhs[rhs.index(var_name) - 2 : rhs.index(var_name) + len(var_name)]
    ):
        return True
    # '->' after var_name?
    if (
        rhs.index(var_name) + len(var_name) + 2 > len(rhs)
        and rhs[rhs.index(var_name) + len(var_name) : rhs.index(var_name) + len(var_name) + 1] == "->"
    ):
        return True
    return False


def __check_possible_pointer_type(var_name: str, rhs: str) -> bool:
    """Checks conditions for possible pointer types.
    :param var_name: target variable name
    :param rhs: right hand side string to be analyzed
    :return: True, of None should be returned by __get_alias_statement. False, otherwise.
    """
    # '&' prior to var_name?
    if rhs.index(var_name) - 1 >= 0 and not rhs[rhs.index(var_name) - 1] == "&":
        return True
    # var_name has index access?
    if rhs.index(var_name) + len(var_name) < len(rhs) and rhs[rhs.index(var_name) + len(var_name)] == "[":
        return True
    # '*' prior to '&'?
    if rhs.index(var_name) - 2 >= 0 and rhs[rhs.index(var_name) - 1] == "&" and rhs[rhs.index(var_name) - 2] == "*":
        return True
    # '*' and '(' prior, no ')' prior to '&'?
    if (
        rhs.index(var_name) - 2 >= 0
        and rhs[rhs.index(var_name) - 2] == "*"
        and rhs[rhs.index(var_name) - 1] == "("
        and ")" not in rhs[rhs.index(var_name) - 2 : rhs.index(var_name)]
    ):
        return True
    # '->' after var_name?
    if (
        rhs.index(var_name) + len(var_name) + 2 > len(rhs)
        and rhs[rhs.index(var_name) + len(var_name) : rhs.index(var_name) + len(var_name) + 1] == "->"
    ):
        return True
    return False


def __check_pointer_type(var_type: str, var_name: str, rhs: str) -> bool:
    """Distinguishes obvious and possible pointer types.
    :param var_type: type of the variable
    :param var_name: target variable name
    :param rhs: right hand side string to be analyzed
    :return: True, if None should be returned. False, otherwise."""
    # var_name is pointer type?
    if "*" in var_type:
        return __check_obvious_pointer_type(var_name, rhs)
    else:
        return __check_possible_pointer_type(var_name, rhs)


def __get_alias_from_statement(var_name: str, var_type: str, statement: str) -> Optional[List[str]]:
    """Checks if the given statement defines a new alias for var_name.
    Returns a list containing the found alias name or None, if no alias has been defined by statement.
    :param var_name: target variable name
    :param var_type: type of the variable
    :param statement: statement to check for new alias definition
    :return: None, or list containing a found alias name."""
    # prune var_name
    if ".addr" in var_name:
        var_name = var_name.replace(".addr", "")
    # prune statement
    if ":" in statement:
        statement = statement[statement.rindex(":") + 1 :]
    # var_name in statement?
    reg = r"\W" + re.escape(var_name) + r"\W"
    search_match = re.search(reg, statement)
    try:
        search_string: Optional[str] = cast(Match[str], search_match)[0]
    except TypeError:
        search_string = None
    if search_string is None:
        return None
    # operation is '=' ?
    stmt_copy = statement
    stmt_copy = stmt_copy.replace("<=>", "  ").replace("<<=", "   ").replace(">>=", "   ").replace("==", "  ")
    stmt_copy = stmt_copy.replace("!=", "  ").replace("+=", "  ").replace("-=", "  ").replace("*=", "  ")
    stmt_copy = stmt_copy.replace("/=", "  ").replace("%=", "  ").replace("<=", "  ").replace(">=", "  ")
    stmt_copy = stmt_copy.replace("&=", "  ").replace("^=", "  ").replace("|=", "  ")
    if "=" not in stmt_copy:
        return None
    # prune statement to single contained '='
    if stmt_copy.count("=") > 1:
        return __prune_statement(stmt_copy, statement, var_name, var_type)

    # var_name on left hand side?
    if stmt_copy.index(var_name) < stmt_copy.index("="):
        return None
    # var_name contained in function call?
    left_hand_side = statement[: stmt_copy.index("=")]
    right_hand_side = statement[stmt_copy.index("=") + 1 :]
    call_match = re.search(r"[\w]+(?=\().+\)", right_hand_side)
    try:
        call_string: Optional[str] = cast(Match[str], call_match)[0]
    except TypeError:
        call_string = None
    if call_string is not None:
        if var_name in call_string:
            return None
    # check pointer tye
    if __check_pointer_type(var_type, var_name, right_hand_side):
        return None
    # left hand side is single token?
    left_hand_split = left_hand_side.split(" ")
    left_hand_split = [x for x in left_hand_split if len(x) > 0]
    if len(left_hand_split) == 1:
        return left_hand_split
    # only type and modifiers on left hand side?
    if len(left_hand_split) <= 4:
        return [left_hand_split[-1]]
    return None


def __add_alias_information(
    function_information_list: List[Dict[str, Any]], statements_file: str
) -> List[Dict[str, Any]]:
    """Wrapper to gather and append alias information to the entries in function_information as a new field.
    Aliases can be found up to a depth of 2.
    Alias detection ignores scopes.
    Alias detection ignores a=b=c constellations.
    :param function_information_list: list of dictionaries representing the functions contained in cu-xml
    :param statements_file: path to file containing the output of getStatements
    :return: Input list of dictionaries, enriched with alias information."""
    result_list = []
    for function_information in function_information_list:
        file_id = function_information["id"].split(":")[0]
        body_start_line = function_information["startsAtLine"].split(":")[1]
        body_end_line = function_information["endsAtLine"].split(":")[1]
        # get such statements which occur inside current functions body
        relevant_statements = []
        with open(statements_file, "r") as sf:
            for line in sf.readlines():
                line_file_id = line[: line.index(":")]
                line_code_line = line[line.index(":") + 1 :]
                line_code_line = line_code_line[: line_code_line.index(":")]
                if file_id != line_file_id:
                    continue
                if int(body_start_line) > int(line_code_line):
                    continue
                if int(body_end_line) < int(line_code_line):
                    continue
                line = line.replace("\n", "")
                # append line + line_code_line for sorting, removed afterwards
                relevant_statements.append((line, int(line_code_line)))
        # order relevant statements by line number
        relevant_statements.sort(key=lambda x: x[1])
        relevant_statements_strings = [x[0] for x in relevant_statements]
        # get aliases for each argument
        function_information["aliases"] = []
        for arg_idx, arg_name in enumerate(function_information["args"]):
            aliases = []
            for statement in relevant_statements_strings:
                # search for first-level aliases
                statement_result = __get_alias_from_statement(
                    arg_name, function_information["arg_types"][arg_idx], statement
                )
                if statement_result is not None:
                    for state_res_entry in statement_result:
                        # first level alias found
                        # search for second level aliases
                        for inner_statement in relevant_statements_strings:
                            statement_line = statement[statement.index(":") + 1 :]
                            statement_line = statement_line[: statement_line.index(":")]
                            inner_statement_line = inner_statement[inner_statement.index(":") + 1 :]
                            inner_statement_line = inner_statement_line[: inner_statement_line.index(":")]
                            if int(inner_statement_line) < int(statement_line):
                                continue
                            inner_statement_result = __get_alias_from_statement(state_res_entry, "*", inner_statement)
                            if inner_statement_result is not None:
                                # second level alias found
                                aliases += inner_statement_result
                    aliases += statement_result
            aliases = list(dict.fromkeys(aliases))
            function_information["aliases"].append(aliases)
        result_list.append(function_information)
    return result_list


def __get_function_information(cu_xml: str) -> List[Dict[str, Any]]:
    """Extracts information on functions from given cu_xml file and stores it in a dictionary representation.
    :param cu_xml: path to cu_xml file
    :return: List of dictionaries representing functions from cu_xml"""
    with open(cu_xml) as xml_fd:
        xml_content = ""
        for line in xml_fd.readlines():
            if not (line.rstrip().endswith("</Nodes>") or line.rstrip().endswith("<Nodes>")):
                xml_content = xml_content + line
    xml_content = "<Nodes>{0}</Nodes>".format(xml_content)
    parsed_cu = objectify.fromstring(xml_content)
    function_information = []
    for node in parsed_cu.Node:
        node.childrenNodes = str(node.childrenNodes).split(",") if node.childrenNodes else []
        if node.get("type") == "1":
            entry = dict()
            entry["name"] = node.get("name")
            entry["startsAtLine"] = node.get("startsAtLine")
            entry["endsAtLine"] = node.get("endsAtLine")
            entry["id"] = node.get("id")
            entry["args"] = []
            if hasattr(node, "funcArguments") and hasattr(node.funcArguments, "arg"):
                entry["args"] = [v.text for v in node.funcArguments.arg]
            entry["arg_types"] = []
            if hasattr(node, "funcArguments") and hasattr(node.funcArguments, "arg"):
                entry["arg_types"] = [v.get("type") for v in node.funcArguments.arg]
            function_information.append(entry)
    return function_information


def __create_statements_file(file_mapping: str, output_file: str, application_path: str) -> None:
    """Wrapper to start getStatements application for each source code file in file_mapping
    :param file_mapping: path to file_mapping file
    :param output_file: path to output file
    :param application_path: path to getStatements executable"""
    file_mapping_dict = dict()  # maps path to file-id
    with open(file_mapping) as fm:
        for line in fm.readlines():
            line = line.replace("\n", "")
            split_line = line.split("\t")
            file_mapping_dict[split_line[1]] = split_line[0]
    # execute application for each file in file_mapping
    for file in file_mapping_dict:
        process = subprocess.Popen(
            application_path + " " + file + " >> " + output_file,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.wait()
    # cleanup results and replace paths with file-ids
    if os.path.exists(output_file + "_tmp"):
        os.remove(output_file + "_tmp")
    with open(output_file + "_tmp", "w+") as tmp_of:
        with open(output_file, "r") as of:
            for line in of.readlines():
                line = line.replace("\n", "")
                if len(line) == 0:
                    continue
                left = line[: line.rfind(":")]
                right = line[line.rfind(":") :]
                left = re.sub(r"<.*>", "", left)
                file_path = left[: left.find(":")]
                left = left.replace(file_path, file_mapping_dict[file_path])
                line = left + right
                while " :" in line or ": " in line:
                    line = line.replace(" :", ":")
                    line = line.replace(": ", ":")
                if "=" not in line:
                    continue
                tmp_of.write(line + "\n")
    os.remove(output_file)
    os.rename(output_file + "_tmp", output_file)


def get_alias_information(file_mapping: str, cu_xml: str, temp_file: str, build_path: str) -> str:
    """Gather simple alias information for every file in filemapping and return the results in string format.
    :param file_mapping: path to filemapping-file
    :param cu_xml: path to cu_xml file
    :param temp_file: path to temporary file(s)
    :param build_path: path to discopop build directory
    :return: string, containing found aliases for each function"""
    if build_path.endswith("/"):
        build_path = build_path[:-1]

    if not os.path.isfile(file_mapping):
        raise ValueError(f'File not found: "{file_mapping}"')
    if not os.path.isfile(cu_xml):
        raise ValueError(f'File not found: "{cu_xml}"')

    # remove output file if it already exists
    if os.path.exists(temp_file + "_statements"):
        os.remove(temp_file + "_statements")
    if os.path.exists(temp_file):
        os.remove(temp_file)
    # create statements file
    __create_statements_file(
        file_mapping,
        temp_file + "_statements",
        str(pathlib.Path(build_path).joinpath("rtlib", "simple-alias-detection", "getStatements")),
    )
    # get function information file
    function_information = __get_function_information(cu_xml)
    # add alias information to function_information
    function_information = __add_alias_information(function_information, temp_file + "_statements")
    # create alias output file
    alias_str = ""
    for fn_info in function_information:
        if len(fn_info["args"]) == 0:
            continue
        for idx, alias_entry in enumerate(fn_info["aliases"]):
            if len(alias_entry) > 0:
                for alias_name in alias_entry:
                    alias_str += (
                        fn_info["id"] + ";" + fn_info["name"] + ";" + fn_info["args"][idx] + ";" + alias_name + "\n"
                    )
    # cleanup
    if os.path.exists(temp_file + "_statements"):
        os.remove(temp_file + "_statements")
    if os.path.exists(temp_file):
        os.remove(temp_file)
    return alias_str
