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
from discopop_library.ProjectManager.qt_gui.main_window import TAB_EDITOR, TAB_EXECUTE, TAB_REPORT
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
        self.editor_opened = 0


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

    def open_editor() -> None:
        holder[0].editor_opened += 1

    panel = ConfigListPanel(
        arguments, state, status, confirm_leave_config=leave, open_compilation_editor=open_editor, tabs=tabs
    )
    qtbot.addWidget(panel)
    holder.append(Env(panel, tabs, events))
    events.clear()
    return holder[0]


def click_row(env: Env, row: int) -> None:
    env.panel.list.setCurrentRow(row)


def test_the_list_shows_the_sorted_configurations_and_selects_the_first(qtbot: QtBot, tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path / "project")
    for name in ("b", "a"):
        Path(arguments.project_config_dir, name).mkdir()
    state = ProjectState()
    seen: List[Optional[str]] = []
    state.subscribe(ConfigChanged, lambda e: seen.append(e.configuration))
    status = StatusLine()
    qtbot.addWidget(status)
    panel = ConfigListPanel(arguments, state, status, lambda: True, lambda: None, FakeTabs())
    qtbot.addWidget(panel)
    assert panel.names() == ["a", "b"] and state.current_config == "a" and seen == ["a"]
    assert panel.new_button.text() == "+ New" and panel.edit_compilation_button.text() == "Edit Compilation"


def test_selecting_publishes_and_leaves_execute_and_report(env: Env) -> None:
    env.tabs.current = TAB_EXECUTE
    click_row(env, 1)
    assert env.panel.project_state.current_config == "b"
    assert env.events == [ConfigChanged("b")]
    assert env.tabs.shown == [TAB_EDITOR]
    env.tabs.current = TAB_REPORT
    click_row(env, 0)
    assert env.tabs.shown == [TAB_EDITOR, TAB_EDITOR]


def test_selecting_while_the_editor_is_in_front_keeps_the_tab(env: Env) -> None:
    click_row(env, 1)
    assert env.tabs.shown == []


def test_the_selection_stays_when_leaving_is_refused(env: Env) -> None:
    env.allow_leave = False
    click_row(env, 1)
    assert env.panel.project_state.current_config == "a" and env.events == []
    assert env.panel.list.currentRow() == 0 and [i.text() for i in env.panel.list.selectedItems()] == ["a"]


def test_edit_compilation_button(env: Env) -> None:
    env.panel.edit_compilation_button.click()
    assert env.editor_opened == 1


def test_new_config_creates_and_selects_it(env: Env, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_string", " c ")
    env.panel.new_button.click()
    assert env.panel.names() == ["a", "b", "c"] and env.panel.project_state.current_config == "c"
    assert env.panel.list.currentRow() == 2
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
    assert env.panel.list.currentRow() == 1 and ConfigChanged("z") in env.events
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


def test_the_context_menu_offers_copy_rename_delete(env: Env, dialog_answers: DialogRecorder) -> None:
    menu = env.panel.context_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Copy", "Rename", "Delete"]
    dialog_answers.answer("ask_yes_no", True)
    menu.actions()[3].trigger()
    assert env.panel.names() == ["b"]


def test_right_click_selects_the_item_under_the_cursor(env: Env) -> None:
    env.panel.show()
    item = env.panel.list.item(1)
    assert item is not None
    position = env.panel.list.visualItemRect(item).center()
    env.panel._on_right_click(position)
    assert env.panel.project_state.current_config == "b"
    assert env.panel._menu is not None
    env.panel._menu.close()


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
    assert env.tabs.shown == [TAB_EXECUTE] and ConfigChanged("wiz") in env.events
    assert env.panel._wizard is None
