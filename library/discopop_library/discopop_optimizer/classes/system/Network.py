# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, Tuple, List, Optional, cast
import warnings

from sympy import Expr, Symbol, Integer  # type: ignore

from discopop_library.discopop_optimizer.classes.system.devices.Device import Device


class Network(object):
    __host_device: Optional[Device]
    __transfer_speeds: Dict[Tuple[Device, Device], Expr]  # (MB/s)
    __transfer_initialization_costs: Dict[Tuple[Device, Device], Expr]

    def __init__(self) -> None:
        self.__host_device = None
        self.__transfer_speeds = dict()
        self.__transfer_initialization_costs = dict()

    def add_connection(self, source: Device, target: Device, transfer_speed: Expr, initialization_delay: Expr) -> None:
        if source == target:
            transfer_speed = Integer(10000 * 1000)  # 10000 GB/s = 10000 * 1000 MB/s
        self.__transfer_speeds[(source, target)] = transfer_speed
        self.__transfer_initialization_costs[(source, target)] = initialization_delay

    def get_transfer_speed(self, source: Device, target: Device) -> Expr:
        if source == target:
            return cast(Expr, Integer(1000000))  # 1000 GB/s
        if (source, target) not in self.__transfer_speeds:
            if self.__host_device is None:
                raise ValueError("Host device of network unspecified!")
            S_to_H_speed = self.__transfer_speeds[(source, self.__host_device)]
            H_to_T_speed = self.__transfer_speeds[(self.__host_device, target)]
            return min(S_to_H_speed, H_to_T_speed)
        return self.__transfer_speeds[(source, target)]

    def get_transfer_initialization_costs(self, source: Device, target: Device) -> Expr:
        if source == target:
            return cast(Expr, Integer(0))
        if (source, target) not in self.__transfer_speeds:
            if self.__host_device is None:
                raise ValueError("Host device of network unspecified!")
            S_to_H_init_costs = self.__transfer_initialization_costs[(source, self.__host_device)]
            H_to_T_init_costs = self.__transfer_initialization_costs[(self.__host_device, target)]
            return cast(Expr, S_to_H_init_costs + H_to_T_init_costs)
        return self.__transfer_initialization_costs[(source, target)]

    def get_free_symbols(self) -> List[Tuple[Symbol, Optional[Expr]]]:
        result_list: List[Tuple[Symbol, Optional[Expr]]] = []
        for expr in self.__transfer_speeds.values():
            result_list += [(cast(Symbol, s), None) for s in expr.free_symbols]
        for expr in self.__transfer_initialization_costs.values():
            result_list += [(cast(Symbol, s), None) for s in expr.free_symbols]
        return result_list

    def set_host_device(self, host_device: Device) -> None:
        self.__host_device = host_device
