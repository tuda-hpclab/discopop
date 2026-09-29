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


class ScrollableTextWidget(object):
    frame: tk.Frame
    text_container: tk.Text

    def __init__(self, parent_frame: Union[tk.Frame, Tk]):
        self.frame = ttk.Frame(parent_frame)  # type: ignore
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        # create content frame and scroll bars
        self.text_container = tk.Text(self.frame, wrap=tk.NONE)
        self.text_container.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        # create a Scrollbar and associate it with the content frame
        y_scrollbar = ttk.Scrollbar(self.frame, command=self.text_container.yview)
        y_scrollbar.grid(row=0, column=1, sticky="nsew")
        self.text_container["yscrollcommand"] = y_scrollbar.set
        x_scrollbar = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text_container.xview)
        x_scrollbar.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.text_container["xscrollcommand"] = x_scrollbar.set
        self.text_container.config(state=tk.DISABLED)

    def set_text(self, content: str) -> None:
        self.text_container.config(state=tk.NORMAL)
        self.text_container.delete("1.0", tk.END)
        self.text_container.insert("1.0", content)
        self.text_container.update()
        self.text_container.config(state=tk.DISABLED)
