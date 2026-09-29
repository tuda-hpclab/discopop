# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum


class PragmaPosition(IntEnum):
    BEFORE_START = 0
    AFTER_START = 1
    BEFORE_END = 2
    AFTER_END = 3


class OmpConstructPositioning(IntEnum):
    BEFORE_LINE = 0
    AFTER_LINE = 1


class PragmaType(IntEnum):
    PRAGMA = 1
    REGION = 2
