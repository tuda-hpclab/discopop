# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The modal dialogs of the GUI, in one place.

Panels call them through the module (``dialogs.show_error(...)``), never import the functions by name: the tests
replace them here, as a modal dialog would block a test (and does not show at all on the offscreen platform).
"""

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.qt_gui import widgets


def _message_box(parent: Optional[QWidget], icon: QMessageBox.Icon, title: str, message: str) -> QMessageBox:
    box = QMessageBox(icon, title, message, QMessageBox.StandardButton.Ok, parent)
    # long messages (tracebacks, file lists) stay selectable for a bug report
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return box


def show_message(parent: Optional[QWidget], title: str, message: str) -> None:
    _message_box(parent, QMessageBox.Icon.Information, title, message).exec()


def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    _message_box(parent, QMessageBox.Icon.Warning, title, message).exec()


def show_error(parent: Optional[QWidget], title: str, message: str) -> None:
    _message_box(parent, QMessageBox.Icon.Critical, title, message).exec()


def ask_yes_no(parent: Optional[QWidget], title: str, message: str) -> bool:
    """True for Yes; No is the default button, so an accidental Enter does not confirm a destructive action."""
    answer = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def ask_string(parent: Optional[QWidget], title: str, prompt: str, initial: str = "") -> Optional[str]:
    """The text the user entered, or None if the dialog was cancelled."""
    text, ok = QInputDialog.getText(parent, title, prompt, QLineEdit.EchoMode.Normal, initial)
    return text if ok else None


def ask_choice(parent: Optional[QWidget], title: str, prompt: str, choices: Sequence[str]) -> Optional[str]:
    """One of ``choices``, or None if the dialog was cancelled."""
    item, ok = QInputDialog.getItem(parent, title, prompt, list(choices), 0, False)
    return item if ok else None


def ask_open_file(parent: Optional[QWidget], title: str, directory: str = "", filters: str = "") -> Optional[str]:
    """The chosen path, or None if the dialog was cancelled."""
    path, _ = QFileDialog.getOpenFileName(parent, title, directory, filters)
    return path or None


def ask_directory(parent: Optional[QWidget], title: str, directory: str = "") -> Optional[str]:
    """The chosen directory, or None if the dialog was cancelled."""
    path = QFileDialog.getExistingDirectory(parent, title, directory)
    return path or None


def ask_save_file(parent: Optional[QWidget], title: str, directory: str = "", filters: str = "") -> Optional[str]:
    """The chosen path, or None if the dialog was cancelled."""
    path, _ = QFileDialog.getSaveFileName(parent, title, directory, filters)
    return path or None


REVIEW_ACCEPT = "accept"
REVIEW_IGNORE = "ignore"


def review_build_changes(
    parent: Optional[QWidget], title: str, message: str, file_lines: Sequence[str], suggested_patterns: Sequence[str]
) -> Optional[Tuple[str, str]]:
    """Show what changed since a build and let the user decide: ``(REVIEW_IGNORE, patterns)`` (one pattern per
    line) to leave paths out of the fingerprint, ``(REVIEW_ACCEPT, "")`` to accept the build as current, or None."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(760, 560)
    layout = QVBoxLayout(dialog)
    text = QLabel(message)
    text.setWordWrap(True)
    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(text)
    fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if file_lines:
        layout.addWidget(QLabel("Changed files (M modified, A added, D deleted):"))
        files = QPlainTextEdit("\n".join(file_lines))
        files.setReadOnly(True)
        files.setFont(fixed)
        files.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(files, 1)
    layout.addWidget(
        QLabel(
            "Ignore in the fingerprint of every build (one pattern per line, e.g. dp_build/ or *.log; the files are "
            "still compiled):"
        )
    )
    patterns = QPlainTextEdit("\n".join(suggested_patterns))
    patterns.setFont(fixed)
    layout.addWidget(widgets.resizable(patterns, 90, minimum=40))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    ignore_button = QPushButton("Ignore and check again")
    ignore_button.setToolTip("Stores the patterns in the project and checks the build again.")
    accept_button = QPushButton("Accept build as current...")
    accept_button.setToolTip(
        "Runs reuse this build although the project changed. Use it only if the changes do not affect the build."
    )
    buttons.addButton(ignore_button, QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(accept_button, QDialogButtonBox.ButtonRole.ActionRole)
    layout.addWidget(buttons)
    choice: List[Tuple[str, str]] = []

    def choose(kind: str) -> None:
        choice.append((kind, patterns.toPlainText() if kind == REVIEW_IGNORE else ""))
        dialog.accept()

    ignore_button.clicked.connect(lambda: choose(REVIEW_IGNORE))
    accept_button.clicked.connect(lambda: choose(REVIEW_ACCEPT))
    buttons.rejected.connect(dialog.reject)
    dialog.exec()
    return choice[0] if choice else None


__all__: List[str] = [
    "show_message",
    "show_warning",
    "show_error",
    "ask_yes_no",
    "ask_string",
    "ask_choice",
    "ask_open_file",
    "ask_directory",
    "ask_save_file",
    "review_build_changes",
]
