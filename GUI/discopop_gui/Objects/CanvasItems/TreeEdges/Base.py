# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Generic

from discopop_gui.Types.T import T

class Base(Generic[T]):
    def __init__(self, source_node_id: T, target_node_id: T):
        self._source_node_id = source_node_id
        self._target_node_id = target_node_id

    def get_source_node_id(self) -> T:
        return self._source_node_id

    def get_target_node_id(self) -> T:
        return self._target_node_id