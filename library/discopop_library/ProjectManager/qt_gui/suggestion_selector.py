# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Picks a subset of the parallelization suggestions by ID.

The control shows the suggestions as a table (ID, type, location, function, hotness) with a check box per row, a
Select all / Deselect all toggle and an entry for comma-separated IDs and ranges (``1,3,5-8``). It is embedded in
several places (the Execute tab, the search space and the evaluation of the Autotuning tab); each instance has its own
``storage_key``, and all of them persist the set of *de-selected* IDs in ``suggestion_selections.json``, so a newly
detected suggestion is selected by default. The filters of the table only change what is shown, never what is selected.
"""

from typing import Callable, List, Optional

from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.suggestion_table import COLUMNS, SuggestionTable
from discopop_library.ProjectManager.services.selections import load_deselected, parse_id_ranges, save_deselected
from discopop_library.ProjectManager.services.suggestions import load_suggestions

NO_SUGGESTIONS = "No suggestions available."


class SuggestionSelector(QWidget):
    """A table of suggestions with check boxes, select-all and range-entry helpers."""

    def __init__(
        self,
        dot_dp_path: str,
        storage_key: str,
        on_change: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        *,
        list_height: int = 170,
    ) -> None:
        super().__init__(parent)
        self._dot_dp_path = dot_dp_path
        self._storage_key = storage_key
        self._on_change = on_change
        self._ids: List[str] = []
        self._updating = False

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("e.g. 1,3,5-8")
        self.entry.returnPressed.connect(self._on_apply_entry)
        self.apply_button = widgets.create_button("Apply", self._on_apply_entry)
        self.toggle_button: QPushButton = widgets.create_button("Deselect all", self._on_toggle_all)
        self.table = SuggestionTable(checkable=True, empty_text=NO_SUGGESTIONS)
        self.table.setMinimumHeight(list_height)
        # it sits in narrow forms: the function and the pragma are shown by the Pattern Detection stage and the browser
        for name in ("Function", "Pragma"):
            self.table.view.setColumnHidden(self.table.model.offset + COLUMNS.index(name), True)
        self.table.checks_changed.connect(self._on_checks_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(widgets.hbox(QLabel("Select IDs:"), self.entry, self.apply_button, self.toggle_button))
        layout.addWidget(self.table, 1)
        self.refresh()

    # ── public API ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-scan the available suggestions and rebuild the table; the stored de-selection is applied again."""
        deselected = load_deselected(self._dot_dp_path, self._storage_key)
        infos = load_suggestions(self._dot_dp_path)
        self._ids = [info.id for info in infos]
        self._updating = True
        try:
            self.table.set_suggestions(infos, {info.id for info in infos if info.id not in deselected})
        finally:
            self._updating = False
        self._update_toggle_label()

    def get_selected_ids(self) -> List[str]:
        """The checked suggestion IDs, numerically sorted."""
        return self.table.checked_ids()

    def get_available_ids(self) -> List[str]:
        """All suggestion IDs currently offered, numerically sorted."""
        return list(self._ids)

    def is_all_selected(self) -> bool:
        """True if every available ID is selected (or there are none)."""
        return len(self.table.checked_ids()) == len(self._ids)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the whole control."""
        self.setEnabled(enabled)

    def set_selected_ids(self, selected: List[str]) -> None:
        """Check exactly ``selected`` (as the entry does); persisted and reported like a click."""
        self._set_checked(set(selected))

    # ── internals ────────────────────────────────────────────────────────────

    def _set_checked(self, selected: "set[str]") -> None:
        # the model reports a change itself; an unchanged selection is still persisted and reported, as before
        self._updating = True
        try:
            self.table.set_checked_ids(selected)
        finally:
            self._updating = False
        self._after_change()

    def _on_toggle_all(self) -> None:
        # all selected -> deselect all; otherwise select all
        self._set_checked(set() if self.is_all_selected() else set(self._ids))

    def _on_apply_entry(self) -> None:
        self._set_checked(set(parse_id_ranges(self.entry.text(), self._ids)))

    def _on_checks_changed(self) -> None:
        if not self._updating:
            self._after_change()

    def _after_change(self) -> None:
        self._update_toggle_label()
        selected = set(self.table.checked_ids())
        save_deselected(self._dot_dp_path, self._storage_key, (sid for sid in self._ids if sid not in selected))
        if self._on_change is not None:
            self._on_change()

    def _update_toggle_label(self) -> None:
        self.toggle_button.setText("Deselect all" if self.is_all_selected() and self._ids else "Select all")
