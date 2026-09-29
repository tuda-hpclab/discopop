# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import json
import os
from typing import TYPE_CHECKING, Dict, List

from discopop_explorer.aliases.NodeID import NodeID

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments


def output_code_statistics(
    arguments: ExplorerArguments,
    maximum_call_path_depth: int,
    summed_cyclomatic_complexity: int,
    cc_min: int,
    cc_max: int,
    cc_avg: int,
    cc_lower_quart: int,
    cc_upper_quart: int,
    cu_count: int,
    func_count: int,
    loop_count: int,
    dependency_count: int,
) -> None:
    # create statistics directory
    if not os.path.exists(os.path.join(arguments.project_path, "explorer", "statistics")):
        os.mkdir(os.path.join(arguments.project_path, "explorer", "statistics"))
    # clear existing result
    statistics_file = os.path.join(arguments.project_path, "explorer", "statistics", "code_statistics.json")
    if os.path.exists(statistics_file):
        os.remove(statistics_file)

    statistics_dict: Dict[str, int] = dict()
    statistics_dict["maximum_call_path_depth"] = maximum_call_path_depth
    statistics_dict["summed_cyclomatic_complexity"] = summed_cyclomatic_complexity
    statistics_dict["cc_min"] = cc_min
    statistics_dict["cc_max"] = cc_max
    statistics_dict["cc_avg"] = cc_avg
    statistics_dict["cc_lower_quart"] = cc_lower_quart
    statistics_dict["cc_upper_quart"] = cc_upper_quart
    statistics_dict["cu_count"] = cu_count
    statistics_dict["func_count"] = func_count
    statistics_dict["loop_count"] = loop_count
    statistics_dict["dependency_count"] = dependency_count

    with open(statistics_file, "w+") as f:
        f.write(json.dumps(statistics_dict) + "\n")


def output_suggestion_statistics(
    arguments: ExplorerArguments,
    suggestion_call_path_depths: Dict[int, int],
    suggestion_num_function_calls: Dict[int, int],
    suggestion_immediate_lines_of_code: Dict[int, int],
    suggestion_lines_of_code_including_calls: Dict[int, int],
    suggestion_summed_cyclomatic_complexity_from_calls: Dict[int, int],
) -> None:
    # create statistics directory
    if not os.path.exists(os.path.join(arguments.project_path, "explorer", "statistics")):
        os.mkdir(os.path.join(arguments.project_path, "explorer", "statistics"))
    # clear existing result
    statistics_file_by_suggestionID = os.path.join(
        arguments.project_path, "explorer", "statistics", "suggestion_statistics_by_suggestionID.json"
    )
    if os.path.exists(statistics_file_by_suggestionID):
        os.remove(statistics_file_by_suggestionID)

    statistics_dict_by_suggestionID: Dict[int, Dict[str, int]] = dict()

    for suggestion_id in suggestion_call_path_depths:
        if suggestion_id not in statistics_dict_by_suggestionID:
            statistics_dict_by_suggestionID[suggestion_id] = dict()
        statistics_dict_by_suggestionID[suggestion_id]["suggestion_call_path_depth"] = suggestion_call_path_depths[
            suggestion_id
        ]

    for suggestion_id in suggestion_num_function_calls:
        if suggestion_id not in statistics_dict_by_suggestionID:
            statistics_dict_by_suggestionID[suggestion_id] = dict()
        statistics_dict_by_suggestionID[suggestion_id]["suggestion_num_function_calls"] = suggestion_num_function_calls[
            suggestion_id
        ]

    for suggestion_id in suggestion_summed_cyclomatic_complexity_from_calls:
        if suggestion_id not in statistics_dict_by_suggestionID:
            statistics_dict_by_suggestionID[suggestion_id] = dict()
        statistics_dict_by_suggestionID[suggestion_id]["suggestion_summed_cyclomatic_complexity_from_calls"] = (
            suggestion_summed_cyclomatic_complexity_from_calls[suggestion_id]
        )

    for suggestion_id in suggestion_immediate_lines_of_code:
        if suggestion_id not in statistics_dict_by_suggestionID:
            statistics_dict_by_suggestionID[suggestion_id] = dict()
        statistics_dict_by_suggestionID[suggestion_id]["suggestion_immediate_lines_of_code"] = (
            suggestion_immediate_lines_of_code[suggestion_id]
        )

    for suggestion_id in suggestion_lines_of_code_including_calls:
        if suggestion_id not in statistics_dict_by_suggestionID:
            statistics_dict_by_suggestionID[suggestion_id] = dict()
        statistics_dict_by_suggestionID[suggestion_id]["suggestion_lines_of_code_including_calls"] = (
            suggestion_lines_of_code_including_calls[suggestion_id]
        )

    with open(statistics_file_by_suggestionID, "w+") as f:
        f.write(json.dumps(statistics_dict_by_suggestionID) + "\n")


def output_aggregated_suggestion_statistics(
    arguments: ExplorerArguments,
    suggestion_call_path_depths: Dict[int, int],
    suggestion_num_function_calls: Dict[int, int],
    suggestion_immediate_lines_of_code: Dict[int, int],
    suggestion_lines_of_code_including_calls: Dict[int, int],
    suggestion_summed_cyclomatic_complexity_from_calls: Dict[int, int],
) -> None:
    res_dict: Dict[str, Dict[str, int]] = dict()  # {value_identifier : {value_descriptor: value}}
    # create statistics directory
    if not os.path.exists(os.path.join(arguments.project_path, "explorer", "statistics")):
        os.mkdir(os.path.join(arguments.project_path, "explorer", "statistics"))
    # clear existing result
    statistics_file = os.path.join(arguments.project_path, "explorer", "statistics", "suggestion_statistics.json")
    if os.path.exists(statistics_file):
        os.remove(statistics_file)

    values: List[int] = []
    # suggestion_call_path_depths
    values = list(suggestion_call_path_depths.values())
    if len(values) > 0:
        v_min = min(values)
        v_max = max(values)
        v_avg = int(sum(values) / len(values))
        lower_quartile_idx = int((len(values) + 1) * 1 / 4)
        upper_quartile_idx = min(len(values) - 1, int((len(values) + 1) * 3 / 4))
        lower_quartile = sorted(values)[lower_quartile_idx]
        upper_quartile = sorted(values)[upper_quartile_idx]
    else:
        v_min = 0
        v_max = 0
        v_avg = 0
        lower_quartile = 0
        upper_quartile = 0
    res_dict["suggestion_call_path_depths"] = {
        "min": v_min,
        "max": v_max,
        "avg": v_avg,
        "lower_quartile": lower_quartile,
        "upper_quartile": upper_quartile,
    }

    # suggestion_num_function_calls
    values = list(suggestion_num_function_calls.values())
    if len(values) > 0:
        v_min = min(values)
        v_max = max(values)
        v_avg = int(sum(values) / len(values))
        lower_quartile_idx = int((len(values) + 1) * 1 / 4)
        upper_quartile_idx = min(len(values) - 1, int((len(values) + 1) * 3 / 4))
        lower_quartile = sorted(values)[lower_quartile_idx]
        upper_quartile = sorted(values)[upper_quartile_idx]
    else:
        v_min = 0
        v_max = 0
        v_avg = 0
        lower_quartile = 0
        upper_quartile = 0
    res_dict["suggestion_num_function_calls"] = {
        "min": v_min,
        "max": v_max,
        "avg": v_avg,
        "lower_quartile": lower_quartile,
        "upper_quartile": upper_quartile,
    }

    # suggestion_immediate_lines_of_code
    values = list(suggestion_immediate_lines_of_code.values())
    if len(values) > 0:
        v_min = min(values)
        v_max = max(values)
        v_avg = int(sum(values) / len(values))
        lower_quartile_idx = int((len(values) + 1) * 1 / 4)
        upper_quartile_idx = min(len(values) - 1, int((len(values) + 1) * 3 / 4))
        lower_quartile = sorted(values)[lower_quartile_idx]
        upper_quartile = sorted(values)[upper_quartile_idx]
    else:
        v_min = 0
        v_max = 0
        v_avg = 0
        lower_quartile = 0
        upper_quartile = 0
    res_dict["suggestion_immediate_lines_of_code"] = {
        "min": v_min,
        "max": v_max,
        "avg": v_avg,
        "lower_quartile": lower_quartile,
        "upper_quartile": upper_quartile,
    }

    # suggestion_lines_of_code_including_calls
    values = list(suggestion_lines_of_code_including_calls.values())
    if len(values) > 0:
        v_min = min(values)
        v_max = max(values)
        v_avg = int(sum(values) / len(values))
        lower_quartile_idx = int((len(values) + 1) * 1 / 4)
        upper_quartile_idx = min(len(values) - 1, int((len(values) + 1) * 3 / 4))
        lower_quartile = sorted(values)[lower_quartile_idx]
        upper_quartile = sorted(values)[upper_quartile_idx]
    else:
        v_min = 0
        v_max = 0
        v_avg = 0
        lower_quartile = 0
        upper_quartile = 0
    res_dict["suggestion_lines_of_code_including_calls"] = {
        "min": v_min,
        "max": v_max,
        "avg": v_avg,
        "lower_quartile": lower_quartile,
        "upper_quartile": upper_quartile,
    }

    # suggestion_summed_cyclomatic_complexity_from_calls
    values = list(suggestion_summed_cyclomatic_complexity_from_calls.values())
    if len(values) > 0:
        v_min = min(values)
        v_max = max(values)
        v_avg = int(sum(values) / len(values))
        lower_quartile_idx = int((len(values) + 1) * 1 / 4)
        upper_quartile_idx = min(len(values) - 1, int((len(values) + 1) * 3 / 4))
        lower_quartile = sorted(values)[lower_quartile_idx]
        upper_quartile = sorted(values)[upper_quartile_idx]
    else:
        v_min = 0
        v_max = 0
        v_avg = 0
        lower_quartile = 0
        upper_quartile = 0
    res_dict["suggestion_summed_cyclomatic_complexity_from_calls"] = {
        "min": v_min,
        "max": v_max,
        "avg": v_avg,
        "lower_quartile": lower_quartile,
        "upper_quartile": upper_quartile,
    }

    # suggestion_count
    suggestion_count = max(
        len(suggestion_call_path_depths),
        len(suggestion_num_function_calls),
        len(suggestion_immediate_lines_of_code),
        len(suggestion_lines_of_code_including_calls),
        len(suggestion_summed_cyclomatic_complexity_from_calls),
    )
    res_dict["suggestion_count"] = {"total": suggestion_count}

    with open(statistics_file, "w+") as f:
        f.write(json.dumps(res_dict) + "\n")
