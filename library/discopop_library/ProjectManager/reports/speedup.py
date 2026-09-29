# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from tabulate import tabulate  # type: ignore
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.reports import entries

import logging
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger("ProjectManager")


def generate_speedup_report(arguments: ProjectManagerArguments, timestamp: str) -> None:
    execution_results_path = os.path.join(arguments.project_dir, "execution_results.json")
    if not os.path.exists(execution_results_path):
        print("No execution data available to report generation.")
        return
    with open(execution_results_path, "r") as f:
        execution_results = json.load(f)

    __plot_output(arguments, execution_results, timestamp)


def __plot_output(arguments: ProjectManagerArguments, execution_results: Dict[str, Any], timestamp: str) -> None:
    fig, ax = plt.subplots(layout="constrained")  # type: ignore
    configuration_names: List[str] = []
    tmp_values: Dict[str, Dict[int, Dict[str, Dict[str, float]]]] = dict()
    values: Dict[str, Tuple[float, ...]] = dict()
    # collect data for plot
    for configuration in execution_results:
        configuration_names.append(configuration)
        for script in execution_results[configuration]:
            if script != "execute.sh":
                continue
            for setting in execution_results[configuration][script]:
                applied_suggestions_string = ""
                return_codes_string = ""
                times_string = ""

                # get sequential runtime for speedup calculation
                seq_runtime: float = -1.0
                if "seq_settings.json" in execution_results[configuration][script]:
                    for execution in execution_results[configuration][script]["seq_settings.json"]:
                        if execution["code"] == 0 and entries.was_executed(execution):
                            seq_runtime = execution["time"]

                best_values_by_label: Dict[str, Dict[str, Any]] = dict()
                for execution in execution_results[configuration][script][setting]:
                    # a skipped run (suggestions not applied) is not a measurement
                    if not entries.was_executed(execution):
                        continue
                    label = execution["label"] if "label" in execution else ""
                    if label not in best_values_by_label:
                        best_values_by_label[label] = dict()
                        best_values_by_label[label]["best_execution_time"] = None
                        best_values_by_label[label]["best_thread_count"] = 1

                    applied_suggestions_string += str(execution["applied_suggestions"]) + "\n"
                    return_codes_string += str(execution["code"]) + "\n"
                    times_string += str(execution["time"]) + "\n"
                    if execution["code"] == 0:
                        if best_values_by_label[label]["best_execution_time"] is None:
                            best_values_by_label[label]["best_execution_time"] = execution["time"]
                            best_values_by_label[label]["best_thread_count"] = execution["thread_count"]
                        if execution["time"] < best_values_by_label[label]["best_execution_time"]:
                            best_values_by_label[label]["best_execution_time"] = execution["time"]
                            best_values_by_label[label]["best_thread_count"] = execution["thread_count"]

                clean_setting_str = setting.replace("_settings.json", "")

                # collect, filter, and add values for plotting
                # only plot the best found option

                if "seq" not in clean_setting_str and "par" not in clean_setting_str:
                    continue
                if clean_setting_str not in tmp_values:
                    tmp_values[clean_setting_str] = dict()
                for label in best_values_by_label:
                    if best_values_by_label[label]["best_thread_count"] not in tmp_values[clean_setting_str]:
                        tmp_values[clean_setting_str][best_values_by_label[label]["best_thread_count"]] = dict()
                    if label not in tmp_values[clean_setting_str][best_values_by_label[label]["best_thread_count"]]:
                        tmp_values[clean_setting_str][best_values_by_label[label]["best_thread_count"]][label] = dict()

                    if best_values_by_label[label]["best_execution_time"] is None:
                        speedup = 0.0
                    else:
                        speedup = round(seq_runtime / best_values_by_label[label]["best_execution_time"], 3)
                    tmp_values[clean_setting_str][best_values_by_label[label]["best_thread_count"]][label][
                        configuration
                    ] = speedup

    # prepare values for plotting
    list_values: Dict[str, Dict[int, Dict[str, List[float]]]] = dict()
    for setting in tmp_values:
        if setting not in list_values:
            list_values[setting] = dict()
        for thread_count in tmp_values[setting]:
            if thread_count not in list_values[setting]:
                list_values[setting][thread_count] = dict()
            for label in tmp_values[setting][thread_count]:
                if label not in list_values[setting][thread_count]:
                    list_values[setting][thread_count][label] = []
                for spec in configuration_names:
                    if spec in tmp_values[setting][thread_count][label]:
                        list_values[setting][thread_count][label].append(tmp_values[setting][thread_count][label][spec])
                    else:
                        # fill missing values
                        list_values[setting][thread_count][label].append(0.0)
    # convert lists to tuples
    for setting in list_values:
        for thread_count in list_values[setting]:
            for label in list_values[setting][thread_count]:
                label_string = "" if len(label) == 0 else ("[" + label + "]")
                values[setting + label_string + "(" + str(thread_count) + ")"] = tuple(
                    list_values[setting][thread_count][label]
                )

    # get max y value
    max_y_value = 0.0
    for setting in list_values:
        for thread_count in list_values[setting]:
            for label in list_values[setting][thread_count]:
                for val in list_values[setting][thread_count][label]:
                    if val is None:
                        val = max_y_value
                    if val > max_y_value:
                        max_y_value = val

    x = np.arange(len(configuration_names))  # the label locations
    width = 0.25  # the width of the bars
    multiplier = 0

    for attribute, measurement in values.items():
        if None in measurement:
            continue
        offset = width * multiplier
        rects = ax.bar(x + offset, measurement, width, label=attribute)
        ax.bar_label(rects, padding=3)
        multiplier += 1

    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel("Speedup")
    ax.set_title("Speedups of best valid configurations")
    ax.set_xticks(x + width, configuration_names)
    ax.legend(loc="upper left", ncols=3)
    ax.set_ylim(0, max_y_value + max_y_value * 0.15)

    reports_dir = os.path.join(arguments.project_dir, "reports")
    if not os.path.exists(reports_dir):
        os.mkdir(reports_dir)
    timestamp_dir = os.path.join(reports_dir, timestamp)
    if not os.path.exists(timestamp_dir):
        os.mkdir(timestamp_dir)
    plt.savefig(os.path.join(timestamp_dir, "speedups.pdf"))
