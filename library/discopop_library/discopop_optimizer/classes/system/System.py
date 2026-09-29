# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
import pathlib
import warnings
from typing import Any, Dict, List, Tuple, Optional, cast

from sympy import Float, Symbol, Expr, Integer  # type: ignore
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution

from discopop_library.discopop_optimizer.classes.system.Network import Network
from discopop_library.discopop_optimizer.classes.system.devices.CPU import CPU
from discopop_library.discopop_optimizer.classes.system.devices.Device import Device
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum
from discopop_library.discopop_optimizer.classes.system.devices.GPU import GPU
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments


class System(object):
    __devices: Dict[int, Device]
    __host_device_id: int
    __network: Network
    __device_do_all_overhead_models: Dict[Device, Expr]
    __device_do_all_shared_overhead_models: Dict[Device, Expr]
    __device_reduction_overhead_models: Dict[Device, Expr]
    __symbol_substitutions: List[
        Tuple[
            Symbol,
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[FreeSymbolDistribution],
        ]
    ]

    def __init__(self, arguments: OptimizerArguments):
        self.__devices = dict()
        self.__host_device_id = -1
        self.__network = Network()
        self.__device_do_all_overhead_models = dict()
        self.__device_do_all_shared_overhead_models = dict()
        self.__device_reduction_overhead_models = dict()
        self.__symbol_substitutions = []

        self.__build_from_configuration_file(arguments)

    # todo: support the replication of device ids (e.g. CPU-0 and GPU-0)

    def __build_from_configuration_file(self, arguments: OptimizerArguments) -> None:
        with open(arguments.system_configuration_path, "r") as f:
            system_configuration = json.load(f)
        self.__host_device_id = system_configuration["host_device"]
        # register devices
        for device_dict in system_configuration["devices"]:
            if device_dict["device_type"] == DeviceTypeEnum.CPU:
                self.__build_CPU(device_dict)
            elif device_dict["device_type"] == DeviceTypeEnum.GPU:
                self.__build_GPU(device_dict)
            else:
                raise ValueError("Unknown device type: " + str(device_dict["device_type"]) + " in: " + str(device_dict))
        # register host device for device -> device transfers
        self.__network.set_host_device(self.get_device(self.__host_device_id))

        # register connections
        for device_dict in system_configuration["devices"]:
            if "transfer_speeds" in device_dict:
                # register connection with given transfer speed
                self.__network.add_connection(
                    source=self.get_device(self.__host_device_id),
                    target=self.get_device(device_dict["device_id"]),
                    transfer_speed=Float(device_dict["transfer_speeds"]["H2D_MB/s"]),
                    initialization_delay=Float(device_dict["transfer_init_delays[us]"]["average"]),
                )  # H2D
                self.__network.add_connection(
                    source=self.get_device(device_dict["device_id"]),
                    target=self.get_device(self.__host_device_id),
                    transfer_speed=Float(device_dict["transfer_speeds"]["D2H_MB/s"]),
                    initialization_delay=Float(device_dict["transfer_init_delays[us]"]["average"]),
                )  # D2H
            else:
                # no transfer speed information exists
                pass

    def __build_CPU(self, device_configuration: Dict[str, Any]) -> None:
        cpu = CPU(
            frequency=Integer(device_configuration["frequency"]),
            thread_count=Integer(device_configuration["threads"]),
            openmp_device_id=device_configuration["device_id"],
            device_specific_compiler_flags="",
            speedup=device_configuration["speedup"],
            compute_init_delays=device_configuration["compute_init_delays[us]"],
        )
        self.add_device(cpu, device_configuration["device_id"])

    def __build_GPU(self, device_configuration: Dict[str, Any]) -> None:
        gpu = GPU(
            frequency=Integer(device_configuration["frequency"]),
            thread_count=Integer(device_configuration["threads"]),
            openmp_device_id=device_configuration["device_id"],
            device_specific_compiler_flags="",
            speedup=device_configuration["speedup"],
            compute_init_delays=device_configuration["compute_init_delays[us]"],
        )
        self.add_device(gpu, device_configuration["device_id"])

    def set_device_doall_overhead_model(self, device: Device, model: Expr, arguments: OptimizerArguments) -> None:
        if arguments.verbose:
            print("System: Set DOALL overhead model: ", model)
        self.__device_do_all_overhead_models[device] = model

    def set_device_doall_shared_overhead_model(
        self, device: Device, model: Expr, arguments: OptimizerArguments
    ) -> None:
        if arguments.verbose:
            print("System: Set DOALL SHARED overhead model: ", model)
        self.__device_do_all_shared_overhead_models[device] = model

    def set_reduction_overhead_model(self, device: Device, model: Expr, arguments: OptimizerArguments) -> None:
        if arguments.verbose:
            print("System: Set REDUCTION overhead model: ", model)
        self.__device_reduction_overhead_models[device] = model

    def get_device_doall_overhead_model(self, device: Device, arguments: OptimizerArguments) -> Expr:
        if device not in self.__device_do_all_overhead_models:
            if arguments.verbose:
                warnings.warn("No DOALL overhead model, assuming 0 for device: " + str(device))
            return cast(Expr, Integer(0))
        return self.__device_do_all_overhead_models[device]

    def get_device_doall_shared_overhead_model(self, device: Device, arguments: OptimizerArguments) -> Expr:
        if device not in self.__device_do_all_shared_overhead_models:
            if arguments.verbose:
                warnings.warn("No DOALL SHARED overhead model, assuming 0 for device: " + str(device))
            return cast(Expr, Integer(0))
        return self.__device_do_all_shared_overhead_models[device]

    def get_device_reduction_overhead_model(self, device: Device, arguments: OptimizerArguments) -> Expr:
        if device not in self.__device_reduction_overhead_models:
            if arguments.verbose:
                warnings.warn("No REDUCTION overhead model, assuming 0 for device: " + str(device))
            return cast(Expr, Integer(0))
        return self.__device_reduction_overhead_models[device]

    def add_device(self, device: Device, device_id: int) -> None:
        self.__devices[device_id] = device

    def get_device(self, device_id: Optional[int]) -> Device:
        if device_id is None:
            return self.__devices[self.get_host_device_id()]
        return self.__devices[device_id]

    def get_device_ids_by_type(self, device_type: type) -> List[int]:
        result_device_ids = []
        for device_id in self.__devices:
            if type(self.__devices[device_id]) == device_type:
                result_device_ids.append(device_id)
        return result_device_ids

    def get_network(self) -> Network:
        return self.__network

    def get_free_symbols(self) -> List[Tuple[Symbol, Optional[Expr]]]:
        result_list: List[Tuple[Symbol, Optional[Expr]]] = []
        for device in self.__devices.values():
            result_list += device.get_free_symbols()
        result_list += self.__network.get_free_symbols()
        return result_list

    def get_device_id(self, device: Device) -> int:
        for key in self.__devices:
            if device == self.__devices[key]:
                return key
        raise ValueError("Unknown device: ", device)

    def get_host_device_id(self) -> int:
        return self.__host_device_id

    def get_symbol_values_and_distributions(
        self,
    ) -> List[Tuple[Symbol, Optional[float], Optional[float], Optional[float], Optional[FreeSymbolDistribution]]]:
        return self.__symbol_substitutions


# define a default system
