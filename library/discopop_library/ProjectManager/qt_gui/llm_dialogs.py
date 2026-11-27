# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Settings > LLM connections / LLM backends: the editors of the LLM configuration.

Both edit ``<.discopop>/patch_repair/llm_config.json`` (``PatchRepair/llm_config.py``), which patch repair and the
blocker resolution share: the connections (which model, through which agent, with which settings) and the backends
(where each agent is installed on this machine, and what every connection through it defaults to). Each dialog saves
only its own section over what is on disk, validated first. The logic that is not widget code lives in
``qt_gui/llm_logic.py``; probes of an agent (version, model list) run off the UI thread.

Ported from the benchmark harness's ``gui/qt/llm_dialogs.py``; its prompts dialog is not, as the prompts of the
blocker resolution have a dialog of their own (``prompt_settings_dialog.py``).
"""

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from discopop_library.PatchRepair import llm_backends, llm_config
from discopop_library.ProjectManager.qt_gui import dialogs, llm_logic, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkFinished, WorkRunner

ENV_HINT = "One KEY=VALUE per line. Credentials belong into the agent's own configuration, not here."


def _no_auto_default(button: QPushButton) -> QPushButton:
    # Enter in a text field must not press Save or Close
    button.setAutoDefault(False)
    button.setDefault(False)
    return button


def _env_editor() -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setFont(widgets.monospace_font())
    edit.setFixedHeight(70)
    edit.setTabChangesFocus(True)
    return edit


# ---- small widgets --------------------------------------------------------------------------------------------


class FieldGrid(QWidget):
    """The editor of a backend's own settings, built from its ``FIELDS`` and rebuilt when the backend changes. Every
    field can be blank (= inherit); the value that then applies is named in its hint."""

    def __init__(self, on_change: Callable[[], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on_change = on_change
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._inner: Optional[QWidget] = None
        self.specs: Tuple[Any, ...] = ()
        self.widgets: Dict[str, QWidget] = {}
        self.hints: Dict[str, QLabel] = {}

    def rebuild(self, specs: Any, stored: Dict[str, Any], inherited: Dict[str, Any]) -> None:
        if self._inner is not None:
            self._outer.removeWidget(self._inner)
            self._inner.setParent(None)
            self._inner.deleteLater()
        self._inner = QWidget(self)
        form = QFormLayout(self._inner)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._outer.addWidget(self._inner)
        self.specs = tuple(specs)
        self.widgets = {}
        self.hints = {}
        if not self.specs:
            form.addRow(widgets.caption_label("This backend has no settings of its own."))
            return
        for spec in self.specs:
            choices = llm_logic.field_choices(spec)
            text = llm_logic.field_text(stored.get(spec.key))
            field: QWidget
            if choices is not None:
                combo = QComboBox()
                combo.addItems(list(choices))
                if text and text not in choices:
                    combo.addItem(text)  # kept, not dropped: validation names it on save
                combo.setCurrentText(text)
                combo.currentTextChanged.connect(lambda _text: self._on_change())
                field = combo
            else:
                edit = QLineEdit(text)
                edit.textEdited.connect(lambda _text: self._on_change())
                field = edit
            self.widgets[spec.key] = field
            hint = widgets.caption_label(llm_logic.field_hint(spec, inherited))
            hint.setWordWrap(True)
            self.hints[spec.key] = hint
            form.addRow(spec.label + ":", widgets.vbox(field, hint, spacing=2))

    def texts(self) -> Dict[str, str]:
        out = {}
        for key, field in self.widgets.items():
            out[key] = field.currentText() if isinstance(field, QComboBox) else field.text()  # type: ignore[attr-defined]
        return out

    def values(self) -> Dict[str, Any]:
        """What was actually set, blanks left out."""
        return llm_logic.field_values(self.specs, self.texts())


# ---- base dialog ----------------------------------------------------------------------------------------------


class LlmDialog(QDialog):
    """An item list at the left, the editor of the selected item at the right, Save / Close below.

    Switching items keeps the edits (in memory, validated); Save writes this dialog's section of the file; Close, the
    window's close button and Esc ask about unsaved edits.
    """

    saved = Signal()

    section = ""
    title_text = ""
    list_label = ""
    allow_add_remove = True

    def __init__(self, path: str, config: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.path = path
        self.config_data = config
        self.current: Optional[str] = None
        self._dirty = False
        self._loading = False  # filling the widgets fires the signals that mark the dialog edited
        self._probes: Dict[str, WorkRunner] = {}
        self.setWindowTitle(self.title_text)
        self.setWindowFlag(Qt.WindowType.Window)
        self.resize(900, 640)
        self.setMinimumSize(700, 450)

        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        left = widgets.vbox(QLabel(self.list_label), self.listbox)
        left.setStretchFactor(self.listbox, 1)
        self.add_button: Optional[QPushButton] = None
        self.copy_button: Optional[QPushButton] = None
        self.remove_button: Optional[QPushButton] = None
        if self.allow_add_remove:
            self.add_button = _no_auto_default(widgets.create_button("Add", self._add))
            self.copy_button = _no_auto_default(widgets.create_button("Copy", self._copy))
            self.remove_button = _no_auto_default(widgets.create_button("Remove", self._remove))
            left.addLayout(widgets.hbox(self.add_button, self.copy_button, self.remove_button))
        left_widget = QWidget()
        left_widget.setLayout(left)

        self.editor = QWidget()
        self._build_editor(self.editor)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.editor)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_widget)
        split.addWidget(area)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 700])

        self.status = widgets.caption_label("")
        self.status.setWordWrap(True)
        self.save_button = _no_auto_default(widgets.primary_button("Save", self._save_clicked))
        self.close_button = _no_auto_default(widgets.create_button("Close", self.reject))
        footer = widgets.hbox(self.status, self.save_button, self.close_button)
        footer.setStretchFactor(self.status, 1)
        layout = widgets.vbox(split, footer, margins=10, spacing=8)
        layout.setStretchFactor(split, 1)
        self.setLayout(layout)

        self.listbox.currentRowChanged.connect(self._on_select)
        self.finished.connect(lambda _result=0: self.cancel_probes())
        self._refresh_list()

    # -- provided by the concrete dialogs
    def _build_editor(self, parent: QWidget) -> None:
        raise NotImplementedError

    def _names(self) -> List[str]:
        raise NotImplementedError

    def _load(self, name: Optional[str]) -> None:
        raise NotImplementedError

    def _store(self, name: Optional[str]) -> bool:
        """Write the editor back into ``config_data``; False (after telling the user) if it is not usable."""
        raise NotImplementedError

    def _new_item(self) -> Optional[str]:
        return None

    def _delete_item(self, name: str) -> None:
        pass

    def _copy_item(self, source: str, name: str) -> None:
        pass

    def _problems(self, config: Dict[str, Any]) -> List[str]:
        """The validation problems of this dialog's section of ``config``."""
        raise NotImplementedError

    # -- state
    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self, *_args: Any) -> None:
        if not self._loading:
            self._dirty = True

    def _error(self, message: str) -> None:
        dialogs.show_error(self, self.title_text, message)

    def _refresh_list(self, select: Optional[str] = None) -> None:
        names = self._names()
        if select is None:
            select = self.current if self.current in names else (names[0] if names else None)
        self.listbox.blockSignals(True)
        self.listbox.clear()
        self.listbox.addItems(names)
        if select is not None:
            self.listbox.setCurrentRow(names.index(select))
        self.listbox.blockSignals(False)
        self.current = select
        self._load_item(select)
        self._update_buttons()

    def _update_buttons(self) -> None:
        for button in (self.copy_button, self.remove_button):
            if button is not None:
                button.setEnabled(self.current is not None)
        self.editor.setEnabled(self.current is not None)

    def _load_item(self, name: Optional[str]) -> None:
        self._loading = True
        try:
            self._load(name)
        finally:
            self._loading = False

    def _on_select(self, row: int) -> None:
        item = self.listbox.item(row) if row >= 0 else None
        if item is None or item.text() == self.current:
            return
        # the edits of the item being left are kept (in memory) if they are valid; otherwise it stays selected
        if self.current is not None and not self._store(self.current):
            self.listbox.blockSignals(True)
            self.listbox.setCurrentRow(self._names().index(self.current))
            self.listbox.blockSignals(False)
            return
        self.current = item.text()
        self._load_item(self.current)
        self._update_buttons()

    def _ask_name(self, prompt: str, initial: str = "") -> Optional[str]:
        taken = self._names()
        while True:
            name = dialogs.ask_string(self, self.title_text, prompt, initial)
            if name is None or not name.strip():
                return None
            name = name.strip()
            if name not in taken:
                return name
            self._error(f"'{name}' already exists.")
            initial = name

    # -- actions
    def _add(self) -> None:
        if self.current is not None and not self._store(self.current):
            return
        name = self._new_item()
        if name is None:
            return
        self._dirty = True
        self._refresh_list(select=name)

    def _copy(self) -> None:
        source = self.current
        if source is None or not self._store(source):
            return
        name = self._ask_name(f"Name of the copy of '{source}':", f"{source}_copy")
        if name is None:
            return
        self._copy_item(source, name)
        self._dirty = True
        self._refresh_list(select=name)

    def _remove(self) -> None:
        if self.current is None:
            return
        if not dialogs.ask_yes_no(self, self.title_text, f"Remove '{self.current}'?"):
            return
        self._delete_item(self.current)
        self.current = None
        self._dirty = True
        self._refresh_list()

    def _save_clicked(self) -> None:
        self.save()

    def save(self) -> bool:
        """Store the editor and write this dialog's section over the file on disk, validated; False if refused."""
        if self.current is not None and not self._store(self.current):
            return False
        try:
            on_disk = llm_config.load_config(self.path)
        except ValueError as error:
            self._error(f"{error}\n\nFix or delete the file, then save again.")
            return False
        merged = llm_logic.merge_section(on_disk, self.config_data, self.section)
        problems = self._problems(merged)
        if problems:
            self._error("The configuration cannot be saved yet:\n\n- " + "\n- ".join(problems))
            return False
        try:
            llm_config.save_config(self.path, merged)
        except OSError as error:
            self._error(f"The configuration could not be saved: {error}")
            return False
        self.config_data = copy.deepcopy(merged)
        self._dirty = False
        self.status.setText("Saved to " + self.path)
        self.saved.emit()
        return True

    def _confirm_leave(self) -> bool:
        """True if the edits are saved or discarded (or there are none), False to stay."""
        if not self._dirty:
            return True
        answer = dialogs.ask_save_discard(self, "Unsaved changes", f"The {self.title_text} have unsaved changes.")
        if answer == dialogs.SAVE:
            return self.save()
        if answer == dialogs.DISCARD:
            self._dirty = False
            return True
        return False

    def reject(self) -> None:
        # Close, Esc and the window's close button (QDialog.closeEvent calls reject) all end here
        if self._confirm_leave():
            super().reject()

    # -- probes off the UI thread
    def _probe(self, key: str, work: Callable[[], Any], apply: Callable[[Any], None]) -> None:
        """Run ``work`` on a worker thread; ``apply`` gets its result (None on an error) unless the dialog closed or
        a newer probe of ``key`` was started."""
        previous = self._probes.pop(key, None)
        if previous is not None:
            previous.cancel()
        runner: Optional[WorkRunner] = None

        def run(_ctx: WorkContext) -> Any:
            return work()

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished) or self._probes.get(key) is not runner:
                return
            del self._probes[key]
            apply(event.result if event.error is None else None)

        runner = start_work(self, run, handle)
        self._probes[key] = runner

    def probes_running(self) -> bool:
        return bool(self._probes)

    def cancel_probes(self) -> None:
        for runner in self._probes.values():
            runner.cancel()
        self._probes = {}


def _row(form: QFormLayout, label: str, field: Any, hint: str = "") -> Optional[QLabel]:
    if not hint:
        form.addRow(label, field)
        return None
    caption = widgets.caption_label(hint)
    caption.setWordWrap(True)
    form.addRow(label, widgets.vbox(field, caption, spacing=2))
    return caption


def _form(parent: QWidget) -> QFormLayout:
    form = QFormLayout(parent)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


# ---- connections ----------------------------------------------------------------------------------------------


class ConnectionsDialog(LlmDialog):
    """The connections: backend first (it decides the model list and the settings below it), the editor filled from
    the connection as written, blank = inherit everywhere. Settings typed for another backend are kept while
    switching back and forth, but only the chosen backend's are saved."""

    section = llm_logic.CONNECTIONS
    title_text = "LLM connections"
    list_label = "Connections"

    def _build_editor(self, parent: QWidget) -> None:
        # (version or None, models) per backend, probed once per dialog
        self._backend_info: Dict[str, Tuple[Optional[str], List[str]]] = {}
        self._options_by_backend: Dict[str, Dict[str, Any]] = {}
        self._fields_backend: Optional[str] = None
        self._backend_unset = False
        self._backend_chosen = False
        form = _form(parent)
        self.description_edit = QLineEdit()
        _row(form, "Description:", self.description_edit)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(llm_backends.available_backends())
        self.backend_combo.setToolTip(llm_logic.BACKEND_TOOLTIP)
        hint = _row(form, "Backend:", self.backend_combo, " ")
        assert hint is not None
        self.backend_hint = hint

        # editable: the list is only what the backend reports, any model must be enterable
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        hint = _row(form, "Model:", self.model_combo, " ")
        assert hint is not None
        self.model_hint = hint

        self.timeout_edit = QLineEdit()
        self.timeout_edit.setMaximumWidth(120)
        _row(
            form,
            "Timeout per call (s):",
            self.timeout_edit,
            "Blank: the agent timeout of the run (patch repair / blocker resolution, Advanced). A value here wins "
            "over it for every run through this connection.",
        )
        self.extra_args_edit = QLineEdit()
        _row(form, "Extra arguments:", self.extra_args_edit, "Passed to the agent after its own; space separated.")
        self.env_text = _env_editor()
        _row(form, "Environment:", self.env_text, ENV_HINT)
        self.options_label = widgets.heading_label("Backend settings")
        form.addRow(self.options_label)
        self.fields = FieldGrid(self.mark_dirty)
        form.addRow(self.fields)

        self.description_edit.textEdited.connect(self.mark_dirty)
        self.timeout_edit.textEdited.connect(self.mark_dirty)
        self.extra_args_edit.textEdited.connect(self.mark_dirty)
        self.env_text.textChanged.connect(self.mark_dirty)
        self.model_combo.currentTextChanged.connect(self.mark_dirty)
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)

    # -- the backend-driven parts
    def backend_name(self) -> str:
        name = self.backend_combo.currentText()
        return name if name in llm_backends.available_backends() else llm_backends.DEFAULT_BACKEND

    def stored_backend(self) -> str:
        """The backend a save writes: "" (not set) for a connection without one, unless one was chosen here."""
        if self._backend_unset and not self._backend_chosen:
            return ""
        return self.backend_name()

    def _on_backend_changed(self, _text: str) -> None:
        self.mark_dirty()
        self._backend_chosen = True
        previous = self._fields_backend
        if previous is not None and previous != self.backend_name():
            # remembered, so switching back brings back what was typed
            self._options_by_backend[previous] = self.fields.values()
        self._rebuild_fields()
        self._show_backend_info()

    def _rebuild_fields(self) -> None:
        name = self.backend_name()
        self._fields_backend = name
        specs = llm_backends.fields_of(name)
        self.fields.rebuild(
            specs, self._options_by_backend.get(name, {}), llm_logic.inherited_defaults(self.config_data, name)
        )
        self.options_label.setText(f"Settings only {name} understands" if specs else "Backend settings")

    def _show_backend_info(self) -> None:
        """The availability line and the model list of the selected backend; probed off the UI thread once."""
        name = self.backend_name()
        self.model_hint.setText(llm_logic.model_note(name))
        info = self._backend_info.get(name)
        if info is not None:
            self._apply_backend_info(name, info)
            return
        self.backend_hint.setText(f"Querying {name}…")
        widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE)
        section = llm_logic.backend_section(self.config_data, name)

        def query() -> Tuple[Optional[str], List[str]]:
            module = llm_backends.get(name)
            version = module.version(section)
            return version, (list(module.list_models(section)) if version else [])

        def apply(result: Any) -> None:
            info = result if result is not None else (None, [])
            self._backend_info[name] = info
            if self.backend_name() == name:
                self._apply_backend_info(name, info)

        self._probe("backend:" + name, query, apply)

    def _apply_backend_info(self, name: str, info: Tuple[Optional[str], List[str]]) -> None:
        version, models = info
        text = llm_logic.backend_hint(self.config_data, name, version)
        if self.stored_backend() == "":
            text = llm_logic.UNSET_BACKEND_NOTE + " " + text
        self.backend_hint.setText(text)
        widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE if version else widgets.STATUS_FAIL)
        typed = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setEditText(typed)
        self.model_combo.blockSignals(False)

    # -- the item itself
    def _names(self) -> List[str]:
        return sorted(llm_logic.connections_of(self.config_data))

    def _load(self, name: Optional[str]) -> None:
        raw = llm_logic.stored_connection(self.config_data, name)
        self.backend_combo.blockSignals(True)
        self.backend_combo.setCurrentText(llm_logic.connection_backend(raw))
        self.backend_combo.blockSignals(False)
        self.description_edit.setText(str(raw.get("description") or ""))
        self.model_combo.setEditText(str(raw.get("model") or ""))
        timeout = raw.get("timeout")
        self.timeout_edit.setText("" if timeout is None else str(timeout))
        self.extra_args_edit.setText(llm_logic.format_args(raw.get("extra_args")))
        self.env_text.setPlainText(llm_logic.format_env(raw.get("env")))
        # the memo is per connection: settings typed for one connection never carry over to another
        self._options_by_backend = {self.backend_name(): llm_backends.stored_options(raw)}
        # a connection without a backend (the first installed agent) keeps it unset until one is chosen here
        self._backend_unset = not str(raw.get("backend") or "")
        self._backend_chosen = False
        self._fields_backend = None
        self._rebuild_fields()
        self._show_backend_info()

    def current_texts(self) -> Dict[str, str]:
        return {
            "description": self.description_edit.text(),
            "model": self.model_combo.currentText(),
            "timeout": self.timeout_edit.text(),
            "extra_args": self.extra_args_edit.text(),
        }

    def _store(self, name: Optional[str]) -> bool:
        if name is None or name not in llm_logic.connections_of(self.config_data):
            return True
        env, problem = llm_logic.parse_env(self.env_text.toPlainText())
        if env is None:
            self._error(problem or "")
            return False
        connection, problem = llm_logic.build_connection(
            self.current_texts(), self.stored_backend(), self.fields.values(), env
        )
        if connection is None:
            self._error(problem or "")
            return False
        error = llm_logic.store_connection(self.config_data, name, connection)
        if error is not None:
            self._error(error)
            return False
        return True

    def _new_item(self) -> Optional[str]:
        name = self._ask_name("Name of the new connection:")
        if name is None:
            return None
        backend = llm_backends.first_installed_backend() or llm_backends.DEFAULT_BACKEND
        self.config_data.setdefault(llm_logic.CONNECTIONS, {})[name] = llm_logic.new_connection(backend)
        return name

    def _delete_item(self, name: str) -> None:
        llm_logic.connections_of(self.config_data).pop(name, None)

    def _copy_item(self, source: str, name: str) -> None:
        llm_logic.copy_connection(self.config_data, source, name)

    def _problems(self, config: Dict[str, Any]) -> List[str]:
        problems = []
        for name in sorted(llm_logic.connections_of(config)):
            error = llm_config.validate_connection(config, name)
            if error is not None:
                problems.append(error)
        return problems


# ---- backends -------------------------------------------------------------------------------------------------


class BackendsDialog(LlmDialog):
    """How each coding agent is installed on this machine, and what every connection through it defaults to (the
    connections describe the experiment, this the installation). The registered backends; no Add / Remove."""

    section = llm_logic.BACKENDS
    title_text = "LLM backends"
    list_label = "Backends"
    allow_add_remove = False

    def _build_editor(self, parent: QWidget) -> None:
        form = _form(parent)
        self.about = widgets.caption_label("")
        self.about.setWordWrap(True)
        form.addRow(self.about)
        self.binary_edit = QLineEdit()
        self.browse_button = _no_auto_default(widgets.create_button("Browse…", self._browse))
        hint = _row(form, "Executable:", widgets.hbox(self.binary_edit, self.browse_button), " ")
        assert hint is not None
        self.binary_status = hint
        self.args_edit = QLineEdit()
        _row(
            form,
            "Extra arguments:",
            self.args_edit,
            "Added to every call of this agent, before a connection's own; space separated.",
        )
        self.env_text = _env_editor()
        _row(form, "Environment:", self.env_text, ENV_HINT + " A connection's own values win.")
        form.addRow(widgets.heading_label("Defaults for the connections through this backend"))
        self.fields = FieldGrid(self.mark_dirty)
        form.addRow(self.fields)
        self.binary_edit.textEdited.connect(self.mark_dirty)
        # probing runs the executable: on leaving the field, not on every key
        self.binary_edit.editingFinished.connect(self.refresh_status)
        self.args_edit.textEdited.connect(self.mark_dirty)
        self.env_text.textChanged.connect(self.mark_dirty)

    def _browse(self) -> None:
        path = dialogs.ask_open_file(self, self.title_text)
        if path:
            self.binary_edit.setText(path)
            self.mark_dirty()
            self.refresh_status()

    def refresh_status(self) -> None:
        """Say (after a probe off the UI thread) whether the configured executable can be run."""
        name = self.current
        if name is None:
            self.binary_status.setText("")
            return
        text = self.binary_edit.text()
        self.binary_status.setText("Checking…")
        widgets.set_label_color(self.binary_status, widgets.STATUS_IDLE)

        def apply(result: Any) -> None:
            if self.current != name or self.binary_edit.text() != text:
                return  # another backend, or another path, by now
            resolved, version = result if result is not None else (text, None)
            self.binary_status.setText(llm_logic.binary_status(name, resolved, version))
            widgets.set_label_color(self.binary_status, widgets.STATUS_IDLE if version else widgets.STATUS_FAIL)

        self._probe("binary", lambda: llm_logic.binary_probe(name, text), apply)

    def _names(self) -> List[str]:
        return list(llm_backends.available_backends())

    def _load(self, name: Optional[str]) -> None:
        section = {} if name is None else llm_logic.backend_section(self.config_data, name)
        self.binary_edit.setText(str(section.get("binary") or ""))
        self.args_edit.setText(llm_logic.format_args(section.get("extra_args")))
        self.env_text.setPlainText(llm_logic.format_env(section.get("env")))
        if name is None:
            self.about.setText("")
            self.fields.rebuild((), {}, {})
            self.binary_status.setText("")
            return
        backend = llm_backends.get(name)
        about = str(getattr(backend, "DESCRIPTION", "") or "")
        default_binary = str(getattr(backend, "DEFAULT_BINARY", "") or name)
        env_var = str(getattr(backend, "BINARY_ENV_VAR", "") or "")
        about += ("\n\n" if about else "") + f"Blank executable: '{default_binary}' on PATH."
        if env_var:
            about += f" ${env_var} overrides both."
        self.about.setText(about)
        options = section.get("options")
        self.fields.rebuild(
            llm_backends.fields_of(name),
            options if isinstance(options, dict) else {},
            {spec.key: spec.default for spec in llm_backends.fields_of(name)},
        )
        self.refresh_status()

    def _store(self, name: Optional[str]) -> bool:
        if name is None:
            return True
        env, problem = llm_logic.parse_env(self.env_text.toPlainText())
        if env is None:
            self._error(problem or "")
            return False
        section = llm_logic.build_backend_section(
            self.binary_edit.text(), self.args_edit.text(), env, self.fields.values()
        )
        error = llm_logic.store_backend(self.config_data, name, section)
        if error is not None:
            self._error(error)
            return False
        return True

    def _problems(self, config: Dict[str, Any]) -> List[str]:
        problems = []
        for name in sorted(config.get(llm_logic.BACKENDS) or {}):
            error = llm_config.validate_backend(config, name)
            if error is not None:
                problems.append(error)
        return problems


# ---- opening ------------------------------------------------------------------------------------------------------

KINDS = {"connections": ConnectionsDialog, "backends": BackendsDialog}


def open_llm_dialog(parent: Optional[QWidget], kind: str, path: str) -> Optional[LlmDialog]:
    """The editor ``kind`` ("connections" / "backends") over the file at ``path``, shown (not modal); None when the
    file cannot be read (the reason is shown)."""
    dialog_class = KINDS[kind]
    try:
        config = llm_config.load_config(path)
    except ValueError as error:
        dialogs.show_error(parent, dialog_class.title_text, f"{error}\n\nFix or delete the file, then try again.")
        return None
    dialog = dialog_class(path, config, parent)
    dialog.show()
    return dialog
