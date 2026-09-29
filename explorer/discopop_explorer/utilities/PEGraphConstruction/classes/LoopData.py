# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from dataclasses import dataclass


@dataclass
class LoopData(object):
    line_id: str  # file_id:line_nr
    total_iteration_count: int
    entry_count: int
    average_iteration_count: int
    maximum_iteration_count: int
