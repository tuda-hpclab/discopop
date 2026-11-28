# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Callable, Dict, cast

from PySide6.QtWidgets import QGridLayout, QWidget

from discopop_gui.Types.FrameT import FrameT
from discopop_gui.Enums.FrameType import FrameType
from discopop_gui.ClassMaps.Frames import FramesMap
from discopop_gui.Objects.Frames.Base import Base
from discopop_gui.Objects.Frames.CanvasViewerWithTrees import CanvasViewerWithTrees


class MultiFrame(Base):
    def __init__(self, parent: QWidget | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent, *args, **kwargs)
        self._inner_frames: list[Base] = []
        self._layout = QGridLayout(self)

    def initialize(self, inner_frames: list[Base]) -> None:
        self._inner_frames = inner_frames

    def get_from_inner(self, index: int) -> Base:
        return self._inner_frames[index]

    def create_frame(self, row: int, column: int, frame_builder: Callable[[QWidget], FrameT]) -> FrameT:
        frame = frame_builder(self)
        self._layout.addWidget(frame, row, column)
        self._inner_frames.append(frame)
        return frame

    def serialize(self) -> Dict[str, Any]:
        output: Dict[str, Any] = {"inner_frames": []}

        for frame in self._inner_frames:
            layout_index = self._layout.indexOf(frame)

            row, column, _, _ = cast(
                tuple[int, int, int, int],
                self._layout.getItemPosition(layout_index),
            )

            output["inner_frames"].append(
                {
                    "type": FramesMap[frame.__class__.__name__].value,
                    "row": row,
                    "column": column,
                    "data": frame.serialize(),
                }
            )

        return output

    def deserialize(self, data: Dict[str, Any]) -> None:
        for frame in self._inner_frames:
            self._layout.removeWidget(frame)
            frame.deleteLater()

        self._inner_frames = []

        for frame_data in data["inner_frames"]:
            match FrameType(frame_data["type"]):
                case FrameType.CANVAS_VIEWER_WITH_TREES:
                    self.create_frame(
                        int(frame_data["row"]), int(frame_data["column"]), lambda parent: CanvasViewerWithTrees(parent)
                    ).deserialize(frame_data["data"])
                case FrameType.MULTI_FRAME:
                    self.create_frame(
                        int(frame_data["row"]), int(frame_data["column"]), lambda parent: MultiFrame(parent)
                    ).deserialize(frame_data["data"])

                case _:
                    self.create_frame(
                        int(frame_data["row"]), int(frame_data["column"]), lambda parent: Base(parent)
                    ).deserialize(frame_data["data"])
