# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Settings > Blocker resolution prompts: edit the prompt templates the blocker resolution sends to the LLM agent.

The storage is ``discopop_library.BlockerResolution.prompt_store``: a template saved here is kept in the project and
used by the next run of the check; a template equal to the shipped one is not stored.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPlainTextEdit, QWidget

from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.BlockerResolution import prompt_store

_NOTE = (
    "Changes apply to the next run of the blocker resolution. Where no version is saved, the template shipped with "
    "DiscoPoP is used."
)


class PromptSettingsDialog(QDialog):
    """One entry per template of the blocker resolution, an editor for the selected one."""

    def __init__(self, prompt_dir: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.prompt_dir = prompt_dir
        self.setWindowTitle("Blocker resolution prompts")
        self.setWindowFlag(Qt.WindowType.Window)
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)
        self._loading = False
        self._baseline = ""  # the text the editor was filled with (or saved last): the edits are the difference

        self.template_list = QListWidget()
        self.template_list.setFixedWidth(200)
        for template in prompt_store.TEMPLATES:
            self.template_list.addItem(template.title)
        self.purpose_label = QLabel()
        self.purpose_label.setWordWrap(True)
        self.placeholder_label = QLabel()
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.editor = QPlainTextEdit()
        self.editor.setFont(widgets.monospace_font())
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.restore_button = widgets.create_button("Restore default", self.restore_default)
        self.restore_button.setToolTip("Put the template shipped with DiscoPoP into the editor; Save stores it.")
        self.save_button = widgets.primary_button("Save", self._save_clicked)
        self.close_button = widgets.create_button("Close", self._close_clicked)

        right = widgets.vbox(
            self.purpose_label,
            self.placeholder_label,
            self.editor,
            widgets.caption_label(_NOTE),
            widgets.hbox(self.restore_button, None, self.save_button, self.close_button),
        )
        right.setStretchFactor(self.editor, 1)
        layout = widgets.hbox(self.template_list, right, margins=10, spacing=10)
        layout.setStretch(1, 1)
        self.setLayout(layout)

        self._current_row = 0
        self._refresh_titles()
        self._load(0)
        self.template_list.setCurrentRow(0)
        self.template_list.currentRowChanged.connect(self._row_changed)

    # --- state ---

    @property
    def current_name(self) -> str:
        return prompt_store.TEMPLATES[self._current_row].name

    def has_unsaved_changes(self) -> bool:
        return self.editor.toPlainText() != self._baseline

    def _refresh_titles(self) -> None:
        for row, template in enumerate(prompt_store.TEMPLATES):
            marker = " (customized)" if prompt_store.is_customized(self.prompt_dir, template.name) else ""
            self.template_list.item(row).setText(template.title + marker)

    def _load(self, row: int) -> None:
        self._current_row = row
        template = prompt_store.TEMPLATES[row]
        self.purpose_label.setText(template.purpose)
        lines = ["DiscoPoP fills in these placeholders, written as {name}:"]
        lines += ["{" + name + "}: " + description for name, description in template.placeholders]
        self.placeholder_label.setText("\n".join(lines))
        self._baseline = prompt_store.effective_template(template.name, self.prompt_dir)
        self.editor.setPlainText(self._baseline)

    # --- actions ---

    def restore_default(self) -> None:
        self.editor.setPlainText(prompt_store.default_template(self.current_name))

    def _save_clicked(self) -> None:
        self.save()

    def _close_clicked(self) -> None:
        self.close()

    def save(self) -> bool:
        """Store the text of the editor; False if the user declined the warning about the placeholders."""
        name, text = self.current_name, self.editor.toPlainText()
        warnings = []
        missing = prompt_store.missing_placeholders(name, text)
        unknown = prompt_store.unknown_placeholders(name, text)
        if missing:
            warnings.append(
                "Not used: " + ", ".join("{" + p + "}" for p in missing) + ". Their content will not reach the agent."
            )
        if unknown:
            warnings.append(
                "Not filled in by DiscoPoP: "
                + ", ".join("{" + p + "}" for p in unknown)
                + ". They reach the agent as written."
            )
        if warnings and not dialogs.ask_yes_no(self, "Save the prompt?", "\n\n".join(warnings) + "\n\nSave anyway?"):
            return False
        try:
            prompt_store.save_template(self.prompt_dir, name, text)
        except OSError as error:
            dialogs.show_error(self, "Saving failed", f"The prompt could not be saved: {error}")
            return False
        self._baseline = text
        self._refresh_titles()
        return True

    def _confirm_leave(self) -> bool:
        """True if the edits are saved or discarded (or there are none), False to stay."""
        if not self.has_unsaved_changes():
            return True
        answer = dialogs.ask_save_discard(
            self,
            "Unsaved changes",
            f"The {prompt_store.TEMPLATES[self._current_row].title} prompt has unsaved changes.",
        )
        if answer == dialogs.SAVE:
            return self.save()
        return answer == dialogs.DISCARD

    def _row_changed(self, row: int) -> None:
        if row < 0 or row == self._current_row or self._loading:
            return
        if self._confirm_leave():
            self._load(row)
            return
        self._loading = True  # back to the entry being edited, without asking again
        self.template_list.setCurrentRow(self._current_row)
        self._loading = False

    def reject(self) -> None:
        """Esc, Close and closing the window all end here (QDialog's closeEvent calls reject and keeps the window
        open if it stays visible): unsaved edits are asked about first. QDialog.reject hides the dialog through done(),
        which emits finished, so the main window forgets it."""
        if self._confirm_leave():
            super().reject()
