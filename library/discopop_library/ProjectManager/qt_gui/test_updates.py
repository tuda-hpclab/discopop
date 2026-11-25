# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import sys
from pathlib import Path
from typing import List, Optional

import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QWidget

from discopop_library.ProjectManager.qt_gui import updates
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.main_window import MainWindow
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.qt_gui.updates import UpdateController, UpdateDialog
from discopop_library.tools.update_notifications import update_notifier
from discopop_library.tools.update_notifications.update_notifier import (
    SOURCE_EDITABLE,
    AvailableUpdate,
    InstalledPackage,
    UpdateCheckResult,
    UpdateSettings,
)

FROM_PYPI = [InstalledPackage("discopop", "5.0.2"), InstalledPackage("discopop-library", "0.0.1a11")]
LOCAL_PROFILER = InstalledPackage("discopop-profiler", "0.0.1a6", "pip", SOURCE_EDITABLE, "/src/profiler")
UPDATE = UpdateCheckResult("stable", updates=(AvailableUpdate("discopop", "5.0.2", "5.0.3"),), checked=("discopop",))
UP_TO_DATE = UpdateCheckResult("stable", checked=("discopop",))


@pytest.fixture
def window(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


class Restarts:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def make_controller(window: QWidget, busy: str = "") -> "tuple[UpdateController, Restarts]":
    restarts = Restarts()
    return UpdateController(window, lambda: busy, restarts), restarts


def fake_check(monkeypatch: pytest.MonkeyPatch, result: Optional[UpdateCheckResult], calls: List[str]) -> None:
    def check(channel: str = "auto", *_args: object, **_kwargs: object) -> UpdateCheckResult:
        calls.append(channel)
        if result is None:
            raise ConnectionError("offline")
        return result

    monkeypatch.setattr(update_notifier, "check_for_updates", check)


def wait_for_check(qtbot: QtBot, controller: UpdateController) -> None:
    qtbot.waitUntil(lambda: not controller.is_checking(), timeout=5000)


# --- Help -> Version ---


def test_versions_text_lists_packages_and_sources() -> None:
    text = updates.versions_text(FROM_PYPI + [LOCAL_PROFILER], python="/venv/bin/python")
    lines = text.splitlines()
    assert lines[0] == "Installed DiscoPoP packages"
    assert lines[2].split() == ["discopop", "5.0.2", "PyPI"]
    assert lines[4].split() == ["discopop-profiler", "0.0.1a6", "editable:", "/src/profiler"]
    assert lines[-1].endswith(": /venv/bin/python")
    assert "(none found)" in updates.versions_text([])


def test_show_versions_opens_a_window(qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_notifier, "installed_packages", lambda: FROM_PYPI)
    dialog = updates.show_versions(window)
    assert dialog.isVisible() and "discopop-library" in dialog.text.toPlainText()


# --- checking ---


def test_manual_check_with_an_update_shows_the_button_and_the_dialog(
    qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[str] = []
    fake_check(monkeypatch, UPDATE, calls)
    update_notifier.save_settings(UpdateSettings(True, "pre"))
    controller, _ = make_controller(window)
    controller.check(manual=True)
    wait_for_check(qtbot, controller)
    assert calls == ["pre"]
    assert not controller.button.isHidden() and "5.0.2 → 5.0.3" in controller.button.toolTip()
    assert controller.dialog is not None and controller.dialog.isVisible()
    # a second request brings the open dialog to the front
    assert controller.open_dialog() is controller.dialog


def test_manual_check_up_to_date(
    qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch, dialog_answers: DialogRecorder
) -> None:
    fake_check(monkeypatch, UpdateCheckResult("stable", not_checked=(LOCAL_PROFILER,)), [])
    controller, _ = make_controller(window)
    controller.check(manual=True)
    wait_for_check(qtbot, controller)
    assert controller.button.isHidden() and controller.dialog is None
    assert dialog_answers.titles("show_message") == [updates.CHECK_TITLE]
    message = dialog_answers.messages("show_message")[0]
    assert "up to date" in message and "discopop-profiler" in message


@pytest.mark.parametrize(
    "result, dialog, expected",
    [
        (None, "show_warning", "offline"),
        (UpdateCheckResult("stable", errors=("discopop: ConnectionError: x",)), "show_warning", "PyPI could not"),
        (UpdateCheckResult("auto", not_checked=(LOCAL_PROFILER,), development_install=True), "show_message", "git"),
    ],
)
def test_manual_check_reports_failures_and_development_installs(
    qtbot: QtBot,
    window: QWidget,
    monkeypatch: pytest.MonkeyPatch,
    dialog_answers: DialogRecorder,
    result: Optional[UpdateCheckResult],
    dialog: str,
    expected: str,
) -> None:
    fake_check(monkeypatch, result, [])
    controller, _ = make_controller(window)
    controller.check(manual=True)
    wait_for_check(qtbot, controller)
    assert dialog_answers.titles() == [updates.CHECK_TITLE]
    assert expected in dialog_answers.messages(dialog)[0]
    assert controller.button.isHidden()


def test_automatic_check_is_silent(
    qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch, dialog_answers: DialogRecorder
) -> None:
    monkeypatch.setattr(update_notifier, "installed_packages", lambda: FROM_PYPI)
    calls: List[str] = []
    fake_check(monkeypatch, None, calls)
    controller, _ = make_controller(window)
    controller.check_at_start()
    wait_for_check(qtbot, controller)
    assert calls == ["auto"] and dialog_answers.calls == []
    # an update only shows the button
    fake_check(monkeypatch, UPDATE, calls)
    controller.check_at_start()
    wait_for_check(qtbot, controller)
    assert not controller.button.isHidden() and controller.dialog is None


def test_automatic_check_honours_the_setting_and_development_installs(
    qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[str] = []
    fake_check(monkeypatch, UPDATE, calls)
    controller, _ = make_controller(window)
    monkeypatch.setattr(update_notifier, "installed_packages", lambda: [InstalledPackage("discopop", "1", "pip")])
    update_notifier.save_settings(UpdateSettings(False, "auto"))
    controller.check_at_start()
    update_notifier.save_settings(UpdateSettings(True, "auto"))
    editable = InstalledPackage("discopop", "5.0.3a2", "pip", SOURCE_EDITABLE, "/src")
    monkeypatch.setattr(update_notifier, "installed_packages", lambda: [editable])
    controller.check_at_start()
    assert not controller.is_checking() and calls == []


def test_the_check_contacts_nobody_in_the_tests(update_settings_in_tmp: Path) -> None:
    # the fixture of conftest.py: the real check runs, but every request fails
    result = update_notifier.check_for_updates("auto", FROM_PYPI)
    assert result.updates == () and len(result.errors) == 1 and "do not contact PyPI" in result.errors[0]


# --- Settings -> Updates ---


def test_the_settings_menu_shows_and_saves_the_settings(window: QWidget, update_settings_in_tmp: Path) -> None:
    from PySide6.QtWidgets import QMenu

    update_notifier.save_settings(UpdateSettings(False, "pre"))
    controller, _ = make_controller(window)
    parent = QMenu(window)
    menu = controller.build_settings_menu(parent)
    assert menu.title() == "&Updates"
    assert controller.check_at_start_action is not None and not controller.check_at_start_action.isChecked()
    assert controller.channel_actions["pre"].isChecked()
    controller.check_at_start_action.setChecked(True)
    controller.channel_actions["stable"].setChecked(True)
    assert update_notifier.load_settings() == UpdateSettings(True, "stable")
    # changed elsewhere (the wizard): shown when the menu opens
    update_notifier.save_settings(UpdateSettings(False, "auto"))
    controller.refresh_settings_menu()
    assert not controller.check_at_start_action.isChecked() and controller.channel_actions["auto"].isChecked()
    assert update_notifier.load_settings() == UpdateSettings(False, "auto")


def test_the_checkbox_saves_at_once(qtbot: QtBot) -> None:
    update_notifier.save_settings(UpdateSettings(True, "pre"))
    checkbox = updates.check_at_start_checkbox()
    qtbot.addWidget(checkbox)
    assert checkbox.isChecked()
    checkbox.setChecked(False)
    assert update_notifier.load_settings() == UpdateSettings(False, "pre")


# --- the update dialog ---


def make_dialog(
    qtbot: QtBot, window: QWidget, result: UpdateCheckResult, code: str = "print('installed')", busy: str = ""
) -> UpdateDialog:
    dialog = UpdateDialog(result, lambda: busy, window, prefix=[sys.executable, "-c", code], runnable=True)
    dialog.show()
    return dialog


def test_update_now_runs_the_command_and_offers_a_restart(qtbot: QtBot, window: QWidget) -> None:
    dialog = make_dialog(qtbot, window, UPDATE)
    assert dialog.command[-1] == "discopop==5.0.3"
    assert "discopop==5.0.3" in dialog.command_field.text()
    restarts: List[bool] = []
    dialog.restart_requested.connect(lambda: restarts.append(True))
    dialog.start_update()
    assert dialog.is_running() and not dialog.close_button.isEnabled()
    qtbot.waitUntil(lambda: not dialog.is_running(), timeout=10000)
    assert "installed" in dialog.console.toPlainText()
    assert "Restart" in dialog.status_label.text()
    assert dialog.restart_button.isVisibleTo(dialog) and not dialog.update_button.isVisibleTo(dialog)
    dialog.restart_button.click()
    assert restarts == [True]


def test_a_failing_update_says_so(qtbot: QtBot, window: QWidget) -> None:
    dialog = make_dialog(qtbot, window, UPDATE, code="import sys; print('no'); sys.exit(3)")
    dialog.start_update()
    qtbot.waitUntil(lambda: not dialog.is_running(), timeout=10000)
    assert "exit code 3" in dialog.status_label.text()
    assert not dialog.restart_button.isVisibleTo(dialog) and dialog.update_button.isEnabled()


def test_closing_a_running_update_asks_to_stop_it(
    qtbot: QtBot, window: QWidget, dialog_answers: DialogRecorder
) -> None:
    dialog = make_dialog(qtbot, window, UPDATE, code="import time; time.sleep(30)")
    dialog.start_update()
    dialog_answers.answer("ask_yes_no", False)
    dialog.close()
    assert dialog.isVisible() and dialog.is_running()
    dialog_answers.answer("ask_yes_no", True)
    dialog.close()
    qtbot.waitUntil(lambda: not dialog.is_running(), timeout=10000)
    assert "stopped" in dialog.status_label.text()


def test_no_update_while_a_job_runs(qtbot: QtBot, window: QWidget, dialog_answers: DialogRecorder) -> None:
    dialog = make_dialog(qtbot, window, UPDATE, busy="A job is running (Profiling).")
    dialog.start_update()
    assert not dialog.is_running()
    assert "Profiling" in dialog_answers.messages("show_warning")[0]


def test_no_update_now_for_mixed_installs(qtbot: QtBot, window: QWidget) -> None:
    result = UpdateCheckResult("stable", updates=UPDATE.updates, not_checked=(LOCAL_PROFILER,))
    dialog = make_dialog(qtbot, window, result)
    assert not dialog.update_button.isVisibleTo(dialog)
    assert "discopop-profiler" in dialog.notes.text()
    dialog.start_update()
    assert not dialog.is_running()


def test_no_update_now_without_pip(qtbot: QtBot, window: QWidget) -> None:
    dialog = UpdateDialog(UPDATE, lambda: "", window, prefix=["python", "-m", "pip", "install"], runnable=False)
    assert not dialog.update_button.isVisibleTo(dialog) and "Neither pip nor uv" in dialog.notes.text()


# --- the main window ---


def test_the_window_has_the_menus_and_the_button(qtbot: QtBot, tmp_path: Path) -> None:
    main = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(main)
    titles = [action.text() for action in main.menuBar().actions()]
    assert titles == ["&View", "&Settings", "&Help"]
    assert [a.text() for a in main.help_menu.actions()] == ["&Version", "&Check for updates"]
    assert main.updates_menu.menuAction() in main.settings_menu.actions()
    assert main.updates.button.isHidden()
    assert main.busy_reason() == ""


def test_the_check_starts_after_the_wizard(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(main)
    started: List[bool] = []
    monkeypatch.setattr(main.updates, "check_at_start", lambda: started.append(True))
    main.show()
    main.after_show()
    wizard = main.config_list._wizard  # type: ignore[attr-defined]
    assert wizard is not None and started == []
    wizard.done(0)
    assert started == [True]


def test_restart_closes_the_window(qtbot: QtBot, tmp_path: Path) -> None:
    main = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(main)
    main.show()
    main.restart()
    assert main.restart_requested and not main.isVisible()


def test_a_successful_update_hides_the_button(qtbot: QtBot, window: QWidget, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_check(monkeypatch, UPDATE, [])
    controller, restarts = make_controller(window)
    controller.check(manual=True)
    wait_for_check(qtbot, controller)
    dialog = controller.dialog
    assert dialog is not None
    dialog.command = [sys.executable, "-c", "print('installed')"]
    dialog._runnable = True
    dialog.start_update()
    qtbot.waitUntil(lambda: not dialog.is_running(), timeout=10000)
    assert controller.button.isHidden() and controller.result is None
    dialog.restart_button.click()
    assert restarts.count == 1


def test_restart_process_runs_the_same_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from discopop_library.ProjectManager.qt_gui import app

    calls: List[object] = []
    monkeypatch.setattr("os.execv", lambda path, argv: calls.append((path, argv)))
    monkeypatch.setattr("sys.orig_argv", ["python3", "-m", "discopop_library.ProjectManager", "--gui"])
    monkeypatch.setattr("sys.executable", "/venv/bin/python")
    app.restart_process()
    assert calls == [("/venv/bin/python", ["/venv/bin/python", "-m", "discopop_library.ProjectManager", "--gui"])]
