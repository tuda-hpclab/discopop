# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
from pathlib import Path
import sys
from dataclasses import dataclass
from typing import List, Optional
import warnings

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments
from discopop_library.ProjectManager.configurations.repetitions import DEFAULT_MEASURED_REPETITIONS
from logging import Logger


@dataclass
class ProjectManagerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop_project_manager"""

    project_root: str
    full_execute: bool
    list: bool
    execute_configurations: str
    execute_inplace: bool
    skip_cleanup: bool
    generate_report: bool
    show_report: bool
    initialize_directory: bool
    apply_suggestions: Optional[str]
    reset: bool
    reset_execution_results: bool
    gui: bool
    label_prefix: str
    timeout_execution: Optional[float]
    timeout_compilation: Optional[float]
    timeout_validation: Optional[float]
    # Overrides every configuration's stored "read the execution time from the
    # program's output" setting for this invocation: None leaves it alone, the
    # empty string disables the search, anything else is used as the pattern.
    # See discopop_library.ProjectManager.configurations.execution_time.
    execution_time_regex: Optional[str] = None
    # How often each measured execution is repeated; the median of the repetitions
    # is what gets reported. Applies to the seq and par runs, which are the ones
    # that measure something -- the dp and hd runs are instrumented profiling runs
    # whose output feeds the Explorer, and repeating them would multiply the
    # profiling cost while producing no better measurement. See
    # discopop_library.ProjectManager.configurations.repetitions.
    execution_repetitions: int = DEFAULT_MEASURED_REPETITIONS
    # derived values
    dot_dp: str = ""
    project_dir: str = ""
    project_config_dir: str = ""

    def __post_init__(self) -> None:
        # save derived values
        if self.project_root.endswith(".discopop"):
            print(
                "WARNING: Project root set to .discopop directory. \n-> Old project root: "
                + self.project_root
                + "\nFixed as follows:\n-> Project root: "
                + str(Path(self.project_root).parent.absolute())
                + "\n-> .discopop: "
                + self.project_root
            )
            self.project_root = str(Path(self.project_root).parent.absolute())
        self.dot_dp = os.path.join(self.project_root, ".discopop")

        self.project_dir = os.path.join(self.dot_dp, "project")
        self.project_config_dir = os.path.join(self.project_dir, "configs")
        # validate arguments
        self.__validate()

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop_configuration_manager, e.g check if given files exist"""
        # check if .discopop folder exists (allow GUI mode to auto-initialize)
        if not self.initialize_directory and not self.gui and not os.path.exists(self.dot_dp):
            print("ERROR: folder not found: " + self.dot_dp + "\n-> Did you initialize the project using '--init' ? ")
            sys.exit(1)

    def log_config(self, logger: Logger, mode: str = "debug") -> None:
        attributes = "\nConfiguration:\n"
        for attribute in self.__dict__:
            attributes += "-> " + str(attribute) + " : " + str(self.__dict__[attribute]) + "\n"
        if mode == "info":
            logger.info(attributes)
        else:
            logger.debug(attributes)
