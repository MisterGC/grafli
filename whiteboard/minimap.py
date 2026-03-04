"""Minimap rendering mixin for WhiteboardView."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen

from whiteboard.constants import (
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
            for ni in self._note_items:
                if ni.note is note:
                    br = ni.boundingRect()
                    rects.append(QRectF(note.x, note.y, br.width(), br.height()))
                    break
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

    def _minimap_click(self, event_position) -> bool:
        """Handle click-to-navigate on minimap. Returns True if consumed."""
        if (self._minimap_visible
                and not self._minimap_rect.isNull()
                and self._minimap_rect.contains(event_position)):
            sr = self._minimap_scene_rect
            mr = self._minimap_rect
            rx = (event_position.x() - mr.x()) / mr.width()
            ry = (event_position.y() - mr.y()) / mr.height()
            target = QPointF(sr.x() + rx * sr.width(),
                             sr.y() + ry * sr.height())
            self.centerOn(target)
            return True
        return False
