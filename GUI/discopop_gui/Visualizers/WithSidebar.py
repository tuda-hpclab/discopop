# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog
from typing import Any, Dict, Callable, Optional, cast, get_args

from discopop_gui.Types.FrameT import FrameT
from discopop_gui.Visualizers.Base import Base
from discopop_gui.Enums.FrameType import FrameType
from discopop_gui.Enums.ViewableCanvasTypes import ViewableCanvasTypes
from discopop_gui.ClassMaps.Frames import FramesMap
from discopop_gui.ClassMaps.ViewableCanvases import ViewableCanvasesMap
from discopop_gui.Objects.Frames.Base import Base as FrameBase
from discopop_gui.Objects.Frames.MultiFrame import MultiFrame
from discopop_gui.Objects.Frames.CanvasViewer import CanvasViewer
from discopop_gui.Objects.Canvases.Viewables.Base import Base as ViewableCanvasesBase
from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasesWithTrees

class WithSidebar(Base):
    def __init__(self, visualize_on : Optional[tk.Frame] = None) -> None:
        super().__init__(visualize_on)

        self._root.grid_rowconfigure(0, weight=1)
        self._root.grid_columnconfigure(0, weight=1)

        # Draggable split: sidebar | content | filter
        self._pane = tk.PanedWindow(
            self._root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, opaqueresize=False, bg="black"
        )
        self._pane.grid(row=0, column=0, sticky="nsew")

        # Sidebar
        self._sidebar_container = tk.Frame(self._pane)
        self._sidebar_container.grid_rowconfigure(0, weight=1)
        self._sidebar_container.grid_columnconfigure(0, weight=1)

        self._sidebar_canvas = tk.Canvas(self._sidebar_container, highlightthickness=0, width=220)

        self._sidebar_scrollbar = tk.Scrollbar(
            self._sidebar_container, orient="vertical", command=self._sidebar_canvas.yview
        )

        self._sidebar_canvas.grid(row=0, column=0, sticky="nsew")
        self._sidebar_scrollbar.grid(row=0, column=1, sticky="ns")

        self._sidebar = tk.Frame(self._sidebar_canvas)
        self._sidebar.grid_columnconfigure(0, weight=1)

        self._sidebar_window = self._sidebar_canvas.create_window((0, 0), window = self._sidebar, anchor = "nw")

        self._sidebar_canvas.configure(yscrollcommand = self._sidebar_scrollbar.set)

        self._sidebar.bind("<Configure>", self._sidebar_configure)
        self._sidebar_canvas.bind("<Configure>", self._canvas_configure)

        # Save Frame button
        self._save_frame_button = tk.Button(self._sidebar_container, text = "Save Frame", command = self._save_frame)
        self._save_frame_button.grid(row = 1, column = 0, columnspan = 2, sticky = "ew", padx = 5, pady = 2)

        # Load Frame button
        self._load_frame_button = tk.Button(self._sidebar_container, text = "Load Frame", command = self._load_frame)
        self._load_frame_button.grid(row = 2, column = 0, columnspan = 2, sticky = "ew", padx = 5, pady = 2)

        # Content area
        self._frame_container = tk.Frame(self._pane)
        self._frame_container.grid_rowconfigure(0, weight=1)
        self._frame_container.grid_columnconfigure(0, weight=1)

        # Filter area
        self._filter_container = tk.Frame(self._pane)
        self._filter_container.grid_rowconfigure(0, weight=1)
        self._filter_container.grid_columnconfigure(0, weight=1)

        self._filter_scrollbar = tk.Scrollbar(self._filter_container, orient="vertical")

        self._filter = tk.Text(self._filter_container, wrap="word", yscrollcommand=self._filter_scrollbar.set, width=30)

        self._filter_scrollbar.config(command=self._filter.yview)
        self._filter.grid(row=0, column=0, sticky="nsew", padx=5, pady=(5, 2))
        self._filter_scrollbar.grid(row=0, column=1, sticky="ns", pady=(5, 2))

        self._filter_button = tk.Button(self._filter_container, text="Apply Filter", command=self._filter_button_click)

        self._filter_button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(2, 5))
        self._filter_callback: Callable[[str], None] | None = None

        # Add all parts to the Pane
        self._pane.add(self._sidebar_container, minsize=150, width=220, stretch="never")
        self._pane.add(self._frame_container, minsize=300, stretch="always")
        self._pane.add(self._filter_container, minsize=180, width=250, stretch="never")

        self._frame_selectors: Dict[int, tk.Button] = {}

    def _sidebar_configure(self, _: tk.Event[tk.Widget]) -> None:
        self._sidebar_canvas.configure(scrollregion=self._sidebar_canvas.bbox("all"))

    def _canvas_configure(self, event: tk.Event[tk.Widget]) -> None:
        self._sidebar_canvas.itemconfigure(self._sidebar_window, width=event.width)

    def _rebuild_selector_layout(self) -> None:
        for row_index, frame_id in enumerate(self._frame_selectors):
            self._frame_selectors[frame_id].grid_configure(row=row_index)

    def _save_frame(self) -> None:
        data = self.serialize_current_frame()

        if data is None:
            return

        file_path = filedialog.asksaveasfilename(
            parent = self._root,
            title = "Save Frame",
            defaultextension = ".json",
            filetypes = [
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )

        if not file_path:
            return

        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

    def _load_frame(self) -> None:
        file_path = filedialog.askopenfilename(
            parent = self._root,
            title = "Load Frame",
            filetypes = [
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )

        if not file_path:
            return

        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            match FrameType(data["type"]):
                case FrameType.CANVAS_VIEWER:
                    match ViewableCanvasesMap[data["generic_type"]]:
                        case ViewableCanvasTypes.BASE:
                            canvas_frame_with_base = self.create_frame(data["frame_name"], CanvasViewer[ViewableCanvasesBase])
                            canvas_frame_with_base.deserialize(data["data"])
                        case ViewableCanvasTypes.WITH_TREES:
                            canvas_frame_with_trees = self.create_frame(data["frame_name"], CanvasViewer[ViewableCanvasesWithTrees])
                            canvas_frame_with_trees.deserialize(data["data"])
                case FrameType.MULTI_FRAME:
                    multi_frame = self.create_frame(data["frame_name"], MultiFrame)
                    multi_frame.deserialize(data["data"])
                case _:
                    frame = self.create_frame(data["frame_name"], FrameBase)
                    frame.deserialize(data["data"])


    def _filter_button_click(self) -> None:
        if self._filter_callback is not None:
            filter_text = self._filter.get("1.0", tk.END).rstrip()
            self._filter_callback(filter_text)

    def create_frame(self, name: str, frame_builder: Callable[[tk.Misc], FrameT]) -> FrameT:
        frame = frame_builder(self._frame_container)
        frame_id = self._frame_id_counter
        self._frames[frame_id] = frame
        self._frame_names[frame_id] = name
        self._frame_id_counter += 1
        frame.grid(row = 0, column = 0, sticky="nsew")

        def selector_click(frame_name: str = name) -> None:
            self.show_frame(frame_id)

        frame_selector = tk.Button(self._sidebar, text=name, command=selector_click)

        self._frame_selectors[frame_id] = frame_selector

        frame_selector.grid(row=len(self._frame_selectors) - 1, column=0, sticky="ew", padx=5, pady=2)

        if self._current_frame_id is None:
            self.show_frame(frame_id)
        else:
            self.show_frame(self._current_frame_id)

        return frame

    def get_frame_selector(self, frame_id: int) -> tk.Button:
        try:
            return self._frame_selectors[frame_id]
        except KeyError as e:
            raise KeyError(f"No selector button for frame '{frame_id}'.") from e

    def delete_frame(self, frame_id : int) -> None:
        super().delete_frame(frame_id)

        selector = self.get_frame_selector(frame_id)

        selector.destroy()
        del self._frame_selectors[frame_id]

        self._rebuild_selector_layout()

    def set_filter_callback(self, callback: Callable[[str], None]) -> None:
        self._filter_callback = callback

    def set_filter_text(self, text: str) -> None:
        self._filter.delete("1.0", tk.END)
        self._filter.insert("1.0", text)

    def clear(self) -> None:
        super().clear()

        for selector in self._frame_selectors.values():
            selector.destroy()

        self._frame_selectors.clear()
        self._filter.delete("1.0", tk.END)

    def serialize_current_frame(self) -> Dict[str, Any] | None:
        if self._current_frame_id is None:
            return None

        frame = self._frames[self._current_frame_id]
        generic_type = ""

        if isinstance(frame, CanvasViewer):
            generic_type = frame.get_generic_type_as_string()

        return {
            "frame_name": self._frame_names[self._current_frame_id],
            "type" : FramesMap[frame.__class__.__name__].value,
            "data" : frame.serialize(),
            "generic_type" : generic_type
        }

