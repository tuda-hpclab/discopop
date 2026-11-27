# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The base class of the panels that drive an LLM agent (Patch Repair, Blocker Resolution): their "LLM Agent" box.

The box offers the stored connections of the LLM configuration both tools share (``patch_repair/llm_config.json``),
the first entry being the backend and the model chosen in the box itself. A selected connection shows what it resolves
to, read-only, and the run passes ``--connection``. The backend's version and model list are queried with its install
section (Settings > LLM backends: the executable), not with the name on ``PATH``. What the box shows is computed by
``services/llm_connection_view.py``.
"""

from typing import List, Optional, Tuple

from PySide6.QtWidgets import QComboBox, QLabel

from discopop_library.PatchRepair import llm_backends
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.services import llm_connection_view as llm_view
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkFinished, WorkRunner


class LlmAgentPanel(Panel):
    """A panel with an "LLM Agent" box. Build it with :meth:`build_llm_agent_section`, then call
    :meth:`reload_connections` (the main window calls it again on ``LlmConfigChanged``); a run reads
    :meth:`_selected_connection` and refuses to start while :attr:`_connection_problem` is set; ``cancel_jobs`` calls
    :meth:`_cancel_backend_query`."""

    #: the other tool that reads the LLM configuration, named in the hint of the connection selector
    llm_shared_with = "patch repair"
    #: True: with several stored connections, choosing backend and model in the box is reported as a problem

    def build_llm_agent_section(self, model_hint: str) -> widgets.FormSection:
        """The "LLM Agent" box: connection, backend and model."""
        self._backend_query: Optional[WorkRunner] = None
        self._connections_error = ""
        self._connection_names: List[str] = []
        # why the selected connection cannot be resolved, or the box cannot be run as it stands ("" if it can)
        self._connection_problem = ""
        # built from the registry, so a newly added agent reaches the GUI without a change here
        backends = llm_backends.available_backends()
        installed = llm_backends.first_installed_backend()
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(backends)
        self.backend_combo.setCurrentText(installed or (backends[0] if backends else ""))
        self.backend_combo.currentTextChanged.connect(lambda _text: self._on_backend_changed())
        # Editable, not read-only: a backend's model list depends on which providers are authenticated and is not
        # always exhaustive, so a model missing from it must still be typeable.
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText("")
        # The stored connections; the first entry is choosing the backend and the model here. A selected connection
        # shows what it resolves to, read-only.
        self.connection_combo = QComboBox()
        self.connection_combo.currentTextChanged.connect(lambda _text: self._on_connection_changed())
        # what was chosen by hand, restored when the connection is set back to choosing by hand
        self._manual_choice: Optional[Tuple[str, str]] = None

        section = widgets.FormSection("LLM Agent")
        self.connection_hint: QLabel = self._hint(section.add_row("Connection:", self.connection_combo, " "))
        self.connection_hint.setWordWrap(True)
        self.backend_hint: QLabel = self._hint(section.add_row("Backend:", self.backend_combo, " "))
        section.add_row("Model:", self.model_combo, model_hint, stretch_field=True)
        return section

    @staticmethod
    def _hint(label: Optional[QLabel]) -> QLabel:
        assert label is not None
        return label

    # ── the backend and its models ──────────────────────────────────────────

    def _on_backend_changed(self) -> None:
        """Refresh the model list and say so when the selected agent cannot be run."""
        name = self.backend_combo.currentText()
        try:
            module = llm_backends.get(name)
        except KeyError:
            self.backend_hint.setText("Unknown backend: " + name)
            widgets.set_label_color(self.backend_hint, widgets.STATUS_FAIL)
            return
        # the executable configured under Settings > LLM backends, not only the name on PATH
        section = llm_view.backend_section(self.arguments.dot_dp, name)

        if not module.available(section):
            self.backend_hint.setText(str(getattr(module, "INSTALL_HINT", "")) or (name + " could not be run."))
            widgets.set_label_color(self.backend_hint, widgets.STATUS_FAIL)
            self._set_models([])
            return

        def query_backend(_ctx: WorkContext) -> Tuple[str, List[str]]:
            # version() and list_models() run the agent's own command, which can take a moment; they must not block
            # the UI thread. A failure leaves the list empty and the field still typeable.
            return module.version(section) or "", module.list_models(section)

        def apply(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self._backend_query = None
            if self.backend_combo.currentText() != name:
                return  # another backend was selected in the meantime
            version, models = event.result if event.error is None else ("", [])
            self.backend_hint.setText(llm_view.backend_description(version, str(getattr(module, "DESCRIPTION", ""))))
            widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE)
            self._set_models(models)

        self.backend_hint.setText("Querying " + name + "...")
        widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE)
        self._backend_query = start_work(self, query_backend, apply)

    def _set_models(self, models: List[str]) -> None:
        """Fill the model list; what is typed in the field stays."""
        typed = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(typed)

    def _cancel_backend_query(self) -> None:
        if self._backend_query is not None:
            self._backend_query.cancel()

    # ── the stored connections ──────────────────────────────────────────────

    def reload_connections(self) -> None:
        """Re-read the LLM configuration (call after it changed): the stored connections, where the selection stays
        if the connection still exists, and the backend's executable, so the backend is queried again."""
        backend = self.backend_combo.currentText()
        selected = self.connection_combo.currentText()
        names, error = llm_view.load_connections(self.arguments.dot_dp)
        choices = llm_view.connection_choices(names)
        self.connection_combo.blockSignals(True)
        try:
            self.connection_combo.clear()
            self.connection_combo.addItems(choices)
            self.connection_combo.setCurrentText(selected if selected in choices else llm_view.NO_CONNECTION)
        finally:
            self.connection_combo.blockSignals(False)
        self._connections_error = error
        self._connection_names = names
        self._on_connection_changed()
        if self.backend_combo.currentText() == backend:
            # a changed backend was queried by the selector itself; the same one may have another executable now
            self._on_backend_changed()

    def _selected_connection(self) -> str:
        """The stored connection the run uses; "" when the backend and the model are chosen in the panel."""
        name = self.connection_combo.currentText()
        return "" if name in ("", llm_view.NO_CONNECTION) else name

    def _on_connection_changed(self) -> None:
        name = self._selected_connection()
        if not name:
            if self._manual_choice is not None:
                backend, model = self._manual_choice
                self._manual_choice = None
                self.backend_combo.setCurrentText(backend)
                self.model_combo.setCurrentText(model)
            self.backend_combo.setEnabled(True)
            self.model_combo.setEnabled(True)
            self._connection_problem = self._connections_error
            if self._connection_problem:
                self.connection_hint.setText(self._connection_problem)
                widgets.set_label_color(self.connection_hint, widgets.STATUS_FAIL)
            else:
                self.connection_hint.setText(llm_view.manual_choice_note(self._connection_names, self.llm_shared_with))
                widgets.set_label_color(self.connection_hint, widgets.STATUS_IDLE)
            return
        if self._manual_choice is None:
            self._manual_choice = (self.backend_combo.currentText(), self.model_combo.currentText())
        info = llm_view.resolve_connection(self.arguments.dot_dp, name)
        self._connection_problem = info.error
        if info.error:
            self.connection_hint.setText(info.error)
            widgets.set_label_color(self.connection_hint, widgets.STATUS_FAIL)
        else:
            if info.backend and self.backend_combo.findText(info.backend) < 0:
                self.backend_combo.addItem(info.backend)
            self.backend_combo.setCurrentText(info.backend)
            self.model_combo.setCurrentText(info.model)
            self.connection_hint.setText(info.description)
            widgets.set_label_color(self.connection_hint, widgets.STATUS_IDLE)
        # the connection decides: the fields only show what it resolves to
        self.backend_combo.setEnabled(False)
        self.model_combo.setEnabled(False)
