# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from tkinter import *
from typing import Optional

import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.gui.widgets.ScrollableFrame import ScrollableFrameWidget
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.discopop_optimizer.gui.widgets.ScrollableText import ScrollableTextWidget


def display_choices_for_model(graph: nx.DiGraph, model: CostModel, window_title: Optional[str] = None) -> None:
    root = Tk()
    if window_title is not None:
        root.configure()
        root.title(window_title)
    # configure window size
    root.geometry("1000x600")
    # configure weights
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)

    # create scrollable frame
    scrollable_frame_widget = ScrollableFrameWidget(root)
    scrollable_frame = scrollable_frame_widget.get_scrollable_frame()
    # configure weights
    scrollable_frame.rowconfigure(0, weight=1)
    scrollable_frame.rowconfigure(1, weight=1)
    scrollable_frame.rowconfigure(2, weight=1)
    scrollable_frame.columnconfigure(0, weight=1)
    scrollable_frame.columnconfigure(1, weight=1)
    scrollable_frame.columnconfigure(2, weight=1)

    rows = []
    # print mathematical function for model
    fn_label = Entry(scrollable_frame, relief=RIDGE, width=len("Function:"))
    fn_label.grid(row=0, column=0, sticky=NSEW)
    fn_label.insert(END, "Function:")
    fn_label.configure(state=DISABLED, disabledforeground="black")
    fn_function_frame = Frame(scrollable_frame)
    fn_function_frame.grid(row=0, column=1, columnspan=2, sticky=NSEW)
    fn_function = ScrollableTextWidget(fn_function_frame)
    fn_function.set_text(str(model.parallelizable_costs + model.sequential_costs))
    fn_function.text_container.config(height=3)

    column_headers = ["Decision", "Device", "Details"]
    # set column headers
    header_cols = []
    for col_idx, header in enumerate(column_headers):
        e = Entry(scrollable_frame, relief=RIDGE, width=len(header))
        e.grid(row=1, column=col_idx, sticky=NSEW)
        e.insert(END, header)
        e.configure(state=DISABLED, disabledforeground="black")
        header_cols.append(e)
    rows.append(header_cols)

    for row_idx, decision in enumerate(model.path_decisions):
        row_idx = row_idx + 2  # account for mathematical function and header row
        # add decision id
        e = Entry(scrollable_frame, relief=RIDGE)
        e.grid(row=row_idx, column=0, sticky=NSEW)
        e.insert(END, str(decision))
        e.configure(state=DISABLED, disabledforeground="black")

        # add device id
        i = Entry(scrollable_frame, relief=RIDGE)
        i.grid(row=row_idx, column=1, sticky=NSEW)
        i.insert(END, str(data_at(graph, decision).device_id))
        i.configure(state=DISABLED, disabledforeground="black")

        # add decision details
        d = Frame(scrollable_frame)
        d.grid(row=row_idx, column=2, sticky=NSEW)
        stw = ScrollableTextWidget(d)
        stw.set_text(str(data_at(graph, decision).suggestion))
        stw.text_container.config(height=10)

    scrollable_frame_widget.finalize(len(model.path_decisions))

    pass
