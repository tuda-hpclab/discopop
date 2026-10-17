# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import threading

from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QPushButton

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.status import READY, StatusLine


def test_console_appends_without_adding_newlines(qtbot: QtBot) -> None:
    console = widgets.OutputConsole()
    qtbot.addWidget(console)
    console.append_text("a")
    console.append_text("b\n", "SUCCESS")
    console.append_text("c", "no such tag")
    assert console.text() == "ab\nc"
    console.set_text("new")
    assert console.text() == "new"


def test_log_records_of_a_worker_reach_the_console_and_the_handlers_are_restored(qtbot: QtBot) -> None:
    console = widgets.OutputConsole()
    qtbot.addWidget(console)
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level

    restore = widgets.redirect_logging_to_console(console, "INFO")
    worker = threading.Thread(target=lambda: logging.getLogger("worker").warning("from the worker"))
    worker.start()
    worker.join()
    logging.getLogger("main").debug("below the level")
    qtbot.waitUntil(lambda: "from the worker" in console.text(), timeout=5000)
    restore()

    assert "[worker] WARNING: from the worker" in console.text()
    assert "below the level" not in console.text()
    assert root.handlers == handlers_before and root.level == level_before


def test_code_view_shows_code_and_diffs(qtbot: QtBot) -> None:
    view = widgets.CodeView()
    qtbot.addWidget(view)
    view.set_diff("--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n")
    assert view.toPlainText().startswith("--- a")
    view.set_code("int main() {}")
    assert view.toPlainText() == "int main() {}"


def test_script_editor_text_is_not_modified_after_set_text(qtbot: QtBot) -> None:
    editor = widgets.ScriptEditor()
    qtbot.addWidget(editor)
    editor.set_text("make\n")
    assert editor.text() == "make\n" and not editor.document().isModified()
    editor.insertPlainText("x")
    assert editor.document().isModified()


def test_thread_selector_falls_back_to_auto(qtbot: QtBot) -> None:
    selector = widgets.ThreadSelector()
    qtbot.addWidget(selector)
    assert selector.value() == "auto"
    selector.setCurrentText("8")
    assert selector.value() == "8"
    selector.setCurrentText("0")
    assert selector.value() == "auto"
    selector.setCurrentText("")
    assert selector.value() == "auto"


def test_buttons_call_without_arguments_and_switch_variant(qtbot: QtBot) -> None:
    clicked = []
    button = widgets.primary_button("Run", lambda: clicked.append(True))
    qtbot.addWidget(button)
    assert isinstance(button, QPushButton) and button.objectName() == widgets.VARIANT_PRIMARY
    button.click()
    assert clicked == [True]
    widgets.set_button_variant(button, widgets.VARIANT_DANGER)
    assert button.objectName() == widgets.VARIANT_DANGER


def test_status_line_falls_back_to_ready(qtbot: QtBot) -> None:
    status = StatusLine()
    qtbot.addWidget(status)
    status.set("Working", widgets.STATUS_BUSY, reset_ms=50)
    assert status.text() == "Working" and status.color == widgets.STATUS_BUSY
    qtbot.waitUntil(lambda: status.text() == READY, timeout=2000)
