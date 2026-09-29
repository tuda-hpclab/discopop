# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
import networkx as nx
from typing import Any, Dict, Tuple, List, Set, TYPE_CHECKING

from discopop_gui.Constants import TREE_NODES_SPACING, TREE_NODE_RADIUS
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.Enums.EdgeType import EdgeType
from discopop_gui.Objects.Canvases.Viewables.Base import Base
from discopop_gui.utils.TreeNode import TreeNode
from discopop_gui.Objects.CanvasItems.TreeNode import TreeNode as VisualTreeNode
from discopop_gui.Objects.CanvasItems.TreeEdges.Main import Main as VisualMainEdge
from discopop_gui.Objects.CanvasItems.TreeEdges.Dependency import Dependency as VisualDependencyEdge

if TYPE_CHECKING:
    from discopop_gui.Objects.Frames.CanvasViewer import CanvasViewer

class WithTrees(Base):
    def __init__(
        self,
        parent : tk.Frame,
        canvas_viewer : "CanvasViewer[WithTrees]",
        viewer_mode : ViewerMode,
        serializable : bool = True,
        trees : Dict[int, TreeNode] = {},
        highest_managed_dependencies : List[Tuple[TreeNode, TreeNode]] = [],
        *args : Any,
        **kwargs : Any,
    ) -> None:
        super().__init__(parent, viewer_mode, serializable, *args, **kwargs)
        self._canvas_viewer = canvas_viewer
        self._nodes : Dict[int, TreeNode] = trees
        self._highest_managed_dependencies : List[Tuple[TreeNode, TreeNode]] = []
        self._visual_nodes : Dict[int, VisualTreeNode] = {}
        self._highest_visual_node_ids : List[int] = []
        self._highest_visual_nodes_x_offset_data : Dict[int, Tuple[int, int, int]] = {}

    def check_visual_node(self, visual_node_id : int) -> bool:
        return visual_node_id in self._visual_nodes
    
    def check_highest_visual_node(self, visual_node_id : int) -> bool:
        return visual_node_id in self._highest_visual_nodes_x_offset_data

    def get_node(self, node_id : int) -> TreeNode:
        return self._nodes[node_id]

    def get_visual_node(self, visual_node_id : int) -> VisualTreeNode:
        return self._visual_nodes[visual_node_id]

    def get_highest_visual_node_ids(self) -> List[int]:
        return self._highest_visual_node_ids.copy()

    def add_highest_visual_node_id(self, visual_node_id : int, at_index : int | None = None) -> None:
        offset = 0

        if len(self._highest_visual_node_ids) > 0:
            offset = self._highest_visual_nodes_x_offset_data[self._highest_visual_node_ids[-1]][0] + self._highest_visual_nodes_x_offset_data[self._highest_visual_node_ids[-1]][2] + 1

        self._highest_visual_nodes_x_offset_data[visual_node_id] = (offset, 0, 0)
        
        if at_index is not None:
            self._highest_visual_node_ids.insert(at_index, visual_node_id)

            for node_id in self._highest_visual_node_ids[at_index + 1:]:
                self._highest_visual_nodes_x_offset_data[node_id] = (
                    self._highest_visual_nodes_x_offset_data[node_id][0] + 1,
                    self._highest_visual_nodes_x_offset_data[node_id][1],
                    self._highest_visual_nodes_x_offset_data[node_id][2]
                )
        else:
            at_index = len(self._highest_visual_node_ids)
            self._highest_visual_node_ids.append(visual_node_id)

    def remove_highest_visual_node_id(self, visual_node_id : int) -> int:
        left_offset = self._highest_visual_nodes_x_offset_data[visual_node_id][1]
        right_offset = self._highest_visual_nodes_x_offset_data[visual_node_id][2]
        flip = False

        for node_id in self._highest_visual_node_ids:
            if node_id == visual_node_id:
                flip = True
            elif flip == False:
                self._highest_visual_nodes_x_offset_data[node_id] = (self._highest_visual_nodes_x_offset_data[node_id][0] + left_offset, self._highest_visual_nodes_x_offset_data[node_id][1], self._highest_visual_nodes_x_offset_data[node_id][2])
            else:
                self._highest_visual_nodes_x_offset_data[node_id] = (self._highest_visual_nodes_x_offset_data[node_id][0] - right_offset - 1, self._highest_visual_nodes_x_offset_data[node_id][1], self._highest_visual_nodes_x_offset_data[node_id][2])

        value = self._highest_visual_node_ids.index(visual_node_id)
        self._highest_visual_node_ids.remove(visual_node_id)
        self._highest_visual_nodes_x_offset_data.pop(visual_node_id, None)
        return value

    def update_visual_node_offsets(self) -> None:
        for visual_node_id in self._highest_visual_node_ids:
            self.get_visual_node(visual_node_id).set_offset_by_higher_order(self._highest_visual_nodes_x_offset_data[visual_node_id][0], 0)
    
    def request_x_space_by_highest_visual_node(self, visual_node_id : int, space_requested : Tuple[int, int] | None) -> None:
        if visual_node_id not in self._highest_visual_node_ids:
            raise ValueError("Called by non-highest visual node.")
        
        left_offset = 0
        right_offset = 0

        if space_requested is not None:
            left_offset = self._highest_visual_nodes_x_offset_data[visual_node_id][1] - space_requested[0]
            right_offset = space_requested[1] - self._highest_visual_nodes_x_offset_data[visual_node_id][2]
        else:
            self.remove_highest_visual_node_id(visual_node_id)
            return

        flip = False

        for connection_id, _ in self._highest_visual_nodes_x_offset_data.items():
            if connection_id == visual_node_id:
                self._highest_visual_nodes_x_offset_data[connection_id] = (self._highest_visual_nodes_x_offset_data[connection_id][0], space_requested[0], space_requested[1])    
                flip = True
            elif flip == False:
                self._highest_visual_nodes_x_offset_data[connection_id] = (self._highest_visual_nodes_x_offset_data[connection_id][0] + left_offset, self._highest_visual_nodes_x_offset_data[connection_id][1], self._highest_visual_nodes_x_offset_data[connection_id][2])
            else:
                self._highest_visual_nodes_x_offset_data[connection_id] = (self._highest_visual_nodes_x_offset_data[connection_id][0] + right_offset, self._highest_visual_nodes_x_offset_data[connection_id][1], self._highest_visual_nodes_x_offset_data[connection_id][2])

    def create_visual_node(self, visual_node_id: int, state : str = "normal", x_offset : int = 0, y_offset : int = 0) -> bool:
        if visual_node_id in self._visual_nodes:
            return False

        node = self._nodes[visual_node_id]
        x = x_offset * TREE_NODES_SPACING
        y = y_offset * TREE_NODES_SPACING
        label = node.metadata["label"]
        fill_color = node.metadata.get("fill", "cyan")

        oval_id = self.create_oval(
            x - TREE_NODE_RADIUS,
            y - TREE_NODE_RADIUS,
            x + TREE_NODE_RADIUS,
            y + TREE_NODE_RADIUS,
            fill=fill_color,
            outline="black",
            state = state
        )

        text_id = self.create_text(
            x,
            y,
            text=label,
            font=("Arial", 7),
            anchor="center",
            state = state
        )

        self._visual_nodes[visual_node_id] = VisualTreeNode(
            self,
            self._nodes[visual_node_id],
            True if state == "normal" else False,
            self._popup,
            oval_id,
            text_id,
            x_offset,
            y_offset
        )

        return True
    
    def create_visual_main_edge(self, from_id : int, to_id : int, state : str = "hidden") -> VisualMainEdge[int]:
        from_node = self.get_visual_node(from_id)
        to_node = self.get_visual_node(to_id)
        (x1, y1) = from_node.get_location()
        (x2, y2) = to_node.get_location()

        edge_id : int = self.create_line(
            x1,
            y1,
            x2,
            y2,
            fill = "black",
            width = 1,
            state = state,
            tags = "tree_edge"
        )

        return VisualMainEdge[int](
            edge_id,
            from_id,
            to_id
        )

    def create_visual_dependency_edge(self, from_id : int, to_id : int, state : str = "hidden") -> int:
        from_node = self.get_visual_node(from_id)
        to_node = self.get_visual_node(to_id)
        (x1, y1) = from_node.get_location()
        (x2, y2) = to_node.get_location()

        return self.create_line(
            x1,
            y1,
            x2,
            y2,
            fill = "red",
            width = 1,
            dash = (4, 4),
            state = state,
            tags = "tree_edge"
        )

    
    def add_clone_to_canvas_viewer(self, starting_tree_node_id : int) -> None:
        starting_tree_node = self.get_visual_node(starting_tree_node_id)

        def canvas_builder(parent : tk.Frame, canvas_viewer : "CanvasViewer[WithTrees]", canvas_viewer_mode : ViewerMode) -> "WithTrees":
            return WithTrees(parent, canvas_viewer, canvas_viewer_mode, False, self._nodes, self._highest_managed_dependencies, bg = self["bg"])

        cloned_canvas = self._canvas_viewer.get_canvas(self._canvas_viewer.add_canvas(canvas_builder))
        starting_tree_node.recursive_copy_to_canvas(cloned_canvas)
        cloned_canvas.update_visual_node_offsets()

    def build_trees(self, graph: nx.MultiDiGraph) -> None:
        self.delete("all")
        self._nodes.clear()
        self._highest_managed_dependencies.clear()
        self._visual_nodes.clear()
        self._transform_scale = 1
        self._transform_x = 0.0
        self._transform_y = 0.0
        self._highest_visual_node_ids.clear()
        self._highest_visual_nodes_x_offset_data.clear()

        nodes_to_ids : Dict[Any, int] = {}

        for node in graph.nodes:
            node_id = len(self._nodes)
            nodes_to_ids[node] = node_id
            self._nodes[node_id] = TreeNode(node_id)

            self._nodes[node_id].metadata.update(
                {
                    "label": node.get_label(),
                    "fill": "cyan"
                }
            )

        seen_edges : Set[Tuple[int, int]] = set()
        dependency_edges : List[Tuple[int, int]] = []
        
        for source, destination, data in graph.edges(data = True):
            source_node_id = nodes_to_ids[source]
            destination_node_id = nodes_to_ids[destination]

            if (source_node_id, destination_node_id) in seen_edges:
                continue
            
            if data.get("edge_type") == EdgeType.DEPENDENCY:
                dependency_edges.append((source_node_id, destination_node_id))
            elif data.get("edge_type") == EdgeType.MAIN:
                self._nodes[source_node_id].lower_order_main_connections.append(self._nodes[destination_node_id])
                self._nodes[destination_node_id].higher_order_main_connection = self._nodes[source_node_id]

            self._nodes[source_node_id].metadata["fill"] = "orange"
            seen_edges.add((source_node_id, destination_node_id))
            seen_edges.add((destination_node_id, source_node_id))

        for node_id, node in self._nodes.items():
            if node.higher_order_main_connection is not None:
                continue
            
            self.create_visual_node(node_id)
            self.add_highest_visual_node_id(node_id)
            self.request_x_space_by_highest_visual_node(node_id, (0, 0))

        for source_node_id, destination_node_id in dependency_edges:
            source_height = 0
            current_node = self._nodes[source_node_id]

            while current_node.higher_order_main_connection is not None:
                source_height += 1
                current_node = current_node.higher_order_main_connection

            destination_height = 0
            current_node = self._nodes[destination_node_id]

            while current_node.higher_order_main_connection is not None:
                destination_height += 1
                current_node = current_node.higher_order_main_connection

            current_source_node : TreeNode | None = self._nodes[source_node_id]
            current_destination_node : TreeNode | None = self._nodes[destination_node_id]

            while current_source_node is not None and source_height > destination_height:
                current_source_node = self._nodes[current_source_node.id].higher_order_main_connection
                source_height -= 1

            while current_destination_node is not None and destination_height > source_height:
                current_destination_node = self._nodes[current_destination_node.id].higher_order_main_connection
                destination_height -= 1

            while current_source_node is not None and current_destination_node is not None and current_source_node.id != current_destination_node.id:
                current_source_node = self._nodes[current_source_node.id].higher_order_main_connection
                current_destination_node = self._nodes[current_destination_node.id].higher_order_main_connection

            if current_source_node is not None and current_destination_node is not None and current_source_node.id == current_destination_node.id:
                self._nodes[current_source_node.id].managed_dependencies.append((self._nodes[source_node_id], self._nodes[destination_node_id]))
            else:
                visual_edge = VisualDependencyEdge[int](source_node_id, destination_node_id, None)
                current_source_node = self._nodes[source_node_id]
                current_destination_node = self._nodes[destination_node_id]

                while current_source_node.higher_order_main_connection is not None and visual_edge.climb_source_node_id(current_source_node.higher_order_main_connection.id):
                    current_source_node = current_source_node.higher_order_main_connection

                while current_destination_node.higher_order_main_connection is not None and visual_edge.climb_target_node_id(current_destination_node.higher_order_main_connection.id):
                    current_destination_node = current_destination_node.higher_order_main_connection

                self._highest_managed_dependencies.append((self._nodes[source_node_id], self._nodes[destination_node_id]))

        self.update_visual_node_offsets()

    def serialize(self) -> Dict[str, Any]:
        output = super().serialize()

        output.update({
            "nodes": {node_id: node.serialize() for node_id, node in self._nodes.items()},
            "highest_managed_dependencies": [(source_node.id, destination_node.id) for source_node, destination_node in self._highest_managed_dependencies]
        })

        return output

    def deserialize(self, data: Dict[str, Any]) -> None:
        self.delete("all")
        self._nodes.clear()
        self._highest_managed_dependencies.clear()
        self._visual_nodes.clear()
        self._transform_scale = 1
        self._transform_x = 0.0
        self._transform_y = 0.0
        self._highest_visual_node_ids.clear()
        self._highest_visual_nodes_x_offset_data.clear()

        for node_id_data in data["nodes"].keys():
            node_id = int(node_id_data)
            node = TreeNode(node_id)
            self._nodes[node_id] = node

        for node_id, node in self._nodes.items():
            node.deserialize(data["nodes"][str(node_id)], self._nodes)

        for node_id, node in self._nodes.items():
            if node.higher_order_main_connection is not None:
                continue
            
            self.create_visual_node(node_id)
            self.add_highest_visual_node_id(node_id)
            self.request_x_space_by_highest_visual_node(node_id, (0, 0))

        for source_node_id_data, destination_node_id_data in data["highest_managed_dependencies"]:
            source_node_id = int(source_node_id_data)
            destination_node_id = int(destination_node_id_data)
            visual_edge = VisualDependencyEdge[int](source_node_id, destination_node_id, None)
            current_source_node = self._nodes[source_node_id]
            current_destination_node = self._nodes[destination_node_id]

            while current_source_node.higher_order_main_connection is not None and visual_edge.climb_source_node_id(current_source_node.higher_order_main_connection.id):
                current_source_node = current_source_node.higher_order_main_connection

            while current_destination_node.higher_order_main_connection is not None and visual_edge.climb_target_node_id(current_destination_node.higher_order_main_connection.id):
                current_destination_node = current_destination_node.higher_order_main_connection

            self._highest_managed_dependencies.append((self._nodes[source_node_id], self._nodes[destination_node_id]))

        self.update_visual_node_offsets()