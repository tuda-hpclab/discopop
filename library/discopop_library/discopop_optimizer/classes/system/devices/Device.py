# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, Tuple, List, Optional, cast

from sympy import Expr, Float, Symbol  # type: ignore
from sympy import Integer

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum


class Device(object):
    __frequency: Expr
    __thread_count: Expr
    openmp_device_id: int
    __speedup: float  # comapred to sequential execution
    __compute_init_delays: Dict[str, float]

    def __init__(
        self,
        frequency: Expr,  # GHz
        thread_count: Expr,
        openmp_device_id: int,
        device_specific_compiler_flags: str,
        speedup: float,
        compute_init_delays: Dict[str, float],
    ):
        self.__frequency = frequency
        self.__thread_count = thread_count
        self.openmp_device_id = openmp_device_id
        self.device_specific_compiler_flags: str = device_specific_compiler_flags
        self.__speedup = speedup
        self.__compute_init_delays = compute_init_delays

    def get_device_specific_pattern_info(
        self, suggestion: PatternInfo, suggestion_type: str
    ) -> Tuple[PatternInfo, str]:
        return suggestion, suggestion_type

    def get_compute_init_delays(self) -> Dict[str, float]:
        return self.__compute_init_delays

    def get_compute_capability(self) -> Expr:
        return self.__frequency

    def get_thread_count(self) -> Expr:
        return self.__thread_count

    def get_free_symbols(self) -> List[Tuple[Symbol, Optional[Expr]]]:
        result_list: List[Tuple[Symbol, Optional[Expr]]] = []
        result_list += [(cast(Symbol, s), None) for s in self.__frequency.free_symbols]
        result_list += [(cast(Symbol, s), None) for s in self.__thread_count.free_symbols]
        return result_list

    def get_measured_speedup(self) -> Expr:
        return Float(self.__speedup)

    def get_estimated_execution_time_in_micro_seconds(self, workload: Optional[Expr], is_sequential: bool) -> Expr:
        """execution time is estimated by:
        - convert workload to estimated amount of CPU instructions using a extra-p model
        - NOTE: use "perf stat ./<cmd" to get the amount of instructions and instructions per cycle




        execution_time_in_micro_seconds = execution_time_in_seconds * 1000000
         execution_time_in_seconds = workload / instructions_per_second
         instructions_per_second = instructions_per_core_per_second * self.__thread_count
         instructions_per_core_per_second = self.__frequency / avg_cycles_per_instruction
         avg_cycles_per_instruction = 1 / avg_instructions_per_cycle
        """
        if workload is None:
            raise ValueError("workload is None")

        # todo -> define functions to evaluate workloads on different devices. include these functions in the construction of the cost model for later evaluation instead of "manually" converting the workload to time values
        # todo: correctly set is_sequential argument
        # todo mark parallel execution in subtree of suggestions?

        avg_instructions_per_cycle = 0.89  # todo (get from benchmarking)
        # current value determined by manual "measurement" based on a single example!
        average_cycles_per_instruction = 1 / avg_instructions_per_cycle
        instructions_per_core_per_second = self.__frequency / average_cycles_per_instruction
        instructions_per_second = instructions_per_core_per_second * (
            Integer(1) if is_sequential else self.__thread_count
        )
        workload_in_instructions = workload * 2.120152292  # todo (get from benchmarking / extra-p model)
        # current factor determined by manual "measurement" based on a single example!

        execution_time_in_seconds = workload_in_instructions / instructions_per_second
        execution_time_in_micro_seconds = execution_time_in_seconds * 1000000
        return Float(execution_time_in_micro_seconds)

    def get_device_type(self) -> DeviceTypeEnum:
        raise ValueError("This method need to be overwritten by subclasses!")
