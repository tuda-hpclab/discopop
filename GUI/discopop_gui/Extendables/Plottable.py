# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Callable, Dict, List

from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # type: ignore
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from discopop_gui.Visualizers.Base import Base
from discopop_gui.Objects.Frames.Base import Base as BaseFrame
from discopop_gui.Objects.Frames.MultiFrame import MultiFrame
from discopop_gui.Objects.Frames.CanvasViewerWithTrees import CanvasViewerWithTrees
from discopop_gui.Exceptions.VisualizerNotDefined import VisualizerNotDefined


class Plottable:
    def __init__(self, visualizer: Base | None = None) -> None:
        self._visualizer = visualizer

    def __getstate__(self) -> Dict[str, Any]:
        # The visualizer holds Qt widgets it draws on; a pickled or dumped graph (detection_result_dump.json)
        # must not carry them, the copy is not plottable.
        state = self.__dict__.copy()
        state["_visualizer"] = None
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self.__dict__.setdefault("_visualizer", None)

    def plottable(self) -> bool:
        if self._visualizer is None:
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

        def frame_builder(parent: QWidget) -> MultiFrame:
            return MultiFrame(parent)

        frame = self._visualizer.create_frame(name, frame_builder)

        for row in range(rows):
            frame._layout.setRowStretch(row, 1)

        for column in range(columns):
            frame._layout.setColumnStretch(column, 1)

        inner_frames: List[BaseFrame] = []

        for i in range(rows * columns):
            row = i // columns
            column = i % columns

            inner_frame = frame.create_frame(row, column, lambda parent: BaseFrame(parent))
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
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("Task graph")
        canvas = FigureCanvasQTAgg(figure)
        canvas.draw()
        toolbar = NavigationToolbar2QT(canvas, frame)

        layout.addWidget(canvas, 1)
        layout.addWidget(toolbar)
        return axes

    def create_plottable(self, name: str) -> CanvasViewerWithTrees:
        if self._visualizer is None:
            raise VisualizerNotDefined()

        def frame_builder(parent: QWidget) -> CanvasViewerWithTrees:
            return CanvasViewerWithTrees(parent)

        frame = self._visualizer.create_frame(name, frame_builder)

        return frame

    def create_multi_plot(self, name: str, inner_plot_titles: list[str], rows: int, columns: int) -> list[Axes]:
        frame = self.create_multi_frame(name, rows, columns)
        axeses = []

        for index in range(rows * columns):
            inner_frame = frame.get_from_inner(index)
            layout = QVBoxLayout(inner_frame)
            layout.setContentsMargins(0, 0, 0, 0)

            figure = Figure()
            axes = figure.add_subplot(111)
            axes.set_title(inner_plot_titles[index])
            canvas = FigureCanvasQTAgg(figure)
            canvas.draw()
            toolbar = NavigationToolbar2QT(canvas, inner_frame)

            layout.addWidget(canvas, 1)
            layout.addWidget(toolbar)
            axeses.append(axes)

        return axeses

    def run_visualizer(self) -> None:
        if self._visualizer is not None:
            self._visualizer.run()

    def clear_visualizer(self) -> None:
        if self._visualizer is not None:
            self._visualizer.clear()
