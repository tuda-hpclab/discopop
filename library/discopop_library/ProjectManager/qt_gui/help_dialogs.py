# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The help dialogs of the file editors: a read-only text and an OK button, one dialog per file.

Ported from ``gui/mixins/help_dialogs.py``; the texts are in ``services/help_texts.py``.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.services.help_texts import HELP_TEXTS


class HelpDialog(QDialog):
    """A non-modal window showing ``content``; it is deleted when closed."""

    def __init__(self, title: str, content: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.Window)
        self.resize(900, 650)
        self.setMinimumSize(850, 600)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text.setPlainText(content)
        self.ok_button = widgets.primary_button("OK", self._close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(widgets.hbox(self.ok_button, None))

    def _close(self) -> None:
        self.close()


def show_help(parent: QWidget, filename: str) -> HelpDialog:
    """Open the help of ``filename`` (a key of ``HELP_TEXTS``) next to ``parent``; ``parent`` owns the dialog."""
    title, content = HELP_TEXTS[filename]
    dialog = HelpDialog(title, content, parent)
    dialog.show()
    return dialog


def help_button(parent: QWidget, filename: str) -> QPushButton:
    """A "Help" button opening the help of ``filename``."""
    return widgets.create_button("Help", lambda: _open(parent, filename))


def _open(parent: QWidget, filename: str) -> None:
    show_help(parent, filename)
