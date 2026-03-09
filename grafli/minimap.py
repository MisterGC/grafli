"""Minimap rendering mixin for GrafliView."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen

from grafli.constants import (
    BOX_BORDER,
    MINIMAP_BG,
    MINIMAP_BORDER_COLOR,
    MINIMAP_MARGIN,
    MINIMAP_MAX_H,
    MINIMAP_MAX_W,
    MINIMAP_VIEWPORT_COLOR,
    NOTE_COLOR,
    _resolve_color,
)


class MinimapMixin:
    """Mixin providing minimap rendering and click-to-navigate.

    Expects the host class to have: _minimap_visible, _minimap_rect,
    _minimap_scene_rect, _board, _note_items, viewport(), mapToScene().
    """

    def _draw_minimap(self, painter: QPainter):
        """Draw the minimap overlay. Call from drawForeground."""
        if not self._minimap_visible or not self._board:
            return
        if not self._board.boxes and not self._board.notes:
            return

        painter.resetTransform()
        vp = self.viewport().rect()

        # Compute scene bounding rect of all boxes + notes with padding
        rects = []
        for box in self._board.boxes:
            rects.append(QRectF(box.x, box.y, box.w, box.h))
        for note in self._board.notes:
            ni = self._note_items.get(note.id)
            if ni:
                br = ni.boundingRect()
                rects.append(QRectF(note.x, note.y, br.width(), br.height()))
        if not rects:
            return
        scene_rect = rects[0]
        for r in rects[1:]:
            scene_rect = scene_rect.united(r)
        scene_rect = scene_rect.adjusted(-40, -40, 40, 40)
        self._minimap_scene_rect = scene_rect

        # Fit into minimap dimensions preserving aspect ratio
        aspect = scene_rect.width() / max(scene_rect.height(), 1)
        if aspect > MINIMAP_MAX_W / MINIMAP_MAX_H:
            mw = MINIMAP_MAX_W
            mh = mw / max(aspect, 0.01)
        else:
            mh = MINIMAP_MAX_H
            mw = mh * aspect
        mx = vp.width() - mw - MINIMAP_MARGIN
        my = vp.height() - mh - MINIMAP_MARGIN
        self._minimap_rect = QRectF(mx, my, mw, mh)

        # Background
        painter.setPen(QPen(MINIMAP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(MINIMAP_BG))
        painter.drawRoundedRect(self._minimap_rect, 4, 4)

        # Scale factors
        sx = mw / scene_rect.width()
        sy = mh / scene_rect.height()

        # Draw boxes
        painter.setPen(Qt.PenStyle.NoPen)
        for box in self._board.boxes:
            color_hex = _resolve_color(box.color) if box.color else ""
            if color_hex:
                c = QColor(color_hex)
            else:
                c = QColor(BOX_BORDER)
            painter.setBrush(QBrush(c))
            bx = mx + (box.x - scene_rect.x()) * sx
            by = my + (box.y - scene_rect.y()) * sy
            bw = max(box.w * sx, 2)
            bh = max(box.h * sy, 2)
            painter.drawRect(QRectF(bx, by, bw, bh))

        # Draw notes as small markers
        for note in self._board.notes:
            painter.setBrush(QBrush(NOTE_COLOR))
            nx = mx + (note.x - scene_rect.x()) * sx
            ny = my + (note.y - scene_rect.y()) * sy
            painter.drawRect(QRectF(nx, ny, max(3, 20 * sx), max(3, 20 * sy)))

        # Viewport indicator
        vp_scene = self.mapToScene(vp).boundingRect()
        vx = mx + (vp_scene.x() - scene_rect.x()) * sx
        vy = my + (vp_scene.y() - scene_rect.y()) * sy
        vw = vp_scene.width() * sx
        vh = vp_scene.height() * sy
        vp_rect = QRectF(vx, vy, vw, vh).intersected(self._minimap_rect)
        painter.setBrush(QBrush(MINIMAP_VIEWPORT_COLOR))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        painter.drawRect(vp_rect)

    def _minimap_viewport_rect(self) -> QRectF:
        """Compute the viewport indicator rect in minimap (widget) coords."""
        mr = self._minimap_rect
        sr = self._minimap_scene_rect
        if mr.isNull() or sr.isNull():
            return QRectF()
        sx = mr.width() / sr.width()
        sy = mr.height() / sr.height()
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        vx = mr.x() + (vp_scene.x() - sr.x()) * sx
        vy = mr.y() + (vp_scene.y() - sr.y()) * sy
        vw = vp_scene.width() * sx
        vh = vp_scene.height() * sy
        return QRectF(vx, vy, vw, vh).intersected(mr)

    def _minimap_to_scene(self, minimap_pos: QPointF) -> QPointF:
        """Map a minimap widget position to scene coordinates."""
        mr = self._minimap_rect
        sr = self._minimap_scene_rect
        rx = (minimap_pos.x() - mr.x()) / mr.width()
        ry = (minimap_pos.y() - mr.y()) / mr.height()
        return QPointF(sr.x() + rx * sr.width(),
                       sr.y() + ry * sr.height())

    def _minimap_press(self, event_position) -> bool:
        """Handle press on minimap: drag viewport or click-to-jump."""
        if not (self._minimap_visible
                and not self._minimap_rect.isNull()
                and self._minimap_rect.contains(event_position)):
            return False

        vp_ind = self._minimap_viewport_rect()
        if not vp_ind.isNull() and vp_ind.contains(event_position):
            self._minimap_dragging = True
            center = vp_ind.center()
            self._minimap_drag_offset = QPointF(
                event_position.x() - center.x(),
                event_position.y() - center.y(),
            )
        else:
            self.centerOn(self._minimap_to_scene(event_position))
        return True

    def _minimap_move(self, event_position) -> bool:
        """Handle drag on minimap viewport indicator."""
        if not self._minimap_dragging:
            return False
        adjusted = QPointF(
            event_position.x() - self._minimap_drag_offset.x(),
            event_position.y() - self._minimap_drag_offset.y(),
        )
        self.centerOn(self._minimap_to_scene(adjusted))
        return True

    def _minimap_release(self) -> bool:
        """End minimap viewport drag."""
        if not self._minimap_dragging:
            return False
        self._minimap_dragging = False
        return True
