# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The project environment: the instrumentation scope (``DP_PROJECT_ROOT_DIR``) and what it resolves to.

Used by the Project Setup stage and the configuration wizard, as a card (``widgets.FormSection``). What is shown and
how it is stored lives in ``services/project_environment_view.py``; this widget only reads the scope line edit and shows
the results.
"""

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QListWidget, QVBoxLayout, QWidget

from discopop_library.ProjectManager.configurations.project_environment import (
    DEFAULT_SCOPE,
    SCOPE_VARIABLE,
    ProjectEnvironmentError,
    normalize_scope,
)
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.services.project_environment_view import (
    HINT,
    ProjectEnvironmentView,
    build_view,
    save_scope,
    stored_scope,
    use_run_root_variable,
)

REWRITE_BUTTON_TEXT = "Use DP_RUN_ROOT_DIR in these scripts"
TITLE = "Instrumentation scope"


class ProjectEnvironmentWidget(QWidget):
    """Edit the instrumentation scope of a project.

    ``edited`` is emitted when the user changed the scope, ``scripts_rewritten`` after the one-click fix changed
    scripts. ``before_rewrite`` (optional) may veto the rewrite, e.g. while the scripts are open in an editor with
    unsaved changes.
    """

    edited = Signal()
    scripts_rewritten = Signal()

    def __init__(
        self,
        project_root: str,
        project_config_dir: str,
        before_rewrite: Optional[Callable[[], bool]] = None,
        parent: Optional[QWidget] = None,
        *,
        title: str = TITLE,
    ) -> None:
        super().__init__(parent)
        self.project_root = os.path.abspath(project_root)
        self.project_config_dir = project_config_dir
        self._before_rewrite = before_rewrite
        self._stored = DEFAULT_SCOPE
        self._scripts: List[str] = []
        self._warnings: List[str] = []

        self.scope_edit = QLineEdit(DEFAULT_SCOPE)
        self.scope_edit.setPlaceholderText(DEFAULT_SCOPE)
        self.browse_button = widgets.create_button("Browse...", self._browse)
        self.resolved_edit = self._read_only_line()
        self.dot_discopop_edit = self._read_only_line()
        self.warnings_label = widgets.error_label("")
        self.warnings_label.hide()
        self.scripts_label = widgets.error_label(
            SCOPE_VARIABLE + " holds the instrumentation scope, not the project root. These scripts still use it:"
        )
        self.scripts_list = QListWidget()
        self.scripts_list.setMaximumHeight(110)
        self.rewrite_button = widgets.create_button(REWRITE_BUTTON_TEXT, self._rewrite_scripts)
        self.scripts_label.hide()
        self.scripts_list.hide()
        self.rewrite_button.hide()

        self.section = widgets.FormSection(title)
        self.hint_label = self.section.add_row(
            "Directory:", widgets.hbox(self.scope_edit, self.browse_button, margins=0), HINT
        )
        self.section.add_row(SCOPE_VARIABLE + ":", self.resolved_edit, stretch_field=True)
        self.section.add_row("DOT_DISCOPOP:", self.dot_discopop_edit, stretch_field=True)
        self.section.add_widget(self.warnings_label)
        self.section.add_widget(self.scripts_label)
        self.section.add_widget(self.scripts_list)
        self.section.add_widget(widgets.hbox(self.rewrite_button, None, margins=0))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.section)

        self.scope_edit.textChanged.connect(self._on_text_changed)
        self.refresh()

    @staticmethod
    def _read_only_line() -> QLineEdit:
        edit = QLineEdit()
        edit.setReadOnly(True)
        return edit

    # ── state ───────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Show the stored scope, dropping an unsaved edit."""
        try:
            self._stored = stored_scope(self.project_config_dir)
            error = ""
        except ProjectEnvironmentError as e:
            self._stored = DEFAULT_SCOPE
            error = str(e)
        self.scope_edit.blockSignals(True)
        self.scope_edit.setText(self._stored)
        self.scope_edit.blockSignals(False)
        self.refresh()
        if error:
            self._show_warnings([error] + self._warnings)

    def is_modified(self) -> bool:
        return self.normalized_scope() != self._stored

    def normalized_scope(self) -> str:
        return normalize_scope(self.project_root, self.scope_edit.text())

    def save(self) -> bool:
        """Store the scope; False (and an error dialog) if that failed."""
        try:
            self._stored = save_scope(self.project_config_dir, self.project_root, self.scope_edit.text())
        except (OSError, ProjectEnvironmentError) as e:
            dialogs.show_error(self, "Cannot save the project environment", str(e))
            return False
        self.refresh()
        return True

    def refresh(self) -> None:
        """Recompute what is shown for the scope in the line edit (also after scripts changed on disk)."""
        view: ProjectEnvironmentView = build_view(self.project_root, self.project_config_dir, self.scope_edit.text())
        self._warnings = list(view.warnings)
        self.resolved_edit.setText(view.project_root_dir)
        self.dot_discopop_edit.setText(view.dot_discopop)
        self._show_warnings(view.warnings)
        self._scripts = list(view.scripts_using_scope_variable)
        self.scripts_list.clear()
        for path in self._scripts:
            self.scripts_list.addItem(os.path.relpath(path, self.project_config_dir))
        for item in (self.scripts_label, self.scripts_list, self.rewrite_button):
            item.setVisible(bool(self._scripts))

    def _show_warnings(self, warnings: List[str]) -> None:
        self.warnings_label.setText("\n".join("⚠ " + warning for warning in warnings))
        self.warnings_label.setVisible(bool(warnings))

    # ── user actions ────────────────────────────────────────────────────────

    def _on_text_changed(self, _text: str) -> None:
        self.refresh()
        self.edited.emit()

    def _browse(self) -> None:
        start = os.path.normpath(os.path.join(self.project_root, self.scope_edit.text().strip() or DEFAULT_SCOPE))
        if not os.path.isdir(start):
            start = self.project_root
        chosen = dialogs.ask_directory(self, "Choose the instrumentation scope", start)
        if chosen is None:
            return
        scope = normalize_scope(self.project_root, chosen)
        if os.path.isabs(scope):
            dialogs.show_warning(
                self,
                "Outside of the project",
                "Choose a directory inside the project root " + self.project_root + ".",
            )
            return
        self.scope_edit.setText(scope)

    def _rewrite_scripts(self) -> None:
        if self._before_rewrite is not None and not self._before_rewrite():
            return
        try:
            use_run_root_variable(self._scripts)
        except OSError as e:
            dialogs.show_error(self, "Cannot rewrite the scripts", str(e))
            return
        self.refresh()
        self.scripts_rewritten.emit()
