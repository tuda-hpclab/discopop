# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
from typing import Callable, Dict, Optional, Tuple, Literal

class Popup:
    def __init__(self, canvas: tk.Canvas, initial_width: float = 150) -> None:
        self._canvas = canvas
        self._visible = False
        self._min_width : float = initial_width
        self._x : float = 0
        self._y : float = 0
        self._button_height : float = 30

        self._background_id = self._canvas.create_rectangle(
            0.0, 0.0, self._min_width, 0.0 ,
            state = "hidden", 
            fill = "#f2f2f2", 
            outline = "#999999",
            width = 1
        )

        self._callbacks : Dict[str, Callable[[tk.Event], str | None]] = {}
        self._button_items : Dict[str, Tuple[int, int]] = {}
        self._last_bbox : Tuple[float, float, float, float] = (0.0, 0.0, self._min_width, 0.0)

    def _update_layout(self) -> None:
        current_y = self._y + 2 
        min_width = self._min_width

        for _, text_id in self._button_items.values():
            bbox = self._canvas.bbox(text_id)

            if bbox:
                text_width = bbox[2] - bbox[0]

                if text_width + 20 > min_width:
                    min_width = text_width + 20

        for rectangle_id, text_id in self._button_items.values():
            self._canvas.coords(
                rectangle_id,
                self._x + 2,
                current_y,
                self._x + min_width - 2,
                current_y + self._button_height
            )
            
            self._canvas.coords(
                text_id,
                self._x + 10, 
                current_y + self._button_height // 2
            )

            current_y += self._button_height

        current_y += 2

        self._canvas.coords(
            self._background_id,
            self._x,
            self._y,
            self._x + min_width,
            current_y
        )

        self._last_bbox = (
            float(self._x),
            float(self._y),
            float(self._x + min_width),
            float(current_y),
        )

    def get_visible(self) -> bool:
        return self._visible
    
    def get_last_bbox(self) -> tuple[float, float, float, float]:
        return self._last_bbox

    def add_button(self, button_id: str, callback: Callable[[tk.Event], str | None]) -> None:
        self._callbacks[button_id] = callback
        state : Literal["normal", "hidden"] = "normal" if self._visible else "hidden"

        rectangle_id = self._canvas.create_rectangle(
            0.0, 0.0, 0.0, 0.0, 
            state = state, 
            fill = "#ffffff", 
            outline = "#ffffff"
        )
        
        text_id = self._canvas.create_text(
            0.0, 0.0, 
            text = button_id, 
            anchor = "w", 
            state = state, 
            fill = "#000000"
        )

        self._button_items[button_id] = (rectangle_id, text_id)

        def on_click(event: tk.Event) -> str | None:
            if self._visible:
                self.hide()
                return callback(event)
            
            return None

        def on_enter(_ : tk.Event) -> str | None:
            if self._visible:
                self._canvas.itemconfigure(rectangle_id, fill = "#cfe8ff", outline = "#cfe8ff")
            
            return None
                
        def on_exit(_ : tk.Event) -> str | None:
            if self._visible:
                self._canvas.itemconfigure(rectangle_id, fill = "#ffffff", outline = "#ffffff")

            return None

        self._canvas.tag_bind(rectangle_id, "<Button-1>", on_click)
        self._canvas.tag_bind(text_id, "<Button-1>", on_click)
        self._canvas.tag_bind(rectangle_id, "<Enter>", on_enter)
        self._canvas.tag_bind(text_id, "<Enter>", on_enter)
        self._canvas.tag_bind(rectangle_id, "<Leave>", on_exit)
        self._canvas.tag_bind(text_id, "<Leave>", on_exit)

        self._update_layout()

    def remove_button(self, button_id: str) -> None:
        if button_id in self._button_items:
            rectangle_id, text_id = self._button_items[button_id]
            
            self._canvas.delete(rectangle_id)
            self._canvas.delete(text_id)

            del self._button_items[button_id]
            del self._callbacks[button_id]

            self._update_layout()

    def clear_buttons(self) -> None:
        for button_id in list(self._button_items.keys()):
            rectangle_id, text_id = self._button_items[button_id]
            
            self._canvas.delete(rectangle_id)
            self._canvas.delete(text_id)

            del self._button_items[button_id]
            del self._callbacks[button_id]

        self._update_layout()

    def visualize(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        if x is not None:
            self._x = x

        if y is not None:
            self._y = y

        self._update_layout()
        self._visible = True
        self._canvas.itemconfigure(self._background_id, state = "normal")
        self._canvas.tag_raise(self._background_id)

        for rectangle_id, text_id in self._button_items.values():
            self._canvas.itemconfigure(rectangle_id, state = "normal")
            self._canvas.itemconfigure(text_id, state = "normal")
            self._canvas.tag_raise(rectangle_id)
            self._canvas.tag_raise(text_id)

    def hide(self) -> None:
        self._visible = False
        self._canvas.itemconfigure(self._background_id, state = "hidden")
        
        for rectangle_id, text_id in self._button_items.values():
            self._canvas.itemconfigure(rectangle_id, state = "hidden")
            self._canvas.itemconfigure(text_id, state = "hidden")