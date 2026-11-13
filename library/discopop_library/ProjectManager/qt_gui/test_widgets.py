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
from PySide6.QtWidgets import QPushButton, QStyle, QStyleFactory, QStyleOptionTab, QTabWidget, QWidget

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


def test_tab_titles_get_room_below_the_font(qtbot: QtBot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(QWidget(), "compile_validate.sh")
    tabs.show()
    option = QStyleOptionTab()
    tabs.tabBar().initStyleOption(option, 0)
    # against Fusion itself: the style sheet of the application lays out its tabs on its own (with room to spare)
    fusion = QStyleFactory.create("Fusion")
    base = fusion.subElementRect(QStyle.SubElement.SE_TabBarTabText, option, tabs.tabBar())
    roomy = widgets.TabTextRoomStyle("Fusion")
    assert roomy.subElementRect(QStyle.SubElement.SE_TabBarTabText, option, tabs.tabBar()).height() == (
        base.height() + 2 * widgets.TAB_TEXT_EXTRA_PX
    )


def test_a_check_box_keeps_its_whole_frame() -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter, QPalette
    from PySide6.QtWidgets import QStyleOptionButton

    # an indicator of an even size: centering on QRect.center() put half of the left frame line outside
    for size in (13, 16, 20):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        option = QStyleOptionButton()
        option.rect = QRect(0, 0, size, size)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Off
        # a transparent inside: only the frame line is drawn
        option.palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        painter = QPainter(image)
        widgets.draw_indicator(painter, option, radio=False)
        painter.end()
        middle = size // 2
        left = [image.pixelColor(x, middle).alpha() for x in range(middle)]
        right = [image.pixelColor(size - 1 - x, middle).alpha() for x in range(middle)]
        # the whole frame line (1.2 px wide) is drawn, on both sides alike: nothing of it is cut off at the left
        assert left == right, (size, left, right)
        assert sum(left) > 1.1 * 255, (size, left)


def test_combo_boxes_show_their_text_at_the_right(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    style = widgets.TabTextRoomStyle("Fusion")
    combo, editable = QComboBox(), widgets.ThreadSelector()
    for widget in (combo, editable):
        qtbot.addWidget(widget)
        widget.setStyle(style)
    combo.addItems(["all", ""])
    combo.setMinimumWidth(160)
    combo.show()
    editable.show()
    qtbot.waitExposed(combo)
    with_text = combo.grab().toImage()
    combo.setCurrentIndex(1)
    without_text = combo.grab().toImage()
    # where the two differ is the text: in the right half, next to the arrow
    columns = [
        x
        for x in range(combo.width())
        if any(with_text.pixelColor(x, y) != without_text.pixelColor(x, y) for y in range(combo.height()))
    ]
    assert columns and min(columns) > combo.width() // 2, columns[:5]
    # without a selection: the placeholder is shown (QComboBox.paintEvent fills it in, the filter has to as well)
    combo.setPlaceholderText("pick one")
    combo.setCurrentIndex(-1)
    assert combo.grab().toImage() != without_text
    line_edit = editable.lineEdit()
    assert line_edit is not None and line_edit.alignment() & Qt.AlignmentFlag.AlignRight
