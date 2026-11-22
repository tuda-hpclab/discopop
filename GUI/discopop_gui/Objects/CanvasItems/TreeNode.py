# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Tuple, Dict, Set, TYPE_CHECKING, Any
from copy import deepcopy

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsTextItem

from discopop_gui.Constants import TREE_NODES_SPACING, TREE_NODE_RADIUS
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.utils.TreeNode import TreeNode as BaseTreeNode
from discopop_gui.Objects.CanvasItems.Popup import Popup
from discopop_gui.Objects.CanvasItems.TreeEdges.Main import Main as MainEdge
from discopop_gui.Objects.CanvasItems.TreeEdges.Dependency import Dependency as DependencyEdge

if TYPE_CHECKING:
    from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees


class TreeNode:
    def __init__(
        self,
        canvas: "ViewableCanvasWithTrees",
        base_node: BaseTreeNode,
        visible: bool,
        popup: Popup,
        oval: QGraphicsEllipseItem,
        text: QGraphicsTextItem,
        x_offset: int,
        y_offset: int,
    ):
        self._base_node = base_node
        self._visible = visible
        self._canvas = canvas
        self._popup = popup
        self._oval = oval
        self._text = text
        self._higher_order_connections_shown: bool = False
        self._lower_order_connections_shown: bool = False
        self._higher_order_main_connection: MainEdge[int] | None = None
        self._lower_order_main_connections: Dict[int, MainEdge[int]] = {}
        self._higher_order_dependency_connections: Dict[int, Tuple[QGraphicsLineItem, List[DependencyEdge[int]]]] = {}
        self._lower_order_dependency_connections: Dict[int, Tuple[QGraphicsLineItem, List[DependencyEdge[int]]]] = {}
        self._higher_order_main_hide_request: bool = True
        self._lower_order_main_hide_requests: Set[int] = set()
        self._lower_order_main_x_offset_data: Dict[int, Tuple[int, Tuple[int, int] | None]] = {}
        self._x_offset: int = x_offset
        self._y_offset: int = y_offset

        self._canvas.bind_item(self._oval, 1, self._on_left_press)
        self._canvas.bind_item(self._oval, 3, self._on_right_press)
        self._canvas.bind_item(self._text, 1, self._on_left_press)
        self._canvas.bind_item(self._text, 3, self._on_right_press)

    def serialize(self) -> Dict[str, Any]:
        return {
            "visible": self._visible,
            "higher_order_connections_shown": self._higher_order_connections_shown,
            "lower_order_connections_shown": self._lower_order_connections_shown,
            "higher_order_main_connection": (
                {
                    "state": "normal" if self._higher_order_main_connection.get_canvas_edge().isVisible() else "hidden",
                    "data": self._higher_order_main_connection.serialize(),
                }
                if self._higher_order_main_connection is not None
                else None
            ),
            "higher_order_dependency_connections": {
                str(higher_order_dependency_connection_id): {
                    "state": "normal" if edge_data[0].isVisible() else "hidden",
                    "data": [edge.serialize() for edge in edge_data[1]],
                }
                for (
                    higher_order_dependency_connection_id,
                    edge_data,
                ) in self._higher_order_dependency_connections.items()
            },
            "higher_order_main_hide_request": self._higher_order_main_hide_request,
            "lower_order_main_hide_requests": list(self._lower_order_main_hide_requests),
            "lower_order_main_x_offset_data": {
                str(lower_order_main_connection_id): (
                    str(x_offset_data[0]),
                    (str(x_offset_data[1][0]), str(x_offset_data[1][1])) if x_offset_data[1] is not None else None,
                )
                for lower_order_main_connection_id, x_offset_data in self._lower_order_main_x_offset_data.items()
            },
            "x_offset": str(self._x_offset),
            "y_offset": str(self._y_offset),
        }

    def deserialize(self, data: Dict[str, Any]) -> None:
        self._visible = data["visible"]

        self._oval.setVisible(self._visible)
        self._text.setVisible(self._visible)

        self._higher_order_connections_shown = data["higher_order_connections_shown"]
        self._lower_order_connections_shown = data["lower_order_connections_shown"]

        if data["higher_order_main_connection"] is not None:
            self._higher_order_main_connection = self._canvas.create_visual_main_edge(
                self._base_node.id, self._base_node.id, state=data["higher_order_main_connection"]["state"]
            )
            self._higher_order_main_connection.deserialize(
                data["higher_order_main_connection"]["data"], lambda x: int(x)
            )
            self._canvas.get_visual_node(
                self._higher_order_main_connection.get_source_node_id()
            )._lower_order_main_connections[self._base_node.id] = self._higher_order_main_connection

        for higher_order_dependency_connection_id, edge_data in data["higher_order_dependency_connections"].items():
            canvas_edge = self._canvas.create_visual_dependency_edge(
                self._base_node.id, self._base_node.id, state=edge_data["state"]
            )
            self._higher_order_dependency_connections[int(higher_order_dependency_connection_id)] = (canvas_edge, [])

            for edge_serialized in edge_data["data"]:
                edge = DependencyEdge[int](0, 0, 0)
                edge.deserialize(edge_serialized, lambda x: int(x))
                self._higher_order_dependency_connections[int(higher_order_dependency_connection_id)][1].append(edge)

            self._canvas.get_visual_node(
                int(higher_order_dependency_connection_id)
            )._lower_order_dependency_connections[self._base_node.id] = self._higher_order_dependency_connections[
                int(higher_order_dependency_connection_id)
            ]

        self._higher_order_main_hide_request = data["higher_order_main_hide_request"]
        self._lower_order_main_hide_requests = set(
            int(lower_order_main_id) for lower_order_main_id in data["lower_order_main_hide_requests"]
        )
        self._lower_order_main_x_offset_data = {
            int(lower_order_main_connection_id): (
                int(x_offset_data[0]),
                (int(x_offset_data[1][0]), int(x_offset_data[1][1])) if x_offset_data[1] is not None else None,
            )
            for lower_order_main_connection_id, x_offset_data in data["lower_order_main_x_offset_data"].items()
        }
        self._x_offset = int(data["x_offset"])
        self._y_offset = int(data["y_offset"])

    def _on_show_or_hide_higher_order(self) -> None:
        if (self._higher_order_main_connection is None) and (self._base_node.higher_order_main_connection is not None):
            base_node_connection = self._base_node.higher_order_main_connection
            self._canvas.create_visual_node(base_node_connection.id, state="hidden")
            edge = self._canvas.create_visual_main_edge(base_node_connection.id, self._base_node.id, state="hidden")
            connection = self._canvas.get_visual_node(base_node_connection.id)
            connection.add_lower_order_main_connection(edge)
            self._higher_order_main_connection = edge
            self._higher_order_main_hide_request = True

        if self._higher_order_main_hide_request:
            self.visualize_higher_order_connections()
            self._higher_order_connections_shown = True
        else:
            self.hide_higher_order_connections()
            self._higher_order_connections_shown = False

            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(
                    self._higher_order_main_connection.get_source_node_id()
                ).set_lower_order_connections_shown(False)

        highest_visible_id = self.get_highest_visible_by_lower_order()
        current_highest_id = self.get_current_highest_by_lower_order()

        if highest_visible_id is None or current_highest_id is None:
            raise ValueError("No highest visible or current highest node found for lower order.")

        if highest_visible_id != current_highest_id:
            index = self._canvas.remove_highest_visual_node_id(current_highest_id)
            self._canvas.add_highest_visual_node_id(highest_visible_id, index)

        if self._canvas.check_highest_visual_node(self._base_node.id):
            self._canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())
        else:
            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(
                    self._higher_order_main_connection.get_source_node_id()
                ).request_x_space_by_lower_order(self._base_node.id, self.get_x_space())
            else:
                raise ValueError("No main higher order node found of non-highest.")

        self._canvas.update_visual_node_offsets()
        return None

    def _on_left_press(self, _: Any) -> str | None:
        if not (self._canvas.get_viewer_mode() == ViewerMode.MAIN):
            return None

        if len(self._lower_order_main_connections) < len(self._base_node.lower_order_main_connections):
            dependencies_to_add = []

            for managed_dependency in self._base_node.managed_dependencies:
                edge = DependencyEdge[int](managed_dependency[0].id, managed_dependency[1].id, self._base_node.id)
                current_base_node = self._canvas.get_node(edge.get_source_node_id())
                higher_order_base_node = self._canvas.get_node(edge.get_source_node_id()).higher_order_main_connection
                already_created_check = 0
                checked = False

                while (
                    higher_order_base_node is not None
                    and (
                        not self._canvas.check_visual_node(current_base_node.id)
                        or not self._canvas.get_visual_node(current_base_node.id).get_visible()
                    )
                    and edge.climb_source_node_id(higher_order_base_node.id)
                ):
                    if not checked and self._canvas.check_visual_node(current_base_node.id):
                        already_created_check += 1
                        checked = True
                    elif checked and not self._canvas.check_visual_node(current_base_node.id):
                        already_created_check -= 1
                        checked = False

                    current_base_node = higher_order_base_node
                    higher_order_base_node = self._canvas.get_node(current_base_node.id).higher_order_main_connection

                if (
                    (current_base_node is not None)
                    and (not checked)
                    and (self._canvas.check_visual_node(current_base_node.id))
                ):
                    already_created_check += 1

                current_base_node = self._canvas.get_node(edge.get_target_node_id())
                higher_order_base_node = self._canvas.get_node(edge.get_target_node_id()).higher_order_main_connection
                checked = False

                while (
                    already_created_check < 2
                    and higher_order_base_node is not None
                    and (
                        not self._canvas.check_visual_node(current_base_node.id)
                        or not self._canvas.get_visual_node(current_base_node.id).get_visible()
                    )
                    and edge.climb_target_node_id(higher_order_base_node.id)
                ):
                    if not checked and self._canvas.check_visual_node(current_base_node.id):
                        already_created_check += 1
                        checked = True
                    elif checked and not self._canvas.check_visual_node(current_base_node.id):
                        already_created_check -= 1
                        checked = False

                    current_base_node = higher_order_base_node
                    higher_order_base_node = self._canvas.get_node(current_base_node.id).higher_order_main_connection

                if already_created_check < 2:
                    dependencies_to_add.append(edge)

            for base_node_connection in self._base_node.lower_order_main_connections:
                if base_node_connection.id in self._lower_order_main_connections:
                    continue

                self._canvas.create_visual_node(base_node_connection.id, state="hidden")
                base_edge = self._canvas.create_visual_main_edge(
                    self._base_node.id, base_node_connection.id, state="hidden"
                )
                connection = self._canvas.get_visual_node(base_node_connection.id)
                connection.set_higher_order_main_connection(base_edge)
                self.add_lower_order_main_connection(base_edge)

            for dependency_edge in dependencies_to_add:
                source_node = self._canvas.get_visual_node(dependency_edge.get_source_node_id())
                target_node = self._canvas.get_visual_node(dependency_edge.get_target_node_id())
                source_node.add_lower_order_dependency_connection(dependency_edge)
                target_node.add_higher_order_dependency_connection(dependency_edge)

        if len(self._lower_order_main_hide_requests) > 0:
            self.visualize_lower_order_connections()
            self._lower_order_connections_shown = True
        else:
            self.hide_lower_order_connections()
            self._lower_order_connections_shown = False

            for connection_id, __ in self._lower_order_main_connections.items():
                self._canvas.get_visual_node(connection_id).set_higher_order_connections_shown(False)

        if self._canvas.check_highest_visual_node(self._base_node.id):
            self._canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())
        else:
            if self._higher_order_main_connection is not None:
                self._canvas.get_visual_node(
                    self._higher_order_main_connection.get_source_node_id()
                ).request_x_space_by_lower_order(self._base_node.id, self.get_x_space())
            else:
                raise ValueError("No main higher order node found of non-highest.")

        self._canvas.update_visual_node_offsets()
        return None

    def _on_new_canvas(self) -> None:
        self._canvas.add_clone_to_canvas_viewer(self._base_node.id)
        return None

    def _on_right_press(self, event: Any) -> str | None:
        if not (self._canvas.get_viewer_mode() == ViewerMode.MAIN):
            return None

        self._popup.clear_buttons()

        if self._higher_order_main_connection is None and self._base_node.higher_order_main_connection is not None:
            if self._higher_order_main_hide_request:
                self._popup.add_button("Show higher order", self._on_show_or_hide_higher_order)
            else:
                self._popup.add_button("Hide higher order", self._on_show_or_hide_higher_order)

        self._popup.add_button("New canvas", self._on_new_canvas)
        self._popup.show_at(QPoint(int(event.x), int(event.y)))
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

    def get_higher_order_dependency_canvas_edge(
        self, base_node_id: int
    ) -> QGraphicsLineItem | None:
        if self._higher_order_dependency_connections.get(base_node_id) is not None:
            return self._higher_order_dependency_connections[base_node_id][0]

        return None

    def get_lower_order_dependency_canvas_edge(
        self, base_node_id: int
    ) -> QGraphicsLineItem | None:
        if self._lower_order_dependency_connections.get(base_node_id) is not None:
            return self._lower_order_dependency_connections[base_node_id][0]

        return None

    def get_current_highest_by_higher_order(self) -> List[int]:
        if self._canvas.check_highest_visual_node(self._base_node.id):
            return [self._base_node.id]

        output: List[int] = []

        for connection_id, _ in self._lower_order_main_connections.items():
            output.extend(self._canvas.get_visual_node(connection_id).get_current_highest_by_higher_order())

        return output

    def get_current_highest_by_lower_order(self) -> int | None:
        if self._canvas.check_highest_visual_node(self._base_node.id):
            return self._base_node.id

        if self._higher_order_main_connection is not None:
            return self._canvas.get_visual_node(
                self._higher_order_main_connection.get_source_node_id()
            ).get_current_highest_by_lower_order()

        return None

    def get_highest_visible_by_higher_order(self) -> List[int]:
        output: List[int] = []

        if self._visible:
            return [self._base_node.id]

        for connection_id, _ in self._lower_order_main_connections.items():
            output.extend(self._canvas.get_visual_node(connection_id).get_highest_visible_by_higher_order())

        return output

    def get_highest_visible_by_lower_order(self) -> int | None:
        value = None

        if self._visible:
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

            if not left_set:
                space_left = abs(x_offset_data[0]) + x_offset_data[1][0]
                left_set = True

            space_right = abs(x_offset_data[0]) + x_offset_data[1][1]

        if not left_set and not self._visible:
            return None

        return (space_left, space_right)

    def set_offset_by_higher_order(self, x_offset: int, y_offset: int) -> None:
        if self._visible:
            self._x_offset = x_offset
            self._y_offset = y_offset
            node_x = x_offset * TREE_NODES_SPACING
            node_y = y_offset * TREE_NODES_SPACING
            self._oval.setRect(
                QRectF(
                    node_x - TREE_NODE_RADIUS,
                    node_y - TREE_NODE_RADIUS,
                    2 * TREE_NODE_RADIUS,
                    2 * TREE_NODE_RADIUS,
                )
            )
            self._text.setPos(
                node_x - self._text.boundingRect().width() / 2,
                node_y - self._text.boundingRect().height() / 2,
            )

        y_offset_increase = 1 if self._visible else 0

        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            if x_offset_data[1] is None:
                continue

            connection = self._lower_order_main_connections[connection_id]
            self._canvas.get_visual_node(connection_id).set_offset_by_higher_order(
                x_offset + x_offset_data[0], y_offset + y_offset_increase
            )

            if self._visible:
                connection.get_canvas_edge().setLine(
                    x_offset * TREE_NODES_SPACING,
                    y_offset * TREE_NODES_SPACING,
                    (x_offset + x_offset_data[0]) * TREE_NODES_SPACING,
                    (y_offset + y_offset_increase) * TREE_NODES_SPACING,
                )

        if not self._visible:
            return

        for connection_id, edge in self._higher_order_dependency_connections.items():
            source_x, source_y = self._canvas.get_visual_node(connection_id).get_location()
            edge[0].setLine(
                source_x,
                source_y,
                x_offset * TREE_NODES_SPACING,
                y_offset * TREE_NODES_SPACING,
            )

        for connection_id, edge in self._lower_order_dependency_connections.items():
            target_x, target_y = self._canvas.get_visual_node(connection_id).get_location()
            edge[0].setLine(
                x_offset * TREE_NODES_SPACING,
                y_offset * TREE_NODES_SPACING,
                target_x,
                target_y,
            )

    def request_x_space_by_lower_order(self, lower_order_id: int, space_requested: Tuple[int, int] | None) -> None:
        _ = self._lower_order_main_x_offset_data[lower_order_id]
        left_offset = 0
        right_offset = 0
        offset_data = self._lower_order_main_x_offset_data[lower_order_id][1]

        if (space_requested is not None) and (offset_data is not None):
            left_offset = offset_data[0] - space_requested[0]
            right_offset = space_requested[1] - offset_data[1]
        elif space_requested is not None:
            left_offset = -space_requested[0]
            right_offset = space_requested[1]
        elif offset_data is not None:
            left_offset = offset_data[0]
            right_offset = -offset_data[1]
        else:
            return

        space_needed_left: int = 0
        space_needed_right: int = 0
        flip = False
        left_set = False

        for connection_id, _ in self._lower_order_main_x_offset_data.items():
            if connection_id == lower_order_id:
                self._lower_order_main_x_offset_data[connection_id] = (
                    self._lower_order_main_x_offset_data[connection_id][0],
                    space_requested,
                )
                flip = True
            elif not flip:
                self._lower_order_main_x_offset_data[connection_id] = (
                    self._lower_order_main_x_offset_data[connection_id][0] + left_offset,
                    self._lower_order_main_x_offset_data[connection_id][1],
                )
            else:
                self._lower_order_main_x_offset_data[connection_id] = (
                    self._lower_order_main_x_offset_data[connection_id][0] + right_offset,
                    self._lower_order_main_x_offset_data[connection_id][1],
                )

            offset_data = self._lower_order_main_x_offset_data[connection_id][1]

            if offset_data is None:
                continue

            if not left_set:
                space_needed_left = abs(self._lower_order_main_x_offset_data[connection_id][0]) + offset_data[0]
                left_set = True

            space_needed_right = abs(self._lower_order_main_x_offset_data[connection_id][0]) + offset_data[1]

        if self._canvas.check_highest_visual_node(self._base_node.id):
            self._canvas.request_x_space_by_highest_visual_node(
                self._base_node.id,
                None if ((not left_set) and (not self._visible)) else (space_needed_left, space_needed_right),
            )

            return

        if self._higher_order_main_connection is not None:
            self._canvas.get_visual_node(
                self._higher_order_main_connection.get_source_node_id()
            ).request_x_space_by_lower_order(
                self._base_node.id,
                None if ((not left_set) and (not self._visible)) else (space_needed_left, space_needed_right),
            )
        else:
            raise ValueError("No main higher order node found of non-highest.")

    def set_higher_order_connections_shown(self, shown: bool) -> None:
        self._higher_order_connections_shown = shown

    def set_lower_order_connections_shown(self, shown: bool) -> None:
        if (not shown) and (len(self._lower_order_main_hide_requests) < len(self._lower_order_main_connections)):
            return

        self._lower_order_connections_shown = shown

    def set_higher_order_main_connection(self, edge: MainEdge[int]) -> None:
        self._higher_order_main_connection = edge
        self._higher_order_main_hide_request = True

    def add_higher_order_dependency_connection(self, edge: DependencyEdge[int]) -> None:
        if self._higher_order_dependency_connections.get(edge.get_source_node_id()) is None:
            canvas_edge = self._canvas.get_visual_node(
                edge.get_source_node_id()
            ).get_lower_order_dependency_canvas_edge(self._base_node.id)

            if canvas_edge is None:
                canvas_edge = self._canvas.create_visual_dependency_edge(
                    edge.get_source_node_id(), self._base_node.id, state="hidden"
                )

            self._higher_order_dependency_connections[edge.get_source_node_id()] = (canvas_edge, [edge])
        else:
            self._higher_order_dependency_connections[edge.get_source_node_id()][1].append(edge)

    def remove_updated_higher_order_dependency_connection(
        self, original_source_node_id: int, edge: DependencyEdge[int]
    ) -> None:
        self._higher_order_dependency_connections[original_source_node_id][1].remove(edge)

        if len(self._higher_order_dependency_connections[original_source_node_id][1]) == 0:
            visual_edge = self._higher_order_dependency_connections[original_source_node_id][0]
            if visual_edge.scene() is not None:
                visual_edge.scene().removeItem(visual_edge)
            self._higher_order_dependency_connections.pop(original_source_node_id)

    def add_lower_order_main_connection(self, edge: MainEdge[int]) -> None:
        self._lower_order_main_connections[edge.get_target_node_id()] = edge
        self._lower_order_main_hide_requests.add(edge.get_target_node_id())
        self._lower_order_main_x_offset_data[edge.get_target_node_id()] = (0, None)

    def add_lower_order_dependency_connection(self, edge: DependencyEdge[int]) -> None:
        if self._lower_order_dependency_connections.get(edge.get_target_node_id()) is None:
            canvas_edge = self._canvas.get_visual_node(
                edge.get_target_node_id()
            ).get_higher_order_dependency_canvas_edge(self._base_node.id)

            if canvas_edge is None:
                canvas_edge = self._canvas.create_visual_dependency_edge(
                    self._base_node.id, edge.get_target_node_id(), state="hidden"
                )

            self._lower_order_dependency_connections[edge.get_target_node_id()] = (canvas_edge, [edge])
        else:
            self._lower_order_dependency_connections[edge.get_target_node_id()][1].append(edge)

    def remove_updated_lower_order_dependency_connection(
        self, original_target_node_id: int, edge: DependencyEdge[int]
    ) -> None:
        self._lower_order_dependency_connections[original_target_node_id][1].remove(edge)

        if len(self._lower_order_dependency_connections[original_target_node_id][1]) == 0:
            visual_edge = self._lower_order_dependency_connections[original_target_node_id][0]
            if visual_edge.scene() is not None:
                visual_edge.scene().removeItem(visual_edge)
            self._lower_order_dependency_connections.pop(original_target_node_id)

    def visualize_by_higher_order(self, higher_order_id: int) -> None:
        if (self._higher_order_main_connection is None) or not (
            higher_order_id == self._higher_order_main_connection.get_source_node_id()
        ):
            raise ValueError("Higher order id is not a higher order connection of this node.")

        self._oval.setVisible(True)
        self._text.setVisible(True)

        for _, edge in self._higher_order_dependency_connections.items():
            edge[0].setVisible(True)

        for _, edge in self._lower_order_dependency_connections.items():
            edge[0].setVisible(True)

        self._visible = True
        self._higher_order_main_hide_request = False
        self._higher_order_connections_shown = True

        if self._lower_order_connections_shown:
            self.visualize_lower_order_connections()

    def visualize_by_lower_order(self, lower_order_id: int) -> None:
        if lower_order_id not in self._lower_order_main_connections:
            raise ValueError("Lower order id is not a lower order connection of this node.")

        self._lower_order_main_hide_requests.remove(lower_order_id)
        self._oval.setVisible(True)
        self._text.setVisible(True)

        for _, edge in self._higher_order_dependency_connections.items():
            edge[0].setVisible(True)

        for _, edge in self._lower_order_dependency_connections.items():
            edge[0].setVisible(True)

        self._visible = True
        self._lower_order_connections_shown = True

        if self._higher_order_connections_shown:
            self.visualize_higher_order_connections()

    def hide_by_higher_order(self, higher_order_id: int) -> None:
        if (self._higher_order_main_connection is None) or not (
            higher_order_id == self._higher_order_main_connection.get_source_node_id()
        ):
            raise ValueError("Higher order id is not a higher order connection of this node.")

        if self._higher_order_main_hide_request:
            return

        self._higher_order_main_hide_request = True

        if self._higher_order_main_hide_request:
            self._oval.setVisible(False)
            self._text.setVisible(False)
            self._visible = False

            if self._lower_order_connections_shown:
                self.hide_lower_order_connections()

            for connection_id, edges in self._higher_order_dependency_connections.copy().items():
                for edge in edges[1].copy():
                    if edge.climb_target_node_id(self._higher_order_main_connection.get_source_node_id()):
                        edges[1].remove(edge)
                        self._canvas.get_visual_node(
                            edge.get_source_node_id()
                        ).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                        self._canvas.get_visual_node(
                            self._higher_order_main_connection.get_source_node_id()
                        ).add_higher_order_dependency_connection(edge)

                if len(edges[1]) == 0:
                    edges[0].scene().removeItem(edges[0])
                    self._higher_order_dependency_connections.pop(connection_id)

            for connection_id, edges in self._lower_order_dependency_connections.copy().items():
                for edge in edges[1].copy():
                    if edge.climb_source_node_id(self._higher_order_main_connection.get_source_node_id()):
                        edges[1].remove(edge)
                        self._canvas.get_visual_node(
                            edge.get_target_node_id()
                        ).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                        self._canvas.get_visual_node(
                            self._higher_order_main_connection.get_source_node_id()
                        ).add_lower_order_dependency_connection(edge)

                if len(edges[1]) == 0:
                    edges[0].scene().removeItem(edges[0])
                    self._lower_order_dependency_connections.pop(connection_id)

            for _, edges in self._higher_order_dependency_connections.items():
                edges[0].setVisible(False)

            for _, edges in self._lower_order_dependency_connections.items():
                edges[0].setVisible(False)

    def hide_by_lower_order(self, lower_order_id: int) -> None:
        if lower_order_id not in self._lower_order_main_connections:
            raise ValueError("Lower order id is not a lower order connection of this node.")

        if lower_order_id in self._lower_order_main_hide_requests:
            return

        self._lower_order_main_hide_requests.add(lower_order_id)

        if len(self._lower_order_main_hide_requests) == len(self._lower_order_main_connections):
            self._oval.setVisible(False)
            self._text.setVisible(False)
            self._visible = False

            if self._higher_order_main_connection is not None:
                for connection_id, edges in self._higher_order_dependency_connections.copy().items():
                    for edge in edges[1].copy():
                        if edge.climb_target_node_id(self._higher_order_main_connection.get_source_node_id()):
                            edges[1].remove(edge)
                            self._canvas.get_visual_node(
                                edge.get_source_node_id()
                            ).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                            self._canvas.get_visual_node(
                                self._higher_order_main_connection.get_source_node_id()
                            ).add_higher_order_dependency_connection(edge)

                    if len(edges[1]) == 0:
                        edges[0].scene().removeItem(edges[0])
                        self._higher_order_dependency_connections.pop(connection_id)

                for connection_id, edges in self._lower_order_dependency_connections.copy().items():
                    for edge in edges[1].copy():
                        if edge.climb_source_node_id(self._higher_order_main_connection.get_source_node_id()):
                            edges[1].remove(edge)
                            self._canvas.get_visual_node(
                                edge.get_target_node_id()
                            ).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                            self._canvas.get_visual_node(
                                self._higher_order_main_connection.get_source_node_id()
                            ).add_lower_order_dependency_connection(edge)

                    if len(edges[1]) == 0:
                        edges[0].scene().removeItem(edges[0])
                        self._lower_order_dependency_connections.pop(connection_id)

                for _, edges in self._higher_order_dependency_connections.items():
                    edges[0].setVisible(False)

                for _, edges in self._lower_order_dependency_connections.items():
                    edges[0].setVisible(False)

            if self._higher_order_connections_shown:
                self.hide_higher_order_connections()

    def visualize_higher_order_connections(self) -> None:
        if self._higher_order_main_hide_request and self._higher_order_main_connection is not None:
            self._higher_order_main_connection.get_canvas_edge().setVisible(True)
            self._canvas.get_visual_node(
                self._higher_order_main_connection.get_source_node_id()
            ).visualize_by_lower_order(self._base_node.id)

        self._higher_order_main_hide_request = False

    def visualize_lower_order_connections(self) -> None:
        for connection_id, edges in self._higher_order_dependency_connections.copy().items():
            for edge in edges[1].copy():
                move_to_id = edge.pop_climbed_target_node_id()

                if move_to_id is not None:
                    edges[1].remove(edge)
                    self._canvas.get_visual_node(
                        edge.get_source_node_id()
                    ).remove_updated_lower_order_dependency_connection(self._base_node.id, edge)
                    self._canvas.get_visual_node(move_to_id).add_higher_order_dependency_connection(edge)

            if len(edges[1]) == 0:
                edges[0].scene().removeItem(edges[0])
                self._higher_order_dependency_connections.pop(connection_id)

        for connection_id, edges in self._lower_order_dependency_connections.copy().items():
            for edge in edges[1].copy():
                move_to_id = edge.pop_climbed_source_node_id()

                if move_to_id is not None:
                    edges[1].remove(edge)
                    self._canvas.get_visual_node(
                        edge.get_target_node_id()
                    ).remove_updated_higher_order_dependency_connection(self._base_node.id, edge)
                    self._canvas.get_visual_node(move_to_id).add_lower_order_dependency_connection(edge)

            if len(edges[1]) == 0:
                edges[0].scene().removeItem(edges[0])
                self._lower_order_dependency_connections.pop(connection_id)

        for connection_id in self._lower_order_main_hide_requests:
            self._lower_order_main_connections[connection_id].get_canvas_edge().setVisible(True)
            self._canvas.get_visual_node(connection_id).visualize_by_higher_order(self._base_node.id)

        self._lower_order_main_hide_requests = set()

        new_space: int = 0
        centers: List[Tuple[int, int]] = []

        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            space: Tuple[int, int] | None = self._canvas.get_visual_node(connection_id).get_x_space()

            if space is not None:
                centers.append((connection_id, space[0] + new_space))
                new_space += space[0] + space[1] + 1

            self._lower_order_main_x_offset_data[connection_id] = (x_offset_data[0], space)

        offset: int = (new_space - 1) // 2

        for connection_id, center in centers:
            self._lower_order_main_x_offset_data[connection_id] = (
                center - offset,
                self._lower_order_main_x_offset_data[connection_id][1],
            )

    def hide_higher_order_connections(self) -> None:
        if self._higher_order_main_connection is not None and not self._higher_order_main_hide_request:
            self._higher_order_main_connection.get_canvas_edge().setVisible(False)
            self._canvas.get_visual_node(self._higher_order_main_connection.get_source_node_id()).hide_by_lower_order(
                self._base_node.id
            )
            self._higher_order_main_hide_request = True

    def hide_lower_order_connections(self) -> None:
        for connection_id, edge in self._lower_order_main_connections.items():
            if connection_id not in self._lower_order_main_hide_requests:
                edge.get_canvas_edge().setVisible(False)
                self._canvas.get_visual_node(connection_id).hide_by_higher_order(self._base_node.id)
                self._lower_order_main_hide_requests.add(connection_id)

        new_space: int = 0
        centers: List[Tuple[int, int]] = []

        for connection_id, x_offset_data in self._lower_order_main_x_offset_data.items():
            space: Tuple[int, int] | None = self._canvas.get_visual_node(connection_id).get_x_space()

            if space is not None:
                centers.append((connection_id, space[0] + new_space))
                new_space += space[0] + space[1] + 1

            self._lower_order_main_x_offset_data[connection_id] = (x_offset_data[0], space)

        offset: int = (new_space - 1) // 2

        for connection_id, center in centers:
            self._lower_order_main_x_offset_data[connection_id] = (
                center - offset,
                self._lower_order_main_x_offset_data[connection_id][1],
            )

    def recursive_copy_to_canvas(
        self,
        canvas: "ViewableCanvasWithTrees",
        higher_order_edges: MainEdge[int] | Tuple[QGraphicsLineItem, List[DependencyEdge[int]]] | None = None,
    ) -> None:
        state: str = "normal" if self._visible else "hidden"
        created = canvas.create_visual_node(self._base_node.id, state)
        cloned_node = canvas.get_visual_node(self._base_node.id)

        if higher_order_edges is not None:
            if isinstance(higher_order_edges, MainEdge):
                cloned_edge = canvas.create_visual_main_edge(
                    higher_order_edges.get_source_node_id(),
                    higher_order_edges.get_target_node_id(),
                    state="normal" if higher_order_edges.get_canvas_edge().isVisible() else "hidden",
                )
                cloned_node._higher_order_main_connection = cloned_edge

                if canvas.check_highest_visual_node(self._base_node.id):
                    canvas.remove_highest_visual_node_id(self._base_node.id)
                    cloned_node._higher_order_main_hide_request = self._higher_order_main_hide_request
                    cloned_node._higher_order_connections_shown = self._higher_order_connections_shown
            elif isinstance(higher_order_edges, tuple):
                dependency_edges = [edge.copy() for edge in higher_order_edges[1]]
                source_id = dependency_edges[0].get_source_node_id()
                target_id = dependency_edges[0].get_target_node_id()
                cloned_dependency_edge = canvas.create_visual_dependency_edge(
                    source_id,
                    target_id,
                    state="normal" if higher_order_edges[0].isVisible() else "hidden",
                )
                cloned_node._higher_order_dependency_connections[source_id] = (
                    cloned_dependency_edge,
                    dependency_edges,
                )

        if created:
            cloned_node._lower_order_connections_shown = deepcopy(self._lower_order_connections_shown)
            cloned_node._lower_order_main_hide_requests = deepcopy(self._lower_order_main_hide_requests)
            cloned_node._lower_order_main_x_offset_data = deepcopy(self._lower_order_main_x_offset_data)
            cloned_node._higher_order_connections_shown = self._higher_order_connections_shown
            cloned_node._higher_order_main_hide_request = self._higher_order_main_hide_request

            for connection_id, edge in self._lower_order_main_connections.items():
                cloned_canvas_edge = canvas.create_visual_main_edge(
                    self._base_node.id,
                    connection_id,
                    state="normal" if edge.get_canvas_edge().isVisible() else "hidden",
                )
                cloned_node._lower_order_main_connections[connection_id] = cloned_canvas_edge
                self._canvas.get_visual_node(connection_id).recursive_copy_to_canvas(canvas, cloned_canvas_edge)

            for connection_id, (canvas_edge, edges) in self._lower_order_dependency_connections.items():
                cloned_canvas_edge = canvas.create_visual_dependency_edge(
                    self._base_node.id,
                    connection_id,
                    state="normal" if canvas_edge.isVisible() else "hidden",
                )

                cloned_edges = [edge.copy() for edge in edges]
                cloned_node._lower_order_dependency_connections[connection_id] = (cloned_canvas_edge, cloned_edges)
                self._canvas.get_visual_node(connection_id).recursive_copy_to_canvas(
                    canvas, cloned_node._lower_order_dependency_connections[connection_id]
                )

        if higher_order_edges is None or (isinstance(higher_order_edges, tuple) and created):
            cloned_node._higher_order_main_hide_request = True
            cloned_node._higher_order_connections_shown = False
            canvas.add_highest_visual_node_id(self._base_node.id)
            canvas.request_x_space_by_highest_visual_node(self._base_node.id, self.get_x_space())
