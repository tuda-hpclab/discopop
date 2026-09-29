# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import os.path
from typing import Dict, Set, cast

from discopop_explorer.aliases.MemoryRegion import MemoryRegion


def get_sizes_of_memory_regions(
    mem_regs: Set[MemoryRegion], mem_reg_file: str, return_all_memory_regions: bool = False
) -> Dict[MemoryRegion, int]:
    """Returns the size of the allocated memory region in bytes"""
    if not os.path.exists(mem_reg_file):
        raise ValueError("Unknown file: ", mem_reg_file)
    # load memory regions to dictionary
    mem_regs_dict: Dict[str, int] = dict()
    with open(mem_reg_file, "r") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            split_line = line.split(" ")
            mem_regs_dict[split_line[0]] = int(split_line[2])

    if return_all_memory_regions:
        # skip filtering of memory regions
        return cast(Dict[MemoryRegion, int], mem_regs_dict)

    result_dict: Dict[MemoryRegion, int] = dict()
    for mem_reg in mem_regs:
        if str(mem_reg) in mem_regs_dict:
            result_dict[mem_reg] = mem_regs_dict[str(mem_reg)]

    return result_dict
