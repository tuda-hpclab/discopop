# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
import textwrap
from typing import Any, Dict, List

from tabulate import tabulate  # type: ignore

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.reports import entries


def generate_csv_report(arguments: ProjectManagerArguments, timestamp: str) -> None:
    execution_results_path = os.path.join(arguments.project_dir, "execution_results.json")
    if not os.path.exists(execution_results_path):
        print("No execution data available to report generation.")
        return
    with open(execution_results_path, "r") as f:
        execution_results = json.load(f)

    __create_csv(arguments, execution_results, timestamp)


def __create_csv(arguments: ProjectManagerArguments, execution_results: Dict[str, Any], timestamp: str) -> None:
    # prepare table for display
    table_column_headers = [
        "Config",
        "Script",
        "Setting",
        "Label",
        "Applied Suggestions",
        "Threads",
        "Code",
        "Time",
        "Speedup",
        "Efficiency",
    ]
    table: List[str] = [";".join(table_column_headers)]
    for configuration in execution_results:
        for script in execution_results[configuration]:
            for setting in execution_results[configuration][script]:
                # get sequential runtime for speedup calculation
                seq_runtime: float = -1.0
                if "seq_settings.json" in execution_results[configuration][script]:
                    for execution in execution_results[configuration][script]["seq_settings.json"]:
                        if execution["code"] == 0 and entries.was_executed(execution):
                            seq_runtime = execution["time"]

                for execution in execution_results[configuration][script][setting]:
                    applied_suggestions_string = ""
                    return_codes_string = ""
                    times_string = ""
                    thread_counts_string = ""
                    speedup_string = ""
                    efficiency_string = ""
                    applied_suggestions_string += entries.applied_suggestions_text(execution) + ";"
                    return_codes_string += str(execution["code"]) + ";"
                    times_string += entries.runtime_text(execution) + ";"
                    thread_counts_string += str(execution["thread_count"]) + ";"
                    # a skipped run has no runtime; "-" instead of a division by zero
                    speedup_string += entries.format_metric(entries.speedup_of(seq_runtime, execution)) + ";"
                    efficiency_string += entries.format_metric(entries.efficiency_of(seq_runtime, execution)) + ";"
                    label_string = (execution["label"] + ";") if "label" in execution else ";"

                    clean_setting_str = setting.replace("_settings.json", "") + ";"
                    clean_configuration_str = configuration + ";"
                    clean_script_str = script + ";"

                    table_row = ""
                    table_row += clean_configuration_str
                    table_row += clean_script_str
                    table_row += clean_setting_str
                    table_row += label_string
                    table_row += applied_suggestions_string
                    table_row += thread_counts_string
                    table_row += return_codes_string
                    table_row += times_string
                    table_row += speedup_string
                    table_row += efficiency_string
                    table.append(table_row)

    # save csv
    reports_dir = os.path.join(arguments.project_dir, "reports")
    if not os.path.exists(reports_dir):
        os.mkdir(reports_dir)
    timestamp_dir = os.path.join(reports_dir, timestamp)
    if not os.path.exists(timestamp_dir):
        os.mkdir(timestamp_dir)
    with open(os.path.join(timestamp_dir, "report.csv"), "w+") as f:
        for line in table:
            f.write(line)
            f.write("\n")
