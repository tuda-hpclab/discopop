# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import networkx as nx
from typing import Any, Callable, Dict, List, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_gui.Objects.Frames.Base import Base
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Mouse import Mouse as MouseButton
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Magnifier import Magnifier as MagnifierButton
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Cross import Cross as CrossButton
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Plus import Plus as PlusButton
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.utils.TreeNode import TreeNode
from discopop_gui.Enums.EdgeType import EdgeType
from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees


class CanvasViewerWithTrees(Base):
    def __init__(self, parent: QWidget | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent, *args, **kwargs)

        self._selected_option: ViewerMode = ViewerMode.MAIN
        self._canvases: Dict[str, ViewableCanvasWithTrees] = {}
        self._canvas_selectors: Dict[str, QPushButton] = {}
        self._active_canvas_id: str | None = None
        self._canvas_id_counter: int = 0
        self._nodes: Dict[int, TreeNode] = {}
        self._highest_managed_dependencies: List[Tuple[TreeNode, TreeNode]] = []
        self._saved_canvases: List[Any] = []
        self._saved_canvases_loaders_buttons: List[QPushButton] = []
        self._tab_visible = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._top_container = QStackedWidget(self)
        root_layout.addWidget(self._top_container, 1)

        self._canvas_container = QStackedWidget(self._top_container)
        self._top_container.addWidget(self._canvas_container)

        self._saved_canvases_loaders_container = QWidget(self)
        saved_container_layout = QVBoxLayout(self._saved_canvases_loaders_container)
        saved_container_layout.setContentsMargins(4, 2, 4, 2)
        self._saved_canvases_loaders_container.setFixedHeight(44)
        saved_scroll_area = QScrollArea(self._saved_canvases_loaders_container)
        saved_scroll_area.setWidgetResizable(True)
        self._saved_canvases_loaders_frame = QWidget()
        self._saved_canvases_loaders_layout = QHBoxLayout(self._saved_canvases_loaders_frame)
        self._saved_canvases_loaders_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        saved_scroll_area.setWidget(self._saved_canvases_loaders_frame)
        saved_scroll_area.setFixedHeight(38)
        saved_container_layout.addWidget(saved_scroll_area)
        root_layout.addWidget(self._saved_canvases_loaders_container)
        self._saved_canvases_loaders_container.setVisible(False)

        self._bottom_container = QWidget(self)
        bottom_layout = QHBoxLayout(self._bottom_container)
        bottom_layout.setContentsMargins(2, 2, 2, 2)
        root_layout.addWidget(self._bottom_container)

        self._toolbar = QWidget(self._bottom_container)
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._main = MouseButton(self._toolbar, self.select_main)
        self._magnifier = MagnifierButton(self._toolbar, self.select_magnifier)
        self._plus = PlusButton(self._toolbar, self._on_toggle_addable_canvases)
        toolbar_layout.addWidget(self._main)
        toolbar_layout.addWidget(self._magnifier)
        toolbar_layout.addWidget(self._plus)
        bottom_layout.addWidget(self._toolbar)

        self._switcher_container = QWidget(self._bottom_container)
        switcher_layout = QHBoxLayout(self._switcher_container)
        switcher_layout.setContentsMargins(0, 0, 0, 0)
        switcher_scroll_area = QScrollArea(self._switcher_container)
        switcher_scroll_area.setWidgetResizable(True)
        self._switcher_frame = QWidget()
        self._switcher_layout = QHBoxLayout(self._switcher_frame)
        self._switcher_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        switcher_scroll_area.setWidget(self._switcher_frame)
        self._delete_canvas_button = CrossButton(self._switcher_container, self.delete_canvas)
        switcher_layout.addWidget(switcher_scroll_area, 1)
        switcher_layout.addWidget(self._delete_canvas_button)
        bottom_layout.addWidget(self._switcher_container, 1)

        self._update_toolbar()
        self._update_switcher_visibility()

    def _build_canvas(
        self,
        parent: QWidget,
        canvas_viewer: "CanvasViewerWithTrees",
        canvas_viewer_mode: ViewerMode,
        nodes: Dict[int, TreeNode],
        highest_managed_dependencies: List[Tuple[TreeNode, TreeNode]],
    ) -> ViewableCanvasWithTrees:
        return ViewableCanvasWithTrees(
            parent,
            canvas_viewer,
            canvas_viewer_mode,
            nodes=nodes,
            highest_managed_dependencies=highest_managed_dependencies,
        )

    def _on_toggle_addable_canvases(self) -> None:
        self._tab_visible = not self._tab_visible
        self._saved_canvases_loaders_container.setVisible(self._tab_visible)

    def _on_saved_canvas_loader_clicked(self, index: int) -> None:
        canvas_data = self._saved_canvases[index]
        canvas_id = self.add_canvas(self._build_canvas)

        self.get_canvas(canvas_id).deserialize(canvas_data)
        self._on_toggle_addable_canvases()

    def _update_toolbar(self) -> None:
        self._main.set_selected(self._selected_option == ViewerMode.MAIN)
        self._magnifier.set_selected(self._selected_option == ViewerMode.ZOOM)

    def _update_switcher_visibility(self) -> None:
        self._switcher_container.setVisible(len(self._canvases) > 1)

    def _update_saved_canvases_loaders(self) -> None:
        for button in self._saved_canvases_loaders_buttons:
            self._saved_canvases_loaders_layout.removeWidget(button)
            button.deleteLater()

        self._saved_canvases_loaders_buttons.clear()

        for index in range(len(self._saved_canvases)):
            button = QPushButton(str(index), self._saved_canvases_loaders_frame)
            button.clicked.connect(lambda _checked=False, index=index: self._on_saved_canvas_loader_clicked(index))
            self._saved_canvases_loaders_layout.addWidget(button)
            self._saved_canvases_loaders_buttons.append(button)

    def get_canvas(self, canvas_id: str | None = None) -> ViewableCanvasWithTrees:
        if not canvas_id and self._active_canvas_id:
            return self._canvases[self._active_canvas_id]

        if not canvas_id:
            raise ValueError("No active canvas.")

        try:
            return self._canvases[canvas_id]
        except KeyError as error:
            raise KeyError(f"No Canvas id '{canvas_id}'.") from error

    def add_canvas(
        self,
        canvas_builder: Callable[
            [QWidget, "CanvasViewerWithTrees", ViewerMode, Dict[int, TreeNode], List[Tuple[TreeNode, TreeNode]]],
            ViewableCanvasWithTrees,
        ],
    ) -> str:
        self._canvas_id_counter += 1
        canvas_id = str(self._canvas_id_counter)
        new_canvas = canvas_builder(
            self._canvas_container, self, self._selected_option, self._nodes, self._highest_managed_dependencies
        )
        self._canvases[canvas_id] = new_canvas
        self._canvas_container.addWidget(new_canvas)

        selector_button = QPushButton(canvas_id, self._switcher_frame)
        selector_button.clicked.connect(lambda: self.show_canvas(canvas_id))
        self._canvas_selectors[canvas_id] = selector_button
        self._switcher_layout.addWidget(selector_button)
        self._update_switcher_visibility()
        self.show_canvas(canvas_id)
        return canvas_id

    def delete_canvas(self, canvas_id: str | None = None) -> None:
        if canvas_id is None:
            canvas_id = self._active_canvas_id

        if canvas_id is None or len(self._canvases) <= 1 or canvas_id not in self._canvases:
            return

        canvas = self._canvases.pop(canvas_id)
        self._canvas_container.removeWidget(canvas)
        canvas.deleteLater()
        selector = self._canvas_selectors.pop(canvas_id)
        self._switcher_layout.removeWidget(selector)
        selector.deleteLater()
        self._update_switcher_visibility()

        if self._active_canvas_id == canvas_id:
            self._active_canvas_id = None
            self.show_canvas(next(iter(self._canvases)))

    def delete_all_canvases(self) -> None:
        for canvas_id in list(self._canvases.keys()):
            self.delete_canvas(canvas_id)

        self._canvas_id_counter = 0

    def show_canvas(self, canvas_id: str) -> None:
        if canvas_id in self._canvases:
            self._canvas_container.setCurrentWidget(self._canvases[canvas_id])
            self._active_canvas_id = canvas_id
            self._canvases[canvas_id].set_viewer_mode(self._selected_option)

    def select_main(self) -> None:
        self._selected_option = ViewerMode.MAIN

        if self._active_canvas_id:
            self.get_canvas(self._active_canvas_id).set_viewer_mode(self._selected_option)

        self._update_toolbar()

    def select_magnifier(self) -> None:
        self._selected_option = ViewerMode.ZOOM

        if self._active_canvas_id:
            self.get_canvas(self._active_canvas_id).set_viewer_mode(self._selected_option)

        self._update_toolbar()

    def serialize(self) -> Dict[str, Any]:
        return {
            "nodes": {node_id: node.serialize() for node_id, node in self._nodes.items()},
            "highest_managed_dependencies": [
                (node1.id, node2.id) for node1, node2 in self._highest_managed_dependencies
            ],
            "canvases": [canvas.serialize() for canvas in self._canvases.values()],
        }

    def deserialize(self, data: Dict[str, Any]) -> None:
        self.delete_all_canvases()
        self._nodes.clear()
        self._highest_managed_dependencies.clear()
        self._saved_canvases = list(data["canvases"])

        for node_id in data["nodes"].keys():
            node = TreeNode(int(node_id))
            self._nodes[int(node_id)] = node

        for node in self._nodes.values():
            node.deserialize(data["nodes"][str(node.id)], self._nodes)

        for node1_id, node2_id in data["highest_managed_dependencies"]:
            self._highest_managed_dependencies.append((self._nodes[node1_id], self._nodes[node2_id]))

        canvas_id = self.add_canvas(self._build_canvas)

        self.get_canvas(canvas_id).build_initial()
        self._update_saved_canvases_loaders()

    def build_initial(self, graph: nx.MultiDiGraph) -> None:
        self.delete_all_canvases()
        self._nodes.clear()
        self._highest_managed_dependencies.clear()
        nodes_to_ids: Dict[Any, int] = {}

        for node in graph.nodes:
            node_id = len(self._nodes)
            nodes_to_ids[node] = node_id
            self._nodes[node_id] = TreeNode(node_id)
            self._nodes[node_id].metadata.update({"label": node.get_label(), "fill": "cyan"})

        seen_edges: Set[Tuple[int, int]] = set()
        dependency_edges: List[Tuple[int, int]] = []

        for source, destination, data in graph.edges(data=True):
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

            current_source_node: TreeNode | None = self._nodes[source_node_id]
            current_destination_node: TreeNode | None = self._nodes[destination_node_id]

            while current_source_node is not None and source_height > destination_height:
                current_source_node = current_source_node.higher_order_main_connection
                source_height -= 1

            while current_destination_node is not None and destination_height > source_height:
                current_destination_node = current_destination_node.higher_order_main_connection
                destination_height -= 1

            while (
                current_source_node is not None
                and current_destination_node is not None
                and current_source_node.id != current_destination_node.id
            ):
                current_source_node = current_source_node.higher_order_main_connection
                current_destination_node = current_destination_node.higher_order_main_connection

            if current_source_node is not None and current_destination_node is not None:
                self._nodes[current_source_node.id].managed_dependencies.append(
                    (self._nodes[source_node_id], self._nodes[destination_node_id])
                )
            else:
                self._highest_managed_dependencies.append(
                    (self._nodes[source_node_id], self._nodes[destination_node_id])
                )

        canvas_id = self.add_canvas(self._build_canvas)

        self.get_canvas(canvas_id).build_initial()
