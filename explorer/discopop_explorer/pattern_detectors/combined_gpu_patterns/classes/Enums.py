# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum


class ExitPointPositioning(IntEnum):
    BEFORE_CU = 0
    AFTER_CU = 1


class EntryPointPositioning(IntEnum):
    BEFORE_CU = 0
    AFTER_CU = 1


class ExitPointType(IntEnum):
    FROM_DEVICE = 0
    DELETE = 1
    ASYNC_FROM_DEVICE = 2


class EntryPointType(IntEnum):
    TO_DEVICE = 0
    ALLOCATE = 1
    ASYNC_TO_DEVICE = 2
    ASYNC_ALLOCATE = 3


class UpdateType(IntEnum):
    TO_DEVICE = 0
    FROM_DEVICE = 1
    # TO_FROM should not occur ideally, since data should only be modified either on the host or the device for now
    TO_FROM_DEVICE = 2
    ALLOCATE = 3
