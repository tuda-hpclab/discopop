# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The folder tree of the project in which directories are excluded from the instrumentation by a check box.

A checked directory is no project code: the builds of the project manager pass it to the profiler as
``DP_PROJECT_EXCLUDE_DIRS`` (see ``services/excluded_directories.py``, which holds the logic). Its subdirectories are
excluded with it; they show a check mark that cannot be changed on its own. Every toggle is saved at once.

The tree is filled lazily: a directory's subdirectories are read when it is expanded, so a large build directory
costs nothing until it is opened.
"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from discopop_library.ProjectManager.services.excluded_directories import (
    excluding_directory,
    is_symbolic_link,
    load_excluded_directories,
    save_excluded_directories,
    subdirectories,
    toggle,
)

PATH_ROLE = Qt.ItemDataRole.UserRole
# the child of a directory whose subdirectories were not read yet (so that it shows an expand arrow)
_PLACEHOLDER = "…"
EXCLUDED_TOOLTIP = "Excluded: neither instrumented nor part of the file mapping and the AST"
INCLUDED_TOOLTIP = "Check to exclude this directory and everything below it from the instrumentation"


def _inherited_tooltip(directory: str) -> str:
    return f"Excluded with {directory}; uncheck {directory} to include it again"


class ExcludedDirectoriesTree(QTreeWidget):
    """The directories of ``project_root``, checked if excluded; the list is stored in ``project_dir``.

    ``changed`` is emitted with the stored list after every toggle that changed it, ``failed`` with a message if the
    list could not be stored (the tree then shows the stored state again).
    """

    changed = Signal(list)
    failed = Signal(str)

    def __init__(self, project_root: str, project_dir: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.project_dir = project_dir
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setUniformRowHeights(True)
        self.excluded: List[str] = []
        self._items: Dict[str, QTreeWidgetItem] = {}
        self._updating = False
        self.itemExpanded.connect(self._fill)
        self.itemChanged.connect(self._on_item_changed)
        self.reload()

    # -- content ---------------------------------------------------------------------------------------------------

    def reload(self) -> None:
        """Read the list and the top level directories again (subdirectories of expanded directories, too)."""
        expanded = [path for path, item in self._items.items() if item.isExpanded()]
        self.excluded = load_excluded_directories(self.project_dir)
        self._updating = True
        try:
            self.clear()
            self._items.clear()
            for path in subdirectories(self.project_root):
                self.addTopLevelItem(self._new_item(path))
        finally:
            self._updating = False
        for path in sorted(expanded, key=lambda p: p.count("/")):
            item = self._items.get(path)
            if item is not None:
                item.setExpanded(True)
        self._refresh_checks()

    def item_of(self, path: str) -> Optional[QTreeWidgetItem]:
        """The item of ``path`` (relative to the project directory) if it was read already."""
        return self._items.get(path)

    def expand_path(self, path: str) -> Optional[QTreeWidgetItem]:
        """Expand the directories down to ``path`` and return its item (None if it does not exist)."""
        parts = path.split("/")
        item: Optional[QTreeWidgetItem] = None
        for depth in range(1, len(parts) + 1):
            item = self._items.get("/".join(parts[:depth]))
            if item is None:
                return None
            if depth < len(parts):
                item.setExpanded(True)
        return item

    def _new_item(self, path: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([path.rsplit("/", 1)[-1]])
        item.setData(0, PATH_ROLE, path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        # a symbolic link is shown (it can be excluded) but not entered: links can form cycles
        if not is_symbolic_link(self.project_root, path) and subdirectories(self.project_root, path):
            item.addChild(QTreeWidgetItem([_PLACEHOLDER]))
        self._items[path] = item
        return item

    def _fill(self, item: QTreeWidgetItem) -> None:
        """Read the subdirectories of ``item`` when it is expanded the first time."""
        first = item.child(0) if item.childCount() == 1 else None
        if first is None or first.data(0, PATH_ROLE) is not None:
            return
        self._updating = True
        try:
            item.takeChild(0)
            for path in subdirectories(self.project_root, item.data(0, PATH_ROLE)):
                item.addChild(self._new_item(path))
        finally:
            self._updating = False
        self._refresh_checks()

    # -- check boxes -----------------------------------------------------------------------------------------------

    def _refresh_checks(self) -> None:
        """Show the stored list: listed directories checked, the ones below them checked, locked and faded."""
        # palette roles only, so that a dark desktop scheme keeps working
        faded = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
        normal = QBrush()
        self._updating = True
        try:
            for path, item in self._items.items():
                directory = excluding_directory(self.excluded, path)
                if directory is None:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, INCLUDED_TOOLTIP)
                    item.setForeground(0, normal)
                elif directory == path:
                    item.setCheckState(0, Qt.CheckState.Checked)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, EXCLUDED_TOOLTIP)
                    item.setForeground(0, normal)
                else:
                    item.setCheckState(0, Qt.CheckState.Checked)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, _inherited_tooltip(directory))
                    item.setForeground(0, faded)
        finally:
            self._updating = False

    def set_excluded(self, path: str, excluded: bool) -> None:
        """Exclude or include ``path`` as a click on its check box would (for the tests and keyboard users)."""
        if (excluding_directory(self.excluded, path) is not None) != excluded:
            self._toggle(path)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        path = item.data(0, PATH_ROLE)
        if path is None:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if (excluding_directory(self.excluded, path) is not None) != checked:
            self._toggle(path)
        else:
            self._refresh_checks()

    def _toggle(self, path: str) -> None:
        wanted = toggle(self.excluded, path)
        if wanted == self.excluded:
            # excluded through a directory above it: nothing to change on its own
            self._refresh_checks()
            return
        try:
            self.excluded = save_excluded_directories(self.project_dir, wanted)
        except OSError as error:
            self._refresh_checks()
            self.failed.emit(f"The excluded directories could not be saved: {error}")
            return
        self._refresh_checks()
        self.changed.emit(list(self.excluded))
