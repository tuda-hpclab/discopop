# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The workflow sidebar: the stages of the pipeline with what each one has done, instead of a row of equal tabs.

Every stage shows its title, a badge (✓ done, ! stale, ○ not run, 🔒 locked) and a line of detail ("12
suggestions", "sources changed", "needs profiling data"); the stages are grouped into setup, pipeline and results.
A locked stage cannot be selected; its reason is its detail line and tooltip.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.services.workflow_status import StageState, StageStatus

# item data roles
_NAME_ROLE = Qt.ItemDataRole.UserRole
_DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
_STATE_ROLE = Qt.ItemDataRole.UserRole + 2
_SECTION_ROLE = Qt.ItemDataRole.UserRole + 3

BADGES: Dict[Optional[StageState], Tuple[str, str]] = {
    StageState.DONE: ("✓", widgets.STATUS_OK),
    StageState.STALE: ("!", widgets.STATUS_STOP),
    StageState.NOT_RUN: ("○", widgets.STATUS_IDLE),
    StageState.LOCKED: ("🔒", widgets.STATUS_IDLE),
    None: ("", widgets.STATUS_IDLE),
}

_ITEM_HEIGHT = 46
_SECTION_HEIGHT = 26
_BADGE_WIDTH = 26


class _StageDelegate(QStyledItemDelegate):
    """Draws a stage as badge | title over detail, and a section heading as small gray capitals."""

    def sizeHint(  # noqa: N802 (Qt's name)
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        height = _SECTION_HEIGHT if index.data(_SECTION_ROLE) else _ITEM_HEIGHT
        return QSize(option.rect.width(), height)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        painter.save()
        try:
            rect: QRect = option.rect  # type: ignore[attr-defined]
            palette: QPalette = option.palette  # type: ignore[attr-defined]
            state = option.state  # type: ignore[attr-defined]
            font = QFont(option.font)  # type: ignore[attr-defined]
            if index.data(_SECTION_ROLE):
                font.setPointSize(max(font.pointSize() - 1, 7))
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(widgets.STATUS_IDLE))
                painter.drawText(
                    rect.adjusted(12, 6, -8, 0),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    str(index.data(Qt.ItemDataRole.DisplayRole)).upper(),
                )
                return
            enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
            selected = bool(state & QStyle.StateFlag.State_Selected)
            hovered = bool(state & QStyle.StateFlag.State_MouseOver) and enabled
            if selected or hovered:
                background = palette.color(QPalette.ColorRole.Highlight)
                if not selected:
                    background.setAlpha(40)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                painter.drawRoundedRect(rect.adjusted(6, 2, -6, -2), 6, 6)
            text_color = palette.color(
                QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.WindowText
            )
            if not enabled:
                text_color = QColor(widgets.STATUS_IDLE)
            state_value = index.data(_STATE_ROLE)
            badge, badge_color = BADGES.get(state_value, BADGES[None])
            badge_rect = QRect(rect.left() + 10, rect.top(), _BADGE_WIDTH, rect.height())
            badge_font = QFont(font)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(text_color if selected else QColor(badge_color))
            painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), badge)

            text_left = badge_rect.right() + 6
            title_rect = QRect(text_left, rect.top() + 5, rect.right() - text_left - 8, rect.height() // 2 - 3)
            detail_rect = QRect(text_left, rect.top() + rect.height() // 2, title_rect.width(), rect.height() // 2 - 5)
            title_font = QFont(font)
            title_font.setBold(selected)
            painter.setFont(title_font)
            painter.setPen(text_color)
            title = str(index.data(Qt.ItemDataRole.DisplayRole))
            painter.drawText(
                title_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()),
            )
            detail_font = QFont(font)
            detail_font.setPointSize(max(font.pointSize() - 1, 7))
            painter.setFont(detail_font)
            detail_color = QColor(text_color)
            detail_color.setAlpha(170)
            painter.setPen(detail_color)
            detail = str(index.data(_DETAIL_ROLE) or "")
            painter.drawText(
                detail_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, detail_rect.width()),
            )
        finally:
            painter.restore()


class WorkflowNav(QListWidget):
    """The stages as a list; ``stage_selected`` carries the key of the stage the user picked.

    ``sections``: ``(heading, [(key, title), ...])`` in display order.
    """

    stage_selected = Signal(str)

    def __init__(self, sections: Sequence[Tuple[str, Sequence[Tuple[str, str]]]], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setItemDelegate(_StageDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMouseTracking(True)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QListWidget { background: transparent; outline: none; }")
        self._items: Dict[str, QListWidgetItem] = {}
        self._titles: Dict[str, str] = {}
        self._enabled: Dict[str, bool] = {}
        self._locked_reason: Dict[str, str] = {}
        for heading, stages in sections:
            section = QListWidgetItem(heading)
            section.setData(_SECTION_ROLE, True)
            section.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(section)
            for key, title in stages:
                item = QListWidgetItem(title)
                item.setData(_NAME_ROLE, key)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.addItem(item)
                self._items[key] = item
                self._titles[key] = title
                self._enabled[key] = True
        self.currentItemChanged.connect(self._on_current_changed)
        self.setMinimumWidth(200)
        self.setMaximumWidth(260)

    # --- what the main window asks ---

    def stages(self) -> List[str]:
        return list(self._items)

    def title(self, key: str) -> str:
        return self._items[key].text()

    def default_title(self, key: str) -> str:
        return self._titles[key]

    def detail(self, key: str) -> str:
        return str(self._items[key].data(_DETAIL_ROLE) or "")

    def stage_state(self, key: str) -> Optional[StageState]:
        value = self._items[key].data(_STATE_ROLE)
        return value if isinstance(value, StageState) else None

    def item_tooltip(self, key: str) -> str:
        return self._items[key].toolTip()

    def is_stage_enabled(self, key: str) -> bool:
        return self._enabled[key]

    def current_stage(self) -> str:
        item = self.currentItem()
        return str(item.data(_NAME_ROLE)) if item is not None and item.data(_NAME_ROLE) else ""

    # --- changes ---

    def select_stage(self, key: str) -> None:
        self.setCurrentItem(self._items[key])

    def set_title(self, key: str, title: str) -> None:
        self._items[key].setText(title)

    def set_stage_enabled(self, key: str, enabled: bool, reason: str = "") -> None:
        """A disabled stage cannot be selected; ``reason`` is its detail line and tooltip."""
        item = self._items[key]
        self._enabled[key] = enabled
        self._locked_reason[key] = "" if enabled else reason
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        item.setFlags(flags if enabled else Qt.ItemFlag.NoItemFlags)
        item.setToolTip(reason)
        if not enabled:
            item.setData(_STATE_ROLE, StageState.LOCKED)
            item.setData(_DETAIL_ROLE, reason.splitlines()[-1] if reason else "")

    def set_status(self, key: str, status: StageStatus) -> None:
        """Show ``status``; a stage disabled by its panel keeps its lock and reason."""
        item = self._items[key]
        if not self._enabled[key]:
            return
        item.setData(_STATE_ROLE, status.state)
        item.setData(_DETAIL_ROLE, status.detail)
        item.setToolTip(status.detail)

    def _on_current_changed(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        if current is not None and current.data(_NAME_ROLE):
            self.stage_selected.emit(str(current.data(_NAME_ROLE)))
