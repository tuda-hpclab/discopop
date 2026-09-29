# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict

from sympy import Integer  # type: ignore
from discopop_library.discopop_optimizer.classes.system.devices.Device import Device
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum


class CPU(Device):
    def __init__(
        self,
        frequency: Integer,
        thread_count: Integer,
        openmp_device_id: int,
        device_specific_compiler_flags: str,
        speedup: float,
        compute_init_delays: Dict[str, float],
    ):
        super().__init__(
            frequency, thread_count, openmp_device_id, device_specific_compiler_flags, speedup, compute_init_delays
        )

    def get_device_type(self) -> DeviceTypeEnum:
        return DeviceTypeEnum.CPU
