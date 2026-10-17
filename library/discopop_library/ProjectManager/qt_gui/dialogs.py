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

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget


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
]
