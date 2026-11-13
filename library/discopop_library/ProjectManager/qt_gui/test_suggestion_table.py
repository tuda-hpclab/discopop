# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Optional

from pytestqt.qtbot import QtBot
from PySide6.QtCore import Qt

from discopop_library.ProjectManager.plots import hotspot_charts
from discopop_library.ProjectManager.qt_gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.qt_gui.suggestion_table import SuggestionTable
from discopop_library.ProjectManager.services.suggestions import SuggestionInfo

INFOS = [
    SuggestionInfo("10", "reduction", "b.c", "/p/b.c", 7, 9, "#pragma omp parallel for reduction(+:s)", "sum", "NO"),
    SuggestionInfo("2", "doall", "a.c", "/p/a.c", 20, 22, "#pragma omp parallel for", "main", "YES"),
    SuggestionInfo("9", "doall", "a.c", "/p/a.c", 5, 6, "#pragma omp parallel for", "init", "MAYBE"),
    SuggestionInfo("1"),
]


def column(table: SuggestionTable, name: int) -> List[str]:
    return [table.proxy.index(row, name).data() for row in range(table.proxy.rowCount())]


def test_ids_sort_numerically_and_hotness_by_heat(qtbot: QtBot) -> None:
    table = SuggestionTable()
    qtbot.addWidget(table)
    table.set_suggestions(INFOS)
    assert column(table, 0) == ["1", "2", "9", "10"]
    table.view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert column(table, 0) == ["10", "9", "2", "1"]
    table.view.sortByColumn(4, Qt.SortOrder.AscendingOrder)
    assert column(table, 4) == ["YES", "MAYBE", "NO", "—"]
    table.view.sortByColumn(2, Qt.SortOrder.AscendingOrder)
    assert column(table, 2) == ["a.c:5", "a.c:20", "b.c:7", "—"]


def test_hotness_is_colored_and_missing_values_are_dashes(qtbot: QtBot) -> None:
    table = SuggestionTable()
    qtbot.addWidget(table)
    table.set_suggestions(INFOS)
    row = column(table, 0).index("2")
    brush = table.proxy.index(row, 4).data(Qt.ItemDataRole.ForegroundRole)
    assert brush.color().name() == hotspot_charts.hotness_color("YES").lower()
    assert table.proxy.index(column(table, 0).index("1"), 1).data() == "—"


def test_filters_narrow_the_rows_and_the_empty_states_say_why(qtbot: QtBot) -> None:
    table = SuggestionTable(empty_text="Nothing here")
    qtbot.addWidget(table)
    assert table.stack.currentWidget() is table.empty_label and table.empty_label.text() == "Nothing here"
    table.set_suggestions(INFOS)
    assert table.stack.currentWidget() is table.view and table.type_combo.count() == 3
    table.filter_edit.setText("a.c main")
    assert table.visible_ids() == ["2"]
    table.filter_edit.setText("")
    table.type_combo.setCurrentText("reduction")
    assert table.visible_ids() == ["10"] and table.count_label.text() == "1 of 4 shown"
    table.filter_edit.setText("zzz")
    assert table.stack.currentWidget() is table.empty_label and "filter" in table.empty_label.text()


def test_the_current_suggestion_is_reported_and_kept(qtbot: QtBot) -> None:
    table = SuggestionTable()
    qtbot.addWidget(table)
    seen: List[Optional[str]] = []
    table.current_changed.connect(lambda info: seen.append(info.id if info else None))
    table.set_suggestions(INFOS)
    assert table.select_id("9") and seen[-1] == "9"
    table.set_suggestions(INFOS)  # same content: the row stays current
    current = table.current_suggestion()
    assert current is not None and current.id == "9"
    table.set_suggestions(INFOS[:2])  # gone
    assert table.current_suggestion() is None and seen[-1] is None


def test_check_marks_survive_filters(qtbot: QtBot) -> None:
    table = SuggestionTable(checkable=True)
    qtbot.addWidget(table)
    changes: List[bool] = []
    table.checks_changed.connect(lambda: changes.append(True))
    table.set_suggestions(INFOS, {"1", "2"})
    assert table.checked_ids() == ["1", "2"]
    table.type_combo.setCurrentText("reduction")
    assert table.visible_ids() == ["10"] and table.checked_ids() == ["1", "2"]
    table.set_checked_ids({"10", "unknown"})
    assert table.checked_ids() == ["10"] and changes


def test_selector_filters_do_not_change_the_selection(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    for sid in ("1", "2"):
        (tmp_path / "patch_generator" / sid).mkdir(parents=True)
        (tmp_path / "patch_generator" / sid / "1.patch").write_text("")
    selector = SuggestionSelector(str(tmp_path), "execute")
    qtbot.addWidget(selector)
    selector.table.filter_edit.setText("2")
    assert selector.table.visible_ids() == ["2"] and selector.get_selected_ids() == ["1", "2"]
    selector.toggle_button.click()
    assert selector.get_selected_ids() == [] and selector.table.visible_ids() == ["2"]
