# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Any, Dict, Optional

from discopop_explorer.aliases.MemoryRegion import MemoryRegion


class ReadDataAccess(object):
    memory_region: MemoryRegion
    var_name: Optional[str]
    from_call: bool

    def __init__(self, memory_region: MemoryRegion, var_name: Optional[str], from_call: bool = False) -> None:
        self.memory_region = memory_region
        self.var_name = var_name
        self.from_call = from_call

    def __str__(self) -> str:
        return_str = ""
        return_str += "C" if self.from_call else ""
        return_str += "R(" + self.memory_region + ")"
        return return_str


class WriteDataAccess(object):
    memory_region: MemoryRegion
    unique_id: int
    var_name: Optional[str]
    from_call: bool

    def __init__(self, memory_region: MemoryRegion, unique_id: int, var_name: Optional[str], from_call: bool = False):
        self.memory_region = memory_region
        self.unique_id = unique_id
        self.var_name = var_name
        self.from_call = from_call

    def __str__(self) -> str:
        return_str = ""
        return_str += "C" if self.from_call else ""
        return_str += "W(" + self.memory_region + "-" + str(self.unique_id) + ", --> " + str(self.var_name) + ")"
        return return_str

    def __hash__(self) -> int:
        return self.unique_id

    def toDict(self) -> Dict[str, Any]:
        result_dict: Dict[str, Any] = {}
        result_dict["memory_region"] = self.memory_region
        result_dict["unique_id"] = self.unique_id
        result_dict["var_name"] = self.var_name
        result_dict["from_call"] = self.from_call
        return result_dict


def write_data_access_from_dict(values: Dict[str, Any]) -> WriteDataAccess:
    return WriteDataAccess(values["memory_region"], values["unique_id"], values["var_name"], values["from_call"])
