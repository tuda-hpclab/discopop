# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The list of directories outside the project whose code is project code as well, with Add… and Remove.

The builds of the project manager pass them to the profiler as ``DP_PROJECT_INCLUDE_DIRS`` (see
``services/included_directories.py``, which holds the logic). Every change is saved at once.
"""

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.services.included_directories import (
    load_included_directories,
    problems,
    save_included_directories,
)

ADD_TEXT = "Add…"
REMOVE_TEXT = "Remove"


class IncludedDirectoriesList(QWidget):
    """The included directories of the project in ``project_root``; the list is stored in ``project_dir``.

    ``changed`` is emitted with the stored list after every change, ``failed`` with a message if the list could not be
    stored (the widget then shows the stored state again).
    """

    changed = Signal(list)
    failed = Signal(str)

    def __init__(self, project_root: str, project_dir: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.project_dir = project_dir
        self.included: List[str] = []
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.add_button = widgets.create_button(
            ADD_TEXT, self.add_directory, tooltip="Add a directory outside the project"
        )
        self.remove_button = widgets.create_button(REMOVE_TEXT, self.remove_selected)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list, 1)
        layout.addLayout(widgets.hbox(self.add_button, self.remove_button, None, margins=0))
        self.reload()

    def reload(self) -> None:
        """Show the stored list again."""
        self.included = load_included_directories(self.project_dir)
        self.list.clear()
        self.list.addItems(self.included)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.remove_button.setEnabled(self.list.currentRow() >= 0)

    def add_directory(self) -> None:
        chosen = dialogs.ask_directory(self, "Add a directory outside the project", self.project_root)
        if chosen is None:
            return
        reasons = problems(self.project_root, chosen)
        if reasons:
            dialogs.show_warning(self, "Cannot add the directory", "\n".join(reasons))
            return
        self._store([*self.included, chosen])

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        self._store([path for index, path in enumerate(self.included) if index != row])

    def _store(self, directories: List[str]) -> None:
        try:
            stored = save_included_directories(self.project_dir, self.project_root, directories)
        except OSError as error:
            self.reload()
            self.failed.emit(f"Cannot save the included directories: {error}")
            return
        changed = stored != self.included
        self.reload()
        if changed:
            self.changed.emit(stored)
