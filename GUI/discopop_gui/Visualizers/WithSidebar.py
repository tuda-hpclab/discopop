# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import json
from typing import Any, Dict, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_gui.Types.FrameT import FrameT
from discopop_gui.Visualizers.Base import Base
from discopop_gui.Enums.FrameType import FrameType
from discopop_gui.ClassMaps.Frames import FramesMap
from discopop_gui.Objects.Frames.Base import Base as FrameBase
from discopop_gui.Objects.Frames.MultiFrame import MultiFrame
from discopop_gui.Objects.Frames.CanvasViewerWithTrees import CanvasViewerWithTrees


class WithSidebar(Base):
    def __init__(self, visualize_on: Optional[QWidget] = None) -> None:
        super().__init__(visualize_on)

        # Draggable split: sidebar | content | filter
        self._pane = QSplitter(Qt.Orientation.Horizontal, self._root)
        root_layout = QVBoxLayout(self._root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._pane)

        # Sidebar
        self._sidebar_container = QWidget(self._pane)
        sidebar_container_layout = QVBoxLayout(self._sidebar_container)
        sidebar_container_layout.setContentsMargins(0, 0, 0, 0)

        self._sidebar_scroll_area = QScrollArea(self._sidebar_container)
        self._sidebar_scroll_area.setWidgetResizable(True)
        self._sidebar = QWidget()
        self._sidebar_layout = QVBoxLayout(self._sidebar)
        self._sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._sidebar_scroll_area.setWidget(self._sidebar)
        sidebar_container_layout.addWidget(self._sidebar_scroll_area)

        # Save Frame button
        self._save_frame_button = QPushButton("Save Frame", self._sidebar_container)
        self._save_frame_button.clicked.connect(self._save_frame)
        sidebar_container_layout.addWidget(self._save_frame_button)

        # Load Frame button
        self._load_frame_button = QPushButton("Load Frame", self._sidebar_container)
        self._load_frame_button.clicked.connect(self._load_frame)
        sidebar_container_layout.addWidget(self._load_frame_button)

        # Content area
        self._frame_container = QStackedWidget(self._pane)

        # Filter area
        self._filter_container = QWidget(self._pane)
        filter_layout = QVBoxLayout(self._filter_container)

        self._filter = QPlainTextEdit(self._filter_container)
        self._filter.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._filter_button = QPushButton("Apply Filter", self._filter_container)
        self._filter_button.clicked.connect(self._filter_button_click)
        filter_layout.addWidget(self._filter)
        filter_layout.addWidget(self._filter_button)
        self._filter_callback: Callable[[str], None] | None = None

        # Add all parts to the Pane
        self._pane.addWidget(self._sidebar_container)
        self._pane.addWidget(self._frame_container)
        self._pane.addWidget(self._filter_container)
        self._pane.setMinimumWidth(630)
        self._pane.setSizes([220, 300, 250])
        self._pane.setStretchFactor(0, 0)
        self._pane.setStretchFactor(1, 1)
        self._pane.setStretchFactor(2, 0)

        self._frame_selectors: Dict[int, QPushButton] = {}

    def _rebuild_selector_layout(self) -> None:
        self._sidebar_layout.invalidate()

    def _save_frame(self) -> None:
        data = self.serialize_current_frame()

        if data is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self._root,
            "Save Frame",
            "",
            "JSON files (*.json);;All files (*)"
        )

        if not file_path:
            return

        with open(file_path, "w", encoding = "utf-8") as file:
            json.dump(data, file, indent = 4)

    def _load_frame(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self._root,
            "Load Frame",
            "",
            "JSON files (*.json);;All files (*)"
        )

        if not file_path:
            return

        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            
            match FrameType(data["type"]):
                case FrameType.CANVAS_VIEWER_WITH_TREES:
                    canvas_frame_with_trees = self.create_frame(data["frame_name"], CanvasViewerWithTrees)
                    canvas_frame_with_trees.deserialize(data["data"])
                case FrameType.MULTI_FRAME:
                    multi_frame = self.create_frame(data["frame_name"], MultiFrame)
                    multi_frame.deserialize(data["data"])
                case _:
                    frame = self.create_frame(data["frame_name"], FrameBase)
                    frame.deserialize(data["data"])

    def _filter_button_click(self) -> None:
        if self._filter_callback is not None:
            filter_text = self._filter.toPlainText().rstrip()
            self._filter_callback(filter_text)

    def show_frame(self, frame_id: int) -> None:
        frame = self.get_frame(frame_id)
        self._frame_container.setCurrentWidget(frame)
        self._current_frame_id = frame_id

    def create_frame(self, name: str, frame_builder: Callable[[QWidget], FrameT]) -> FrameT:
        frame = frame_builder(self._frame_container)
        frame_id = self._frame_id_counter
        self._frames[frame_id] = frame
        self._frame_names[frame_id] = name
        self._frame_id_counter += 1
        self._frame_container.addWidget(frame)

        def selector_click() -> None:
            self.show_frame(frame_id)

        frame_selector = QPushButton(name, self._sidebar)
        frame_selector.clicked.connect(selector_click)

        self._frame_selectors[frame_id] = frame_selector
        self._sidebar_layout.insertWidget(len(self._frame_selectors) - 1, frame_selector)

        if self._current_frame_id is None:
            self.show_frame(frame_id)
        else:
            self.show_frame(self._current_frame_id)

        return frame

    def get_frame_selector(self, frame_id: int) -> QPushButton:
        try:
            return self._frame_selectors[frame_id]
        except KeyError as e:
            raise KeyError(f"No selector button for frame '{frame_id}'.") from e

    def delete_frame(self, frame_id: int) -> None:
        frame = self.get_frame(frame_id)
        self._frame_container.removeWidget(frame)
        super().delete_frame(frame_id)

        selector = self.get_frame_selector(frame_id)
        self._sidebar_layout.removeWidget(selector)
        selector.deleteLater()
        del self._frame_selectors[frame_id]
        self._rebuild_selector_layout()

    def set_filter_callback(self, callback: Callable[[str], None]) -> None:
        self._filter_callback = callback

    def set_filter_text(self, text: str) -> None:
        self._filter.setPlainText(text)

    def clear(self) -> None:
        for frame in self._frames.values():
            self._frame_container.removeWidget(frame)

        super().clear()

        for selector in self._frame_selectors.values():
            self._sidebar_layout.removeWidget(selector)
            selector.deleteLater()

        self._frame_selectors.clear()
        self._filter.clear()

    def serialize_current_frame(self) -> Dict[str, Any] | None:
        if self._current_frame_id is None:
            return None

        frame = self._frames[self._current_frame_id]

        return {
            "frame_name": self._frame_names[self._current_frame_id],
            "type": FramesMap[frame.__class__.__name__].value,
            "data": frame.serialize(),
        }
