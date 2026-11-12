# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path
from typing import Any, List, Optional

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.main_window import TAB_EDITOR, TAB_EXECUTE, TAB_PROFILING
from discopop_library.ProjectManager.qt_gui.panels.config_list_panel import ConfigListPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.project_state import ConfigChanged, ConfigurationsChanged, ProjectState


class FakeTabs:
    def __init__(self) -> None:
        self.current = TAB_EDITOR
        self.shown: List[str] = []

    def show_tab(self, name: str) -> None:
        self.current = name
        self.shown.append(name)

    def current_tab(self) -> str:
        return self.current

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        pass

    def set_tab_title(self, name: str, title: str) -> None:
        pass


class Env:
    def __init__(self, panel: ConfigListPanel, tabs: FakeTabs, events: List[Any]) -> None:
        self.panel = panel
        self.tabs = tabs
        self.events = events
        self.allow_leave = True


@pytest.fixture
def env(qtbot: QtBot, tmp_path: Path) -> Env:
    arguments = make_arguments(tmp_path / "project")
    for name in ("b", "a"):
        Path(arguments.project_config_dir, name).mkdir()
    state = ProjectState()
    events: List[Any] = []
    state.subscribe(ConfigChanged, events.append)
    state.subscribe(ConfigurationsChanged, events.append)
    status = StatusLine()
    qtbot.addWidget(status)
    tabs = FakeTabs()
    holder: List[Env] = []

    def leave() -> bool:
        return holder[0].allow_leave

    panel = ConfigListPanel(arguments, state, status, confirm_leave_config=leave, tabs=tabs)
    qtbot.addWidget(panel)
    holder.append(Env(panel, tabs, events))
    events.clear()
    return holder[0]


def click_row(env: Env, row: int) -> None:
    """Click the tab of the configuration in ``row``."""
    env.panel.tab_bar.setCurrentIndex(row)


def test_the_list_shows_the_sorted_configurations_and_selects_the_first(qtbot: QtBot, tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path / "project")
    for name in ("b", "a"):
        Path(arguments.project_config_dir, name).mkdir()
    state = ProjectState()
    seen: List[Optional[str]] = []
    state.subscribe(ConfigChanged, lambda e: seen.append(e.configuration))
    status = StatusLine()
    qtbot.addWidget(status)
    panel = ConfigListPanel(arguments, state, status, lambda: True, FakeTabs())
    qtbot.addWidget(panel)
    assert panel.names() == ["a", "b"] and state.current_config == "a" and seen == ["a"]
    assert panel.tab_bar.currentIndex() == 0 and panel.caption_label.text() == "EXECUTION CONFIGURATION"


def test_the_menu_names_the_selected_configuration(env: Env) -> None:
    assert env.panel.menu_actions() == [
        "New Configuration…",
        "New with Wizard…",
        "",
        "Copy “a”…",
        "Rename “a”…",
        "Delete “a”…",
        "",
    ]
    click_row(env, 1)
    assert env.panel.menu_actions()[3:6] == ["Copy “b”…", "Rename “b”…", "Delete “b”…"]


def test_entries_added_behind_the_menu_stay_when_it_changes(env: Env) -> None:
    env.panel.menu().addAction("Theme")
    click_row(env, 1)
    env.panel.refresh()
    assert env.panel.menu_actions()[3:] == ["Copy “b”…", "Rename “b”…", "Delete “b”…", "", "Theme"]


def test_the_tab_menu_works_on_its_configuration(env: Env, dialog_answers: DialogRecorder) -> None:
    menu = env.panel.tab_menu("b")
    assert [action.text() for action in menu.actions()] == ["Copy “b”…", "Rename “b”…", "Delete “b”…"]
    dialog_answers.answer("ask_string", "z")
    menu.actions()[1].trigger()
    assert env.panel.names() == ["a", "z"] and env.panel.selected() == "z"
    menu.deleteLater()


def test_the_tab_menu_does_nothing_when_leaving_is_refused(env: Env) -> None:
    env.allow_leave = False
    menu = env.panel.tab_menu("b")
    menu.actions()[2].trigger()
    assert env.panel.names() == ["a", "b"] and env.panel.selected() == "a"
    menu.deleteLater()


def test_the_wheel_scrolls_the_tabs_instead_of_switching(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    arguments = make_arguments(tmp_path / "project")
    for index in range(20):
        Path(arguments.project_config_dir, f"configuration_{index:02}").mkdir()
    status = StatusLine()
    qtbot.addWidget(status)
    panel = ConfigListPanel(arguments, ProjectState(), status, lambda: True, FakeTabs())
    qtbot.addWidget(panel)
    panel.resize(400, 40)
    panel.show()
    qtbot.waitExposed(panel)
    right = panel.tab_bar.scroll_button(Qt.ArrowType.RightArrow)
    assert right is not None and right.isVisible()
    first_x = panel.tab_bar.tabRect(0).x()
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(panel.tab_bar, event)
    assert panel.tab_bar.currentIndex() == 0 and panel.selected() == "configuration_00"
    assert panel.tab_bar.tabRect(0).x() < first_x


def test_selecting_publishes_and_keeps_the_stage(env: Env) -> None:
    # the selector is on the stages that work on the selection: Execute stays in front
    env.tabs.current = TAB_EXECUTE
    click_row(env, 1)
    assert env.panel.project_state.current_config == "b"
    assert env.events == [ConfigChanged("b")]
    assert env.tabs.shown == []


def test_selecting_while_the_editor_is_in_front_keeps_the_tab(env: Env) -> None:
    click_row(env, 1)
    assert env.tabs.shown == []


def test_the_selection_stays_when_leaving_is_refused(env: Env) -> None:
    env.allow_leave = False
    click_row(env, 1)
    assert env.panel.project_state.current_config == "a" and env.events == []
    assert env.panel.selected() == "a" and env.panel.tab_bar.currentIndex() == 0


def test_select_asks_like_the_user(env: Env) -> None:
    assert env.panel.select("b") and env.panel.project_state.current_config == "b"
    env.allow_leave = False
    assert not env.panel.select("a") and env.panel.tab_bar.currentIndex() == 1
    assert not env.panel.select("missing") and env.panel.selected() == "b"


def test_new_config_creates_and_selects_it(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", " c ")
    env.panel.new_button.click()
    assert env.panel.names() == ["a", "b", "c"] and env.panel.project_state.current_config == "c"
    assert env.panel.selected() == "c" and env.panel.tab_bar.currentIndex() == 2
    assert ConfigurationsChanged() in env.events and ConfigChanged("c") in env.events
    assert env.panel.status.text() == "Created configuration 'c'" and env.panel.status.color == widgets.STATUS_OK
    assert Path(env.panel.config_dir, "c", "execute.sh").exists()


def test_new_config_errors(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", None, "", "a")
    env.panel.new_config()
    env.panel.new_config()
    assert dialog_answers.calls and not dialog_answers.titles("show_error")
    env.panel.new_config()
    assert dialog_answers.titles("show_error") == ["Already exists"]
    assert env.panel.names() == ["a", "b"] and env.events == []


def test_copy_config(env: Env, dialog_answers: DialogRecorder) -> None:
    Path(env.panel.config_dir, "a", "execute.sh").write_text("x")
    dialog_answers.answer("ask_string", "a2")
    env.panel.copy_config()
    assert env.panel.names() == ["a", "a2", "b"]
    assert Path(env.panel.config_dir, "a2", "execute.sh").read_text() == "x"
    assert env.panel.project_state.current_config == "a"
    assert env.panel.status.text() == "Copied configuration to 'a2'"
    assert dialog_answers.messages("ask_string") == ["Enter new name for copy of 'a':"]


def test_copy_to_an_existing_name_is_an_error(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", "b")
    env.panel.copy_config()
    assert dialog_answers.titles("show_error") == ["Already exists"]


def test_rename_config(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", "z")
    env.panel.rename_config()
    assert env.panel.names() == ["b", "z"] and env.panel.project_state.current_config == "z"
    assert env.panel.tab_bar.currentIndex() == 1 and ConfigChanged("z") in env.events
    assert env.panel.status.text() == "Renamed configuration to 'z'"


def test_rename_to_the_same_name_changes_nothing(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", "a")
    env.panel.rename_config()
    assert dialog_answers.titles("show_message") == ["No change"]
    assert env.panel.names() == ["a", "b"]


def test_delete_config_asks_and_selects_the_first_remaining(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_yes_no", False, True)
    env.panel.delete_config()
    assert env.panel.names() == ["a", "b"]
    env.panel.delete_config()
    assert env.panel.names() == ["b"] and env.panel.project_state.current_config == "b"
    assert dialog_answers.messages("ask_yes_no")[0] == "Are you sure you want to delete 'a'? This cannot be undone."
    assert env.panel.status.text() == "Deleted configuration"


def test_deleting_the_last_configuration_tells_the_panels(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_yes_no", True, True)
    env.panel.delete_config()
    env.panel.delete_config()
    assert env.panel.names() == [] and env.panel.project_state.current_config is None
    assert env.panel.tab_bar.isHidden() and not env.panel.empty_label.isHidden()
    assert env.panel.menu_actions()[3:6] == ["Copy…", "Rename…", "Delete…"]
    assert not any(action.isEnabled() for action in env.panel.menu().actions()[3:6])
    assert env.events[-1] == ConfigChanged(None)


def test_crud_without_a_selection_warns(env: Env, dialog_answers: DialogRecorder) -> None:
    env.panel.project_state.current_config = None
    env.panel.copy_config()
    env.panel.rename_config()
    env.panel.delete_config()
    assert dialog_answers.titles("show_warning") == ["No selection"] * 3
    assert dialog_answers.messages("show_warning")[2] == "Please select a configuration to delete"


def test_a_failing_create_is_reported(
    env: Env, dialog_answers: DialogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discopop_library.ProjectManager.qt_gui.panels import config_list_panel

    def broken(*_args: object) -> str:
        raise OSError("read-only")

    monkeypatch.setattr(config_list_panel, "create_configuration", broken)
    dialog_answers.answer("ask_string", "n")
    env.panel.new_config()
    assert dialog_answers.messages("show_error") == ["Failed to create configuration: read-only"]
    assert env.panel.status.text() == "Error creating config" and env.panel.status.color == widgets.STATUS_FAIL


def test_configurations_changed_refreshes(env: Env) -> None:
    Path(env.panel.config_dir, "c").mkdir()
    env.panel.project_state.publish(ConfigurationsChanged())
    assert env.panel.names() == ["a", "b", "c"] and env.panel.project_state.current_config == "a"


def test_the_menu_actions_work_on_the_selected_configuration(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_yes_no", True)
    env.panel.trigger("Delete “a”…")
    assert env.panel.names() == ["b"]
    dialog_answers.answer("ask_string", "b2")
    env.panel.trigger("Copy “b”…")
    assert env.panel.names() == ["b", "b2"]


def test_the_wizard_opens_for_a_project_without_a_real_configuration(env: Env, dialog_answers: DialogRecorder) -> None:
    env.panel.maybe_open_wizard(True)
    assert dialog_answers.titles("show_message") == ["Project Initialized"]
    wizard = env.panel._wizard
    assert wizard is not None and wizard.isVisible()
    wizard.done(0)
    assert env.panel._wizard is None


def test_the_wizard_stays_closed_with_a_real_configuration(env: Env) -> None:
    Path(env.panel.config_dir, "a", "execute.sh").write_text("#!/bin/bash\n./run\n")
    env.panel.maybe_open_wizard(False)
    assert env.panel._wizard is None


def test_a_finished_wizard_selects_its_configuration_and_shows_execute(env: Env) -> None:
    env.panel.maybe_open_wizard(False)
    wizard = env.panel._wizard
    assert wizard is not None
    for _ in range(6):
        wizard.next()
    wizard.config_name_entry.setText("wiz")
    wizard.next()
    wizard.accept()
    assert env.panel.names() == ["a", "b", "wiz"] and env.panel.project_state.current_config == "wiz"
    assert env.tabs.shown == [TAB_PROFILING] and ConfigChanged("wiz") in env.events
    assert env.panel._wizard is None


def test_the_tabs_are_labeled_as_the_execution_configuration(env: Env) -> None:
    assert env.panel.caption_label.text() == "EXECUTION CONFIGURATION"
    assert env.panel.names() == ["a", "b"]
