# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os.path
from dataclasses import dataclass
from typing import List, Optional

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments


@dataclass
class OptimizerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop_optimizer"""

    verbose: bool
    interactive: bool
    interactive_export: str
    doall_microbench_file: str
    reduction_microbench_file: str
    allow_nested_parallelism: bool
    plot: bool
    system_configuration_path: str
    check_called_function_for_nested_parallelism: bool
    profiling: bool
    pruning_level: int
    optimization_level: int
    optimization_level_2_parameters: str
    single_suggestions: bool
    pin_function_calls_to_host: bool

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop_optimizer, e.g check if given files exist"""
        if self.doall_microbench_file != "None":
            if not os.path.isfile(self.doall_microbench_file):
                raise FileNotFoundError(f"Microbenchmark file not found: {self.doall_microbench_file}")
        if self.reduction_microbench_file != "None":
            if not os.path.isfile(self.reduction_microbench_file):
                raise FileNotFoundError(f"Microbenchmark file not found: {self.reduction_microbench_file}")

        # check pruning level values
        if self.pruning_level not in [0, 1, 2]:
            raise ValueError("Unsupported pruning level: ", self.pruning_level)

        # check optimization level
        if self.optimization_level not in [0, 1, 2, 3]:
            raise ValueError("Unknown optimization level requested: ", self.optimization_level)

        pass
