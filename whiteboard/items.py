"""Graphics items for the whiteboard: boxes, notes, labels, arrows, handles."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QTextOption
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from whiteboard.constants import (
    BOX_BORDER_WIDTH,
    BOX_FONT_SIZES,
    BOX_RADIUS,
    FONT_FAMILY,
    HANDLE_SIZE,
    MIN_BOX_SIZE,
    NOTE_FONT_FAMILY,
    NOTE_FONT_SIZES,
    SCENE_BG,
    _resolve_color,
)
from whiteboard.format import Box, Note

# ── Handle IDs ───────────────────────────────────────────────────

_CORNER_TL = 0
_CORNER_TR = 1
_CORNER_BL = 2
_CORNER_BR = 3
_EDGE_T = 4
_EDGE_R = 5
_EDGE_B = 6
_EDGE_L = 7

_HANDLE_CURSORS = {
    _CORNER_TL: Qt.CursorShape.SizeFDiagCursor,
    _CORNER_TR: Qt.CursorShape.SizeBDiagCursor,
    _CORNER_BL: Qt.CursorShape.SizeBDiagCursor,
    _CORNER_BR: Qt.CursorShape.SizeFDiagCursor,
    _EDGE_T: Qt.CursorShape.SizeVerCursor,
    _EDGE_B: Qt.CursorShape.SizeVerCursor,
    _EDGE_L: Qt.CursorShape.SizeHorCursor,
    _EDGE_R: Qt.CursorShape.SizeHorCursor,
}


def _get_view(item):
    """Get the first view from an item's scene, or None."""
    scene = item.scene()
    if scene and scene.views():
        return scene.views()[0]
    return None


# ── Graphics items ───────────────────────────────────────────────


class ResizeHandle(QGraphicsRectItem):
    """Small handle for resizing a BoxItem (corner or edge)."""

    def __init__(self, handle_id: int, parent: QGraphicsRectItem):
        hs = HANDLE_SIZE
        super().__init__(-hs / 2, -hs / 2, hs, hs, parent)
        self.corner = handle_id
        self.setPen(QPen(QColor("#2F5D5C"), 1))
        self.setBrush(QBrush(QColor("#FFFFFF")))
        self.setCursor(_HANDLE_CURSORS[handle_id])
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setVisible(False)


class BoxItem(QGraphicsRectItem):
    """A draggable box with centered label text."""

    def __init__(self, box: Box):
        super().__init__(0, 0, box.w, box.h)
        self.box = box
        self.setPos(box.x, box.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self._min_h = box.h

        # Resize handles (must exist before _auto_grow)
        self._handles: list[ResizeHandle] = [
            ResizeHandle(_CORNER_TL, self),
            ResizeHandle(_CORNER_TR, self),
            ResizeHandle(_CORNER_BL, self),
            ResizeHandle(_CORNER_BR, self),
            ResizeHandle(_EDGE_T, self),
            ResizeHandle(_EDGE_R, self),
            ResizeHandle(_EDGE_B, self),
            ResizeHandle(_EDGE_L, self),
        ]
        self._resizing = False

        self._label = QGraphicsTextItem(self)
        self._label.setFont(self._box_font())
        self._label.setDefaultTextColor(QColor("#2F3437"))
        self._label.setPlainText(box.label)
        self._label.setTextWidth(box.w - 16)
        self._apply_color()
        self._position_label()
        self._auto_grow()

        if box.annotation:
            self.setToolTip(box.annotation)

        self._update_handles()
        self._resize_corner = -1
        self._resize_origin = QPointF()

    def _apply_color(self):
        hex_color = _resolve_color(self.box.color)
        is_flat = self.box.style == "flat"
        if hex_color:
            c = QColor(hex_color)
            if is_flat:
                self.setPen(QPen(Qt.PenStyle.NoPen))
                c.setAlphaF(0.7)
            else:
                self.setPen(QPen(c.darker(125), BOX_BORDER_WIDTH))
            self.setBrush(QBrush(c))
        else:
            if is_flat:
                self.setPen(QPen(Qt.PenStyle.NoPen))
                fill = QColor(SCENE_BG)
                fill.setAlphaF(0.7)
                self.setBrush(QBrush(fill))
            else:
                self.setPen(QPen(QColor("#2F3437"), BOX_BORDER_WIDTH))
                self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._label.setDefaultTextColor(QColor("#2F3437"))

    def set_color(self, color: str):
        self.box.color = color
        self._apply_color()
        self.update()

    def set_style(self, style: str):
        self.box.style = style
        self._apply_color()
        self.update()

    # ── Auto layout helpers ──

    def _get_effective_anchor(self) -> str:
        if self.box.anchor:
            return self.box.anchor
        view = _get_view(self)
        if view and hasattr(view, '_has_children') and view._has_children(self.box.id):
            return "topleft"
        return ""

    def _get_effective_textsize(self) -> str:
        if self.box.textsize:
            return self.box.textsize
        view = _get_view(self)
        if view and hasattr(view, '_has_children') and view._has_children(self.box.id):
            return "small"
        return ""

    def _box_font(self) -> QFont:
        return QFont(FONT_FAMILY, BOX_FONT_SIZES.get(self._get_effective_textsize(), 13))

    def _position_label(self):
        br = self._label.boundingRect()
        w = self.box.w
        h = self.box.h
        anchor = self._get_effective_anchor()
        doc = self._label.document()
        opt = QTextOption()
        if anchor == "topleft":
            opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self._label.setPos(8, 8)
        elif anchor == "topcenter":
            opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._label.setPos((w - br.width()) / 2, 8)
        else:
            opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._label.setPos((w - br.width()) / 2, (h - br.height()) / 2)
        doc.setDefaultTextOption(opt)

    def refresh_auto_layout(self):
        """Re-apply font and label position based on current effective values."""
        self._label.setFont(self._box_font())
        self._auto_grow()
        self._position_label()
        self.update()

    def set_anchor(self, anchor: str):
        self.box.anchor = anchor
        self._position_label()
        self.update()

    def set_textsize(self, textsize: str):
        self.box.textsize = textsize
        self._label.setFont(self._box_font())
        self._auto_grow()
        self._position_label()
        self.update()

    def update_label(self, text: str):
        self.box.label = text
        self._label.setPlainText(text)
        self._auto_grow()
        self._position_label()

    def _auto_grow(self):
        needed = self._label.boundingRect().height() + 16
        new_h = max(self._min_h, needed)
        if new_h != self.box.h:
            self.box.h = new_h
            self.setRect(0, 0, self.box.w, self.box.h)
            self._update_handles()
            view = _get_view(self)
            if view and hasattr(view, 'arrow_update_needed'):
                view.arrow_update_needed.emit()
                view.mark_dirty()

    def _update_handles(self):
        r = self.rect()
        self._handles[_CORNER_TL].setPos(r.topLeft())
        self._handles[_CORNER_TR].setPos(r.topRight())
        self._handles[_CORNER_BL].setPos(r.bottomLeft())
        self._handles[_CORNER_BR].setPos(r.bottomRight())
        cx = (r.left() + r.right()) / 2
        cy = (r.top() + r.bottom()) / 2
        self._handles[_EDGE_T].setPos(cx, r.top())
        self._handles[_EDGE_R].setPos(r.right(), cy)
        self._handles[_EDGE_B].setPos(cx, r.bottom())
        self._handles[_EDGE_L].setPos(r.left(), cy)

    def _show_handles(self, visible: bool):
        for h in self._handles:
            h.setVisible(visible)

    def _handle_at(self, pos: QPointF) -> int | None:
        hit = HANDLE_SIZE + 8
        r = self.rect()
        # Check corners first (priority over edges)
        corners = [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]
        for i, cp in enumerate(corners):
            if abs(pos.x() - cp.x()) < hit and abs(pos.y() - cp.y()) < hit:
                return i
        # Check edge midpoints
        cx = (r.left() + r.right()) / 2
        cy = (r.top() + r.bottom()) / 2
        edges = [
            (_EDGE_T, QPointF(cx, r.top())),
            (_EDGE_R, QPointF(r.right(), cy)),
            (_EDGE_B, QPointF(cx, r.bottom())),
            (_EDGE_L, QPointF(r.left(), cy)),
        ]
        for eid, ep in edges:
            if abs(pos.x() - ep.x()) < hit and abs(pos.y() - ep.y()) < hit:
                return eid
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = _get_view(self)
            if view and hasattr(view, '_grid_visible') and view._grid_visible:
                spacing = view.GRID_SPACING
                new_pos = value
                return QPointF(
                    round(new_pos.x() / spacing) * spacing,
                    round(new_pos.y() / spacing) * spacing,
                )
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            dx = self.pos().x() - self.box.x
            dy = self.pos().y() - self.box.y
            self.box.x = self.pos().x()
            self.box.y = self.pos().y()
            view = _get_view(self)
            if view and hasattr(view, '_propagating_move'):
                if not view._propagating_move:
                    view._propagating_move = True
                    for child_item in view._descendants(self.box.id):
                        child_item.moveBy(dx, dy)
                    view._propagating_move = False
                view.arrow_update_needed.emit()
                view.mark_dirty()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._show_handles(bool(value))
        return super().itemChange(change, value)

    def boundingRect(self):
        r = super().boundingRect()
        if self.isSelected():
            return r.adjusted(-4, -4, 4, 4)
        return r

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            corner = self._handle_at(event.pos())
            if corner is not None and self.isSelected():
                self._resizing = True
                self._resize_corner = corner
                self._resize_origin = event.pos()
                self.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False
                )
                view = _get_view(self)
                if view and hasattr(view, '_save_pre_action_snapshot'):
                    view._save_pre_action_snapshot()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.pos().x() - self._resize_origin.x()
            dy = event.pos().y() - self._resize_origin.y()
            self._resize_origin = event.pos()
            x, y, w, h = self.box.x, self.box.y, self.box.w, self.box.h

            c = self._resize_corner
            if c == _CORNER_TL:
                x += dx; y += dy; w -= dx; h -= dy
            elif c == _CORNER_TR:
                y += dy; w += dx; h -= dy
            elif c == _CORNER_BL:
                x += dx; w -= dx; h += dy
            elif c == _CORNER_BR:
                w += dx; h += dy
            elif c == _EDGE_T:
                y += dy; h -= dy
            elif c == _EDGE_B:
                h += dy
            elif c == _EDGE_L:
                x += dx; w -= dx
            elif c == _EDGE_R:
                w += dx

            # Clamp to minimum size
            if w < MIN_BOX_SIZE:
                if c in (_CORNER_TL, _CORNER_BL, _EDGE_L):
                    x -= MIN_BOX_SIZE - w
                w = MIN_BOX_SIZE
            if h < MIN_BOX_SIZE:
                if c in (_CORNER_TL, _CORNER_TR, _EDGE_T):
                    y -= MIN_BOX_SIZE - h
                h = MIN_BOX_SIZE

            self.box.x = x
            self.box.y = y
            self.box.w = w
            self.box.h = h
            self.setPos(x, y)
            self.setRect(0, 0, w, h)
            self._label.setTextWidth(w - 16)
            self._position_label()
            self._update_handles()

            view = _get_view(self)
            if view and hasattr(view, 'arrow_update_needed'):
                view.arrow_update_needed.emit()

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._min_h = self.box.h
            self.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True
            )
            view = _get_view(self)
            if view and hasattr(view, '_commit_pre_action_snapshot'):
                view._commit_pre_action_snapshot()
                view.mark_dirty()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        radius = 0 if self.box.style == "flat" else BOX_RADIUS
        painter.drawRoundedRect(self.rect(), radius, radius)

        # Label background — semi-transparent bright rect for contrast
        if _resolve_color(self.box.color):
            label_rect = self._label.mapRectToParent(self._label.boundingRect())
            bg = QColor("#F2F0EB")
            bg.setAlphaF(0.6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(label_rect, 4, 4)

        if self.box.annotation:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#0178D4")))
            painter.drawEllipse(
                QPointF(self.rect().right() - 10, self.rect().top() + 10), 4, 4
            )

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = self.rect().adjusted(-3, -3, 3, 3)
            painter.drawRoundedRect(sel_rect, radius, radius)


class NoteItem(QGraphicsSimpleTextItem):
    """A draggable free-text note."""

    def __init__(self, note: Note):
        super().__init__(note.text)
        self.note = note
        self.setPos(note.x, note.y)
        self.setFont(self._note_font())
        self._apply_color()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        if note.annotation:
            self.setToolTip(note.annotation)

    def boundingRect(self):
        return super().boundingRect().adjusted(-4, -4, 4, 4)

    def paint(self, painter: QPainter, option, widget=None):
        # Semi-transparent background for readability
        pad = 4
        base_rect = QGraphicsSimpleTextItem.boundingRect(self)
        bg_rect = base_rect.adjusted(-pad, -pad, pad, pad)
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bg_rect, 4, 4)

        super().paint(painter, option, widget)
        if self.note.annotation:
            base_rect = QGraphicsSimpleTextItem.boundingRect(self)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#0178D4")))
            painter.drawEllipse(
                QPointF(base_rect.right() + 2, base_rect.top()), 4, 4
            )
        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            base_rect = QGraphicsSimpleTextItem.boundingRect(self)
            sel_rect = base_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)

    def _apply_color(self):
        hex_color = _resolve_color(self.note.color)
        if hex_color:
            self.setBrush(QBrush(QColor(hex_color)))
        else:
            self.setBrush(QBrush(QColor("#2F3437")))

    def _note_font(self) -> QFont:
        family = FONT_FAMILY if self.note.style == "mono" else NOTE_FONT_FAMILY
        return QFont(family, NOTE_FONT_SIZES.get(self.note.textsize, 11))

    def set_color(self, color: str):
        self.note.color = color
        self._apply_color()
        self.update()

    def set_textsize(self, textsize: str):
        self.note.textsize = textsize
        self.setFont(self._note_font())
        self.update()

    def set_style(self, style: str):
        self.note.style = style
        self.setFont(self._note_font())
        self.update()

    def update_text(self, text: str):
        self.note.text = text
        self.setText(text)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = _get_view(self)
            if view and hasattr(view, '_grid_visible') and view._grid_visible:
                spacing = view.GRID_SPACING
                new_pos = value
                return QPointF(
                    round(new_pos.x() / spacing) * spacing,
                    round(new_pos.y() / spacing) * spacing,
                )
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.note.x = self.pos().x()
            self.note.y = self.pos().y()
            view = _get_view(self)
            if view and hasattr(view, 'mark_dirty'):
                view.mark_dirty()
        return super().itemChange(change, value)


class LabelItem(QGraphicsSimpleTextItem):
    """Arrow label with semi-transparent background."""

    def paint(self, painter: QPainter, option, widget=None):
        pad = 4
        bg_rect = self.boundingRect().adjusted(-pad, -pad, pad, pad)
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bg_rect, 4, 4)
        super().paint(painter, option, widget)


class ArrowLineItem(QGraphicsLineItem):
    """Line item with a wider hit area for easier click-to-select."""

    _HIT_WIDTH = 12

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(self.line().p1())
        path.lineTo(self.line().p2())
        stroker = QPainterPathStroker()
        stroker.setWidth(self._HIT_WIDTH)
        return stroker.createStroke(path)
