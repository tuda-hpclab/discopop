# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Picks a subset of the parallelization suggestions by ID.

The control shows only the suggestion IDs (the suggestion browser shows the patches), a Select all / Deselect all
toggle and an entry for comma-separated IDs and ranges (``1,3,5-8``). It is embedded in several places (the Execute
tab, the search space and the evaluation of the Autotuning tab); each instance has its own ``storage_key``, and all
of them persist the set of *de-selected* IDs in ``suggestion_selections.json``, so a newly detected suggestion is
selected by default.
"""

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.services.patches import discover_suggestion_ids
from discopop_library.ProjectManager.services.selections import load_deselected, parse_id_ranges, save_deselected

NO_SUGGESTIONS = "No suggestions available."


class SuggestionSelector(QWidget):
    """A checkbox list of suggestion IDs with select-all and range-entry helpers."""

    def __init__(
        self,
        dot_dp_path: str,
        storage_key: str,
        on_change: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        *,
        list_height: int = 130,
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
        self.list = QListWidget()
        self.list.setMinimumHeight(list_height)
        self.list.itemChanged.connect(self._on_item_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(widgets.hbox(QLabel("Select IDs:"), self.entry, self.apply_button))
        layout.addLayout(widgets.hbox(self.toggle_button, None))
        layout.addWidget(self.list, 1)
        self.refresh()

    # ── public API ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-scan the available IDs and rebuild the list; the stored de-selection is applied again."""
        deselected = load_deselected(self._dot_dp_path, self._storage_key)
        self._ids = discover_suggestion_ids(self._dot_dp_path)
        self._updating = True
        try:
            self.list.clear()
            if not self._ids:
                placeholder = QListWidgetItem(NO_SUGGESTIONS)
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(placeholder)
            for sid in self._ids:
                item = QListWidgetItem(f"Suggestion {sid}")
                item.setData(Qt.ItemDataRole.UserRole, sid)
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Unchecked if sid in deselected else Qt.CheckState.Checked)
                self.list.addItem(item)
        finally:
            self._updating = False
        self._update_toggle_label()

    def get_selected_ids(self) -> List[str]:
        """The checked suggestion IDs, numerically sorted."""
        return [sid for sid, checked in self._states() if checked]

    def get_available_ids(self) -> List[str]:
        """All suggestion IDs currently offered, numerically sorted."""
        return list(self._ids)

    def is_all_selected(self) -> bool:
        """True if every available ID is selected (or there are none)."""
        return all(checked for _, checked in self._states())

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the whole control."""
        self.setEnabled(enabled)

    def set_selected_ids(self, selected: List[str]) -> None:
        """Check exactly ``selected`` (as the entry does); persisted and reported like a click."""
        self._set_checked(set(selected))

    # ── internals ────────────────────────────────────────────────────────────

    def _items(self) -> List[QListWidgetItem]:
        items = [self.list.item(row) for row in range(self.list.count())]
        return [item for item in items if item.data(Qt.ItemDataRole.UserRole) is not None]

    def _states(self) -> List[tuple[str, bool]]:
        return [
            (str(item.data(Qt.ItemDataRole.UserRole)), item.checkState() == Qt.CheckState.Checked)
            for item in self._items()
        ]

    def _set_checked(self, selected: "set[str]") -> None:
        self._updating = True
        try:
            for item in self._items():
                sid = str(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(Qt.CheckState.Checked if sid in selected else Qt.CheckState.Unchecked)
        finally:
            self._updating = False
        self._after_change()

    def _on_toggle_all(self) -> None:
        # all selected -> deselect all; otherwise select all
        self._set_checked(set() if self.is_all_selected() else set(self._ids))

    def _on_apply_entry(self) -> None:
        self._set_checked(set(parse_id_ranges(self.entry.text(), self._ids)))

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        if not self._updating:
            self._after_change()

    def _after_change(self) -> None:
        self._update_toggle_label()
        save_deselected(self._dot_dp_path, self._storage_key, (sid for sid, checked in self._states() if not checked))
        if self._on_change is not None:
            self._on_change()

    def _update_toggle_label(self) -> None:
        self.toggle_button.setText("Deselect all" if self.is_all_selected() and self._ids else "Select all")
