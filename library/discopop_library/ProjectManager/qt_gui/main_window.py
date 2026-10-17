# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The main window: the configuration list on the left, the panels as tabs on the right, the status line below.

The window assembles the panels and wires them: which panel reacts to which :class:`ProjectState` event, and the
few callbacks one panel offers another. The panels do not know each other.
"""

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon, QResizeEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QTabWidget, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.panels.report_panel import ReportPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services.project_state import ProjectState

ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")

TAB_EDITOR = "Editor"
TAB_EXECUTE = "Execute"
TAB_REPORT = "Report"
TAB_HOTSPOT = "Hotspot Detection"
TAB_PATTERN_DETECTION = "Pattern Detection"
TAB_PATCH_REPAIR = "Patch Repair"
TAB_AUTOTUNING = "Autotuning"
# the order of the tabs: hotspots are measured before, and feed into, pattern detection and the autotuner; patch
# repair sits between them, a suggestion that does not build is one the tuner can only record as a failure
TAB_ORDER = (TAB_EDITOR, TAB_EXECUTE, TAB_REPORT, TAB_HOTSPOT, TAB_PATTERN_DETECTION, TAB_PATCH_REPAIR, TAB_AUTOTUNING)


class ElidedPathLabel(QLabel):
    """Shows a path, cut from the left with an ellipsis when it does not fit; the full path is the tooltip."""

    def __init__(self, path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = path
        self.setToolTip(path)
        widgets.set_label_color(self, widgets.STATUS_IDLE)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.width() if self.width() > 1 else 10_000
        self.setText(self.fontMetrics().elidedText(self._path, Qt.TextElideMode.ElideLeft, width))


def placeholder(text: str) -> QWidget:
    """Stands in for a panel that is not available in the Qt GUI yet."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    widgets.set_label_color(label, widgets.STATUS_IDLE)
    return label


class MainWindow(QMainWindow):
    def __init__(self, arguments: ProjectManagerArguments, was_initialized: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("DiscoPoP Project Manager")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1600, 1000)
        self.setMinimumSize(1100, 700)
        self.arguments = arguments
        self.was_initialized = was_initialized
        self.project_state = ProjectState()
        self.panels: List[Panel] = []

        self.status = StatusLine()
        self.dot_dp_label = ElidedPathLabel(arguments.dot_dp)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.dot_dp_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        self.tabs = QTabWidget()
        self._tab_widgets: Dict[str, QWidget] = {}

        self._build_panels()
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 1320])

    # --- assembly ---

    def _build_panels(self) -> None:
        self.config_list: QWidget = placeholder("The configuration list follows in phase P1 of the port.")
        self.splitter.addWidget(self.config_list)
        self.splitter.addWidget(self.tabs)
        for name in TAB_ORDER:
            self.add_tab(name, placeholder(f"The {name} tab is not available in the Qt GUI yet."))

        self.report_panel = ReportPanel(self.arguments, self.project_state, self.status)
        self.add_tab(TAB_REPORT, self.report_panel)

    def add_tab(self, name: str, widget: QWidget) -> None:
        """Put ``widget`` at the place of tab ``name`` (replacing what is there) and register it if it is a panel."""
        if name in self._tab_widgets:
            index = self.tabs.indexOf(self._tab_widgets[name])
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, widget, name)
        else:
            self.tabs.addTab(widget, name)
        self._tab_widgets[name] = widget
        if isinstance(widget, Panel):
            self.panels.append(widget)

    def tab(self, name: str) -> QWidget:
        return self._tab_widgets[name]

    def show_tab(self, name: str) -> None:
        self.tabs.setCurrentWidget(self._tab_widgets[name])

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        index = self.tabs.indexOf(self._tab_widgets[name])
        self.tabs.setTabEnabled(index, enabled)
        self.tabs.setTabToolTip(index, tooltip)

    # --- lifecycle ---

    def cancel_running_jobs(self) -> None:
        """Stop the jobs the panels started.

        Several of them run in a session of their own, which neither the closed window nor a Ctrl+C in the terminal
        reaches.
        """
        for panel in self.panels:
            panel.cancel_jobs()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        self.cancel_running_jobs()
        super().closeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        # the path takes at most half of the status bar; the status text keeps the rest
        self.dot_dp_label.setMaximumWidth(max(self.width() // 2, 100))
