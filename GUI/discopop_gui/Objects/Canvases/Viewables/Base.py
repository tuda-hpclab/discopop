# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from discopop_gui.Enums.ViewerMode import ViewerMode
from discopop_gui.Objects.CanvasItems.Popup import Popup


class Base(QGraphicsView):
    def __init__(self, parent: QWidget | None, viewer_mode: ViewerMode) -> None:
        super().__init__(parent)

        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("white")))

        self._viewer_mode = viewer_mode
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_start: QPointF | None = None
        self._last_pan_position: QPointF | None = None
        self._selection_rect: QRectF | None = None
        self._item_callbacks: dict[QGraphicsItem, dict[int, Any]] = {}
        self._popup = Popup(self.viewport())
        self._popup_hide_threshold = 50.0

        self._apply_view_transform()

    def _apply_view_transform(self) -> None:
        transform = QTransform(
            self._zoom,
            0.0,
            0.0,
            self._zoom,
            self._pan_x,
            self._pan_y,
        )

        self.setTransform(transform)

    def _scene_position(self, event: Any) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def _check_popup_distance(self, position: QPointF) -> None:
        if not self._popup.isVisible():
            return

        popup_geometry = self._popup.geometry()

        popup_scene_rect = QRectF(
            self.mapToScene(popup_geometry.topLeft()),
            self.mapToScene(popup_geometry.bottomRight()),
        ).normalized()

        threshold = self._popup_hide_threshold

        if popup_scene_rect.adjusted(-threshold, -threshold, threshold, threshold).contains(position):
            return

        self._popup.hide()

    def _update_selection(self, position: QPointF) -> None:
        if self._drag_start is None:
            return

        self._selection_rect = QRectF(self._drag_start, position).normalized()
        self.scene().update()

    def _apply_zoom(self, scene_position: QPointF, scale: float) -> None:
        viewport_position = self.mapFromScene(scene_position)
        self._zoom *= scale
        self._apply_view_transform()
        new_viewport_position = self.mapFromScene(scene_position)
        delta = viewport_position - new_viewport_position
        self._pan_x += delta.x()
        self._pan_y += delta.y()
        self._apply_view_transform()

    def _zoom_in(self, selection: QRectF) -> None:
        if self.viewport().width() <= 0 or self.viewport().height() <= 0:
            return

        scale = max(
            self.viewport().width() / selection.width(),
            self.viewport().height() / selection.height(),
        )

        self._apply_zoom(selection.center(), scale)

    def _zoom_out(self, selection: QRectF) -> None:
        if self.viewport().width() <= 0 or self.viewport().height() <= 0:
            return

        scale = 1.0 - (
            selection.width() * selection.height()
            / (self.viewport().width() * self.viewport().height())
        )

        self._apply_zoom(selection.center(), max(0.3, min(1.0, scale)))

    def _reset_drag_state(self) -> None:
        self._drag_start = None
        self._last_pan_position = None
        self._selection_rect = None
        self.scene().update()

    def _pan(self, position: QPointF) -> None:
        if self._last_pan_position is None:
            self._last_pan_position = position
            return

        delta = position - self._last_pan_position
        self._pan_x += delta.x()
        self._pan_y += delta.y()
        self._last_pan_position = position
        self._apply_view_transform()

    def mousePressEvent(self, event: Any) -> None:
        position = self._scene_position(event)
        self._check_popup_distance(position)

        item = self.scene().itemAt(position, self.transform())
        if item is not None:
            button = 1 if event.button() == Qt.MouseButton.LeftButton else 3
            callback = self._item_callbacks.get(item, {}).get(button)
            if callback is not None:
                callback(
                    SimpleNamespace(
                        x=event.position().x(),
                        y=event.position().y(),
                    )
                )

        if event.button() == Qt.MouseButton.RightButton and self._viewer_mode == ViewerMode.MAIN:
            self._last_pan_position = event.position()
        elif self._viewer_mode == ViewerMode.ZOOM:
            self._drag_start = position

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        position = self._scene_position(event)
        self._check_popup_distance(position)

        if event.buttons() & Qt.MouseButton.RightButton:
            if self._viewer_mode == ViewerMode.MAIN:
                self._pan(event.position())
            elif self._viewer_mode == ViewerMode.ZOOM:
                self._update_selection(position)
        elif event.buttons() & Qt.MouseButton.LeftButton and self._viewer_mode == ViewerMode.ZOOM:
            self._update_selection(position)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        position = self._scene_position(event)

        if self._viewer_mode == ViewerMode.ZOOM and self._drag_start is not None:
            selection = QRectF(self._drag_start, position).normalized()

            if selection.width() > 5 and selection.height() > 5:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._zoom_in(selection)
                elif event.button() == Qt.MouseButton.RightButton:
                    self._zoom_out(selection)

        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def bind_item(self, item: QGraphicsItem, button: int, callback: Any) -> None:
        self._item_callbacks.setdefault(item, {})[button] = callback

    def get_viewer_mode(self) -> ViewerMode:
        return self._viewer_mode

    def set_viewer_mode(self, viewer_mode: ViewerMode) -> None:
        self._reset_drag_state()
        self._viewer_mode = viewer_mode

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._apply_view_transform()

    def serialize(self) -> dict[str, Any]:
        return {}

    def deserialize(self, data: dict[str, Any]) -> None:
        del data
