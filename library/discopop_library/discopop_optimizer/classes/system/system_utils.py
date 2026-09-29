# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from typing import Any, Dict, List, Union

from sympy import Integer  # type: ignore

from discopop_library.discopop_optimizer.classes.system.devices.CPU import CPU
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum
from discopop_library.discopop_optimizer.classes.system.devices.GPU import GPU


def generate_default_system_configuration(file_path: str) -> None:
    """Generates a system configuration file using the default values if none exists so far."""
    if os.path.exists(file_path):
        return
    # build default system configuration
    system_configuration: Dict[str, Any] = dict()
    devices: List[Dict[str, Union[float, int, Dict[str, float]]]] = []
    # configure host device
    host_device: Dict[str, Union[float, int, Dict[str, float]]] = {
        "device_id": 0,
        "device_type": DeviceTypeEnum.CPU,
        "frequency": 3000000000,
        "processors": 16,
        "threads": 16,
        "speedup": 9.5,
        "compute_init_delays[us]": {"doall": 300},
    }
    # configure gpu_1
    gpu_1: Dict[str, Union[float, int, Dict[str, float]]] = {
        "compute_init_delays[us]": {"target_teams_distribute_parallel_for": 1000},
        "device_id": 1,
        "device_type": DeviceTypeEnum.GPU,
        "frequency": 256000000,
        "processors": 128,
        "teams": 3200,
        "threads": 3200,
        "transfer_init_delays[us]": {
            "target_data_update": 350,
            "target_enter_data": 900,
            "target_exit_data": 40,
            "average": 730,
        },
        "transfer_speeds": {"D2H_MB/s": 1800, "H2D_MB/s": 3600},  # MB/s
        "speedup": 160.32,
    }
    # configure gpu_2
    gpu_2: Dict[str, Union[float, int, Dict[str, float]]] = {
        "compute_init_delays[us]": {"target_teams_distribute_parallel_for": 5000},
        "device_id": 2,
        "device_type": DeviceTypeEnum.GPU,
        "frequency": 128000000,
        "processors": 128,
        "teams": 3200,
        "threads": 3200,
        "transfer_init_delays[us]": {
            "target_data_update": 710,
            "target_enter_data": 900,
            "target_exit_data": 50,
            "average": 810,
        },
        "transfer_speeds": {"D2H_MB/s": 1900, "H2D_MB/s": 4200},  # MB/s
        "speedup": 105.58,
    }
    # assemble system_configuration
    devices = [host_device, gpu_1, gpu_2]
    system_configuration["devices"] = devices
    system_configuration["host_device"] = host_device["device_id"]

    # output to file
    with open(file_path, "w") as f:
        json.dump(system_configuration, f)
