# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List

REQUIRED_EXECUTABLES: List[str] = [
    "python3",
]

# Each inner list is a group of alternatives; at least one from each group must be present.
REQUIRED_EXECUTABLE_ALTERNATIVES: List[List[str]] = [
    ["clang-19", "clang-20", "clang-21", "clang-22", "clang"],
]
