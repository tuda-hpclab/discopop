# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The editor of the prompts of the patch repair and the patch completion (menu Configuration).

One list entry per template; what is saved is a file of the project (``.discopop/patch_repair/prompts``) that the
tool reads in place of the built-in template, so the next run uses it. What the services decide (which file, what
counts as unchanged, which placeholders a template needs) is in ``services/prompt_templates.py``.
"""

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.services import prompt_templates

_CUSTOMIZED_MARK = " ●"


class PromptConfigDialog(QDialog):
    """Edit the prompt templates of the project.

    Edits of several templates are kept until "Save" writes them all; switching the entry does not lose them.
    """

    def __init__(self, dot_dp: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Patch Repair and Completion")
        self.resize(1100, 750)
        self.dot_dp = dot_dp
        # name -> edited text, for the templates changed and not saved yet
        self._edits: Dict[str, str] = {}
        self._shown: Optional[str] = None
        self._loading = False

        self.template_list = QListWidget()
        self.template_list.setMaximumWidth(300)
        self._items: Dict[str, QListWidgetItem] = {}
        for group in (prompt_templates.GROUP_REPAIR, prompt_templates.GROUP_COMPLETION):
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.template_list.addItem(header)
            for info in prompt_templates.templates_of_group(group):
                item = QListWidgetItem("  " + info.title)
                item.setData(Qt.ItemDataRole.UserRole, info.name)
                self.template_list.addItem(item)
                self._items[info.name] = item
        self.template_list.currentItemChanged.connect(lambda _current, _previous: self._on_selected())

        self.title_label = widgets.heading_label("", title=False)
        self.description_label = widgets.caption_label("")
        self.description_label.setWordWrap(True)
        self.placeholder_label = widgets.caption_label("")
        self.placeholder_label.setWordWrap(True)
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.editor = QPlainTextEdit()
        self.editor.setFont(widgets.monospace_font())
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.textChanged.connect(self._on_text_changed)

        self.reset_button = QPushButton("Reset to default")
        self.reset_button.clicked.connect(self.reset_current)
        self.save_button = widgets.primary_button("Save", self._on_save_clicked)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)

        right = QVBoxLayout()
        right.addWidget(self.title_label)
        right.addWidget(self.description_label)
        right.addWidget(self.placeholder_label)
        right.addWidget(self.editor, 1)
        right.addWidget(self.warning_label)
        right.addLayout(widgets.hbox(self.reset_button, None, self.save_button, self.close_button))
        layout = QHBoxLayout(self)
        layout.addWidget(self.template_list)
        layout.addLayout(right, 1)

        self._refresh_marks()
        first = self._items[prompt_templates.TEMPLATES[0].name]
        self.template_list.setCurrentItem(first)

    # ── state ───────────────────────────────────────────────────────────────

    def has_unsaved_changes(self) -> bool:
        return bool(self._edits)

    def current_name(self) -> Optional[str]:
        return self._shown

    def select(self, name: str) -> None:
        self.template_list.setCurrentItem(self._items[name])

    def text_of(self, name: str) -> str:
        """What the template holds right now: the unsaved edit, else what the tool would send."""
        if name in self._edits:
            return self._edits[name]
        return prompt_templates.current_text(self.dot_dp, name)

    def _on_selected(self) -> None:
        item = self.template_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if name is None:
            return
        self._shown = str(name)
        info = prompt_templates.template_info(self._shown)
        self.title_label.setText(info.group + ": " + info.title)
        self.description_label.setText(info.description)
        placeholders = "  ".join(
            "{" + key + "}" for key in info.available
        )  # what the tool fills in, so an author need not guess
        self.placeholder_label.setText("Placeholders filled in by the tool: " + placeholders)
        self._loading = True
        try:
            self.editor.setPlainText(self.text_of(self._shown))
        finally:
            self._loading = False
        self._update_warning()
        self.reset_button.setEnabled(
            prompt_templates.is_customized(self.dot_dp, self._shown) or self._shown in self._edits
        )

    def _on_text_changed(self) -> None:
        if self._loading or self._shown is None:
            return
        text = self.editor.toPlainText()
        if text.strip() == self._saved_text(self._shown).strip():
            self._edits.pop(self._shown, None)
        else:
            self._edits[self._shown] = text
        self._update_warning()
        self._refresh_marks()
        self.reset_button.setEnabled(True)

    def _saved_text(self, name: str) -> str:
        return prompt_templates.current_text(self.dot_dp, name)

    def _update_warning(self) -> None:
        if self._shown is None:
            return
        text = self.editor.toPlainText()
        missing = prompt_templates.missing_placeholders(self._shown, text)
        unknown = prompt_templates.unknown_placeholders(self._shown, text)
        messages = []
        if missing:
            messages.append(
                "Missing: " + ", ".join("{" + key + "}" for key in missing) + " (the prompt cannot work without)."
            )
        if unknown:
            messages.append(
                "Not filled in for this template: "
                + ", ".join("{" + key + "}" for key in unknown)
                + " (sent as written)."
            )
        self.warning_label.setText(" ".join(messages))
        widgets.set_label_color(self.warning_label, widgets.STATUS_FAIL if missing else widgets.STATUS_STOP)

    def _refresh_marks(self) -> None:
        """Mark what differs from the built-in text (●) and what is not saved yet (*)."""
        for name, item in self._items.items():
            info = prompt_templates.template_info(name)
            mark = _CUSTOMIZED_MARK if prompt_templates.is_customized(self.dot_dp, name) else ""
            unsaved = " *" if name in self._edits else ""
            item.setText("  " + info.title + mark + unsaved)

    # ── actions ─────────────────────────────────────────────────────────────

    def reset_current(self) -> None:
        """Back to the built-in text, for the entry shown (applied by Save, like every edit)."""
        if self._shown is None:
            return
        name = self._shown
        builtin = prompt_templates.builtin_text(name)
        if prompt_templates.is_customized(self.dot_dp, name):
            self._edits[name] = builtin
        else:
            self._edits.pop(name, None)
        self._loading = True
        try:
            self.editor.setPlainText(builtin)
        finally:
            self._loading = False
        self._update_warning()
        self._refresh_marks()

    def _on_save_clicked(self) -> None:
        self.save()

    def save(self) -> bool:
        """Write the edited templates; False if the user stopped because a template lacks a required placeholder."""
        problems = [
            info.title + ": " + ", ".join("{" + key + "}" for key in missing)
            for name in self._edits
            for info in [prompt_templates.template_info(name)]
            for missing in [prompt_templates.missing_placeholders(name, self._edits[name])]
            if missing
        ]
        if problems and not dialogs.ask_yes_no(
            self,
            "Missing placeholders",
            "These prompts lack placeholders they need:\n\n" + "\n".join(problems) + "\n\nSave them anyway?",
        ):
            return False
        try:
            for name, text in self._edits.items():
                prompt_templates.save_template(self.dot_dp, name, text)
        except OSError as error:
            dialogs.show_error(self, "Saving failed", "The prompts could not be saved: " + str(error))
            return False
        self._edits.clear()
        self._refresh_marks()
        self.reset_button.setEnabled(
            self._shown is not None and prompt_templates.is_customized(self.dot_dp, self._shown)
        )
        return True

    def reject(self) -> None:
        if self._edits and not dialogs.ask_yes_no(
            self, "Unsaved changes", "Discard the unsaved changes of the prompts?"
        ):
            return
        super().reject()
