# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import tkinter as tk
from tkinter import *
from typing import Any, List, Tuple, Optional, Dict, cast, Union

from sympy import Symbol, Expr  # type: ignore

from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.gui.widgets.ScrollableFrame import ScrollableFrameWidget


def query_user_for_symbol_values(
    symbols: List[Symbol],
    suggested_values: Dict[Symbol, Expr],
) -> List[Tuple[Symbol, Optional[float], Optional[float], Optional[float], Optional[FreeSymbolDistribution]]]:
    """Opens a GUI-Table to query values for each given Symbol from the user.
    The queried values are: Specific value, Range start, Range end.
    In every case, either a specific value, or a range must be given.
    In case the optimizer is started in headless mode, the suggested values are used.
    Return: [(symbol, symbol_value, range_start, range_end, distribution)]"""
    query_result: List[
        Tuple[
            Symbol,
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[FreeSymbolDistribution],
        ]
    ] = []
    column_headers = ["Symbol Name", "Symbol Value", "Range Start", "Range End", "Range Relevance"]

    root = Tk()
    parent_frame = Frame(root)

    # configure weights
    parent_frame.rowconfigure(0, weight=1)
    parent_frame.columnconfigure(0, weight=1)
    # create scrollable frame
    scrollable_frame_widget = ScrollableFrameWidget(parent_frame)
    scrollable_frame = scrollable_frame_widget.get_scrollable_frame()

    rows = []
    # set column headers
    header_cols = []
    for col_idx, header in enumerate(column_headers):
        e = Entry(scrollable_frame, relief=RIDGE)
        e.grid(row=0, column=col_idx, sticky=NSEW)
        e.insert(END, header)
        e.configure(state=DISABLED, disabledforeground="black")
        header_cols.append(e)
    rows.append(header_cols)

    # create choice vars for range relevance
    range_relevance_vars: Dict[Symbol, tk.StringVar] = dict()
    for free_symbol in symbols:
        range_relevance_vars[free_symbol] = tk.StringVar()

    # create query Table
    for row_idx, free_symbol in enumerate(symbols):
        row_idx = row_idx + 1  # to account for column headers
        cols = []
        for col_idx, column_name in enumerate(column_headers):
            e = Entry(scrollable_frame, relief=RIDGE)
            e.grid(row=row_idx, column=col_idx, sticky=NSEW)
            if col_idx == 0:
                # symbol name
                e.insert(END, str(free_symbol))
                e.configure(state=DISABLED, disabledforeground="black")
            elif col_idx == 4:
                # range relevance
                choices = ["-->", "<--", "=="]
                range_relevance_vars[free_symbol].set(choices[0])
                option_menu = tk.OptionMenu(e, range_relevance_vars[free_symbol], *choices)
                option_menu.grid(sticky=NSEW)
            else:
                # queried value
                if col_idx == 1 and free_symbol in suggested_values:
                    # insert suggested value, if one exists
                    e.insert(END, str(suggested_values[free_symbol]))
            cols.append(e)
        rows.append(cols)
    root.mainloop()

    def validate() -> bool:
        ret_val = True
        # validate entries
        for row_idx, row in enumerate(rows):
            if row_idx == 0:
                continue
            row_valid = False
            # check if either a specific value or ranges are set
            if len(row[1].get()) != 0:
                # specific value
                row_valid = True
            elif len(row[2].get()) != 0 and len(row[3].get()) != 0:
                # range specified
                row_valid = True
            else:
                # row invalid
                ret_val = False
            # mark row
            if row_valid:
                for col in row[1:]:
                    col.configure(background="grey")
            else:
                for col in row[1:]:
                    col.configure(background="red")
        return ret_val

    def onPress() -> None:
        if not validate():
            return
        # fetch entries
        for row_idx, row in enumerate(rows):
            if row_idx == 0:
                continue
            row_element: List[Any] = []
            for col_idx, col in enumerate(row):
                if col_idx == 0:
                    # append symbol to row_element
                    row_element.append(symbols[row_idx - 1])  # -1 to account for column headers
                elif col_idx == 4:
                    # ignore range relevance, as it is added afterwards
                    pass
                else:
                    field_value = col.get()
                    if len(field_value) == 0:
                        row_element.append(None)
                    else:
                        row_element.append(float(field_value))
            # get enum object from range relevance choice if no specific value has been set in the row
            if row_element[1] is None:
                string_value = range_relevance_vars[row_element[0]].get()
                if string_value == "-->":
                    range_relevance = FreeSymbolDistribution.RIGHT_HEAVY
                elif string_value == "<--":
                    range_relevance = FreeSymbolDistribution.LEFT_HEAVY
                else:
                    range_relevance = FreeSymbolDistribution.UNIFORM
            else:
                range_relevance = None
            row_element.append(range_relevance)

            # create result tuple
            query_result.append(
                cast(
                    Tuple[
                        Symbol,
                        Optional[float],
                        Optional[float],
                        Optional[float],
                        Optional[FreeSymbolDistribution],
                    ],
                    tuple(row_element),
                )
            )

        # close elements on optimizer_frame
        for c in parent_frame.winfo_children():
            c.destroy()

        parent_frame.quit()

    scrollable_frame_widget.finalize(len(symbols), row=0, col=0)
    Button(parent_frame, text="Save", command=lambda: onPress()).grid()
    Button(parent_frame, text="Validate", command=lambda: validate()).grid()
    parent_frame.mainloop()
    return query_result
