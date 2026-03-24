"""Graphics items for grafli: boxes, notes, labels, arrows, handles."""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from grafli.constants import (
    BOX_BORDER_WIDTH,
    BOX_FONT_SIZES,
    BOX_RADIUS,
    DISCUSSION_COLORS,
    FONT_FAMILY,
    HANDLE_SIZE,
    MIN_BOX_SIZE,
    NOTE_PEN_COLOR,
    NOTE_QUESTION_COLOR,
    NOTE_TASK_COLOR,
    SCENE_BG,
    _resolve_color,
)

_RE_SPEAKER = re.compile(r"^([A-Z]{2,3}): ")
from grafli.format import Box, Image, Note

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


class BoxLabelItem(QGraphicsTextItem):
    """Scene-level label for a BoxItem, renders above arrows."""

    def __init__(self, box_item: BoxItem):
        super().__init__()
        self._box_item = box_item
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptHoverEvents(False)

    def paint(self, painter: QPainter, option, widget=None):
        if _resolve_color(self._box_item.box.color):
            bg_rect = self.boundingRect()
            bg = QColor("#F2F0EB")
            bg.setAlphaF(0.6)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(bg_rect, 4, 4)
        super().paint(painter, option, widget)


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
        self.setAcceptHoverEvents(True)

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
        self._is_parent = False

        self._label = BoxLabelItem(self)
        self._label.setFont(self._box_font())
        self._label.setDefaultTextColor(QColor("#2F3437"))
        self._label.setPlainText(box.label)
        self._label.setTextWidth(box.w - 16)
        self._apply_color()
        self._position_label()
        self._auto_grow()

        self._update_url_indicator()

        self._update_handles()
        self._resize_corner = -1
        self._resize_origin = QPointF()

    def _apply_color(self):
        hex_color = _resolve_color(self.box.color)
        is_flat = self.box.style == "flat" or self._is_parent
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

    def _update_url_indicator(self):
        """Refresh underline + tooltip based on url and annotation."""
        font = self._label.font()
        font.setUnderline(bool(self.box.url))
        self._label.setFont(font)
        parts = []
        if self.box.annotation:
            parts.append(self.box.annotation)
        if self.box.url:
            parts.append(self.box.url)
        self.setToolTip("\n".join(parts) if parts else "")

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
        bx = self.pos().x()
        by = self.pos().y()
        anchor = self._get_effective_anchor()
        doc = self._label.document()
        opt = QTextOption()
        if anchor == "topleft":
            opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self._label.setPos(bx + 8, by + 8)
        elif anchor == "topcenter":
            opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._label.setPos(bx + (w - br.width()) / 2, by + 8)
        else:
            opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._label.setPos(bx + (w - br.width()) / 2, by + (h - br.height()) / 2)
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
        self._label.setTextWidth(self.box.w - 16)
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
        pass  # resize is via border proximity, no visible handles needed

    def _handle_at(self, pos: QPointF) -> int | None:
        r = self.rect()
        margin = 10

        near_l = abs(pos.x() - r.left()) < margin
        near_r = abs(pos.x() - r.right()) < margin
        near_t = abs(pos.y() - r.top()) < margin
        near_b = abs(pos.y() - r.bottom()) < margin

        in_x = r.left() - margin < pos.x() < r.right() + margin
        in_y = r.top() - margin < pos.y() < r.bottom() + margin

        # Corners (both edges near)
        if near_l and near_t:
            return _CORNER_TL
        if near_r and near_t:
            return _CORNER_TR
        if near_l and near_b:
            return _CORNER_BL
        if near_r and near_b:
            return _CORNER_BR

        # Edges (one edge near, within extent of the other axis)
        if near_t and in_x:
            return _EDGE_T
        if near_b and in_x:
            return _EDGE_B
        if near_l and in_y:
            return _EDGE_L
        if near_r and in_y:
            return _EDGE_R

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
            self._position_label()
            view = _get_view(self)
            if view and hasattr(view, '_propagating_move'):
                if not view._propagating_move:
                    view._propagating_move = True
                    view._suppress_child_updates = True
                    for child_item in view._descendants(self.box.id):
                        child_item.moveBy(dx, dy)
                    view._suppress_child_updates = False
                    view._propagating_move = False
                if not view._suppress_child_updates and not view._batch_move_updates:
                    view.arrow_update_needed.emit()
                    view.mark_dirty()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._show_handles(bool(value))
        return super().itemChange(change, value)

    def boundingRect(self):
        r = super().boundingRect()
        if self.isSelected():
            return r.adjusted(-6, -6, 6, 6)
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

    def _apply_resize_delta(self, dx: float, dy: float, corner: int):
        """Apply a resize delta for the given handle direction."""
        x, y, w, h = self.box.x, self.box.y, self.box.w, self.box.h

        if corner == _CORNER_TL:
            x += dx; y += dy; w -= dx; h -= dy
        elif corner == _CORNER_TR:
            y += dy; w += dx; h -= dy
        elif corner == _CORNER_BL:
            x += dx; w -= dx; h += dy
        elif corner == _CORNER_BR:
            w += dx; h += dy
        elif corner == _EDGE_T:
            y += dy; h -= dy
        elif corner == _EDGE_B:
            h += dy
        elif corner == _EDGE_L:
            x += dx; w -= dx
        elif corner == _EDGE_R:
            w += dx

        # Clamp to minimum size
        if w < MIN_BOX_SIZE:
            if corner in (_CORNER_TL, _CORNER_BL, _EDGE_L):
                x -= MIN_BOX_SIZE - w
            w = MIN_BOX_SIZE
        if h < MIN_BOX_SIZE:
            if corner in (_CORNER_TL, _CORNER_TR, _EDGE_T):
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

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.pos().x() - self._resize_origin.x()
            dy = event.pos().y() - self._resize_origin.y()
            self._resize_origin = event.pos()
            corner = self._resize_corner

            self._apply_resize_delta(dx, dy, corner)

            scene = self.scene()
            if scene:
                for item in scene.selectedItems():
                    if isinstance(item, BoxItem) and item is not self:
                        item._apply_resize_delta(dx, dy, corner)

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

    def hoverMoveEvent(self, event):
        if self.isSelected():
            handle = self._handle_at(event.pos())
            if handle is not None:
                self.setCursor(_HANDLE_CURSORS[handle])
            else:
                self.unsetCursor()
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        radius = 0 if self.box.style == "flat" or self._is_parent else BOX_RADIUS
        painter.drawRoundedRect(self.rect(), radius, radius)

        if self.box.annotation:
            dot_color = QColor("#D4804E")
            dot_color.setAlphaF(0.8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dot_color))
            r = self.rect()
            painter.drawEllipse(QPointF(r.right() - 5, r.top() + 5), 3, 3)

        if self.isSelected():
            sel_rect = self.rect().adjusted(-4, -4, 4, 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            shadow = QColor("#000000")
            shadow.setAlphaF(0.25)
            painter.setPen(QPen(shadow, 7, Qt.PenStyle.SolidLine))
            painter.drawRoundedRect(sel_rect, radius, radius)
            sel_color = QColor("#D4BA6A")
            sel_color.setAlphaF(0.85)
            painter.setPen(QPen(sel_color, 4, Qt.PenStyle.SolidLine))
            painter.drawRoundedRect(sel_rect, radius, radius)


class NoteItem(QGraphicsSimpleTextItem):
    """A draggable free-text note with Neovim-style badge rendering."""

    _PAD = 6
    _BADGE_GAP = 5
    _BADGE_HPAD = 5
    _BADGE_RADIUS = 3
    _BG_RADIUS = 4
    _BLOCK_GAP = 4

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
        self._update_url_indicator()

    def _parse_note(self):
        """Extract badge prefix, body text, and accent color."""
        text = self.note.text
        if text.startswith("T: "):
            return "T:", text[3:], NOTE_TASK_COLOR
        elif text.startswith("Q: "):
            return "Q:", text[3:], NOTE_QUESTION_COLOR
        return "", text, NOTE_PEN_COLOR

    def _parse_discussion(self):
        """Parse speaker blocks for discussion notes.

        Returns list of (speaker, lines, color) tuples when 2+ distinct
        speakers are found, otherwise ``None``.
        """
        lines = self.note.text.split("\n")
        blocks: list[tuple[str, list[str]]] = []
        cur_speaker: str | None = None
        cur_lines: list[str] = []
        speakers: dict[str, int] = {}

        for line in lines:
            m = _RE_SPEAKER.match(line)
            if m:
                if cur_speaker is not None:
                    blocks.append((cur_speaker, cur_lines))
                cur_speaker = m.group(1)
                if cur_speaker not in speakers:
                    speakers[cur_speaker] = len(speakers)
                cur_lines = [line[m.end():]]
            elif cur_speaker is not None:
                cur_lines.append(line)
            else:
                return None

        if cur_speaker is not None:
            blocks.append((cur_speaker, cur_lines))

        if len(speakers) < 2:
            return None

        return [
            (sp, lns, DISCUSSION_COLORS[speakers[sp] % len(DISCUSSION_COLORS)])
            for sp, lns in blocks
        ]

    def _discussion_metrics(self, blocks):
        """Compute shared layout metrics for discussion rendering."""
        font = self._note_font()
        fm = QFontMetricsF(font)
        bold_font = QFont(font)
        bold_font.setBold(True)
        bfm = QFontMetricsF(bold_font)
        line_h = fm.height()
        pad = self._PAD

        max_badge_w = max(
            bfm.horizontalAdvance(sp) + self._BADGE_HPAD * 2
            for sp, _, _ in blocks
        )
        body_w = max(
            (fm.horizontalAdvance(ln) for _, lns, _ in blocks for ln in lns),
            default=0,
        )
        total_lines = sum(len(lns) for _, lns, _ in blocks)
        gap_h = (len(blocks) - 1) * self._BLOCK_GAP
        total_w = pad + max_badge_w + self._BADGE_GAP + body_w + pad
        total_h = pad + total_lines * line_h + gap_h + pad
        return max_badge_w, body_w, line_h, total_w, total_h

    def boundingRect(self):
        discussion = self._parse_discussion()
        if discussion:
            _, _, _, tw, th = self._discussion_metrics(discussion)
            r = QRectF(0, 0, tw, th)
            if self.isSelected():
                return r.adjusted(-4, -4, 4, 4)
            return r

        prefix, body, _ = self._parse_note()
        font = self._note_font()
        fm = QFontMetricsF(font)
        pad = self._PAD

        body_font = QFont(font)
        body_font.setUnderline(bool(self.note.url))
        body_fm = QFontMetricsF(body_font)
        lines = body.split("\n")
        body_w = max((body_fm.horizontalAdvance(ln) for ln in lines), default=0)
        line_h = fm.height()
        n_lines = len(lines)

        if prefix:
            bold_font = QFont(font)
            bold_font.setBold(True)
            bfm = QFontMetricsF(bold_font)
            badge_w = bfm.horizontalAdvance(prefix) + self._BADGE_HPAD * 2
            total_w = pad + badge_w + self._BADGE_GAP + body_w + pad
        else:
            total_w = pad + body_w + pad

        total_h = pad + n_lines * line_h + pad
        r = QRectF(0, 0, total_w, total_h)
        if self.isSelected():
            return r.adjusted(-4, -4, 4, 4)
        return r

    def paint(self, painter: QPainter, option, widget=None):
        discussion = self._parse_discussion()
        if discussion:
            self._paint_discussion(painter, discussion)
            return

        prefix, body, accent = self._parse_note()
        font = self._note_font()
        fm = QFontMetricsF(font)
        pad = self._PAD
        line_h = fm.height()

        body_font = QFont(font)
        body_font.setUnderline(bool(self.note.url))
        body_fm = QFontMetricsF(body_font)
        lines = body.split("\n")
        body_w = max((body_fm.horizontalAdvance(ln) for ln in lines), default=0)
        n_lines = len(lines)

        if prefix:
            bold_font = QFont(font)
            bold_font.setBold(True)
            bfm = QFontMetricsF(bold_font)
            badge_text_w = bfm.horizontalAdvance(prefix)
            badge_w = badge_text_w + self._BADGE_HPAD * 2
            total_w = pad + badge_w + self._BADGE_GAP + body_w + pad
        else:
            badge_w = 0
            total_w = pad + body_w + pad

        total_h = pad + n_lines * line_h + pad
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Light background
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.85)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bg_rect, self._BG_RADIUS, self._BG_RADIUS)

        text_y = pad + fm.ascent()

        if prefix:
            # Badge: solid accent rounded rect with white bold text
            badge_rect = QRectF(pad, pad, badge_w, line_h)
            painter.setBrush(QBrush(accent))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge_rect, self._BADGE_RADIUS, self._BADGE_RADIUS)

            bold_font = QFont(font)
            bold_font.setBold(True)
            painter.setFont(bold_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(
                QPointF(pad + self._BADGE_HPAD, text_y), prefix
            )

            # Body lines in accent color
            painter.setFont(body_font)
            painter.setPen(accent)
            body_x = pad + badge_w + self._BADGE_GAP
            for i, ln in enumerate(lines):
                painter.drawText(QPointF(body_x, text_y + i * line_h), ln)
        else:
            # Plain note: accent-colored text, no badge
            painter.setFont(body_font)
            painter.setPen(accent)
            for i, ln in enumerate(lines):
                painter.drawText(QPointF(pad, text_y + i * line_h), ln)

        if self.note.annotation:
            dot_color = QColor("#D4804E")
            dot_color.setAlphaF(0.8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dot_color))
            painter.drawEllipse(QPointF(bg_rect.right() - 5, bg_rect.top() + 5), 3, 3)

        # Selection indicator
        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)

    def _paint_discussion(self, painter: QPainter, blocks):
        """Render a multi-speaker discussion note."""
        font = self._note_font()
        fm = QFontMetricsF(font)
        pad = self._PAD
        line_h = fm.height()
        bold_font = QFont(font)
        bold_font.setBold(True)

        max_badge_w, _, _, total_w, total_h = self._discussion_metrics(blocks)
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.85)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bg_rect, self._BG_RADIUS, self._BG_RADIUS)

        body_x = pad + max_badge_w + self._BADGE_GAP
        y = pad

        for blk_idx, (speaker, lines, color) in enumerate(blocks):
            # Speaker badge on first line
            bfm = QFontMetricsF(bold_font)
            badge_w = bfm.horizontalAdvance(speaker) + self._BADGE_HPAD * 2
            badge_rect = QRectF(pad, y, badge_w, line_h)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                badge_rect, self._BADGE_RADIUS, self._BADGE_RADIUS
            )

            painter.setFont(bold_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(
                QPointF(pad + self._BADGE_HPAD, y + fm.ascent()), speaker
            )

            # Body lines
            painter.setFont(font)
            painter.setPen(color)
            for ln in lines:
                painter.drawText(QPointF(body_x, y + fm.ascent()), ln)
                y += line_h

            if blk_idx < len(blocks) - 1:
                y += self._BLOCK_GAP

        if self.note.annotation:
            dot_color = QColor("#D4804E")
            dot_color.setAlphaF(0.8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dot_color))
            painter.drawEllipse(
                QPointF(bg_rect.right() - 5, bg_rect.top() + 5), 3, 3
            )

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)

    def _apply_color(self):
        self.update()

    def _note_font(self) -> QFont:
        return QFont(FONT_FAMILY, BOX_FONT_SIZES.get(self.note.textsize, 13))

    def set_color(self, color: str):
        self.note.color = color
        self._apply_color()

    def set_textsize(self, textsize: str):
        self.note.textsize = textsize
        self.setFont(self._note_font())
        self.prepareGeometryChange()
        self.update()

    def set_style(self, style: str):
        pass

    def _update_url_indicator(self):
        """Refresh underline + tooltip based on url and annotation."""
        parts = []
        if self.note.annotation:
            parts.append(self.note.annotation)
        if self.note.url:
            parts.append(self.note.url)
        self.setToolTip("\n".join(parts) if parts else "")
        self.update()

    def update_text(self, text: str):
        self.note.text = text
        self.setText(text)
        self.prepareGeometryChange()
        self._apply_color()

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
            suppress = (view and hasattr(view, '_suppress_child_updates')
                        and (view._suppress_child_updates
                             or view._batch_move_updates))
            if not suppress:
                if view and hasattr(view, 'arrow_update_needed'):
                    view.arrow_update_needed.emit()
                if view and hasattr(view, 'mark_dirty'):
                    view.mark_dirty()
        return super().itemChange(change, value)


class ImageItem(QGraphicsPixmapItem):
    """A draggable image annotation with aspect-ratio-locked resize."""

    _BORDER_PAD = 2
    _HANDLE_PAD = 4
    _MIN_SIZE = 40

    def __init__(self, image: Image, base_dir: str = ""):
        super().__init__()
        self.image = image
        self._base_dir = base_dir
        self._aspect_ratio: float = 1.0
        self._resizing = False
        self._resize_corner = -1
        self._resize_origin = QPointF()

        self._load_pixmap()
        self.setPos(image.x, image.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAcceptHoverEvents(True)

        self._handles: list[ResizeHandle] = [
            ResizeHandle(_CORNER_TL, self),
            ResizeHandle(_CORNER_TR, self),
            ResizeHandle(_CORNER_BL, self),
            ResizeHandle(_CORNER_BR, self),
        ]
        self._update_handles()

    def _load_pixmap(self):
        import os
        path = self.image.image_path
        if self._base_dir and not os.path.isabs(path):
            path = os.path.join(self._base_dir, path)
        pm = QPixmap(path)
        if pm.isNull():
            pm = QPixmap(int(self.image.w), int(self.image.h))
            pm.fill(QColor("#D5D0C8"))
            self._placeholder = True
        else:
            self._aspect_ratio = pm.width() / max(pm.height(), 1)
            self._placeholder = False
        self._full_pixmap = pm

    def _update_handles(self):
        w, h = self.image.w, self.image.h
        positions = {
            _CORNER_TL: (0, 0),
            _CORNER_TR: (w, 0),
            _CORNER_BL: (0, h),
            _CORNER_BR: (w, h),
        }
        for handle in self._handles:
            pos = positions.get(handle.corner)
            if pos:
                handle.setPos(*pos)
            handle.setVisible(self.isSelected())

    def _apply_resize_delta(self, dx: float, dy: float, corner: int):
        x, y, w, h = self.image.x, self.image.y, self.image.w, self.image.h
        ar = self._aspect_ratio

        # Use the larger delta to drive proportional resize
        if corner == _CORNER_TL:
            dw = -dx
            new_w = max(self._MIN_SIZE, w + dw)
            new_h = new_w / ar
            x -= new_w - w
            y -= new_h - h
        elif corner == _CORNER_TR:
            new_w = max(self._MIN_SIZE, w + dx)
            new_h = new_w / ar
            y -= new_h - h
        elif corner == _CORNER_BL:
            dw = -dx
            new_w = max(self._MIN_SIZE, w + dw)
            new_h = new_w / ar
            x -= new_w - w
        elif corner == _CORNER_BR:
            new_w = max(self._MIN_SIZE, w + dx)
            new_h = new_w / ar
        else:
            return

        self.image.x = x
        self.image.y = y
        self.image.w = new_w
        self.image.h = new_h
        self.setPos(x, y)
        self.prepareGeometryChange()
        self._update_handles()
        self.update()

    def boundingRect(self):
        r = QRectF(0, 0, self.image.w, self.image.h)
        if self.isSelected():
            return r.adjusted(-4, -4, 4, 4)
        return r

    def shape(self):
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.image.w, self.image.h))
        return path

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        target = QRectF(0, 0, self.image.w, self.image.h)
        source = QRectF(self._full_pixmap.rect())
        painter.drawPixmap(target, self._full_pixmap, source)

        # Subtle border
        border = QColor("#CDC8BF")
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target)

        if self.image.annotation:
            dot_color = QColor("#D4804E")
            dot_color.setAlphaF(0.8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dot_color))
            painter.drawEllipse(
                QPointF(target.right() - 5, target.top() + 5), 3, 3
            )

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = target.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)

    def hoverMoveEvent(self, event):
        # Check proximity to corner handles for resize cursor
        pos = event.pos()
        w, h = self.image.w, self.image.h
        corners = {
            _CORNER_TL: QPointF(0, 0),
            _CORNER_TR: QPointF(w, 0),
            _CORNER_BL: QPointF(0, h),
            _CORNER_BR: QPointF(w, h),
        }
        for cid, cpos in corners.items():
            if (pos - cpos).manhattanLength() < HANDLE_SIZE * 2:
                self.setCursor(_HANDLE_CURSORS[cid])
                return
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected():
            pos = event.pos()
            w, h = self.image.w, self.image.h
            corners = {
                _CORNER_TL: QPointF(0, 0),
                _CORNER_TR: QPointF(w, 0),
                _CORNER_BL: QPointF(0, h),
                _CORNER_BR: QPointF(w, h),
            }
            for cid, cpos in corners.items():
                if (pos - cpos).manhattanLength() < HANDLE_SIZE * 2:
                    self._resizing = True
                    self._resize_corner = cid
                    self._resize_origin = pos
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
            self._apply_resize_delta(dx, dy, self._resize_corner)
            view = _get_view(self)
            if view and hasattr(view, 'arrow_update_needed'):
                view.arrow_update_needed.emit()
            if view and hasattr(view, 'mark_dirty'):
                view.mark_dirty()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            view = _get_view(self)
            if view and hasattr(view, '_commit_pre_action_snapshot'):
                view._commit_pre_action_snapshot()
            event.accept()
            return
        super().mouseReleaseEvent(event)

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
            self.image.x = self.pos().x()
            self.image.y = self.pos().y()
            view = _get_view(self)
            suppress = (view and hasattr(view, '_suppress_child_updates')
                        and (view._suppress_child_updates
                             or view._batch_move_updates))
            if not suppress:
                if view and hasattr(view, 'arrow_update_needed'):
                    view.arrow_update_needed.emit()
                if view and hasattr(view, 'mark_dirty'):
                    view.mark_dirty()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._update_handles()
        return super().itemChange(change, value)


class LabelItem(QGraphicsSimpleTextItem):
    """Arrow label with semi-transparent background."""

    def paint(self, painter: QPainter, option, widget=None):
        pad = 4
        bg_rect = self.boundingRect().adjusted(-pad, -pad, pad, pad)
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.6)
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
