# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Callable, List
import tkinter as tk
from matplotlib.axes import Axes
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # type: ignore
from matplotlib.figure import Figure

from discopop_gui.Visualizers.Base import Base
from discopop_gui.Objects.Frames.Base import Base as BaseFrame
from discopop_gui.Objects.Frames.MultiFrame import MultiFrame
from discopop_gui.Objects.Frames.CanvasViewer import CanvasViewer
from discopop_gui.Enums.ViewerMode import ViewerMode as CanvasViewerMode
from discopop_gui.Exceptions.VisualizerNotDefined import VisualizerNotDefined
from discopop_gui.Objects.Canvases.Viewables.WithTrees import WithTrees as ViewableCanvasWithTrees


class Plottable:
    def __init__(self, visualizer: Base | None = None) -> None:
        self._visualizer = visualizer

    def plottable(self) -> bool:
        if self._visualizer == None:
            return False

        return True

    def create_frame(self, name: str) -> BaseFrame:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        return self._visualizer.create_frame(name, BaseFrame)

    def create_multi_frame(self, name: str, rows: int, columns: int) -> MultiFrame:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        if rows < 1 or columns < 1:
            raise ValueError("Rows and columns must be >= 1")

        def frame_builder(parent: tk.Misc) -> MultiFrame:
            return MultiFrame(parent)

        frame = self._visualizer.create_frame(name, frame_builder)

        for row in range(rows):
            frame.grid_rowconfigure(row, weight=1)

        for column in range(columns):
            frame.grid_columnconfigure(column, weight=1)

        inner_frames : List[BaseFrame] = []

        for i in range(rows * columns):
            row = i // columns
            column = i % columns

            inner_frame = BaseFrame(frame, borderwidth=1, relief="solid")
            inner_frame.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
            inner_frames.append(inner_frame)

        frame.initialize(inner_frames)
        return frame

    def set_filter_callback(self, callback: Callable[[str], None]) -> None:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        self._visualizer.set_filter_callback(callback)

    def delete_frame(self, frame_id: int) -> None:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        self._visualizer.delete_frame(frame_id)

    def create_plot(self, name: str) -> Axes:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        frame: BaseFrame = self._visualizer.create_frame(name, BaseFrame)
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("Task graph")
        canvas = FigureCanvasTkAgg(figure, master=frame)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(canvas, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        return axes

    def create_plottable_canvas(self, name: str) -> ViewableCanvasWithTrees:
        if self._visualizer is None:
            raise VisualizerNotDefined()
        
        def canvas_builder(parent : tk.Frame, canvas_viewer : CanvasViewer[ViewableCanvasWithTrees], canvas_viewer_mode : CanvasViewerMode) -> ViewableCanvasWithTrees:
            return ViewableCanvasWithTrees(parent, canvas_viewer, canvas_viewer_mode, bg="white")
        
        def frame_builder(parent : tk.Misc) -> CanvasViewer[ViewableCanvasWithTrees]:
            return CanvasViewer[ViewableCanvasWithTrees](parent)

        frame = self._visualizer.create_frame(name, frame_builder)
        canvas = frame.get_canvas(frame.add_canvas(canvas_builder))

        frame.grid_rowconfigure(0, weight = 1)
        frame.grid_columnconfigure(0, weight = 1)

        return canvas

    def create_multi_plot(self, name: str, inner_plot_titles: list[str], rows: int, columns: int) -> list[Axes]:
        frame = self.create_multi_frame(name, rows, columns)
        axeses = []

        for index in range(rows * columns):
            inner_frame = frame.get_from_inner(index)
            figure = Figure()
            axes = figure.add_subplot(111)
            axes.set_title(inner_plot_titles[index])
            canvas = FigureCanvasTkAgg(figure, master = inner_frame)
            canvas.draw()
            canvas.get_tk_widget().grid(row=0, sticky="nsew")
            toolbar = NavigationToolbar2Tk(canvas, pack_toolbar=False)
            toolbar.update()
            toolbar.grid(row = 1)
            inner_frame.grid_rowconfigure(0, weight = 1)
            inner_frame.grid_columnconfigure(0, weight = 1)
            axeses.append(axes)

        return axeses

    def run_visualizer(self) -> None:
        if self._visualizer is not None:
            self._visualizer.run()

    def clear_visualizer(self) -> None:
        if self._visualizer is not None:
            self._visualizer.clear()
