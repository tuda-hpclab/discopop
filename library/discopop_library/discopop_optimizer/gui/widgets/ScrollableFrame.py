# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import tkinter as tk
from tkinter import Tk, ttk
from typing import Union


class ScrollableFrameWidget(object):
    container: ttk.Frame
    canvas: tk.Canvas
    scrollbar: tk.Scrollbar
    scrollable_frame: tk.Frame  # important

    def __init__(self, parent_frame: Union[tk.Frame, Tk]) -> None:
        self.container = ttk.Frame(parent_frame)
        self.canvas = tk.Canvas(self.container)
        self.scrollbar = ttk.Scrollbar(self.container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)  # type: ignore

        # configure weights
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.canvas.rowconfigure(0, weight=1)
        self.canvas.columnconfigure(0, weight=1)
        self.scrollable_frame.rowconfigure(0, weight=1)
        self.scrollable_frame.columnconfigure(0, weight=1)

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

    def finalize(self, row_count: int, row: int = 0, col: int = 0, rowspan: int = 1, columnspan: int = 1) -> None:
        if rowspan < 1:
            rowspan = 1
        if columnspan < 1:
            columnspan = 1
        self.container.grid(row=row, column=col, columnspan=columnspan, rowspan=rowspan, sticky=tk.NSEW)
        self.canvas.grid(row=0, column=0, sticky=tk.NSEW)
        self.scrollbar.grid(row=0, rowspan=max(row_count, 1), column=1, sticky=tk.NS)

    def get_scrollable_frame(self) -> tk.Frame:
        return self.scrollable_frame
