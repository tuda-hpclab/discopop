# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The main window: the workflow sidebar on the left, the panel of the selected stage on the right with the output
pane below it, the status line at the bottom. The configuration selector is at the top of the stages that work on the
selected configuration (``tabs.CONFIG_STAGES``), the color theme in a menu at the bottom of the sidebar.

The window assembles the panels and wires them: which panel reacts to which :class:`ProjectState` event, and the
few callbacks one panel offers another. The panels do not know each other. The window is their :class:`TabHost`:
the "tabs" of the panels are the stages of the sidebar.
"""

import os
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import theme, widgets
from discopop_library.ProjectManager.qt_gui.output_pane import OutputPane
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.panels.autotuning_panel import AutotuningPanel
from discopop_library.ProjectManager.qt_gui.panels.config_list_panel import ConfigListPanel
from discopop_library.ProjectManager.qt_gui.panels.editor_panel import EditorPanel
from discopop_library.ProjectManager.qt_gui.panels.execute_panel import ExecutePanel
from discopop_library.ProjectManager.qt_gui.panels.hotspot_panel import HotspotPanel
from discopop_library.ProjectManager.qt_gui.panels.patch_repair_panel import PatchRepairPanel
from discopop_library.ProjectManager.qt_gui.panels.pattern_detection_panel import PatternDetectionPanel
from discopop_library.ProjectManager.qt_gui.panels.profiling_panel import ProfilingPanel
from discopop_library.ProjectManager.qt_gui.panels.report_panel import ReportPanel
from discopop_library.ProjectManager.qt_gui.panels.setup_panel import SetupPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine

# re-exported: the names were defined here first
from discopop_library.ProjectManager.qt_gui.tabs import (
    CONFIG_STAGES,
    NAV_SECTIONS,
    TAB_AUTOTUNING as TAB_AUTOTUNING,
    TAB_EDITOR as TAB_EDITOR,
    TAB_EXECUTE as TAB_EXECUTE,
    TAB_HOTSPOT as TAB_HOTSPOT,
    TAB_ORDER as TAB_ORDER,
    TAB_PATCH_REPAIR as TAB_PATCH_REPAIR,
    TAB_PATTERN_DETECTION as TAB_PATTERN_DETECTION,
    TAB_PROFILING as TAB_PROFILING,
    TAB_REPORT as TAB_REPORT,
    TAB_SETUP as TAB_SETUP,
)
from discopop_library.ProjectManager.qt_gui.workflow_nav import WorkflowNav
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    ConfigurationsChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectDirectoriesChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.workflow_status import forget_build_states, stage_statuses

ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")

# the statuses of the stages are recomputed this long after the last event (a job publishes several in a row)
STATUS_DEBOUNCE_MS = 150
# and at most this often when the window is activated (the sources may have changed outside the GUI)
STATUS_ON_ACTIVATE_MIN_S = 2.0


class ElidedPathLabel(QLabel):
    """Shows a path, cut in the middle with an ellipsis when it does not fit; the full path is the tooltip."""

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
        # in the middle: the start (where the project lives) and the end (its name) are the informative parts
        self.setText(self.fontMetrics().elidedText(self._path, Qt.TextElideMode.ElideMiddle, width))


# the widest the path of the .discopop directory is shown in the status line (shortened in the middle beyond)
_PATH_MAX_WIDTH = 520


class MainWindow(QMainWindow):
    """The window; it is the :class:`TabHost` of the panels."""

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
        self.statusBar().addWidget(self.status, 1)
        # the project's path at the right end of the status line: there when needed, without taking the eye
        self.dot_dp_label = ElidedPathLabel(arguments.dot_dp)
        self.dot_dp_label.setMinimumWidth(80)
        self.dot_dp_label.setMaximumWidth(_PATH_MAX_WIDTH)
        self.statusBar().addPermanentWidget(self.dot_dp_label)

        self.nav = WorkflowNav([(heading, list(stages)) for heading, stages in NAV_SECTIONS])
        self.nav.stage_selected.connect(self._on_stage_selected)
        self.stack = QStackedWidget()
        self.output_pane = OutputPane()
        # the panel above, the output below; the pane collapses to its header
        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(False)
        self._expanded_output_height = 260
        self.output_pane.expanded_changed.connect(self._on_output_expanded)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self._tab_widgets: Dict[str, QWidget] = {}
        self._pending_tab_state: Dict[str, Tuple[bool, str]] = {}
        self._pending_tab_titles: Dict[str, str] = {}
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_DEBOUNCE_MS)
        self._status_timer.timeout.connect(self.refresh_stage_statuses)
        self._statuses_computed_at = 0.0
        # set on close: a job ending afterwards publishes events, the sidebar must not be refreshed any more
        self._closing = False

        self._build_panels()
        self._build_frame()
        self.refresh_stage_statuses()
        self.show_tab(TAB_EDITOR)

    # --- assembly ---

    def _build_panels(self) -> None:
        """Create the panels and wire them: the events each one reacts to beyond its own, and the callbacks."""
        args, state, status = self.arguments, self.project_state, self.status
        # Execute and Profiling run the configuration (Profiling in place): one at a time; the Report holds its PDF
        # report back while either runs
        self.execute_panel = ExecutePanel(
            args,
            state,
            status,
            self,
            run_state_changed=lambda running: self._run_state_changed(self.profiling_panel, running),
        )
        self.profiling_panel = ProfilingPanel(
            args,
            state,
            status,
            self,
            run_state_changed=lambda running: self._run_state_changed(self.execute_panel, running),
        )
        self.setup_panel = SetupPanel(args, state, status, self)
        self.editor_panel = EditorPanel(args, state, status, self)
        self.report_panel = ReportPanel(args, state, status, self.execute_panel.console.append_text)
        self.hotspot_panel = HotspotPanel(args, state, status, self.execute_panel.timeouts)
        self.pattern_detection_panel = PatternDetectionPanel(args, state, status, self)
        self.patch_repair_panel = PatchRepairPanel(args, state, status)
        self.autotuning_panel = AutotuningPanel(args, state, status, self)
        self.config_list = ConfigListPanel(
            args,
            state,
            status,
            confirm_leave_config=self.editor_panel.confirm_leave,
            tabs=self,
        )
        self.panels.append(self.config_list)
        self._add_theme_menu()
        panels: Dict[str, Panel] = {
            TAB_SETUP: self.setup_panel,
            TAB_EDITOR: self.editor_panel,
            TAB_PROFILING: self.profiling_panel,
            TAB_HOTSPOT: self.hotspot_panel,
            TAB_PATTERN_DETECTION: self.pattern_detection_panel,
            TAB_PATCH_REPAIR: self.patch_repair_panel,
            TAB_AUTOTUNING: self.autotuning_panel,
            TAB_EXECUTE: self.execute_panel,
            TAB_REPORT: self.report_panel,
        }
        # in the order of the sidebar
        for name in TAB_ORDER:
            self.add_tab(name, panels[name])

        # the autotuner records its measurements as execution results
        state.subscribe(AutotuningFinished, lambda _event: self.report_panel.update_display())
        # a profiling run (results) or a new configuration can make the Autotuning tab usable
        state.subscribe(ResultsChanged, lambda _event: self.autotuning_panel.update_tab_state())
        state.subscribe(ConfigurationsChanged, lambda _event: self.autotuning_panel.update_tab_state())
        self.autotuning_panel.update_tab_state()
        self.pattern_detection_panel.refresh()
        # every change of the project can change what the stages have done
        for event_type in (
            ConfigChanged,
            ConfigurationsChanged,
            ResultsChanged,
            PatternsChanged,
            HotspotsChanged,
            AutotuningChanged,
            AutotuningFinished,
            ProjectDirectoriesChanged,
        ):
            state.subscribe(event_type, lambda _event: self._status_timer.start())
        # a measurement or a run can rebuild what the hotspot stage compares with the sources
        state.subscribe(HotspotsChanged, lambda _event: forget_build_states())
        state.subscribe(ResultsChanged, lambda _event: forget_build_states())
        QShortcut(QKeySequence.StandardKey.Save, self, self.save_shortcut)

    def _add_theme_menu(self) -> None:
        """The menu "Theme" (System / Light / Dark) of the button at the bottom of the sidebar."""
        self.theme_menu = QMenu("Theme", self)
        self.theme_actions: Dict[str, QAction] = {}
        group = QActionGroup(self.theme_menu)
        group.setExclusive(True)
        for key in theme.THEMES:
            action = self.theme_menu.addAction(theme.THEME_TITLES[key])
            action.setCheckable(True)
            action.setChecked(key == theme.current_theme())
            action.triggered.connect(lambda _checked=False, key=key: self.set_theme(key))
            group.addAction(action)
            self.theme_actions[key] = action

    def set_theme(self, key: str) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.set_theme(app, key)
        self.theme_actions[theme.current_theme()].setChecked(True)

    def _run_state_changed(self, other: "ExecutePanel | ProfilingPanel", running: bool) -> None:
        other.set_blocked(running)
        self.report_panel.set_execution_running(running)
        self.setup_panel.set_blocked(running)

    def save_shortcut(self) -> None:
        """Ctrl+S: saves the files of the stage in front (Project Setup or Configuration Setup)."""
        current = self.current_tab()
        if current == TAB_SETUP:
            self.setup_panel.save()
        elif current == TAB_EDITOR:
            self.editor_panel.save()

    def _build_frame(self) -> None:
        """Sidebar | (panel over output pane), the whole height of the window (no header bar: the title is the
        window's, the configuration selector is on the stages that use it)."""
        # the sidebar and the status line are the frame of the window, in a color of their own (widgets.chrome_color)
        # and separated from the page by a line
        self.sidebar = QFrame()
        self.sidebar.setObjectName(widgets.SIDEBAR_NAME)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 8, 0, 8)
        sidebar_layout.addWidget(self.nav, 1)
        # the settings of the application (the color theme) at the bottom of the sidebar, on every stage
        self.theme_button = QToolButton()
        self.theme_button.setObjectName(widgets.FLAT_NAME)
        self.theme_button.setText("◐ Theme")
        self.theme_button.setToolTip("The color theme: System, Light or Dark")
        self.theme_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_button.setMenu(self.theme_menu)
        footer = widgets.hbox(self.theme_button, None, margins=0)
        # in line with the stages above it (their tiles are 6 px in from the edges)
        footer.setContentsMargins(6, 4, 6, 0)
        sidebar_layout.addLayout(footer)
        self.statusBar().setObjectName(widgets.STATUS_BAR_NAME)

        self.content_splitter.addWidget(self.stack)
        self.content_splitter.addWidget(self.output_pane)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.content_splitter)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 1380])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)
        self.stack.currentChanged.connect(lambda _index: self._place_config_selector())
        self._place_config_selector()

    def after_show(self) -> None:
        """Called once the window is visible: the wizard of a fresh project opens on top of it."""
        # the first stage in the sidebar has the keyboard focus, not the first widget of the page
        self.nav.setFocus()
        self.config_list.maybe_open_wizard(self.was_initialized)

    # --- the stages ---

    def add_tab(self, name: str, widget: QWidget) -> None:
        """Put ``widget`` at the place of stage ``name`` (replacing what is there) and register it if it is a panel.

        A state set before the stage existed (enabled, tooltip, title) is applied to it.
        """
        if name in self._tab_widgets:
            old = self._tab_widgets[name]
            if isinstance(old, Panel):
                self.panels.remove(old)
                old_console = old.output_console()
                if old_console is not None:
                    self.output_pane.remove_console(old_console)
            if self.config_list.parentWidget() is old:
                # the selector outlives the page it was on
                old_layout = old.layout()
                if old_layout is not None:
                    old_layout.removeWidget(self.config_list)
                self.config_list.setParent(self)
                self.config_list.setVisible(False)
            index = self.stack.indexOf(old)
            was_current = self.stack.currentWidget() is old
            self.stack.removeWidget(old)
            self.stack.insertWidget(index, widget)
            if was_current:
                self.stack.setCurrentWidget(widget)
        else:
            self.stack.addWidget(widget)
        self._tab_widgets[name] = widget
        if isinstance(widget, Panel):
            self.panels.append(widget)
            self._add_output_of(name, widget)
            # every stage gets the same page margins, whatever its own layout set
            layout = widget.layout()
            if layout is not None:
                layout.setContentsMargins(*widgets.PAGE_MARGINS)
        if name in self._pending_tab_state:
            self.set_tab_enabled(name, *self._pending_tab_state.pop(name))
        if name in self._pending_tab_titles:
            self.set_tab_title(name, self._pending_tab_titles.pop(name))

    def _place_config_selector(self) -> None:
        """Put the configuration selector first into the content of the stage in front (below its header, so the
        titles of all stages are at the same height) if it works on the selected configuration (``CONFIG_STAGES``),
        else hide it. Every way to another page (the sidebar, ``show_tab``, a
        replaced page) changes the current widget of the stack, which calls this."""
        selector = self.config_list
        current = self.current_tab()
        page = self._tab_widgets.get(current)
        layout = page.layout() if page is not None and current in CONFIG_STAGES else None
        if not isinstance(layout, QVBoxLayout):
            # on the other stages it stays where it was, hidden (and parented: it is the parent of its dialogs)
            selector.setVisible(False)
            return
        if selector.parentWidget() is not page:
            old_parent = selector.parentWidget()
            old_layout = old_parent.layout() if old_parent is not None else None
            if old_layout is not None:
                old_layout.removeWidget(selector)
            # the first content of the page: right below its header (a page without one: at the top)
            header = getattr(page, "header", None)
            index = layout.indexOf(header) + 1 if isinstance(header, QWidget) else 0
            layout.insertWidget(max(index, 0), selector, 0, Qt.AlignmentFlag.AlignLeft)
        selector.setVisible(True)

    def config_selector_stage(self) -> str:
        """The stage showing the configuration selector ("" if none does)."""
        if not self.config_list.isVisibleTo(self):
            return ""
        return next(
            (name for name, widget in self._tab_widgets.items() if widget is self.config_list.parentWidget()), ""
        )

    def tab(self, name: str) -> QWidget:
        return self._tab_widgets[name]

    def tab_names(self) -> List[str]:
        """The stages in the order of the sidebar."""
        return self.nav.stages()

    def show_tab(self, name: str) -> None:
        if name not in self._tab_widgets:
            return
        self.stack.setCurrentWidget(self._tab_widgets[name])
        if self.nav.current_stage() != name:
            self.nav.select_stage(name)

    def current_tab(self) -> str:
        current = self.stack.currentWidget()
        return next((name for name, widget in self._tab_widgets.items() if widget is current), "")

    def set_tab_title(self, name: str, title: str) -> None:
        """Show ``title`` for stage ``name``; the key in it (e.g. "Editor *") is replaced by the stage's title."""
        if name not in self._tab_widgets:
            self._pending_tab_titles[name] = title
            return
        default = self.nav.default_title(name)
        self.nav.set_title(name, default + title[len(name) :] if title.startswith(name) else title)

    def tab_title(self, name: str) -> str:
        return self.nav.title(name)

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        if name not in self._tab_widgets:
            # a panel decides about its stage in its constructor, before the window added it
            self._pending_tab_state[name] = (enabled, tooltip)
            return
        self.nav.set_stage_enabled(name, enabled, tooltip)
        if enabled:
            self._status_timer.start()
        elif self.current_tab() == name:
            self.show_tab(TAB_EDITOR)

    def is_tab_enabled(self, name: str) -> bool:
        return self.nav.is_stage_enabled(name)

    def tab_tooltip(self, name: str) -> str:
        return self.nav.item_tooltip(name)

    def _on_stage_selected(self, name: str) -> None:
        if name in self._tab_widgets:
            self.stack.setCurrentWidget(self._tab_widgets[name])

    def refresh_stage_statuses(self) -> None:
        """Ask the services what each stage has done and show it in the sidebar."""
        if self._closing:
            return
        self._statuses_computed_at = time.monotonic()
        statuses = stage_statuses(self.arguments, self.project_state.current_config)
        for name, status in statuses.items():
            if name in self._tab_widgets:
                self.nav.set_status(name, status)

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.WindowActivate
            and time.monotonic() - self._statuses_computed_at > STATUS_ON_ACTIVATE_MIN_S
        ):
            # the sources may have been edited in another program
            forget_build_states()
            self._status_timer.start()
        return super().event(event)

    # --- the output pane ---

    def _add_output_of(self, name: str, panel: Panel) -> None:
        """Put the console of ``panel`` into the output pane; its jobs bring it to the front."""
        console = panel.output_console()
        if console is None or console in self.output_pane.consoles():
            return
        self.output_pane.add_console(panel.output_title or name, console)
        panel.output_requested.connect(lambda c=console: self.output_pane.show_console(c))

    def _on_output_expanded(self, expanded: bool) -> None:
        sizes = self.content_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        if expanded:
            output = min(self._expanded_output_height, total // 2)
        else:
            if len(sizes) == 2 and sizes[1] > self.output_pane.maximumHeight():
                self._expanded_output_height = sizes[1]
            output = self.output_pane.maximumHeight()
        self.content_splitter.setSizes([total - output, output])

    # --- lifecycle ---

    def cancel_running_jobs(self) -> None:
        """Stop the jobs the panels started.

        Several of them run in a session of their own, which neither the closed window nor a Ctrl+C in the terminal
        reaches.
        """
        for panel in self.panels:
            panel.cancel_jobs()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        self._closing = True
        self._status_timer.stop()
        self.cancel_running_jobs()
        super().closeEvent(event)
