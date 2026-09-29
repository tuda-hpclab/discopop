# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Dict, Tuple, Any

class TreeNode:
    def __init__(self, id : int) -> None:
        self.id : int = id
        self.lower_order_main_connections : List["TreeNode"] = []
        self.higher_order_main_connection : "TreeNode | None" = None
        self.managed_dependencies : List[Tuple["TreeNode", "TreeNode"]] = []
        self.metadata : Dict[str, str] = {}

    def serialize(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lower_order_main_connection_ids": [str(node.id) for node in self.lower_order_main_connections],
            "higher_order_main_connection_id": str(self.higher_order_main_connection.id) if self.higher_order_main_connection else None,
            "managed_dependency_ids": [(str(dependency[0].id), str(dependency[1].id)) for dependency in self.managed_dependencies],
            "metadata": self.metadata.copy()
        }

    def deserialize(self, data: Dict[str, Any], nodes_dictionary: Dict[int, "TreeNode"]) -> None:
        self.id = int(data["id"])
        self.lower_order_main_connections = [nodes_dictionary[int(node_id)] for node_id in data["lower_order_main_connection_ids"]]
        self.higher_order_main_connection = nodes_dictionary[int(data["higher_order_main_connection_id"])] if data["higher_order_main_connection_id"] is not None else None
        self.managed_dependencies = [(nodes_dictionary[int(dependency[0])], nodes_dictionary[int(dependency[1])]) for dependency in data["managed_dependency_ids"]]
        self.metadata = data["metadata"].copy()