# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The editor of the LLM configuration (``llm_config.json``) of the patch repair tool.

Two tabs over one file: *Connections* (which model to ask through which agent, with which defaults) and *Backends*
(where each agent is installed on this machine and what every connection through it defaults to). The editors for
the backend specific settings are generated from the ``FIELDS`` of the ``llm_backends`` registry. The file format
is documented in ``PatchRepair/llm_config.py``; no credentials are stored, so none are asked for.

Nothing here blocks the UI thread on an agent: the model list and the status of a binary come from a ``WorkRunner``.
The logic (text to stored values and back, name validation) lives in ``services/llm_config_edit.py``.
"""

import copy
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.PatchRepair import llm_backends, llm_config
from discopop_library.PatchRepair.llm_backends import FieldSpec
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.services import llm_config_edit
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkFinished, WorkRunner

_TITLE = "LLM Configuration"
_BOOL_CHOICES = ("", llm_config_edit.BOOL_TRUE, llm_config_edit.BOOL_FALSE)
_IMPLICIT_BACKEND_TEXT = "(first installed agent)"


class OptionFields(QWidget):
    """The editors of one backend's ``FIELDS``, rebuilt when the backend changes.

    A blank field means "inherit"; ``values()`` returns the text of every field, ``llm_config_edit`` drops the blanks.
    """

    def __init__(self, on_change: Callable[[], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on_change = on_change
        self.editors: Dict[str, QWidget] = {}
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def rebuild(self, specs: Sequence[FieldSpec], texts: Dict[str, str], inherited: Dict[str, str]) -> None:
        """Show ``specs`` filled from ``texts``; ``inherited`` (key -> text) is what a blank field falls back to."""
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self.editors = {}
        if not specs:
            self._layout.addRow(widgets.caption_label("This backend has no settings of its own."))
            return
        for spec in specs:
            editor: QWidget
            if spec.kind in ("bool", "choice") and (spec.kind == "bool" or spec.choices):
                combo = QComboBox()
                combo.addItems(list(_BOOL_CHOICES) if spec.kind == "bool" else ["", *[c for c in spec.choices if c]])
                combo.setCurrentText(texts.get(spec.key, ""))
                combo.currentTextChanged.connect(lambda _text: self._on_change())
                editor = combo
            else:
                line = QLineEdit(texts.get(spec.key, ""))
                line.textChanged.connect(lambda _text: self._on_change())
                editor = line
            self.editors[spec.key] = editor
            fallback = inherited.get(spec.key, "")
            hint = spec.hint + ("; " if spec.hint else "") + "blank = " + (fallback or "unset")
            self._layout.addRow(spec.label + ":", widgets.vbox(editor, widgets.caption_label(hint)))

    def values(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, editor in self.editors.items():
            out[key] = editor.currentText() if isinstance(editor, QComboBox) else str(getattr(editor, "text")())
        return out

    def set_value(self, key: str, text: str) -> None:
        editor = self.editors[key]
        if isinstance(editor, QComboBox):
            editor.setCurrentText(text)
        else:
            getattr(editor, "setText")(text)


def _env_editor(on_change: Callable[[], None]) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setFont(widgets.monospace_font(10))
    edit.setFixedHeight(80)
    edit.textChanged.connect(on_change)
    return edit


def _scrolled(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(content)
    return area


class LlmConfigDialog(QDialog):
    """Editor of ``llm_config.json``; emits ``saved`` after every successful Save.

    Edits are kept in memory until Save; Close asks when there are unsaved changes. A missing file starts an empty
    configuration, an unreadable one is reported and replaced by an empty one (Save then overwrites it).
    """

    saved = Signal()

    def __init__(self, config_path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.dirty = False
        self._loading = 0
        self._switching = False
        self._current_connection: Optional[str] = None
        self._connection_backend = ""
        self._shown_backend: Optional[str] = None
        # option texts per backend of the connection being edited, so switching the selector does not lose them
        self._options_memo: Dict[str, Dict[str, str]] = {}
        self._preserved: Dict[str, Any] = {}
        self._model_query: Optional[WorkRunner] = None
        self._status_query: Optional[WorkRunner] = None
        self.setWindowTitle(_TITLE)
        self.resize(900, 640)

        self.config = self._load_config()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connections_tab(), "Connections")
        self.tabs.addTab(self._build_backends_tab(), "Backends")
        self.path_label = widgets.caption_label("File: " + config_path)
        self.save_button = widgets.primary_button("Save", self._on_save_clicked)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.path_label)
        layout.addLayout(widgets.hbox(None, self.save_button, self.close_button))

        self._fill_connection_list(None)
        self._fill_backend_list()

    # ── file ────────────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        try:
            config = llm_config.load_config(self.config_path)
        except ValueError as error:
            dialogs.show_error(
                self, _TITLE, str(error) + "\n\nStarting with an empty configuration; Save replaces the file."
            )
            return llm_config.empty_config()
        if not isinstance(config.get("connections"), dict):
            config["connections"] = {}
        if not isinstance(config.get("backends"), dict):
            config["backends"] = {}
        return config

    def save(self) -> bool:
        """Validate both editors and write the file; False (after an error message) when nothing was written."""
        if not self._store_connection() or not self._store_backend():
            return False
        try:
            llm_config.save_config(self.config_path, self.config)
        except OSError as error:
            dialogs.show_error(self, _TITLE, "Could not write " + self.config_path + ": " + str(error))
            return False
        self.dirty = False
        self.saved.emit()
        return True

    def _on_save_clicked(self) -> None:
        self.save()

    def _mark_dirty(self) -> None:
        if not self._loading:
            self.dirty = True

    def reject(self) -> None:
        if self.dirty and not dialogs.ask_yes_no(self, _TITLE, "There are unsaved changes. Close without saving?"):
            return
        self._cancel_queries()
        super().reject()

    def _cancel_queries(self) -> None:
        for query in (self._model_query, self._status_query):
            if query is not None:
                query.cancel()
        self._model_query = self._status_query = None

    # ── connections tab ─────────────────────────────────────────────────────

    def _build_connections_tab(self) -> QWidget:
        self.connection_list = QListWidget()
        self.connection_list.setMaximumWidth(220)
        self.connection_list.currentItemChanged.connect(self._on_connection_selected)
        self.new_button = QPushButton("New")
        self.new_button.clicked.connect(self.new_connection)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_connection)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_connection)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem(_IMPLICIT_BACKEND_TEXT, "")
        for name in llm_backends.available_backends():
            self.backend_combo.addItem(name, name)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_choice_changed)
        self.backend_hint = widgets.caption_label("")
        self.backend_hint.setWordWrap(True)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.currentTextChanged.connect(lambda _text: self._mark_dirty())
        self.description_edit = QLineEdit()
        self.prompts_edit = QLineEdit()
        self.prompts_edit.setPlaceholderText("default")
        self.retries_edit = QLineEdit()
        self.retries_edit.setPlaceholderText("default")
        self.timeout_edit = QLineEdit()
        self.timeout_edit.setPlaceholderText("default (seconds)")
        self.extra_args_edit = QLineEdit()
        self.extra_args_edit.setPlaceholderText("arguments added to every call, e.g. --flag 'a b'")
        self.env_edit = _env_editor(self._mark_dirty)
        for line in (
            self.description_edit,
            self.prompts_edit,
            self.retries_edit,
            self.timeout_edit,
            self.extra_args_edit,
        ):
            line.textChanged.connect(lambda _text: self._mark_dirty())
        self.options = OptionFields(self._mark_dirty)

        form = QFormLayout()
        form.addRow("Backend:", self.backend_combo)
        form.addRow("", self.backend_hint)
        form.addRow("Model:", self.model_combo)
        form.addRow("", widgets.caption_label("Leave empty to use the backend's own default model."))
        form.addRow("Description:", self.description_edit)
        form.addRow("Prompts:", self.prompts_edit)
        form.addRow("", widgets.caption_label("Independent attempts with a fresh context."))
        form.addRow("Retries:", self.retries_edit)
        form.addRow("", widgets.caption_label("Follow-up turns inside one attempt."))
        form.addRow("Timeout (s):", self.timeout_edit)
        form.addRow("Extra arguments:", self.extra_args_edit)
        form.addRow("Environment:", self.env_edit)
        form.addRow("", widgets.caption_label("One KEY=VALUE per line. Credentials belong to the agent, not here."))
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addLayout(form)
        content_layout.addWidget(widgets.heading_label("Backend settings"))
        content_layout.addWidget(self.options)
        content_layout.addStretch(1)
        self.connection_editor = _scrolled(content)

        left = widgets.vbox(
            widgets.heading_label("Connections"),
            self.connection_list,
            widgets.hbox(self.new_button, self.copy_button, self.delete_button),
        )
        tab = QWidget()
        tab_layout = widgets.hbox(left, self.connection_editor)
        tab_layout.setStretch(1, 1)
        tab.setLayout(tab_layout)
        return tab

    def connection_names(self) -> List[str]:
        return [self.connection_list.item(i).text() for i in range(self.connection_list.count())]

    def _fill_connection_list(self, select: Optional[str]) -> None:
        self._switching = True
        self.connection_list.clear()
        for name in llm_config.connection_names(self.config):
            self.connection_list.addItem(name)
        self._switching = False
        names = self.connection_names()
        target = select if select in names else (names[0] if names else None)
        self._current_connection = None
        if target is None:
            self._load_connection(None)
        else:
            self.connection_list.setCurrentRow(names.index(target))

    def select_connection(self, name: str) -> None:
        """Show the connection ``name`` (stores the one shown before; stays put when that is invalid)."""
        self.connection_list.setCurrentRow(self.connection_names().index(name))

    def _on_connection_selected(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        if self._switching:
            return
        if self._current_connection is not None and not self._store_connection():
            self._switching = True
            self.connection_list.setCurrentRow(self.connection_names().index(self._current_connection))
            self._switching = False
            return
        self._load_connection(current.text() if current is not None else None)

    def _specs_of(self, backend: str) -> List[FieldSpec]:
        return llm_backends.fields_of(backend) if backend else []

    def _selected_backend(self) -> str:
        return str(self.backend_combo.currentData() or "")

    def _set_backend(self, backend: str) -> None:
        index = self.backend_combo.findData(backend)
        if index < 0:  # a backend the registry no longer knows stays selectable, so Save does not rewrite it
            self.backend_combo.addItem(backend, backend)
            index = self.backend_combo.findData(backend)
        self.backend_combo.setCurrentIndex(index)

    def _load_connection(self, name: Optional[str]) -> None:
        self._loading += 1
        try:
            self._current_connection = name
            self.connection_editor.setEnabled(name is not None)
            self.copy_button.setEnabled(name is not None)
            self.delete_button.setEnabled(name is not None)
            stored: Dict[str, Any] = {}
            if name is not None:
                stored = dict((self.config.get("connections") or {}).get(name) or {})
            backend = str(stored.get("backend") or "")
            options = llm_backends.stored_options(stored) if backend else dict(stored.get("backend_options") or {})
            specs = self._specs_of(backend)
            form = llm_config_edit.connection_to_form(stored, specs, options)
            self._preserved = llm_config_edit.undeclared_options(specs, options)
            self._options_memo = {backend: dict(form.options)}
            self._connection_backend = backend
            self._set_backend(backend)
            self.model_combo.clear()
            self.model_combo.setCurrentText(form.model)
            self.description_edit.setText(form.description)
            self.prompts_edit.setText(form.prompts)
            self.retries_edit.setText(form.retries)
            self.timeout_edit.setText(form.timeout)
            self.extra_args_edit.setText(form.extra_args)
            self.env_edit.setPlainText(form.env)
            self._rebuild_options(backend)
        finally:
            self._loading -= 1
        if name is not None:
            self._refresh_models()

    def _rebuild_options(self, backend: str) -> None:
        specs = self._specs_of(backend)
        inherited = {
            spec.key: llm_config_edit.option_to_text(spec, self._backend_default(backend, spec)) for spec in specs
        }
        self.options.rebuild(specs, self._options_memo.get(backend, {}), inherited)

    def _backend_default(self, backend: str, spec: FieldSpec) -> Any:
        defaults = llm_config.backend_defaults(self.config, backend).get("options") or {}
        return defaults.get(spec.key, spec.default)

    def _on_backend_choice_changed(self, _index: int) -> None:
        if self._loading:
            return
        previous = self._connection_backend or ""
        self._options_memo[previous] = self.options.values()
        backend = self._selected_backend()
        self._connection_backend = backend
        self._loading += 1
        try:
            self._rebuild_options(backend)
        finally:
            self._loading -= 1
        self._mark_dirty()
        self._refresh_models()

    def _form_of_connection(self) -> llm_config_edit.ConnectionForm:
        return llm_config_edit.ConnectionForm(
            backend=self._selected_backend(),
            model=self.model_combo.currentText(),
            description=self.description_edit.text(),
            prompts=self.prompts_edit.text(),
            retries=self.retries_edit.text(),
            timeout=self.timeout_edit.text(),
            extra_args=self.extra_args_edit.text(),
            env=self.env_edit.toPlainText(),
            options=self.options.values(),
        )

    def _store_connection(self) -> bool:
        """Write the shown connection into ``self.config``; False after reporting an invalid value."""
        name = self._current_connection
        if name is None:
            return True
        connections = self.config.setdefault("connections", {})
        try:
            connections[name] = llm_config_edit.connection_from_form(
                self._form_of_connection(),
                self._specs_of(self._selected_backend()),
                connections.get(name),
                self._preserved,
            )
        except ValueError as error:
            dialogs.show_error(self, _TITLE, "Connection '" + name + "': " + str(error))
            return False
        return True

    def _ask_connection_name(self, prompt: str, initial: str = "") -> Optional[str]:
        """A valid new name from the user, or None when cancelled or invalid (invalid ones are reported)."""
        name = dialogs.ask_string(self, _TITLE, prompt, initial)
        if name is None:
            return None
        error = llm_config_edit.validate_connection_name(name, self.connection_names())
        if error is not None:
            dialogs.show_error(self, _TITLE, error)
            return None
        return name.strip()

    def new_connection(self) -> None:
        if not self._store_connection():
            return
        name = self._ask_connection_name("Name of the new connection:")
        if name is not None:
            self.config.setdefault("connections", {})[name] = {}
            self._mark_dirty()
            self._fill_connection_list(name)

    def copy_connection(self) -> None:
        source = self._current_connection
        if source is None or not self._store_connection():
            return
        name = self._ask_connection_name("Name of the copy:", source + "_copy")
        if name is not None:
            connections = self.config.setdefault("connections", {})
            connections[name] = copy.deepcopy(connections[source])
            self._mark_dirty()
            self._fill_connection_list(name)

    def delete_connection(self) -> None:
        name = self._current_connection
        if name is None:
            return
        (self.config.get("connections") or {}).pop(name, None)
        self._mark_dirty()
        self._fill_connection_list(None)

    def _refresh_models(self) -> None:
        """Fill the model list of the selected backend in the background; what is typed in the field stays."""
        backend = self._selected_backend()
        if self._model_query is not None:
            self._model_query.cancel()
            self._model_query = None
        if not backend or backend not in llm_backends.BACKENDS:
            self.backend_hint.setText("" if not backend else "Unknown backend: " + backend)
            return
        module = llm_backends.get(backend)
        section = llm_config.backend_defaults(self.config, backend)
        description = str(getattr(module, "DESCRIPTION", ""))

        def query(_ctx: WorkContext) -> Tuple[str, List[str]]:
            return module.version(section) or "", list(module.list_models(section))

        def apply(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self._model_query = None
            if backend != self._selected_backend():
                return  # another backend was selected in the meantime
            version, models = event.result if event.error is None else ("", [])
            self.backend_hint.setText(("Version " + version + "\n" if version else "") + description)
            typed = self.model_combo.currentText()
            self._loading += 1
            try:
                self.model_combo.clear()
                self.model_combo.addItems(models)
                self.model_combo.setCurrentText(typed)
            finally:
                self._loading -= 1

        self.backend_hint.setText("Querying " + backend + "...")
        self._model_query = start_work(self, query, apply)

    # ── backends tab ────────────────────────────────────────────────────────

    def _build_backends_tab(self) -> QWidget:
        self.backend_list = QListWidget()
        self.backend_list.setMaximumWidth(220)
        self.backend_list.currentItemChanged.connect(self._on_backend_selected)

        self.about_label = widgets.caption_label("")
        self.about_label.setWordWrap(True)
        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("empty: the default binary on PATH")
        self.binary_edit.textChanged.connect(lambda _text: self._mark_dirty())
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_binary)
        self.check_button = QPushButton("Check")
        self.check_button.clicked.connect(self._refresh_status)
        self.status_label = widgets.caption_label("")
        self.status_label.setWordWrap(True)
        self.backend_args_edit = QLineEdit()
        self.backend_args_edit.setPlaceholderText(
            "arguments added to every call of every connection through this agent"
        )
        self.backend_args_edit.textChanged.connect(lambda _text: self._mark_dirty())
        self.backend_env_edit = _env_editor(self._mark_dirty)
        self.backend_options = OptionFields(self._mark_dirty)

        form = QFormLayout()
        form.addRow("Binary:", widgets.hbox(self.binary_edit, self.browse_button, self.check_button))
        form.addRow("", self.status_label)
        form.addRow("Extra arguments:", self.backend_args_edit)
        form.addRow("Environment:", self.backend_env_edit)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self.about_label)
        content_layout.addLayout(form)
        content_layout.addWidget(widgets.heading_label("Default settings"))
        content_layout.addWidget(
            widgets.caption_label("Used by every connection through this agent that leaves the setting blank.")
        )
        content_layout.addWidget(self.backend_options)
        content_layout.addStretch(1)
        self.backend_editor = _scrolled(content)

        tab = QWidget()
        tab_layout = widgets.hbox(widgets.vbox(widgets.heading_label("Agents"), self.backend_list), self.backend_editor)
        tab_layout.setStretch(1, 1)
        tab.setLayout(tab_layout)
        return tab

    def _fill_backend_list(self) -> None:
        self._switching = True
        self.backend_list.clear()
        for name in llm_backends.available_backends():
            self.backend_list.addItem(name)
        self._switching = False
        if self.backend_list.count():
            self.backend_list.setCurrentRow(0)
        else:
            self._load_backend(None)

    def select_backend(self, name: str) -> None:
        """Show the section of the agent ``name`` on the Backends tab."""
        self.backend_list.setCurrentRow(llm_backends.available_backends().index(name))

    def _on_backend_selected(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        if self._switching:
            return
        if self._shown_backend is not None and not self._store_backend():
            self._switching = True
            self.backend_list.setCurrentRow(llm_backends.available_backends().index(self._shown_backend))
            self._switching = False
            return
        self._load_backend(current.text() if current is not None else None)

    def _load_backend(self, name: Optional[str]) -> None:
        self._loading += 1
        try:
            self._shown_backend = name
            self.backend_editor.setEnabled(name is not None)
            if name is None:
                self.about_label.setText("")
                self.backend_options.rebuild([], {}, {})
                return
            module = llm_backends.get(name)
            specs = list(module.FIELDS)
            form = llm_config_edit.backend_to_form(llm_config.backend_defaults(self.config, name), specs)
            self.about_label.setText(
                str(module.DESCRIPTION)
                + "\n\nThe binary defaults to '"
                + str(module.DEFAULT_BINARY)
                + "' on PATH; $"
                + str(module.BINARY_ENV_VAR)
                + " overrides both."
            )
            self.binary_edit.setText(form.binary)
            self.backend_args_edit.setText(form.extra_args)
            self.backend_env_edit.setPlainText(form.env)
            self.backend_options.rebuild(
                specs, form.options, {spec.key: llm_config_edit.option_to_text(spec, spec.default) for spec in specs}
            )
        finally:
            self._loading -= 1
        self._refresh_status()

    def _store_backend(self) -> bool:
        """Write the shown backend section into ``self.config``; False after reporting an invalid value."""
        name = self._shown_backend
        if name is None:
            return True
        backends = self.config.setdefault("backends", {})
        form = llm_config_edit.BackendForm(
            binary=self.binary_edit.text(),
            extra_args=self.backend_args_edit.text(),
            env=self.backend_env_edit.toPlainText(),
            options=self.backend_options.values(),
        )
        try:
            section = llm_config_edit.backend_from_form(form, list(llm_backends.get(name).FIELDS), backends.get(name))
        except ValueError as error:
            dialogs.show_error(self, _TITLE, "Backend '" + name + "': " + str(error))
            return False
        # what was decided is written, not an empty object per registered agent
        if section:
            backends[name] = section
        else:
            backends.pop(name, None)
        return True

    def _browse_binary(self) -> None:
        path = dialogs.ask_open_file(self, "Select the executable", self.binary_edit.text().strip())
        if path:
            self.binary_edit.setText(path)
            self._refresh_status()

    def _refresh_status(self) -> None:
        """Say in the background whether the binary as entered can be run."""
        name = self._shown_backend
        if name is None:
            self.status_label.setText("")
            return
        if self._status_query is not None:
            self._status_query.cancel()
            self._status_query = None
        module = llm_backends.get(name)
        section = {"binary": self.binary_edit.text().strip()}

        def query(_ctx: WorkContext) -> Optional[str]:
            return str(module.version(section) or "") or None

        def apply(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self._status_query = None
            if name != self._shown_backend:
                return
            version = event.result if event.error is None else None
            if version:
                self.status_label.setText("The binary can be run: " + str(version))
                widgets.set_label_color(self.status_label, widgets.STATUS_OK)
            else:
                self.status_label.setText("The binary could not be run. " + str(getattr(module, "INSTALL_HINT", "")))
                widgets.set_label_color(self.status_label, widgets.STATUS_FAIL)

        self.status_label.setText("Checking...")
        widgets.set_label_color(self.status_label, widgets.STATUS_IDLE)
        self._status_query = start_work(self, query, apply)
