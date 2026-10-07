# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from collections import deque
from typing import Generic, Callable, Dict, Any

from discopop_gui.Types.T import T
from discopop_gui.Objects.CanvasItems.TreeEdges.Base import Base


class Dependency(Base[T], Generic[T]):
    def __init__(self, source_node_id: T, target_node_id: T, highest_common_node_id: T | None = None):
        super().__init__(source_node_id, target_node_id)

        self._highest_common_node_id = highest_common_node_id
        self._climbed_source_node_ids: deque[T] = deque()
        self._climbed_target_node_ids: deque[T] = deque()

    def get_highest_common_node_id(self) -> T | None:
        return self._highest_common_node_id

    def climb_source_node_id(self, node_id: T) -> bool:
        if node_id == self._highest_common_node_id:
            return False

        self._climbed_source_node_ids.append(self._source_node_id)
        self._source_node_id = node_id
        return True

    def climb_target_node_id(self, node_id: T) -> bool:
        if node_id == self._highest_common_node_id:
            return False

        self._climbed_target_node_ids.append(self._target_node_id)
        self._target_node_id = node_id
        return True

    def pop_climbed_source_node_id(self) -> T | None:
        if not self._climbed_source_node_ids:
            return None

        self._source_node_id = self._climbed_source_node_ids.pop()
        return self._source_node_id

    def pop_climbed_target_node_id(self) -> T | None:
        if not self._climbed_target_node_ids:
            return None

        self._target_node_id = self._climbed_target_node_ids.pop()
        return self._target_node_id

    def copy(self) -> "Dependency[T]":
        dependency = Dependency(
            self._source_node_id,
            self._target_node_id,
            self._highest_common_node_id,
        )

        dependency._climbed_source_node_ids = self._climbed_source_node_ids.copy()
        dependency._climbed_target_node_ids = self._climbed_target_node_ids.copy()

        return dependency

    def serialize(self) -> Dict[str, Any]:
        output = super().serialize()
        output["highest_common_node_id"] = (
            str(self._highest_common_node_id) if self._highest_common_node_id is not None else None
        )
        output["climbed_source_node_ids"] = [str(node_id) for node_id in self._climbed_source_node_ids]
        output["climbed_target_node_ids"] = [str(node_id) for node_id in self._climbed_target_node_ids]
        return output

    def deserialize(self, data: Dict[str, Any], converter: Callable[[str], T]) -> None:
        super().deserialize(data, converter)
        self._highest_common_node_id = (
            converter(data["highest_common_node_id"]) if data["highest_common_node_id"] is not None else None
        )
        self._climbed_source_node_ids = deque(converter(node_id) for node_id in data["climbed_source_node_ids"])
        self._climbed_target_node_ids = deque(converter(node_id) for node_id in data["climbed_target_node_ids"])
