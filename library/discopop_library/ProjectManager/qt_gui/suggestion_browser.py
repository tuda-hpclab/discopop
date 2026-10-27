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
from PySide6.QtWidgets import QDialog, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.services.patches import discover_patches

# what an item of the tree stands for: a whole suggestion, or one patch file of it
_ROLE_SUGGESTION = Qt.ItemDataRole.UserRole
_ROLE_PATCH_PATH = Qt.ItemDataRole.UserRole + 1


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


class SuggestionBrowserDialog(QDialog):
    """The suggestions as a tree (suggestion -> patch files) and the selected patch as a diff.

    Clicking a suggestion shows all its patches, read-only; clicking a file shows that patch, which can be edited and
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

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.save_button = widgets.primary_button("Save File", self.save_current_patch)
        self.save_button.setEnabled(False)
        self.editor = widgets.CodeView()
        self.editor.textChanged.connect(self._on_text_changed)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(widgets.heading_label(f"Suggestions ({len(self.patches)})"))
        left_layout.addWidget(self.tree, 1)
        if not self.patches:
            left_layout.addWidget(widgets.caption_label("No suggestions found."))
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addLayout(widgets.hbox(self.save_button, None))
        right_layout.addWidget(self.editor, 1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 880])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self._fill_tree()

    def _fill_tree(self) -> None:
        for sid in self.patches:  # in numeric order
            suggestion = QTreeWidgetItem([f"Suggestion {sid}"])
            suggestion.setData(0, _ROLE_SUGGESTION, sid)
            for filename in self.patches[sid]:
                path = os.path.join(self.dot_dp_path, "patch_generator", sid, filename)
                patch = QTreeWidgetItem([patch_display_name(path)])
                patch.setData(0, _ROLE_PATCH_PATH, path)
                patch.setForeground(0, QColor(widgets.LINK_FG))
                suggestion.addChild(patch)
            self.tree.addTopLevelItem(suggestion)
            suggestion.setExpanded(True)

    def suggestion_ids(self) -> List[str]:
        """The suggestions in the order the tree shows them."""
        items = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        return [str(item.data(0, _ROLE_SUGGESTION)) for item in items if item is not None]

    # ── showing ──────────────────────────────────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, _ROLE_PATCH_PATH)
        if path is not None:
            self.show_patch(str(path))
        else:
            self.show_suggestion(str(item.data(0, _ROLE_SUGGESTION)))

    def _keep_unsaved_changes(self) -> None:
        if self.is_modified() and dialogs.ask_yes_no(
            self, "Unsaved Changes", "You have unsaved changes. Save before switching?"
        ):
            self.save_current_patch()

    def show_suggestion(self, sid: str) -> None:
        """All patches of suggestion ``sid``, read-only."""
        self._keep_unsaved_changes()
        parts = []
        for filename in self.patches.get(sid, []):
            path = os.path.join(self.dot_dp_path, "patch_generator", sid, filename)
            try:
                with open(path, "r") as f:
                    parts.append(f.read())
            except IOError as e:
                parts.append(f"Error reading {filename}: {e}\n")
        self._current_patch_path = None
        self._show("\n".join(parts), editable=False)

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
