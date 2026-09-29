# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import tkinter as tk
from typing import Any, Dict

from discopop_gui.Constants import TREE_NODES_SPACING
from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.Objects.CanvasItems.Popup import Popup


class Base(tk.Canvas):
    def __init__(self, parent: tk.Misc, viewer_mode: ViewerMode, serializable : bool = True, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent, *args, **kwargs)

        self._viewer_mode = viewer_mode
        self._serializable = serializable

        self._original_coordinates : dict[int, tuple[float, ...]] = {}
        self._transform_scale : float = 1
        self._transform_x : float = 0.0
        self._transform_y : float = 0.0

        self._drag_start_x : float | None = None
        self._drag_start_y : float | None = None
        self._last_drag_x : float | None = None
        self._last_drag_y : float | None = None
        self._drag_rectangle_id : int | None = None

        self._popup = Popup(self)
        self._popup_hide_threshold : float = 50.0

        self.bind("<ButtonPress-1>", self._left_press)
        self.bind("<B1-Motion>", self._left_drag)
        self.bind("<ButtonRelease-1>", self._left_release)

        self.bind("<ButtonPress-3>", self._right_press)
        self.bind("<B3-Motion>", self._right_drag)
        self.bind("<ButtonRelease-3>", self._right_release)

        self.bind("<Motion>", self._check_popup_distance)

    def _check_popup_distance(self, event: tk.Event) -> None:
        if self._popup.get_visible() == False:
            return

        bbox = self._popup.get_last_bbox()
        x1, y1, x2, y2 = bbox
        cx = self.canvasx(event.x)
        cy = self.canvasy(event.y)
        threshold = self._popup_hide_threshold

        if ((x1 - threshold) <= cx <= (x2 + threshold)) and ((y1 - threshold) <= cy <= (y2 + threshold)):
            return
        
        self._popup.hide()
        
    def _left_press(self, event: tk.Event[tk.Canvas]) -> None:
        self._start_drag(event, button=1)

    def _left_drag(self, event: tk.Event[tk.Canvas]) -> None:
        if self._viewer_mode == ViewerMode.ZOOM:
            self._update_zoom_rectangle(event, outline="blue")

    def _left_release(self, event: tk.Event[tk.Canvas]) -> None:
        self._finish_drag(event, button=1)

    def _right_press(self, event: tk.Event[tk.Canvas]) -> None:
        self._start_drag(event, button=3)

    def _right_drag(self, event: tk.Event[tk.Canvas]) -> None:
        if self._viewer_mode == ViewerMode.MAIN:
            self._update_pan(event)
        elif self._viewer_mode == ViewerMode.ZOOM:
            self._update_zoom_rectangle(event, outline="red")

    def _right_release(self, event: tk.Event[tk.Canvas]) -> None:
        self._finish_drag(event, button=3)

    def _start_drag(self, event: tk.Event[tk.Canvas], button: int) -> None:
        self._drag_start_x = self.canvasx(event.x)
        self._drag_start_y = self.canvasy(event.y)
        assert self._drag_start_x is not None
        assert self._drag_start_y is not None

        if self._viewer_mode == ViewerMode.MAIN:
            if button == 3:
                self._last_drag_x = self._drag_start_x
                self._last_drag_y = self._drag_start_y

            return

        if self._drag_rectangle_id is not None:
            super().delete(self._drag_rectangle_id)

        self._drag_rectangle_id = super().create_rectangle(
            self._drag_start_x,
            self._drag_start_y,
            self._drag_start_x,
            self._drag_start_y,
            outline="blue" if button == 1 else "red",
            dash=(4, 2),
        )

    def _update_pan(self, event: tk.Event[tk.Canvas]) -> None:
        current_x = self.canvasx(event.x)
        current_y = self.canvasy(event.y)

        if self._last_drag_x is None or self._last_drag_y is None:
            self._last_drag_x = current_x
            self._last_drag_y = current_y
            return

        dx = current_x - self._last_drag_x
        dy = current_y - self._last_drag_y

        self._transform_x += dx
        self._transform_y += dy

        self._last_drag_x = current_x
        self._last_drag_y = current_y

        self._apply_transform()

    def _update_zoom_rectangle(self, event: tk.Event[tk.Canvas], outline: str) -> None:
        if self._drag_start_x is None or self._drag_start_y is None or self._drag_rectangle_id is None:
            return

        current_x = self.canvasx(event.x)
        current_y = self.canvasy(event.y)

        self.itemconfig(self._drag_rectangle_id, outline=outline)
        self.coords(
            self._drag_rectangle_id,
            self._drag_start_x,
            self._drag_start_y,
            current_x,
            current_y,
        )

    def _finish_drag(self, event: tk.Event[tk.Canvas], button: int) -> None:
        if (
            self._viewer_mode == ViewerMode.MAIN
            or self._drag_start_x is None
            or self._drag_start_y is None
            or self._drag_rectangle_id is None
        ):
            self._reset_drag_state()
            return

        end_x = self.canvasx(event.x)
        end_y = self.canvasy(event.y)

        x1 = min(self._drag_start_x, end_x)
        y1 = min(self._drag_start_y, end_y)
        x2 = max(self._drag_start_x, end_x)
        y2 = max(self._drag_start_y, end_y)

        if ((x2 - x1) > 5) and ((y2 - y1) > 5):
            if button == 1:
                self._left_drag_area_selected(x1, y1, x2, y2)
            elif button == 3:
                self._right_drag_area_selected(x1, y1, x2, y2)

        self._reset_drag_state()

    def _reset_drag_state(self) -> None:
        if self._drag_rectangle_id is not None:
            super().delete(self._drag_rectangle_id)

        self._drag_start_x = None
        self._drag_start_y = None
        self._last_drag_x = None
        self._last_drag_y = None
        self._drag_rectangle_id = None

    def _left_drag_area_selected(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> None:
        self._zoom_in(x1, y1, x2, y2)

    def _right_drag_area_selected(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> None:
        self._zoom_out(x1, y1, x2, y2)

    def _apply_transform_to_item(self, item_id: int) -> None:
        coordinates = self._original_coordinates[item_id]
        new_coords = []

        for i in range(0, len(coordinates), 2):
            x = (coordinates[i] * self._transform_scale) + self._transform_x
            y = (coordinates[i + 1] * self._transform_scale) + self._transform_y
            new_coords.extend([x, y])

        self.coords(item_id, *new_coords)

    def _apply_transform(self) -> None:
        for item_id in self._original_coordinates.keys():
            self._apply_transform_to_item(item_id)

    def _zoom_in(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> None:
        canvas_width = self.winfo_width()
        canvas_height = self.winfo_height()

        if canvas_width <= 1:
            canvas_width = int(self.cget("width"))

        if canvas_height <= 1:
            canvas_height = int(self.cget("height"))

        selected_width = x2 - x1
        selected_height = y2 - y1

        if selected_width <= 0 or selected_height <= 0:
            return

        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        canvas_ratio = canvas_width / canvas_height
        selected_ratio = selected_width / selected_height
        scale_factor = 1.0

        if selected_ratio > canvas_ratio:
            scale_factor = canvas_width / selected_width
        else:
            scale_factor = canvas_height / selected_height

        self._transform_scale *= scale_factor
        self._transform_x = (scale_factor * (self._transform_x - center_x)) + center_x
        self._transform_y = (scale_factor * (self._transform_y - center_y)) + center_y
        self._apply_transform()

    def _zoom_out(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> None:
        canvas_width = self.winfo_width()
        canvas_height = self.winfo_height()

        if canvas_width <= 1:
            canvas_width = int(self.cget("width"))
        if canvas_height <= 1:
            canvas_height = int(self.cget("height"))

        selected_width = x2 - x1
        selected_height = y2 - y1

        if selected_width <= 0 or selected_height <= 0:
            return

        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        canvas_area = canvas_width * canvas_height
        selected_area = selected_width * selected_height

        scale_factor = 1 - (selected_area / canvas_area)
        scale_factor = max(0.3, min(1.0, scale_factor))

        self._transform_scale *= scale_factor
        self._transform_x = (scale_factor * (self._transform_x - center_x)) + center_x
        self._transform_y = (scale_factor * (self._transform_y - center_y)) + center_y
        self._apply_transform()

    def _store_original_coordinates(self, item_id: int) -> None:
        self._original_coordinates[item_id] = tuple(self.coords(item_id))

    def get_viewer_mode(self) -> ViewerMode:
        return self._viewer_mode

    def get_serializable(self) -> bool:
        return self._serializable
    
    def coords_unscaled(self, item_id: int, *coords: float) -> None:
        self._original_coordinates[item_id] = tuple(coords)
        self._apply_transform_to_item(item_id)

    def set_viewer_mode(self, viewer_mode: ViewerMode) -> None:
        self._reset_drag_state()
        self._viewer_mode = viewer_mode

    def create_oval(self, *args: Any, **kwargs: Any) -> int:
        item_id = super().create_oval(*args, **kwargs)
        self._store_original_coordinates(item_id)
        self._apply_transform_to_item(item_id)
        return item_id

    def create_line(self, *args: Any, **kwargs: Any) -> int:
        item_id = super().create_line(*args, **kwargs)
        self._store_original_coordinates(item_id)
        self._apply_transform_to_item(item_id)
        return item_id

    def create_text(self, *args: Any, **kwargs: Any) -> int:
        item_id = super().create_text(*args, **kwargs)
        self._store_original_coordinates(item_id)
        self._apply_transform_to_item(item_id)
        return item_id

    def create_rectangle(self, *args: Any, **kwargs: Any) -> int:
        item_id = super().create_rectangle(*args, **kwargs)
        self._store_original_coordinates(item_id)
        self._apply_transform_to_item(item_id)
        return item_id

    def create_polygon(self, *args: Any, **kwargs: Any) -> int:
        item_id = super().create_polygon(*args, **kwargs)
        self._store_original_coordinates(item_id)
        self._apply_transform_to_item(item_id)
        return item_id
    
    def clone_item_to_canvas(self, canvas: "Base", item_id: int,) -> int:
        item_type = self.type(item_id)

        coords = self._original_coordinates.get(item_id, tuple(self.coords(item_id)))

        options = {}

        config = self.itemconfigure(item_id)

        if not config:
            raise ValueError(f"Invalid canvas item_id: {item_id}")

        for option in config:
            try:
                options[option] = self.itemcget(item_id, option)
            except tk.TclError:
                pass

        match item_type:
            case "oval":
                return canvas.create_oval(*coords, **options)

            case "rectangle":
                return canvas.create_rectangle(*coords, **options)

            case "line":
                return canvas.create_line(*coords, **options)

            case "polygon":
                return canvas.create_polygon(*coords, **options)

            case "text":
                return canvas.create_text(*coords, **options)

            case _:
                raise NotImplementedError(
                    f"Canvas item type '{item_type}' is not supported."
                )

    def delete(self, *args: Any) -> None:
        if "all" in args:
            self._original_coordinates.clear()
        else:
            for item in args:
                if isinstance(item, int):
                    self._original_coordinates.pop(item, None)

        super().delete(*args)

    def serialize(self) -> Dict[str, Any]:
        return {}

    def deserialize(self, _ : Dict[str, Any]) -> None:
        pass
