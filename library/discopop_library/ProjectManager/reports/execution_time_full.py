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


def generate_execution_time_report_full(arguments: ProjectManagerArguments, timestamp: str) -> None:
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
    list_values: Dict[str, Dict[int, Dict[str, List[float]]]] = dict()
    # collect configuration names to allow filling missing information with default value 0.0
    for configuration in execution_results:
        configuration_names.append(configuration)
    # collect data for plot
    for configuration in execution_results:
        for script in execution_results[configuration]:
            if script != "execute.sh":
                continue
            for setting in execution_results[configuration][script]:
                applied_suggestions_string = ""
                return_codes_string = ""
                times_string = ""
                clean_setting_str = setting.replace("_settings.json", "")
                if clean_setting_str not in list_values:
                    list_values[clean_setting_str] = dict()

                for execution in execution_results[configuration][script][setting]:
                    # a skipped run (suggestions not applied) has no runtime; keeping it
                    # would overwrite a measured value with 0.0
                    if not entries.was_executed(execution):
                        continue
                    label = execution["label"] if "label" in execution else ""
                    thread_count = execution["thread_count"]
                    if thread_count not in list_values[clean_setting_str]:
                        list_values[clean_setting_str][thread_count] = dict()

                    if label not in list_values[clean_setting_str][thread_count]:
                        # set default values
                        list_values[clean_setting_str][thread_count][label] = [0.0] * len(configuration_names)

                    # overwrite default values, if a value exists
                    list_values[clean_setting_str][thread_count][label][configuration_names.index(configuration)] = (
                        execution["time"]
                    )

    # dummy list_values
    #    list_values = {"setting1": {8: {"label1": [11.2, 42.3]}}, "setting2": {8: {"label1": [31.2, 22.3]}}}

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
    width = 0.9 / (max(1, len(values.items())))  # 0.25  # the width of the bars
    multiplier = 0

    for attribute, measurement in values.items():
        if None in measurement:
            continue
        offset = width * multiplier
        rects = ax.bar(x + offset, measurement, width, label=attribute)
        ax.bar_label(rects, padding=3, rotation=90)
        multiplier += 1

    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel("Execution time [s]")
    ax.set_title("Raw execution times")
    ax.set_xticks(x + width, configuration_names, rotation=90)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.25), fancybox=True, shadow=True, ncol=3)
    ax.set_ylim(0, max_y_value + max_y_value * 0.2)

    reports_dir = os.path.join(arguments.project_dir, "reports")
    if not os.path.exists(reports_dir):
        os.mkdir(reports_dir)
    timestamp_dir = os.path.join(reports_dir, timestamp)
    if not os.path.exists(timestamp_dir):
        os.mkdir(timestamp_dir)
    plt.savefig(os.path.join(timestamp_dir, "execution_time_full.pdf"))
