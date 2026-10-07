# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Generic, Callable, Dict, Any

from discopop_gui.Types.T import T


class Base(Generic[T]):
    def __init__(self, source_node_id: T, target_node_id: T):
        self._source_node_id = source_node_id
        self._target_node_id = target_node_id

    def get_source_node_id(self) -> T:
        return self._source_node_id

    def get_target_node_id(self) -> T:
        return self._target_node_id

    def serialize(self) -> Dict[str, Any]:
        return {"source_node_id": str(self._source_node_id), "target_node_id": str(self._target_node_id)}

    def deserialize(self, data: Dict[str, Any], converter: Callable[[str], T]) -> None:
        self._source_node_id = converter(data["source_node_id"])
        self._target_node_id = converter(data["target_node_id"])
