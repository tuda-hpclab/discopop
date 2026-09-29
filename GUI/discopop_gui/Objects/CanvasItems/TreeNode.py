# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Tuple, Dict, Set, TYPE_CHECKING
from copy import deepcopy
import tkinter as tk

from discopop_gui.Constants import TREE_NODES_SPACING, TREE_NODE_RADIUS
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.utils.TreeNode import TreeNode as BaseTreeNode
from discopop_gui.Objects.CanvasItems.Popup import Popup
from discopop_gui.Objects.CanvasItems.TreeEdges.Main import Main as MainEdge
from discopop_gui.Objects.CanvasItems.TreeEdges.Dependency import Dependency as DependencyEdge

if TYPE_CHECKING:
    from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees

class TreeNode:
    def __init__(self, canvas : "ViewableCanvasWithTrees", base_node : BaseTreeNode, visible : bool, popup : Popup, oval_id : int, text_id : int, x_offset : int, y_offset : int):
        self._base_node = base_node
        self._visible = visible
        self._canvas = canvas
        self._popup = popup
        self._oval_id : int = oval_id
        self._text_id : int = text_id
        self._higher_order_connections_shown : bool = False
        self._lower_order_connections_shown : bool = False
        self._higher_order_main_connection : MainEdge[int] | None = None
        self._lower_order_main_connections : Dict[int, MainEdge[int]] = {}
        self._higher_order_dependency_connections : Dict[int, Tuple[int, List[DependencyEdge[int]]]] = {}
        self._lower_order_dependency_connections : Dict[int, Tuple[int, List[DependencyEdge[int]]]] = {}
        self._higher_order_main_hide_request : bool = True
        self._lower_order_main_hide_requests : Set[int] = set()
        self._lower_order_main_x_offset_data : Dict[int, Tuple[int, Tuple[int, int] | None]] = {}
        self._x_offset : int = x_offset
        self._y_offset : int = y_offset

        self._canvas.addtag_withtag("tree_node", self._oval_id)
        self._canvas.addtag_withtag("tree_node", self._text_id)
        self._canvas.tag_bind(self._oval_id, "<Button-1>", self._on_left_press)
        self._canvas.tag_bind(self._oval_id, "<Button-3>", self._on_right_press)
        self._canvas.tag_bind(self._text_id, "<Button-1>", self._on_left_press)
        self._canvas.tag_bind(self._text_id, "<Button-3>", self._on_right_press)

    def _on_show_or_hide_higher_order(self, _ : tk.Event) -> str | None:
        if (self._higher_order_main_connection is None) and (self._base_node.higher_order_main_connection is not None):
            base_node_connection = self._base_node.higher_order_main_connection
            self._canvas.create_visual_node(base_node_connection.id, state = "hidden")
            edge = self._canvas.create_visual_main_edge(base_node_connection.id, self._base_node.id, state = "hidden")
            connection = self._canvas.get_visual_node(base_node_connection.id)
            connection.add_lower_order_main_connection(edge)
            self._higher_order_main_connection = edge
            self._higher_order_main_hide_request = True
            self._canvas.tag_lower("tree_edge", "tree_node")

        if (self._higher_order_main_hide_request == True):
            self.visualize_higher_order_connections()
            self._higher_order_connections_shown = True
        else:
            self.hide_higher_order_connections()
            self._higher_order_connections_shown = False

            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).set_lower_order_connections_shown(False)

        highest_visible_id = self.get_highest_visible_by_lower_order()
        current_highest_id = self.get_current_highest_by_lower_order()

        if highest_visible_id is None or current_highest_id is None:
            raise ValueError("No highest visible or current highest node found for lower order.")

        if highest_visible_id != current_highest_id:
            index = self._canvas.remove_highest_visual_node_id(current_highest_id)
            self._canvas.add_highest_visual_node_id(highest_visible_id, index)

        if self._canvas.check_highest_visual_node(self._base_node.id) == True:
            self._canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())
        else:
            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).request_x_space_by_lower_order(self._base_node.id, self.get_x_space())
            else:
                raise ValueError("No main higher order node found of non-highest.")

        self._canvas.update_visual_node_offsets()
        return None

    def _on_left_press(self, _ : tk.Event) -> str | None:
        if not (self._canvas.get_viewer_mode() == ViewerMode.MAIN):
            return None
        
        if (len(self._lower_order_main_connections) < len(self._base_node.lower_order_main_connections)):
            dependencies_to_add = []

            for managed_dependency in self._base_node.managed_dependencies:
                edge = DependencyEdge[int](managed_dependency[0].id, managed_dependency[1].id, self._base_node.id)
                current_base_node = self._canvas.get_node(edge.get_source_node_id())
                higher_order_base_node = self._canvas.get_node(edge.get_source_node_id()).higher_order_main_connection
                already_created_check = 0
                checked = False

                while (
                    higher_order_base_node is not None and
                    (
                        self._canvas.check_visual_node(current_base_node.id) == False or 
                        self._canvas.get_visual_node(current_base_node.id).get_visible() == False
                    ) and
                    edge.climb_source_node_id(higher_order_base_node.id) == True
                ):
                    if checked == False and self._canvas.check_visual_node(current_base_node.id) == True:
                        already_created_check += 1
                        checked = True
                    elif checked == True and self._canvas.check_visual_node(current_base_node.id) == False:
                        already_created_check -= 1
                        checked = False

                    current_base_node = higher_order_base_node
                    higher_order_base_node = self._canvas.get_node(current_base_node.id).higher_order_main_connection

                if (current_base_node is not None) and (checked == False) and (self._canvas.check_visual_node(current_base_node.id) == True):
                    already_created_check += 1

                current_base_node = self._canvas.get_node(edge.get_target_node_id())
                higher_order_base_node = self._canvas.get_node(edge.get_target_node_id()).higher_order_main_connection
                checked = False

                while (
                    already_created_check < 2 and
                    higher_order_base_node is not None and
                    (
                        self._canvas.check_visual_node(current_base_node.id) == False or
                        self._canvas.get_visual_node(current_base_node.id).get_visible() == False
                    ) and
                    edge.climb_target_node_id(higher_order_base_node.id) == True
                ):
                    if checked == False and self._canvas.check_visual_node(current_base_node.id) == True:
                        already_created_check += 1
                        checked = True
                    elif checked == True and self._canvas.check_visual_node(current_base_node.id) == False:
                        already_created_check -= 1
                        checked = False

                    current_base_node = higher_order_base_node
                    higher_order_base_node = self._canvas.get_node(current_base_node.id).higher_order_main_connection

                if (already_created_check < 2):
                    dependencies_to_add.append(edge)
                
            for base_node_connection in self._base_node.lower_order_main_connections:
                if base_node_connection.id in self._lower_order_main_connections:
                    continue

                self._canvas.create_visual_node(base_node_connection.id, state = "hidden")
                base_edge = self._canvas.create_visual_main_edge(self._base_node.id, base_node_connection.id, state = "hidden")
                connection = self._canvas.get_visual_node(base_node_connection.id)
                connection.set_higher_order_main_connection(base_edge)
                self.add_lower_order_main_connection(base_edge)

            for dependency_edge in dependencies_to_add:
                source_node = self._canvas.get_visual_node(dependency_edge.get_source_node_id())
                target_node = self._canvas.get_visual_node(dependency_edge.get_target_node_id())
                source_node.add_lower_order_dependency_connection(dependency_edge)
                target_node.add_higher_order_dependency_connection(dependency_edge)

            self._canvas.tag_lower("tree_edge", "tree_node")

        if len(self._lower_order_main_hide_requests) > 0:
            self.visualize_lower_order_connections()
            self._lower_order_connections_shown = True
        else:
            self.hide_lower_order_connections()
            self._lower_order_connections_shown = False

            for connection_id, __ in self._lower_order_main_connections.items():
                self._canvas.get_visual_node(connection_id).set_higher_order_connections_shown(False)

        if self._canvas.check_highest_visual_node(self._base_node.id) == True:
            self._canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())
        else:
            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).request_x_space_by_lower_order(self._base_node.id, self.get_x_space())
            else:
                raise ValueError("No main higher order node found of non-highest.")

        self._canvas.update_visual_node_offsets()
        return None

    def _on_new_canvas(self, _ : tk.Event) -> str | None:
        self._canvas.add_clone_to_canvas_viewer(self._base_node.id)
        return None

    def _on_right_press(self, event : tk.Event) -> str | None:
        if not (self._canvas.get_viewer_mode() == ViewerMode.MAIN):
            return None
        
        self._popup.clear_buttons()

        if self._higher_order_main_connection is None and self._base_node.higher_order_main_connection is not None:
            if (self._higher_order_main_hide_request == True):
                self._popup.add_button("Show higher order", self._on_show_or_hide_higher_order)
            else:
                self._popup.add_button("Hide higher order", self._on_show_or_hide_higher_order)
            
        self._popup.add_button("New canvas", self._on_new_canvas)
        x = self._canvas.canvasx(event.x)
        y = self._canvas.canvasy(event.y)
        self._popup.visualize(x, y)
        return None

    def get_id(self) -> int:
        return self._base_node.id
    
    def get_visible(self) -> bool:
        return self._visible
    
    def get_location(self) -> Tuple[float, float]:
        return (self._x_offset * TREE_NODES_SPACING, self._y_offset * TREE_NODES_SPACING)

    def get_higher_order_main_id(self) -> int | None:
        if self._higher_order_main_connection is not None:
            return self._higher_order_main_connection.get_source_node_id()
        
        return None

    def get_higher_order_dependency_canvas_edge_id(self, base_node_id : int) -> int | None:
        if self._higher_order_dependency_connections.get(base_node_id) is not None:
            return self._higher_order_dependency_connections[base_node_id][0]

        return None

    def get_lower_order_dependency_canvas_edge_id(self, base_node_id : int) -> int | None:
        if self._lower_order_dependency_connections.get(base_node_id) is not None:
            return self._lower_order_dependency_connections[base_node_id][0]

        return None
    
    def get_current_highest_by_higher_order(self) -> List[int]:
        if self._canvas.check_highest_visual_node(self._base_node.id):
            return [self._base_node.id]
        
        output : List[int] = []

        for connection_id, _ in self._lower_order_main_connections.items():
            output.extend(self._canvas.get_visual_node(connection_id).get_current_highest_by_higher_order())

        return output

    def get_current_highest_by_lower_order(self) -> int | None:
        if self._canvas.check_highest_visual_node(self._base_node.id):
            return self._base_node.id

        if self._higher_order_main_connection is not None:
            return self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).get_current_highest_by_lower_order()

        return None

    def get_highest_visible_by_higher_order(self) -> List[int]:
        output : List[int] = []

        if self._visible == True:
            return [self._base_node.id]

        for connection_id, _ in self._lower_order_main_connections.items():
            output.extend(self._canvas.get_visual_node(connection_id).get_highest_visible_by_higher_order())

        return output

    def get_highest_visible_by_lower_order(self) -> int | None:
        value = None

        if self._visible == True:
            value = self._base_node.id

        if self._higher_order_main_connection is not None:
            connection = self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id())
            connection_value = connection.get_highest_visible_by_lower_order()

            if connection_value is not None:
                value = connection_value

        return value
    
    def get_x_space(self) -> Tuple[int, int] | None:
        space_left = 0
        space_right = 0
        left_set = False

        for _, x_offset_data in self._lower_order_main_x_offset_data.items():
            if x_offset_data[1] is None:
                continue

            if left_set == False:
                space_left = abs(x_offset_data[0]) + x_offset_data[1][0]
                left_set = True

            space_right = abs(x_offset_data[0]) + x_offset_data[1][1]

        if left_set == False and self._visible == False:
            return None
        
        return (space_left, space_right)

    def set_offset_by_higher_order(self, x_offset : int, y_offset : int) -> None:
        if self._visible == True:
            self._x_offset = x_offset
            self._y_offset = y_offset
            self._canvas.coords_unscaled(self._oval_id, x_offset * TREE_NODES_SPACING - TREE_NODE_RADIUS, y_offset * TREE_NODES_SPACING - TREE_NODE_RADIUS, x_offset * TREE_NODES_SPACING + TREE_NODE_RADIUS, y_offset * TREE_NODES_SPACING + TREE_NODE_RADIUS)
            self._canvas.coords_unscaled(self._text_id, x_offset * TREE_NODES_SPACING, y_offset * TREE_NODES_SPACING)

        y_offset_increase = 1 if self._visible == True else 0

        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            if x_offset_data[1] is None:
                continue

            connection = self._lower_order_main_connections[connection_id]
            self._canvas.get_visual_node(connection_id).set_offset_by_higher_order(x_offset + x_offset_data[0], y_offset + y_offset_increase)

            if self._visible == True:
                self._canvas.coords_unscaled(connection.get_canvas_edge_id(), x_offset * TREE_NODES_SPACING, y_offset * TREE_NODES_SPACING, (x_offset + x_offset_data[0]) * TREE_NODES_SPACING, (y_offset + y_offset_increase) * TREE_NODES_SPACING)

        if self._visible == False:
            return
        
        for connection_id, edge in self._higher_order_dependency_connections.items():
            self._canvas.coords_unscaled(edge[0], self._canvas.get_visual_node(connection_id).get_location()[0], self._canvas.get_visual_node(connection_id).get_location()[1], x_offset * TREE_NODES_SPACING, y_offset * TREE_NODES_SPACING)

        for connection_id, edge in self._lower_order_dependency_connections.items():
            self._canvas.coords_unscaled(edge[0], x_offset * TREE_NODES_SPACING, y_offset * TREE_NODES_SPACING, self._canvas.get_visual_node(connection_id).get_location()[0], self._canvas.get_visual_node(connection_id).get_location()[1])

    def request_x_space_by_lower_order(self, lower_order_id : int, space_requested : Tuple[int, int] | None) -> None:
        _ = self._lower_order_main_x_offset_data[lower_order_id]
        left_offset = 0
        right_offset = 0
        offset_data = self._lower_order_main_x_offset_data[lower_order_id][1]

        if ((space_requested is not None) and (offset_data is not None)):
            left_offset = offset_data[0] - space_requested[0]
            right_offset = space_requested[1] - offset_data[1]
        elif (space_requested is not None):
            left_offset = -space_requested[0]
            right_offset = space_requested[1]
        elif (offset_data is not None):
            left_offset = offset_data[0]
            right_offset = -offset_data[1]
        else:
            return

        space_needed_left : int = 0
        space_needed_right : int = 0
        flip = False
        leftSet = False

        for connection_id, _ in self._lower_order_main_x_offset_data.items():
            if connection_id == lower_order_id:
                self._lower_order_main_x_offset_data[connection_id] = (self._lower_order_main_x_offset_data[connection_id][0], space_requested)
                flip = True
            elif flip == False:
                self._lower_order_main_x_offset_data[connection_id] = (self._lower_order_main_x_offset_data[connection_id][0] + left_offset, self._lower_order_main_x_offset_data[connection_id][1])
            else:
                self._lower_order_main_x_offset_data[connection_id] = (self._lower_order_main_x_offset_data[connection_id][0] + right_offset, self._lower_order_main_x_offset_data[connection_id][1])

            offset_data = self._lower_order_main_x_offset_data[connection_id][1]

            if (offset_data is None):
                continue

            if leftSet == False:
                space_needed_left = abs(self._lower_order_main_x_offset_data[connection_id][0]) + offset_data[0]
                leftSet = True

            space_needed_right = abs(self._lower_order_main_x_offset_data[connection_id][0]) + offset_data[1]

        if (self._canvas.check_highest_visual_node(self._base_node.id) == True):
            self._canvas.request_x_space_by_highest_visual_node(
                self._base_node.id, None if ((leftSet == False) and (self._visible == False)) else (space_needed_left, space_needed_right)
            )

            return

        if (self._higher_order_main_connection is not None):
            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).request_x_space_by_lower_order(
                self._base_node.id, None if ((leftSet == False) and (self._visible == False)) else (space_needed_left, space_needed_right)
            )
        else:
            raise ValueError("No main higher order node found of non-highest.")

    def set_higher_order_connections_shown(self, shown : bool) -> None:
        self._higher_order_connections_shown = shown

    def set_lower_order_connections_shown(self, shown : bool) -> None:
        if (shown == False) and (len(self._lower_order_main_hide_requests) < len(self._lower_order_main_connections)):
            return
        
        self._lower_order_connections_shown = shown
    
    def set_higher_order_main_connection(self, edge : MainEdge[int]) -> None:
        self._higher_order_main_connection = edge
        self._higher_order_main_hide_request = True

    def add_higher_order_dependency_connection(self, edge : DependencyEdge[int]) -> None:
        if self._higher_order_dependency_connections.get(edge.get_source_node_id()) is None:
            canvas_edge_id = self._canvas.get_visual_node(edge.get_source_node_id()).get_lower_order_dependency_canvas_edge_id(self._base_node.id)

            if canvas_edge_id is None:
                canvas_edge_id = self._canvas.create_visual_dependency_edge(edge.get_source_node_id(), self._base_node.id, state = "hidden")

            self._higher_order_dependency_connections[edge.get_source_node_id()] = (canvas_edge_id, [edge])
        else:
            self._higher_order_dependency_connections[edge.get_source_node_id()][1].append(edge)

    def remove_updated_higher_order_dependency_connection(self, original_source_node_id : int, edge : DependencyEdge[int]) -> None:
        self._higher_order_dependency_connections[original_source_node_id][1].remove(edge)

        if len(self._higher_order_dependency_connections[original_source_node_id][1]) == 0:
            self._canvas.delete(self._higher_order_dependency_connections[original_source_node_id][0])
            self._higher_order_dependency_connections.pop(original_source_node_id)

    def add_lower_order_main_connection(self, edge : MainEdge[int]) -> None:
        self._lower_order_main_connections[edge.get_target_node_id()] = edge
        self._lower_order_main_hide_requests.add(edge.get_target_node_id())
        self._lower_order_main_x_offset_data[edge.get_target_node_id()] = (0, None)

    def add_lower_order_dependency_connection(self, edge : DependencyEdge[int]) -> None:
        if self._lower_order_dependency_connections.get(edge.get_target_node_id()) is None:
            canvas_edge_id = self._canvas.get_visual_node(edge.get_target_node_id()).get_higher_order_dependency_canvas_edge_id(self._base_node.id)

            if canvas_edge_id is None:
                canvas_edge_id = self._canvas.create_visual_dependency_edge(self._base_node.id, edge.get_target_node_id(), state = "hidden")

            self._lower_order_dependency_connections[edge.get_target_node_id()] = (canvas_edge_id, [edge])
        else:
            self._lower_order_dependency_connections[edge.get_target_node_id()][1].append(edge)

    def remove_updated_lower_order_dependency_connection(self, original_target_node_id : int, edge : DependencyEdge[int]) -> None:
        self._lower_order_dependency_connections[original_target_node_id][1].remove(edge)

        if len(self._lower_order_dependency_connections[original_target_node_id][1]) == 0:
            self._canvas.delete(self._lower_order_dependency_connections[original_target_node_id][0])
            self._lower_order_dependency_connections.pop(original_target_node_id)

    def visualize_by_higher_order(self, higher_order_id : int) -> None:
        if (self._higher_order_main_connection is None) or not (higher_order_id == self._higher_order_main_connection.get_source_node_id()):
            raise ValueError("Higher order id is not a higher order connection of this node.")
        
        self._canvas.itemconfigure(self._oval_id, state = "normal")
        self._canvas.itemconfigure(self._text_id, state = "normal")

        for _, edge in self._higher_order_dependency_connections.items():
            self._canvas.itemconfigure(edge[0], state = "normal")

        for _, edge in self._lower_order_dependency_connections.items():
            self._canvas.itemconfigure(edge[0], state = "normal")

        self._visible = True
        self._higher_order_main_hide_request = False
        self._higher_order_connections_shown = True

        if (self._lower_order_connections_shown == True):
            self.visualize_lower_order_connections()

    def visualize_by_lower_order(self, lower_order_id : int) -> None:
        if (lower_order_id not in self._lower_order_main_connections):
            raise ValueError("Lower order id is not a lower order connection of this node.")

        self._lower_order_main_hide_requests.remove(lower_order_id)
        self._canvas.itemconfigure(self._oval_id, state = "normal")
        self._canvas.itemconfigure(self._text_id, state = "normal")

        for _, edge in self._higher_order_dependency_connections.items():
            self._canvas.itemconfigure(edge[0], state = "normal")

        for _, edge in self._lower_order_dependency_connections.items():
            self._canvas.itemconfigure(edge[0], state = "normal")

        self._visible = True
        self._lower_order_connections_shown = True

        if (self._higher_order_connections_shown == True):
            self.visualize_higher_order_connections()

    def hide_by_higher_order(self, higher_order_id : int) -> None:
        if (self._higher_order_main_connection is None) or not (higher_order_id == self._higher_order_main_connection.get_source_node_id()):
            raise ValueError("Higher order id is not a higher order connection of this node.")

        if self._higher_order_main_hide_request == True:
            return
        
        self._higher_order_main_hide_request = True
        
        if (self._higher_order_main_hide_request == True):
            self._canvas.itemconfigure(self._oval_id, state = "hidden")
            self._canvas.itemconfigure(self._text_id, state = "hidden")
            self._visible = False

            if (self._lower_order_connections_shown == True):
                self.hide_lower_order_connections()

            for connection_id, edges in self._higher_order_dependency_connections.copy().items():
                for edge in edges[1].copy():
                    if (edge.climb_target_node_id(self._higher_order_main_connection.get_source_node_id()) == True):
                        edges[1].remove(edge)
                        self._canvas.get_visual_node(edge.get_source_node_id()).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                        self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).add_higher_order_dependency_connection(edge)

                if (len(edges[1]) == 0):
                    self._canvas.delete(edges[0])
                    self._higher_order_dependency_connections.pop(connection_id)

            for connection_id, edges in self._lower_order_dependency_connections.copy().items():
                for edge in edges[1].copy():
                    if (edge.climb_source_node_id(self._higher_order_main_connection.get_source_node_id()) == True):
                        edges[1].remove(edge)
                        self._canvas.get_visual_node(edge.get_target_node_id()).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                        self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).add_lower_order_dependency_connection(edge)

                if (len(edges[1]) == 0):
                    self._canvas.delete(edges[0])
                    self._lower_order_dependency_connections.pop(connection_id)

            for _, edges in self._higher_order_dependency_connections.items():
                self._canvas.itemconfigure(edges[0], state = "hidden")

            for _, edges in self._lower_order_dependency_connections.items():
                self._canvas.itemconfigure(edges[0], state = "hidden")

    def hide_by_lower_order(self, lower_order_id : int) -> None:
        if (lower_order_id not in self._lower_order_main_connections):
            raise ValueError("Lower order id is not a lower order connection of this node.")

        if lower_order_id in self._lower_order_main_hide_requests:
            return
        
        self._lower_order_main_hide_requests.add(lower_order_id)
        
        if (len(self._lower_order_main_hide_requests) == len(self._lower_order_main_connections)):
            self._canvas.itemconfigure(self._oval_id, state = "hidden")
            self._canvas.itemconfigure(self._text_id, state = "hidden")
            self._visible = False

            if (self._higher_order_main_connection is not None):
                for connection_id, edges in self._higher_order_dependency_connections.copy().items():
                    for edge in edges[1].copy():
                        if (edge.climb_target_node_id(self._higher_order_main_connection.get_source_node_id()) == True):
                            edges[1].remove(edge)
                            self._canvas.get_visual_node(edge.get_source_node_id()).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).add_higher_order_dependency_connection(edge)

                    if (len(edges[1]) == 0):
                        self._canvas.delete(edges[0])
                        self._higher_order_dependency_connections.pop(connection_id)

                for connection_id, edges in self._lower_order_dependency_connections.copy().items():
                    for edge in edges[1].copy():
                        if (edge.climb_source_node_id(self._higher_order_main_connection.get_source_node_id()) == True):
                            edges[1].remove(edge)
                            self._canvas.get_visual_node(edge.get_target_node_id()).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).add_lower_order_dependency_connection(edge)

                    if (len(edges[1]) == 0):
                        self._canvas.delete(edges[0])
                        self._lower_order_dependency_connections.pop(connection_id)

                for _, edges in self._higher_order_dependency_connections.items():
                    self._canvas.itemconfigure(edges[0], state = "hidden")

                for _, edges in self._lower_order_dependency_connections.items():
                    self._canvas.itemconfigure(edges[0], state = "hidden")
                
            if (self._higher_order_connections_shown == True):
                self.hide_higher_order_connections()

    def visualize_higher_order_connections(self) -> None:
        if (self._higher_order_main_hide_request == True and self._higher_order_main_connection is not None):
            self._canvas.itemconfigure(self._higher_order_main_connection.get_canvas_edge_id(), state = "normal")
            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).visualize_by_lower_order(self._base_node.id)

        self._higher_order_main_hide_request = False

    def visualize_lower_order_connections(self) -> None:
        for connection_id, edges in self._higher_order_dependency_connections.copy().items():
            for edge in edges[1].copy():
                move_to_id = edge.pop_climbed_target_node_id()

                if move_to_id is not None:
                    edges[1].remove(edge)
                    self._canvas.get_visual_node(edge.get_source_node_id()).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                    self._canvas.get_visual_node(move_to_id).add_higher_order_dependency_connection(edge)

            if (len(edges[1]) == 0):
                self._canvas.delete(edges[0])
                self._higher_order_dependency_connections.pop(connection_id)

        for connection_id, edges in self._lower_order_dependency_connections.copy().items():
            for edge in edges[1].copy():
                move_to_id = edge.pop_climbed_source_node_id()

                if move_to_id is not None:
                    edges[1].remove(edge)
                    self._canvas.get_visual_node(edge.get_target_node_id()).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                    self._canvas.get_visual_node(move_to_id).add_lower_order_dependency_connection(edge)

            if (len(edges[1]) == 0):
                self._canvas.delete(edges[0])
                self._lower_order_dependency_connections.pop(connection_id)

        for connection_id in self._lower_order_main_hide_requests:
            self._canvas.itemconfigure(self._lower_order_main_connections[connection_id].get_canvas_edge_id(), state = "normal")
            self._canvas.get_visual_node(connection_id).visualize_by_higher_order(self._base_node.id)
            
        self._lower_order_main_hide_requests = set()

        new_space : int = 0
        centers : List[Tuple[int, int]] = []
        
        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            space : Tuple[int, int] | None = self._canvas.get_visual_node(connection_id).get_x_space()

            if space is not None:
                centers.append((connection_id, space[0] + new_space))
                new_space += space[0] + space[1] + 1

            self._lower_order_main_x_offset_data[connection_id] = (x_offset_data[0], space)

        offset : int = (new_space - 1) // 2

        for connection_id, center in centers:
            self._lower_order_main_x_offset_data[connection_id] = (center - offset, self._lower_order_main_x_offset_data[connection_id][1])

    def hide_higher_order_connections(self) -> None:
        if (self._higher_order_main_connection is not None and self._higher_order_main_hide_request == False):
            self._canvas.itemconfigure(self._higher_order_main_connection.get_canvas_edge_id(), state = "hidden")
            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).hide_by_lower_order(self._base_node.id)
            self._higher_order_main_hide_request = True

    def hide_lower_order_connections(self) -> None:
        for connection_id, edge in self._lower_order_main_connections.items():
            if not (connection_id in self._lower_order_main_hide_requests):
                self._canvas.itemconfigure(edge.get_canvas_edge_id(), state = "hidden")
                self._canvas.get_visual_node(connection_id).hide_by_higher_order(self._base_node.id)
                self._lower_order_main_hide_requests.add(connection_id)

        new_space : int = 0
        centers : List[Tuple[int, int]] = []
        
        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            space : Tuple[int, int] | None = self._canvas.get_visual_node(connection_id).get_x_space()

            if space is not None:
                centers.append((connection_id, space[0] + new_space))
                new_space += space[0] + space[1] + 1

            self._lower_order_main_x_offset_data[connection_id] = (x_offset_data[0], space)

        offset : int = (new_space - 1) // 2

        for connection_id, center in centers:
            self._lower_order_main_x_offset_data[connection_id] = (center - offset, self._lower_order_main_x_offset_data[connection_id][1])

    def recursive_copy_to_canvas(
        self,
        canvas : "ViewableCanvasWithTrees",
        higher_order_edges : MainEdge[int] | Tuple[int, List[DependencyEdge[int]]] | None = None
    ) -> None:
        state : str = "normal" if self._visible else "hidden"
        created = canvas.create_visual_node(self._base_node.id, state)
        cloned_node = canvas.get_visual_node(self._base_node.id)

        if higher_order_edges is not None:
            canvas.tag_lower("tree_edge", "tree_node")

            if isinstance(higher_order_edges, MainEdge):
                cloned_node._higher_order_main_connection = higher_order_edges

                if (canvas.check_highest_visual_node(self._base_node.id) == True):
                    canvas.remove_highest_visual_node_id(self._base_node.id)
                    cloned_node._higher_order_main_hide_request = self._higher_order_main_hide_request
                    cloned_node._higher_order_connections_shown = self._higher_order_connections_shown
            elif isinstance(higher_order_edges, tuple):
                cloned_node._higher_order_dependency_connections[higher_order_edges[1][0].get_source_node_id()] = (higher_order_edges[0], higher_order_edges[1])

        if (created == True):
            cloned_node._lower_order_connections_shown = deepcopy(self._lower_order_connections_shown)
            cloned_node._lower_order_main_hide_requests = deepcopy(self._lower_order_main_hide_requests)
            cloned_node._lower_order_main_x_offset_data = deepcopy(self._lower_order_main_x_offset_data)
            cloned_node._higher_order_connections_shown = self._higher_order_connections_shown
            cloned_node._higher_order_main_hide_request = self._higher_order_main_hide_request

            for connection_id, edge in self._lower_order_main_connections.items():
                cloned_canvas_edge_id = self._canvas.clone_item_to_canvas(canvas, edge.get_canvas_edge_id())
                cloned_edge = MainEdge[int](cloned_canvas_edge_id, self._base_node.id, connection_id)
                cloned_node._lower_order_main_connections[connection_id] = cloned_edge
                self._canvas.get_visual_node(connection_id).recursive_copy_to_canvas(canvas, cloned_edge)

            for connection_id, (canvas_edge_id, edges) in self._lower_order_dependency_connections.items():
                cloned_canvas_edge_id = self._canvas.clone_item_to_canvas(canvas, canvas_edge_id)
                cloned_edges = [edge.copy() for edge in edges]
                cloned_node._lower_order_dependency_connections[connection_id] = (cloned_canvas_edge_id, cloned_edges)
                self._canvas.get_visual_node(connection_id).recursive_copy_to_canvas(canvas, cloned_node._lower_order_dependency_connections[connection_id])

        if (higher_order_edges is None or (isinstance(higher_order_edges, tuple) and created == True)):
            cloned_node._higher_order_main_hide_request = True
            cloned_node._higher_order_connections_shown = False
            canvas.add_highest_visual_node_id(self._base_node.id)
            canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())