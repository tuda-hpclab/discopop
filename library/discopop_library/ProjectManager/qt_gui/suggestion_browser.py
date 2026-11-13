# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Read and edit the generated patches (choosing suggestions is the :class:`SuggestionSelector`'s job)."""

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QSplitter, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.suggestion_table import SuggestionTable
from discopop_library.ProjectManager.services.patches import discover_patches
from discopop_library.ProjectManager.services.suggestions import SuggestionInfo, load_suggestions

# what an item of the file list stands for: one patch file (no path: all patches of the suggestion)
_ROLE_PATCH_PATH = Qt.ItemDataRole.UserRole
_ALL_PATCHES = "All patches"
_PLACEHOLDER = "Select a suggestion on the left to read its patch.\nSelect one of its files to edit it."


def patch_display_name(patch_path: str) -> str:
    """The source file a patch changes, from its ``---`` header line; the patch's own name if there is none."""
    try:
        with open(patch_path, "r") as f:
            for line in f:
                if line.startswith("---"):
                    name = os.path.basename(line[4:].split("\t")[0].strip())
                    if name:
                        return name
    except IOError:
        pass
    return os.path.basename(patch_path)


def read_suggestion_patches(dot_dp_path: str, sid: str, filenames: List[str]) -> str:
    """The patch files ``filenames`` of suggestion ``sid`` as one text (a file that cannot be read is named in it)."""
    parts = []
    for filename in filenames:
        path = os.path.join(dot_dp_path, "patch_generator", sid, filename)
        try:
            with open(path, "r") as f:
                parts.append(f.read())
        except IOError as e:
            parts.append(f"Error reading {filename}: {e}\n")
    return "\n".join(parts)


class SuggestionBrowserDialog(QDialog):
    """The suggestions as a table, the patch files of the selected one below it and the patch as a diff.

    Selecting a suggestion shows all its patches, read-only; selecting a file shows that patch, which can be edited and
    saved. The dialog is window-modal but not blocking: open it with ``show()``.
    """

    def __init__(self, parent: Optional[QWidget], dot_dp_path: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Browse Parallelization Suggestions")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1300, 800)
        self.dot_dp_path = dot_dp_path
        self.patches: Dict[str, List[str]] = discover_patches(dot_dp_path)
        self._current_patch_path: Optional[str] = None
        self._content_on_load = ""

        self.table = SuggestionTable(empty_text="No suggestions found.")
        self.table.set_suggestions(load_suggestions(dot_dp_path))
        self.table.current_changed.connect(self._on_suggestion_changed)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(130)
        self.file_list.currentItemChanged.connect(self._on_file_changed)
        self.save_button = widgets.primary_button("Save File", self.save_current_patch)
        self.save_button.setEnabled(False)
        self.editor = widgets.CodeView()
        self.editor.setPlaceholderText(_PLACEHOLDER)
        self.editor.textChanged.connect(self._on_text_changed)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(widgets.heading_label(f"Suggestions ({len(self.patches)})"))
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(widgets.heading_label("Patch files"))
        left_layout.addWidget(self.file_list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(widgets.hbox(self.save_button, None))
        right_layout.addWidget(self.editor, 1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([560, 740])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def suggestion_ids(self) -> List[str]:
        """The suggestions in the order the table shows them."""
        return self.table.visible_ids()

    def _patch_path(self, sid: str, filename: str) -> str:
        return os.path.join(self.dot_dp_path, "patch_generator", sid, filename)

    def _fill_file_list(self, sid: Optional[str]) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        if sid is not None and sid in self.patches:
            self.file_list.addItem(QListWidgetItem(_ALL_PATCHES))
            for filename in self.patches[sid]:
                path = self._patch_path(sid, filename)
                item = QListWidgetItem(patch_display_name(path))
                item.setData(_ROLE_PATCH_PATH, path)
                item.setToolTip(filename)
                item.setForeground(QColor(widgets.LINK_FG))
                self.file_list.addItem(item)
            self.file_list.setCurrentRow(0)
        self.file_list.blockSignals(False)

    def _on_suggestion_changed(self, info: Optional[SuggestionInfo]) -> None:
        if info is None:
            self._keep_unsaved_changes()
            self._fill_file_list(None)
            self._current_patch_path = None
            self._show("", editable=False)
            return
        self._fill_file_list(info.id)
        self.show_suggestion(info.id)

    def _on_file_changed(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        sid = self.table.current_suggestion()
        if current is None or sid is None:
            return
        path = current.data(_ROLE_PATCH_PATH)
        if path is not None:
            self.show_patch(str(path))
        else:
            self.show_suggestion(sid.id)

    # ── showing ──────────────────────────────────────────────────────────────

    def _keep_unsaved_changes(self) -> None:
        if self.is_modified() and dialogs.ask_yes_no(
            self, "Unsaved Changes", "You have unsaved changes. Save before switching?"
        ):
            self.save_current_patch()

    def show_suggestion(self, sid: str) -> None:
        """All patches of suggestion ``sid``, read-only."""
        self._keep_unsaved_changes()
        content = read_suggestion_patches(self.dot_dp_path, sid, self.patches.get(sid, []))
        self._current_patch_path = None
        self._show(content, editable=False)

    def show_patch(self, patch_path: str) -> None:
        """One patch, editable."""
        self._keep_unsaved_changes()
        try:
            with open(patch_path, "r") as f:
                content = f.read()
        except IOError as e:
            content = f"Error reading file: {e}"
        self._current_patch_path = patch_path
        self._show(content, editable=True)

    def _show(self, content: str, *, editable: bool) -> None:
        self._content_on_load = content
        self.editor.set_diff(content)
        self.editor.setReadOnly(not editable)
        self.save_button.setEnabled(editable)
        self.save_button.setText("Save File")

    # ── editing ──────────────────────────────────────────────────────────────

    def is_modified(self) -> bool:
        return self._current_patch_path is not None and self.editor.toPlainText() != self._content_on_load

    def _on_text_changed(self) -> None:
        if self._current_patch_path is not None:
            self.save_button.setText("Save File *" if self.is_modified() else "Save File")

    def save_current_patch(self) -> None:
        if not self._current_patch_path:
            return
        content = self.editor.toPlainText()
        try:
            with open(self._current_patch_path, "w") as f:
                f.write(content)
        except IOError as e:
            dialogs.show_error(self, "Save Error", f"Could not save file: {e}")
            return
        self._content_on_load = content
        self.save_button.setText("Save File")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        if self.is_modified() and dialogs.ask_yes_no(
            self, "Unsaved Changes", "You have unsaved changes. Save before closing?"
        ):
            self.save_current_patch()
        super().closeEvent(event)


def open_suggestion_browser(parent: Optional[QWidget], dot_dp_path: str) -> SuggestionBrowserDialog:
    """Show the browser (not blocking) and return it."""
    dialog = SuggestionBrowserDialog(parent, dot_dp_path)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog
