# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The parallelization suggestions as a table: ID, type, location, function, hotness and pragma.

Shared by the Pattern Detection tab (results view), the suggestion browser and the :class:`SuggestionSelector` (with a
check box column). The rows are :class:`~discopop_library.ProjectManager.services.suggestions.SuggestionInfo`; the
columns sort (IDs numerically, hotness YES before MAYBE before NO, locations by file and line) and a filter line plus a
type filter narrow the rows that are shown. Filters never change which rows are checked.
"""

from typing import Any, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QLineEdit,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.plots import hotspot_charts
from discopop_library.ProjectManager.plots.hotspot_data import HOTNESS_ORDER
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.services.patches import suggestion_order
from discopop_library.ProjectManager.services.suggestions import SuggestionInfo

COLUMN_ID = "ID"
COLUMNS = (COLUMN_ID, "Type", "Location", "Function", "Hotness", "Pragma")
ALL_TYPES = "All types"
NO_SUGGESTIONS_TEXT = "No suggestions yet. Run pattern detection to find parallelization opportunities."
NO_MATCH_TEXT = "No suggestion matches the filter."
_MISSING = "—"
_SORT_ROLE = Qt.ItemDataRole.UserRole + 1

_Index = Any  # QModelIndex or QPersistentModelIndex


class SuggestionModel(QAbstractTableModel):
    """One row per suggestion; with ``checkable`` an extra first column of check boxes."""

    checks_changed = Signal()

    def __init__(self, checkable: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.checkable = checkable
        self._infos: List[SuggestionInfo] = []
        self._checked: Set[str] = set()

    @property
    def offset(self) -> int:
        return 1 if self.checkable else 0

    # ── data ─────────────────────────────────────────────────────────────────

    def set_suggestions(self, infos: Sequence[SuggestionInfo], checked: Optional[Set[str]] = None) -> None:
        """Replace the rows; ``checked``: the IDs with a check mark (default: all of them)."""
        self.beginResetModel()
        self._infos = list(infos)
        self._checked = {info.id for info in infos} if checked is None else {i.id for i in infos if i.id in checked}
        self.endResetModel()

    def info_at(self, row: int) -> Optional[SuggestionInfo]:
        return self._infos[row] if 0 <= row < len(self._infos) else None

    def infos(self) -> List[SuggestionInfo]:
        return list(self._infos)

    def checked_ids(self) -> Set[str]:
        return set(self._checked)

    def set_checked_ids(self, checked: Set[str]) -> None:
        """Check exactly ``checked`` (unknown IDs are ignored); emits ``checks_changed`` once if something changed."""
        wanted = {info.id for info in self._infos if info.id in checked}
        if wanted == self._checked:
            return
        self._checked = wanted
        if self._infos:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._infos) - 1, 0), [Qt.ItemDataRole.CheckStateRole]
            )
        self.checks_changed.emit()

    # ── model interface ──────────────────────────────────────────────────────

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: N802 (Qt's name)
        return 0 if parent.isValid() else len(self._infos)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: N802 (Qt's name)
        return 0 if parent.isValid() else len(COLUMNS) + self.offset

    def headerData(  # noqa: N802 (Qt's name)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            column = section - self.offset
            return COLUMNS[column] if 0 <= column < len(COLUMNS) else ""
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.checkable and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        info = self.info_at(index.row())
        if info is None or not index.isValid():
            return None
        column = index.column() - self.offset
        if column < 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if info.id in self._checked else Qt.CheckState.Unchecked
            if role == _SORT_ROLE:
                return (0 if info.id in self._checked else 1,)
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.cell_text(info, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return info.pragma if COLUMNS[column] == "Pragma" and info.pragma else self.cell_text(info, column)
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 0:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and COLUMNS[column] == "Hotness" and info.hotness:
            return QBrush(QColor(hotspot_charts.hotness_color(info.hotness)))
        if role == _SORT_ROLE:
            return self.sort_key(info, column)
        return None

    def setData(  # noqa: N802 (Qt's name)
        self, index: _Index, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        info = self.info_at(index.row())
        if info is None or not (self.checkable and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole):
            return False
        if Qt.CheckState(value) == Qt.CheckState.Checked:
            self._checked.add(info.id)
        else:
            self._checked.discard(info.id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.checks_changed.emit()
        return True

    @staticmethod
    def cell_text(info: SuggestionInfo, column: int) -> str:
        name = COLUMNS[column]
        if name == COLUMN_ID:
            return info.id
        value = {
            "Type": info.pattern_type,
            "Location": info.location,
            "Function": info.function,
            "Hotness": info.hotness,
            "Pragma": " ".join(info.pragma.split()),
        }[name]
        return value or _MISSING

    @staticmethod
    def sort_key(info: SuggestionInfo, column: int) -> Tuple[Any, ...]:
        name = COLUMNS[column]
        if name == COLUMN_ID:
            return suggestion_order(info.id)
        if name == "Location":
            return (not info.location, info.file_name, info.start_line)
        if name == "Hotness":
            return (HOTNESS_ORDER.index(info.hotness) if info.hotness in HOTNESS_ORDER else len(HOTNESS_ORDER),)
        text = {"Type": info.pattern_type, "Function": info.function, "Pragma": info.pragma}[name]
        return (not text, text.lower())


class _FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.text = ""
        self.pattern_type = ""
        self.setSortRole(_SORT_ROLE)

    def set_filters(self, text: str, pattern_type: str) -> None:
        begin = getattr(self, "beginFilterChange", None)  # Qt >= 6.9 deprecates invalidateFilter
        if begin is not None:
            begin()
        self.text = text.strip().lower()
        self.pattern_type = pattern_type
        if begin is not None:
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: _Index) -> bool:  # noqa: N802 (Qt's name)
        model = self.sourceModel()
        info = model.info_at(row) if isinstance(model, SuggestionModel) else None
        if info is None:
            return False
        if self.pattern_type and info.pattern_type != self.pattern_type:
            return False
        if not self.text:
            return True
        haystack = " ".join((info.id, info.pattern_type, info.location, info.function)).lower()
        return all(word in haystack for word in self.text.split())

    def lessThan(self, left: _Index, right: _Index) -> bool:  # noqa: N802 (Qt's name)
        left_key = left.data(_SORT_ROLE)
        right_key = right.data(_SORT_ROLE)
        if left_key is None or right_key is None:
            return False
        return bool(left_key < right_key)


class SuggestionTable(QWidget):
    """A filter line, a type filter and the sortable table of suggestions; an empty state text when there are none.

    ``current_changed`` carries the :class:`SuggestionInfo` of the current row (``None`` when there is none),
    ``checks_changed`` (only with ``checkable``) fires when a check mark changes. The check marks belong to the
    suggestions, not to the rows shown: a filter hides rows without unchecking them.
    """

    current_changed = Signal(object)
    checks_changed = Signal()

    def __init__(
        self,
        *,
        checkable: bool = False,
        empty_text: str = NO_SUGGESTIONS_TEXT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.model = SuggestionModel(checkable, self)
        self.proxy = _FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.empty_text = empty_text

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by ID, type, location or function")
        self.filter_edit.setClearButtonEnabled(True)
        self.type_combo = QComboBox()
        self.type_combo.addItem(ALL_TYPES)
        self.count_label = widgets.caption_label("")

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(26)
        header = self.view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        offset = self.model.offset
        for column, width in enumerate((50, 80, 140, 120, 70)):
            header.resizeSection(column + offset, width)
        if checkable:
            header.resizeSection(0, 34)
            self.view.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        else:
            self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.empty_label = widgets.empty_state_label(empty_text)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty_label)

        self.filter_bar = QWidget()
        bar = widgets.hbox(self.filter_edit, self.type_combo, margins=0)
        self.filter_bar.setLayout(bar)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.count_label)

        self.filter_edit.textChanged.connect(self._filters_changed)
        self.type_combo.currentTextChanged.connect(self._filters_changed)
        self.view.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        self.model.checks_changed.connect(self.checks_changed)
        self.proxy.layoutChanged.connect(self._update_state)
        self.filter_bar.hide()
        self._update_state()

    # ── content ──────────────────────────────────────────────────────────────

    def set_suggestions(self, infos: Sequence[SuggestionInfo], checked: Optional[Set[str]] = None) -> None:
        """Show ``infos``; the current row and the type filter are kept when they still exist.

        ``checked`` (checkable tables only): the IDs with a check mark, all of them by default.
        """
        previous = self.current_suggestion()
        previous_type = self.type_combo.currentText()
        types = sorted({info.pattern_type for info in infos if info.pattern_type})
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems([ALL_TYPES, *types])
        self.type_combo.setCurrentText(previous_type if previous_type in types else ALL_TYPES)
        self.type_combo.blockSignals(False)
        self.proxy.set_filters(self.filter_edit.text(), self._type_filter())
        self.model.set_suggestions(infos, checked)
        self.filter_bar.setVisible(bool(infos))
        self._update_state()
        if previous is not None and self.select_id(previous.id):
            return
        self.current_changed.emit(None)

    def suggestions(self) -> List[SuggestionInfo]:
        """All suggestions of the table, shown or not, in the order they were set."""
        return self.model.infos()

    def visible_ids(self) -> List[str]:
        """The IDs of the rows the filters let through, in the order of the table."""
        ids = []
        for row in range(self.proxy.rowCount()):
            info = self.model.info_at(self.proxy.mapToSource(self.proxy.index(row, 0)).row())
            if info is not None:
                ids.append(info.id)
        return ids

    def current_suggestion(self) -> Optional[SuggestionInfo]:
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        return self.model.info_at(self.proxy.mapToSource(index).row())

    def select_id(self, suggestion_id: str) -> bool:
        """Make the row of ``suggestion_id`` current; False if it is unknown or filtered out."""
        for row in range(self.proxy.rowCount()):
            source_row = self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            info = self.model.info_at(source_row)
            if info is not None and info.id == suggestion_id:
                self.view.setCurrentIndex(self.proxy.index(row, self.model.offset))
                return True
        return False

    def set_empty_text(self, text: str) -> None:
        self.empty_text = text
        self._update_state()

    # ── check marks ──────────────────────────────────────────────────────────

    def checked_ids(self) -> List[str]:
        """The checked IDs (shown or not), numerically sorted."""
        return sorted(self.model.checked_ids(), key=suggestion_order)

    def set_checked_ids(self, checked: Set[str]) -> None:
        self.model.set_checked_ids(set(checked))

    # ── internals ────────────────────────────────────────────────────────────

    def _type_filter(self) -> str:
        text = self.type_combo.currentText()
        return "" if text == ALL_TYPES else text

    def _filters_changed(self, *_args: Any) -> None:
        self.proxy.set_filters(self.filter_edit.text(), self._type_filter())
        self._update_state()
        if self.current_suggestion() is None:
            self.current_changed.emit(None)

    def _on_current_row_changed(self, current: _Index, _previous: _Index) -> None:
        self.current_changed.emit(self.current_suggestion() if current.isValid() else None)

    def _update_state(self) -> None:
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        if total == 0:
            self.empty_label.setText(self.empty_text)
            self.stack.setCurrentWidget(self.empty_label)
            self.count_label.setText("")
            return
        if shown == 0:
            self.empty_label.setText(NO_MATCH_TEXT)
            self.stack.setCurrentWidget(self.empty_label)
        else:
            self.stack.setCurrentWidget(self.view)
        plural = "" if total == 1 else "s"
        self.count_label.setText(f"{total} suggestion{plural}" if shown == total else f"{shown} of {total} shown")
