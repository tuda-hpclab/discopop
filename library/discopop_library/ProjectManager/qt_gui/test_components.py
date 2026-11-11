# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The shared components of the streamlined layout: run/stop button, form sections, chips, the output pane."""

from pathlib import Path
from typing import List, Optional

from pytestqt.qtbot import QtBot

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSpinBox, QWidget

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.main_window import TAB_ORDER, MainWindow
from discopop_library.ProjectManager.qt_gui.output_pane import OutputPane
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.testing import make_arguments


def test_run_stop_button_toggles_between_run_and_stop(qtbot: QtBot) -> None:
    calls: List[str] = []
    button = widgets.RunStopButton("Run Analysis", lambda: calls.append("run"), lambda: calls.append("stop"))
    qtbot.addWidget(button)
    assert button.text() == "Run Analysis" and button.objectName() == widgets.VARIANT_PRIMARY
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    button.set_running(True)
    assert button.text() == "■ Stop" and button.objectName() == widgets.VARIANT_DANGER and button.isEnabled()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    button.set_running(False, enabled_after=False)
    assert calls == ["run", "stop"]
    assert button.text() == "Run Analysis" and not button.isEnabled() and not button.is_running()


def test_run_stop_button_texts_and_stop_lock(qtbot: QtBot) -> None:
    button = widgets.RunStopButton("Run", lambda: None, lambda: None)
    qtbot.addWidget(button)
    button.set_run_text("Re-run")
    assert button.text() == "Re-run"
    button.set_running(True)
    button.set_run_text("Run again")
    assert button.text() == "■ Stop"
    button.set_stop_enabled(False)
    assert not button.isEnabled()
    button.set_running(False)
    assert button.text() == "Run again" and button.isEnabled()
    # outside a run the stop lock does nothing
    button.set_stop_enabled(False)
    assert button.isEnabled()


def test_form_section_puts_the_hint_below_the_field(qtbot: QtBot) -> None:
    section = widgets.FormSection("Timeouts")
    qtbot.addWidget(section)
    spin = QSpinBox()
    hint = section.add_row("Execution (s):", spin, "0 = disabled")
    assert hint is not None and hint.text() == "0 = disabled"
    assert section.add_row("Plain:", QSpinBox()) is None
    section.show()
    assert hint.geometry().top() > spin.geometry().top()
    assert section.title_label is not None and section.title_label.text() == "Timeouts"
    assert section.form.rowCount() == 2


def test_collapsible_section_hides_its_content(qtbot: QtBot) -> None:
    content = QLabel("advanced")
    section = widgets.CollapsibleSection("Advanced", content)
    qtbot.addWidget(section)
    section.show()
    assert not content.isVisible() and section.toggle.text() == "▸ Advanced"
    section.toggle.click()
    assert content.isVisible() and section.is_expanded() and section.toggle.text() == "▾ Advanced"
    section.set_expanded(False)
    assert not content.isVisible()


def test_status_chip(qtbot: QtBot) -> None:
    chip = widgets.StatusChip()
    qtbot.addWidget(chip)
    chip.show()
    chip.set_status(widgets.CHIP_WARN, "Build stale", "Sources changed since the build.")
    assert chip.text() == "Build stale" and chip.level == widgets.CHIP_WARN
    assert chip.details_button.isVisible() and not chip.detail_label.isVisible()
    chip.details_button.click()
    assert chip.detail_label.isVisible() and chip.detail() == "Sources changed since the build."
    chip.set_status(widgets.CHIP_OK, "Up to date")
    assert not chip.details_button.isVisible() and not chip.detail_label.isVisible()


def test_overflow_button_runs_the_chosen_action(qtbot: QtBot) -> None:
    calls: List[str] = []
    button = widgets.overflow_button([("Reset", lambda: calls.append("reset")), ("Other", lambda: None)])
    qtbot.addWidget(button)
    menu = button.menu()
    assert menu is not None and [a.text() for a in menu.actions()] == ["Reset", "Other"]
    menu.actions()[0].trigger()
    assert calls == ["reset"]


def test_console_reports_appended_text(qtbot: QtBot) -> None:
    console = widgets.OutputConsole()
    qtbot.addWidget(console)
    seen: List[str] = []
    console.text_appended.connect(seen.append)
    console.append_text("a\n", "INFO")
    assert seen == ["a\n"] and console.placeholderText()


def test_output_pane_collapses_and_shows_the_last_line(qtbot: QtBot) -> None:
    pane = OutputPane()
    qtbot.addWidget(pane)
    pane.show()
    first, second = widgets.OutputConsole(), widgets.OutputConsole()
    pane.add_console("Execute", first)
    pane.add_console("Hotspots", second)
    assert not pane.is_expanded() and not pane.tabs.isVisible()
    first.append_text("compiling\nrunning ")
    second.append_text("measuring\n")
    first.append_text("done\n\n")
    assert pane.last_line_text() == "Execute: running done"
    pane.show_console(second)
    assert pane.is_expanded() and pane.tabs.isVisible() and pane.current_console() is second
    pane.clear_current()
    assert second.text() == "" and first.text() != ""
    pane.toggle.click()
    assert not pane.is_expanded()


class _PanelWithOutput(Panel):
    output_title = "Busy"

    def __init__(self, *args: object) -> None:
        super().__init__(*args)  # type: ignore[arg-type]
        self.console = widgets.OutputConsole(self)

    def output_console(self) -> Optional[widgets.OutputConsole]:
        return self.console


def test_main_window_puts_panel_consoles_into_the_output_pane(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    panel = _PanelWithOutput(window.arguments, window.project_state, window.status)
    window.add_tab(TAB_ORDER[1], panel)
    assert panel.console in window.output_pane.consoles()
    assert window.output_pane.tabs.tabText(window.output_pane.tabs.indexOf(panel.console)) == "Busy"
    panel.output_requested.emit()
    assert window.output_pane.is_expanded() and window.output_pane.current_console() is panel.console
    assert window.content_splitter.sizes()[1] > window.output_pane.header.sizeHint().height()
    window.output_pane.set_expanded(False)
    assert window.content_splitter.sizes()[1] <= window.output_pane.maximumHeight()
    # an unrelated widget (not a panel) is not asked for output
    window.add_tab(TAB_ORDER[2], QWidget())
    assert len(window.output_pane.consoles()) == 1
