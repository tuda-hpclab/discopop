# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import tkinter as tk
from typing import Any, Generic, Callable, Dict, cast, get_args

from discopop_gui.Objects.Frames.Base import Base
from discopop_gui.Types.ViewableCanvasT import ViewableCanvasT
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Mouse import Mouse as MouseButton
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Magnifier import Magnifier as MagnifierButton
from discopop_gui.Objects.Canvases.RoundedSquareButtons.Cross import Cross as CrossButton
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.ClassMaps.ViewableCanvases import ViewableCanvasesMap
from discopop_gui.Enums.ViewableCanvasTypes import ViewableCanvasTypes
from discopop_gui.Objects.Canvases.Viewables.Base import Base as ViewableCanvasBase
from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees

class CanvasViewer(Base, Generic[ViewableCanvasT]):
    def __init__(self, parent: tk.Misc, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent, *args, **kwargs)

        self._selected_option: ViewerMode = ViewerMode.MAIN
        self._canvases : Dict[str, ViewableCanvasT] = {}
        self._canvas_selectors : Dict[str, tk.Button] = {}
        self._active_canvas_id : str | None = None
        self._canvas_id_counter : int = 0

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self._canvas_container = tk.Frame(self)
        self._canvas_container.grid(row = 0, column = 0, sticky="nsew")
        self._canvas_container.grid_rowconfigure(0, weight = 1)
        self._canvas_container.grid_columnconfigure(0, weight = 1)

        self._bottom_container = tk.Frame(self)
        self._bottom_container.grid(row=1, column=0, sticky="ew")
        
        self._bottom_container.grid_rowconfigure(0, weight=1)
        self._bottom_container.grid_columnconfigure(0, weight=1, uniform="bottom_split") 
        self._bottom_container.grid_columnconfigure(1, weight=1, uniform="bottom_split")

        self._toolbar = tk.Frame(self._bottom_container)
        self._toolbar.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        self._main = MouseButton(self._toolbar, command=self.select_main)
        self._magnifier = MagnifierButton(self._toolbar, command=self.select_magnifier)
        
        self._main.grid(row=0, column=0, padx=4, pady=4)
        self._magnifier.grid(row=0, column=1, padx=4, pady=4)

        self._switcher_container = tk.Frame(self._bottom_container)
        self._switcher_container.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
        self._switcher_container.grid_rowconfigure(0, weight=1)
        self._switcher_container.grid_columnconfigure(0, weight=1)

        self._switcher_canvas = tk.Canvas(self._switcher_container, highlightthickness=0, height=50)
        self._switcher_scrollbar = tk.Scrollbar(self._switcher_container, orient="horizontal", command=self._switcher_canvas.xview)
        self._delete_canvas_button = CrossButton(self._switcher_container, command = self.delete_canvas)

        self._switcher_canvas.grid(
            row = 0,
            column = 0,
            sticky = "nsew",
        )

        self._switcher_scrollbar.grid(
            row = 1,
            column = 0,
            sticky = "nsew",
        )

        self._delete_canvas_button.grid(
            row = 0,
            column = 1,
            rowspan = 2,
            padx = (4, 0),
            pady = 2,
            sticky = "nsew",
        )

        self._switcher_frame = tk.Frame(self._switcher_canvas)
        self._switcher_frame.grid_rowconfigure(0, weight=1)

        self._switcher_window = self._switcher_canvas.create_window((0, 0), window=self._switcher_frame, anchor="nw")
        self._switcher_canvas.configure(xscrollcommand=self._switcher_scrollbar.set)

        self._switcher_frame.bind("<Configure>", self._switcher_frame_configure)
        self._switcher_canvas.bind("<Configure>", self._switcher_canvas_configure)

        self._update_toolbar()
        self._update_switcher_visibility()

    def _switcher_frame_configure(self, _: tk.Event[tk.Widget]) -> None:
        self._switcher_canvas.configure(scrollregion = self._switcher_canvas.bbox("all"))

    def _switcher_canvas_configure(self, event: tk.Event[tk.Widget]) -> None:
        self._switcher_canvas.itemconfigure(self._switcher_window, height = event.height)

    def _update_toolbar(self) -> None:
        self._main.set_selected(self._selected_option == ViewerMode.MAIN)
        self._magnifier.set_selected(self._selected_option == ViewerMode.ZOOM)

    def _update_switcher_visibility(self) -> None:
        if len(self._canvases) <= 1:
            self._switcher_container.grid_remove()
        else:
            self._switcher_container.grid(
                row = 0,
                column = 1,
                sticky = "nsew",
                padx = 2,
                pady = 2,
            )

    def get_generic_type_as_string(self) -> str:
        return cast(str, get_args(cast(Any, self).__orig_class__)[0].__name__)

    def add_canvas(self, canvas_builder: Callable[[tk.Frame, "CanvasViewer[ViewableCanvasT]", ViewerMode], ViewableCanvasT]) -> str:
        self._canvas_id_counter += 1
        canvas_id = str(self._canvas_id_counter)

        new_canvas = canvas_builder(self._canvas_container, self, self._selected_option)
        self._canvases[canvas_id] = new_canvas
        new_canvas.grid(row=0, column=0, sticky="nsew")

        selector_button = tk.Button(
            self._switcher_frame, 
            text = canvas_id, 
            command = lambda : self.show_canvas(canvas_id)
        )

        self._canvas_selectors[canvas_id] = selector_button
        selector_button.grid(row=0, column=len(self._canvas_selectors) - 1, sticky="ns", padx=5, pady=2)
        self._update_switcher_visibility()
        self.show_canvas(canvas_id)

        return canvas_id

    def delete_canvas(self, canvas_id: str | None = None) -> None:
        if canvas_id is None:
            canvas_id = self._active_canvas_id

        if canvas_id is None:
            return

        if len(self._canvases) <= 1:
            return

        if canvas_id not in self._canvases:
            return

        self._canvases[canvas_id].destroy()
        del self._canvases[canvas_id]
        
        self._canvas_selectors[canvas_id].destroy()
        del self._canvas_selectors[canvas_id]

        self._update_switcher_visibility()

        for column_index, button_id in enumerate(self._canvas_selectors):
            self._canvas_selectors[button_id].grid_configure(column=column_index)

        if self._active_canvas_id == canvas_id:
            self._active_canvas_id = None

            if self._canvases:
                self.show_canvas(next(iter(self._canvases)))

    def show_canvas(self, canvas_id: str) -> None:
        if canvas_id in self._canvases:
            tk.Widget.lift(self._canvases[canvas_id])
            self._active_canvas_id = canvas_id
            self._canvases[canvas_id].set_viewer_mode(self._selected_option)

    def get_canvas(self, canvas_id: str | None = None) -> ViewableCanvasT:
        if not canvas_id and self._active_canvas_id:
            return self._canvases[self._active_canvas_id]
        
        if not canvas_id:
            raise ValueError("No active canvas.")
        
        try:
            return self._canvases[canvas_id]
        except KeyError as error:
            raise KeyError(f"No Canvas id '{canvas_id}'.") from error

    def select_main(self) -> None:
        self._selected_option = ViewerMode.MAIN
        active_canvas_id = self._active_canvas_id

        if active_canvas_id:
            self.get_canvas(active_canvas_id).set_viewer_mode(self._selected_option)

        self._update_toolbar()

    def select_magnifier(self) -> None:
        self._selected_option = ViewerMode.ZOOM
        active_canvas_id = self._active_canvas_id

        if active_canvas_id:
            self.get_canvas(active_canvas_id).set_viewer_mode(self._selected_option)

        self._update_toolbar()

    def serialize(self) -> Dict[str, Any]:
        return {
            "canvases" : {canvas_id : {"type" : ViewableCanvasesMap[canvas.__class__.__name__].value, "data" : canvas.serialize()} for canvas_id, canvas in self._canvases.items() if canvas.get_serializable()}
        }

    def deserialize(self, data: Dict[str, Any]) -> None:
        for canvas_data in data["canvases"].values():
            canvas_type = ViewableCanvasTypes(canvas_data["type"])

            match canvas_type:
                case ViewableCanvasTypes.WITH_TREES:
                    def canvas_builder_with_trees(
                        parent: tk.Frame,
                        canvas_viewer: CanvasViewer[ViewableCanvasWithTrees],
                        canvas_viewer_mode: ViewerMode
                    ) -> ViewableCanvasWithTrees:
                        return ViewableCanvasWithTrees(
                            parent,
                            canvas_viewer,
                            canvas_viewer_mode,
                            bg="white"
                        )

                    canvas = self.get_canvas(
                        self.add_canvas(
                            cast(
                                Callable[
                                    [tk.Frame, CanvasViewer[ViewableCanvasT], ViewerMode],
                                    ViewableCanvasT
                                ],
                                canvas_builder_with_trees
                            )
                        )
                    )

                    canvas.deserialize(canvas_data["data"])
                case _:
                    def canvas_builder_base(
                        parent: tk.Frame,
                        _: CanvasViewer[ViewableCanvasBase],
                        canvas_viewer_mode: ViewerMode
                    ) -> ViewableCanvasBase:
                        return ViewableCanvasBase(
                            parent,
                            canvas_viewer_mode,
                            bg="white"
                        )

                    canvas = self.get_canvas(
                        self.add_canvas(
                            cast(
                                Callable[
                                    [tk.Frame, CanvasViewer[ViewableCanvasT], ViewerMode],
                                    ViewableCanvasT
                                ],
                                canvas_builder_base
                            )
                        )
                    )

                    canvas.deserialize(canvas_data["data"])
