# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The status line at the bottom of the main window, which every panel writes to."""

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.threads import assert_main_thread

READY = "Ready"


class StatusLine(QLabel):
    """One line of status text with a color; :meth:`set` can fall back to "Ready" after a delay."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(READY, parent)
        self._color = widgets.STATUS_IDLE
        widgets.set_label_color(self, self._color)
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(lambda: self.set(READY))

    def set(self, text: str, color: str = widgets.STATUS_IDLE, *, reset_ms: Optional[int] = None) -> None:
        assert_main_thread()
        self._reset_timer.stop()
        self.setText(text)
        self._color = color
        widgets.set_label_color(self, color)
        if reset_ms is not None:
            self._reset_timer.start(reset_ms)

    @property
    def color(self) -> str:
        return self._color
