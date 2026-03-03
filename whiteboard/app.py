"""Whiteboard desktop app — renders and edits .board files with PySide6."""

from __future__ import annotations

import copy
import enum
import math
import sys
from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QTextCursor,
    QTextOption,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
)

from whiteboard.filewatcher import JsonSafeWatcher
from whiteboard.format import Arrow, Board, Box, Note, parse, serialize


# ── Constants ───────────────────────────────────────────────────

BOX_FILL = QColor("#E8E4DD")
BOX_BORDER = QColor("#2F3437")
ARROW_COLOR = QColor("#2F3437")
NOTE_COLOR = QColor("#D4BA6A")
GRID_COLOR = QColor("#CDC8BF")
SCENE_BG = QColor("#E8E4DD")
CONTENT_BORDER_COLOR = QColor("#D5D0C8")

FONT_FAMILY = "JetBrainsMono Nerd Font"
NOTE_FONT_FAMILY = "Patrick Hand"

BOX_FONT = QFont(FONT_FAMILY, 13)
NOTE_FONT = QFont(NOTE_FONT_FAMILY, 11)
LABEL_FONT = QFont(FONT_FAMILY, 10)

BOX_FONT_SIZES = {"": 13, "small": 10, "large": 18, "xlarge": 24, "xxlarge": 32, "xxxlarge": 44}
NOTE_FONT_SIZES = {"": 11, "small": 9, "large": 15, "xlarge": 21, "xxlarge": 28, "xxxlarge": 40}

BOX_RADIUS = 8
BOX_BORDER_WIDTH = 2
ARROW_WIDTH = 2
ARROWHEAD_SIZE = 10

DEFAULT_BOX_W = 160
DEFAULT_BOX_H = 80
MIN_BOX_SIZE = 20
HANDLE_SIZE = 8

COLOR_TOKENS = {
    "base": "#E8E4DD",
    "primary": "#004578",
    "secondary": "#0178D4",
    "tertiary": "#4EBF71",
    "subtle": "#4A4A4A",
    "accent": "#D4804E",
    "highlight": "#D4BA6A",
    "muted": "#B8B3AB",
    "soft": "#B0A1CA",
}

COLOR_PALETTE = [
    ("Default", ""),
    ("Base", "%base"),
    ("Primary", "%primary"),
    ("Secondary", "%secondary"),
    ("Tertiary", "%tertiary"),
    ("Subtle", "%subtle"),
    ("Accent", "%accent"),
    ("Highlight", "%highlight"),
    ("Muted", "%muted"),
    ("Soft", "%soft"),
]


def _resolve_color(color: str) -> str:
    """Resolve %token to hex, or pass through hex/empty as-is."""
    if color.startswith("%"):
        return COLOR_TOKENS.get(color[1:], "")
    return color

_COLOR_VALUES = [c for _, c in COLOR_PALETTE]
_SIZE_SEQUENCE = ["small", "", "large", "xlarge", "xxlarge", "xxxlarge"]
_ANCHOR_CYCLE = ["", "topleft", "topcenter"]
_BOX_STYLE_CYCLE = ["", "flat"]
_NOTE_STYLE_CYCLE = ["", "mono"]
_ARROW_STYLE_CYCLE = ["", "thick", "dashed", "dotted"]

_SIGNIFICANT_MODS = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)

_CTRL_MOD = (
    Qt.KeyboardModifier.MetaModifier
    if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)

_UNDO_LIMIT = 50


# ── Mode enum ──────────────────────────────────────────────────

class Mode(enum.Enum):
    SELECT = "select"
    PAN = "pan"
    RECT = "rect"
    TEXT = "text"
    CONNECT = "connect"


# ── Graphics items ──────────────────────────────────────────────

_CORNER_TL = 0
_CORNER_TR = 1
_CORNER_BL = 2
_CORNER_BR = 3

_CORNER_CURSORS = {
    _CORNER_TL: Qt.CursorShape.SizeFDiagCursor,
    _CORNER_TR: Qt.CursorShape.SizeBDiagCursor,
    _CORNER_BL: Qt.CursorShape.SizeBDiagCursor,
    _CORNER_BR: Qt.CursorShape.SizeFDiagCursor,
}


class ResizeHandle(QGraphicsRectItem):
    """Small corner handle for resizing a BoxItem."""

    def __init__(self, corner: int, parent: QGraphicsRectItem):
        hs = HANDLE_SIZE
        super().__init__(-hs / 2, -hs / 2, hs, hs, parent)
        self.corner = corner
        self.setPen(QPen(QColor("#2F5D5C"), 1))
        self.setBrush(QBrush(QColor("#FFFFFF")))
        self.setCursor(_CORNER_CURSORS[corner])
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
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view and isinstance(view, WhiteboardView) and view._has_children(self.box.id):
            return "topleft"
        return ""

    def _get_effective_textsize(self) -> str:
        if self.box.textsize:
            return self.box.textsize
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view and isinstance(view, WhiteboardView) and view._has_children(self.box.id):
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
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
                view.arrow_update_needed.emit()
                view.mark_dirty()

    def _update_handles(self):
        r = self.rect()
        self._handles[_CORNER_TL].setPos(r.topLeft())
        self._handles[_CORNER_TR].setPos(r.topRight())
        self._handles[_CORNER_BL].setPos(r.bottomLeft())
        self._handles[_CORNER_BR].setPos(r.bottomRight())

    def _show_handles(self, visible: bool):
        for h in self._handles:
            h.setVisible(visible)

    def _corner_at(self, pos: QPointF) -> int | None:
        hit = HANDLE_SIZE + 8
        r = self.rect()
        corners = [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]
        for i, cp in enumerate(corners):
            if abs(pos.x() - cp.x()) < hit and abs(pos.y() - cp.y()) < hit:
                return i
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView) and view._grid_visible:
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
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
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
            corner = self._corner_at(event.pos())
            if corner is not None and self.isSelected():
                self._resizing = True
                self._resize_corner = corner
                self._resize_origin = event.pos()
                self.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False
                )
                view = self.scene().views()[0] if self.scene() and self.scene().views() else None
                if view and isinstance(view, WhiteboardView):
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

            # Clamp to minimum size
            if w < MIN_BOX_SIZE:
                if c in (_CORNER_TL, _CORNER_BL):
                    x -= MIN_BOX_SIZE - w
                w = MIN_BOX_SIZE
            if h < MIN_BOX_SIZE:
                if c in (_CORNER_TL, _CORNER_TR):
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

            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
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
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
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
        r = super().boundingRect()
        if self.isSelected():
            return r.adjusted(-4, -4, 4, 4)
        return r

    def paint(self, painter: QPainter, option, widget=None):
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
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView) and view._grid_visible:
                spacing = view.GRID_SPACING
                new_pos = value
                return QPointF(
                    round(new_pos.x() / spacing) * spacing,
                    round(new_pos.y() / spacing) * spacing,
                )
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.note.x = self.pos().x()
            self.note.y = self.pos().y()
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
                view.mark_dirty()
        return super().itemChange(change, value)


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


# ── Arrow drawing helpers ───────────────────────────────────────

def _box_edge_point(box: Box, target: QPointF) -> QPointF:
    """Find the point on box's edge closest to target along the line
    from box center to target."""
    cx = box.x + box.w / 2
    cy = box.y + box.h / 2
    dx = target.x() - cx
    dy = target.y() - cy

    if dx == 0 and dy == 0:
        return QPointF(cx, cy)

    hw, hh = box.w / 2, box.h / 2

    # Scale factor to reach the rectangle edge
    scales = []
    if dx != 0:
        scales.append(hw / abs(dx))
    if dy != 0:
        scales.append(hh / abs(dy))
    t = min(scales) if scales else 1.0

    return QPointF(cx + dx * t, cy + dy * t)


def _line_rect_clip(p1: QPointF, p2: QPointF, rect: QRectF) -> tuple[QPointF, QPointF]:
    """Find where the line p1→p2 enters and exits *rect*.

    Returns (enter_point, exit_point) using parametric clipping.
    Falls back to (p1, p2) if the line doesn't cross the rect cleanly.
    """
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()

    # Parametric t values for each rect edge
    edges = []
    if dx != 0:
        t_left = (rect.left() - p1.x()) / dx
        t_right = (rect.right() - p1.x()) / dx
        edges.append(t_left)
        edges.append(t_right)
    if dy != 0:
        t_top = (rect.top() - p1.y()) / dy
        t_bottom = (rect.bottom() - p1.y()) / dy
        edges.append(t_top)
        edges.append(t_bottom)

    # Keep only t values where the intersection actually lies on the rect boundary
    valid = []
    for t in edges:
        if t < 0 or t > 1:
            continue
        ix = p1.x() + dx * t
        iy = p1.y() + dy * t
        if (rect.left() - 0.5 <= ix <= rect.right() + 0.5
                and rect.top() - 0.5 <= iy <= rect.bottom() + 0.5):
            valid.append(t)

    if len(valid) < 2:
        return p1, p2

    valid.sort()
    t_enter = valid[0]
    t_exit = valid[-1]

    enter_pt = QPointF(p1.x() + dx * t_enter, p1.y() + dy * t_enter)
    exit_pt = QPointF(p1.x() + dx * t_exit, p1.y() + dy * t_exit)
    return enter_pt, exit_pt


def _arrowhead_polygon(tip: QPointF, angle: float) -> QPolygonF:
    """Create arrowhead triangle at tip pointing in direction angle (radians)."""
    s = ARROWHEAD_SIZE
    p1 = QPointF(
        tip.x() - s * math.cos(angle - math.pi / 6),
        tip.y() - s * math.sin(angle - math.pi / 6),
    )
    p2 = QPointF(
        tip.x() - s * math.cos(angle + math.pi / 6),
        tip.y() - s * math.sin(angle + math.pi / 6),
    )
    return QPolygonF([tip, p1, p2, tip])


# ── Canvas view ─────────────────────────────────────────────────

class WhiteboardView(QGraphicsView):
    """QGraphicsView with pan/zoom and file-backed board rendering."""

    arrow_update_needed = Signal()
    mode_changed = Signal(Mode)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(SCENE_BG))
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self._grid_visible: bool = True
        self.GRID_SPACING = 20

        self._board: Board | None = None
        self._box_items: dict[str, BoxItem] = {}
        self._arrow_items: list[QGraphicsLineItem | QGraphicsPolygonItem | QGraphicsSimpleTextItem] = []
        self._note_items: list[NoteItem] = []
        self._dirty = False

        # Pan state (middle-click always works)
        self._panning = False
        self._pan_start = QPointF()

        # Mode system
        self._mode = Mode.SELECT

        # RECT mode state
        self._rect_preview: QGraphicsRectItem | None = None
        self._rect_origin: QPointF | None = None

        # CONNECT mode state
        self._connect_source: BoxItem | None = None
        self._connect_line: QGraphicsLineItem | None = None

        # Inline text editor
        self._editor: QGraphicsTextItem | None = None
        self._edit_target: BoxItem | NoteItem | None = None

        # Nesting: guard against recursive position propagation
        self._propagating_move = False

        # Undo / Redo
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._pre_move_snapshot: str = ""

        # Copy / Paste clipboard
        self._clipboard_boxes: list[Box] = []
        self._clipboard_notes: list[Note] = []
        self._clipboard_arrows: list[Arrow] = []

        # Reparenting drag highlight
        self._highlight_parent: BoxItem | None = None
        self._highlight_orig_pen: QPen | None = None

        # Jump-to mode state
        self._jump_active = False
        self._jump_labels: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._jump_map: dict[str, BoxItem | NoteItem | Arrow] = {}
        self._jump_prefix = ""

        # Arrow selection state
        self._selected_arrow: Arrow | None = None
        self._selected_arrow_items: list[QGraphicsItem] = []

        self.arrow_update_needed.connect(self._redraw_arrows)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if self._grid_visible:
            spacing = self.GRID_SPACING
            left = int(rect.left()) - (int(rect.left()) % spacing)
            top = int(rect.top()) - (int(rect.top()) % spacing)
            painter.setPen(QPen(GRID_COLOR, 2.0))
            x = left
            while x <= rect.right():
                y = top
                while y <= rect.bottom():
                    painter.drawPoint(int(x), int(y))
                    y += spacing
                x += spacing

        # Content-area border — always drawn as an orientation aid
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            border_rect = items_rect.adjusted(-30, -30, 30, 30)
            pen = QPen(CONTENT_BORDER_COLOR, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(border_rect, 12, 12)

    def toggle_grid(self):
        self._grid_visible = not self._grid_visible
        self.viewport().update()

    @property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode):
        self._cancel_interactions()
        self._mode = mode
        self.mode_changed.emit(mode)

        if mode == Mode.SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._set_items_movable(True)
        elif mode == Mode.PAN:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._set_items_movable(False)
        elif mode == Mode.RECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._set_items_movable(False)
        elif mode == Mode.TEXT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self._set_items_movable(False)
        elif mode == Mode.CONNECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._set_items_movable(False)

    def _set_items_movable(self, movable: bool):
        for item in self._box_items.values():
            if movable:
                item.setFlags(
                    item.flags()
                    | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
            else:
                item.setFlags(
                    item.flags()
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
        for item in self._note_items:
            if movable:
                item.setFlags(
                    item.flags()
                    | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
            else:
                item.setFlags(
                    item.flags()
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )

    def _cancel_interactions(self):
        """Clean up any in-progress mode interactions."""
        self._clear_jump_labels()
        self._deselect_arrow()
        if self._rect_preview:
            self._scene.removeItem(self._rect_preview)
            self._rect_preview = None
            self._rect_origin = None
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None
            self._connect_source = None
        self._commit_editor()

    # ── Arrow selection ──

    def _select_arrow(self, arrow: Arrow):
        self._deselect_arrow()
        self._scene.clearSelection()
        self._selected_arrow = arrow
        sel_color = QColor("#0178D4")
        for gfx in self._arrow_items:
            if gfx.data(0) is arrow:
                self._selected_arrow_items.append(gfx)
                if isinstance(gfx, (QGraphicsLineItem, ArrowLineItem)):
                    old_pen = gfx.pen()
                    pen = QPen(sel_color, old_pen.widthF() + 1)
                    pen.setStyle(old_pen.style())
                    pen.setCapStyle(old_pen.capStyle())
                    gfx.setPen(pen)
                elif isinstance(gfx, QGraphicsPolygonItem):
                    gfx.setPen(QPen(sel_color, 1))
                    gfx.setBrush(QBrush(sel_color))
                elif isinstance(gfx, QGraphicsSimpleTextItem):
                    gfx.setBrush(QBrush(sel_color))

    def _deselect_arrow(self):
        if not self._selected_arrow:
            return
        for gfx in self._selected_arrow_items:
            if isinstance(gfx, (QGraphicsLineItem, ArrowLineItem)):
                old_pen = gfx.pen()
                pen = QPen(ARROW_COLOR, old_pen.widthF() - 1)
                pen.setStyle(old_pen.style())
                pen.setCapStyle(old_pen.capStyle())
                gfx.setPen(pen)
            elif isinstance(gfx, QGraphicsPolygonItem):
                gfx.setPen(QPen(ARROW_COLOR, 1))
                gfx.setBrush(QBrush(ARROW_COLOR))
            elif isinstance(gfx, QGraphicsSimpleTextItem):
                gfx.setBrush(QBrush(QColor("#2F3437")))
        self._selected_arrow = None
        self._selected_arrow_items.clear()

    def _find_existing_arrow(self, id_a: str, id_b: str) -> Arrow | None:
        """Find an arrow between the unordered pair {id_a, id_b}."""
        if not self._board:
            return None
        for arrow in self._board.arrows:
            if {arrow.from_id, arrow.to_id} == {id_a, id_b}:
                return arrow
        return None

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self):
        self._dirty = True
        window = self.window()
        if isinstance(window, MainWindow):
            if window._file_path:
                window.setWindowTitle(window._title_for_path(window._file_path, dirty=True))
            window._schedule_autosave()
        self._update_scene_rect()

    def mark_clean(self):
        self._dirty = False
        window = self.window()
        if isinstance(window, MainWindow) and window._file_path:
            window.setWindowTitle(window._title_for_path(window._file_path))

    def _update_scene_rect(self):
        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isNull():
            return
        inflated = items_rect.adjusted(-2000, -2000, 2000, 2000)
        self._scene.setSceneRect(inflated)

    def load_board(self, board: Board):
        self._board = board
        self._rebuild_scene()

    def _rebuild_scene(self):
        self._scene.clear()
        self._box_items.clear()
        self._arrow_items.clear()
        self._note_items.clear()
        self._editor = None
        self._edit_target = None
        self._rect_preview = None
        self._connect_line = None
        self._connect_source = None
        self._selected_arrow = None
        self._selected_arrow_items.clear()

        if not self._board:
            return

        for box in self._board.boxes:
            item = BoxItem(box)
            self._scene.addItem(item)
            self._box_items[box.id] = item
            item._auto_grow()

        for note in self._board.notes:
            item = NoteItem(note)
            self._scene.addItem(item)
            self._note_items.append(item)

        self._update_z_values()

        # Refresh auto-layout now that all parent-child relationships exist
        for item in self._box_items.values():
            item.refresh_auto_layout()

        self._redraw_arrows()
        self._update_z_values()
        self._update_scene_rect()

    def _redraw_arrows(self):
        for item in self._arrow_items:
            self._scene.removeItem(item)
        self._arrow_items.clear()

        if not self._board:
            return

        # Merge opposite arrow pairs (A->B + B->A) into one line.
        # Build directed lookup: (from, to) -> arrow
        directed: dict[tuple[str, str], Arrow] = {}
        merged: set[int] = set()  # indices of arrows consumed by merge
        # Each entry: (from_box_id, to_box_id, draw_head_to, draw_head_from, fwd_arrow, rev_arrow|None)
        render_list: list[tuple[str, str, bool, bool, Arrow, Arrow | None]] = []

        for i, arrow in enumerate(self._board.arrows):
            directed[(arrow.from_id, arrow.to_id)] = arrow

        for i, arrow in enumerate(self._board.arrows):
            if i in merged:
                continue
            reverse_key = (arrow.to_id, arrow.from_id)
            reverse = directed.get(reverse_key)
            if (
                reverse is not None
                and reverse is not arrow
                and not (arrow.head_from and arrow.head_to)
                and not (reverse.head_from and reverse.head_to)
                and id(reverse) not in {id(self._board.arrows[j]) for j in merged}
            ):
                # Merge: combine head flags from both arrows
                merged.add(self._board.arrows.index(reverse))
                render_list.append((
                    arrow.from_id, arrow.to_id,
                    arrow.head_to or reverse.head_from,
                    arrow.head_from or reverse.head_to,
                    arrow, reverse,
                ))
            else:
                render_list.append((
                    arrow.from_id, arrow.to_id,
                    arrow.head_to, arrow.head_from,
                    arrow, None,
                ))

        for from_id, to_id, draw_head_to, draw_head_from, fwd, rev in render_list:
            from_box = self._board.box_by_id(from_id)
            to_box = self._board.box_by_id(to_id)
            if not from_box or not to_box:
                continue

            pen = QPen(ARROW_COLOR, ARROW_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if fwd.style == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif fwd.style == "dotted":
                pen.setStyle(Qt.PenStyle.DotLine)
            elif fwd.style == "thick":
                pen.setWidthF(ARROW_WIDTH * 2)

            from_center = QPointF(
                from_box.x + from_box.w / 2, from_box.y + from_box.h / 2
            )
            to_center = QPointF(
                to_box.x + to_box.w / 2, to_box.y + to_box.h / 2
            )

            start = _box_edge_point(from_box, to_center)
            end = _box_edge_point(to_box, from_center)

            dx = end.x() - start.x()
            dy = end.y() - start.y()

            # Forward arrowhead (at to_id end)
            if draw_head_to:
                angle = math.atan2(dy, dx)
                head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle))
                head.setPen(QPen(ARROW_COLOR, 1))
                head.setBrush(QBrush(ARROW_COLOR))
                head.setData(0, fwd)
                self._scene.addItem(head)
                self._arrow_items.append(head)

            # Backward arrowhead (at from_id end)
            if draw_head_from:
                back_angle = math.atan2(-dy, -dx)
                back_head = QGraphicsPolygonItem(
                    _arrowhead_polygon(start, back_angle)
                )
                back_head.setPen(QPen(ARROW_COLOR, 1))
                back_head.setBrush(QBrush(ARROW_COLOR))
                back_head.setData(0, fwd)
                self._scene.addItem(back_head)
                self._arrow_items.append(back_head)

            # Collect labels: for merged pairs show both, stacked vertically
            label_texts: list[str] = []
            label_tooltips: list[str] = []
            if fwd.label:
                label_texts.append(fwd.label)
            if fwd.annotation:
                label_tooltips.append(fwd.annotation)
            if rev and rev.label:
                label_texts.append(rev.label)
            if rev and rev.annotation:
                label_tooltips.append(rev.annotation)

            if label_texts:
                mid_x = (start.x() + end.x()) / 2
                mid_y = (start.y() + end.y()) / 2

                combined = "\n".join(label_texts)
                label = QGraphicsSimpleTextItem(combined)
                label.setFont(LABEL_FONT)
                label.setBrush(QBrush(QColor("#2F3437")))
                label.setData(0, fwd)
                if label_tooltips:
                    label.setToolTip("\n".join(label_tooltips))
                br = label.boundingRect()
                label_x = mid_x - br.width() / 2
                label_y = mid_y - br.height() / 2

                # Gap rect around label with padding
                pad = 4
                gap = QRectF(
                    label_x - pad, label_y - pad,
                    br.width() + 2 * pad, br.height() + 2 * pad,
                )

                seg1_end, seg2_start = _line_rect_clip(start, end, gap)

                line1 = ArrowLineItem(
                    start.x(), start.y(), seg1_end.x(), seg1_end.y()
                )
                line1.setPen(pen)
                line1.setData(0, fwd)
                self._scene.addItem(line1)
                self._arrow_items.append(line1)
                line2 = ArrowLineItem(
                    seg2_start.x(), seg2_start.y(), end.x(), end.y()
                )
                line2.setPen(pen)
                line2.setData(0, fwd)
                self._scene.addItem(line2)
                self._arrow_items.append(line2)

                label.setPos(label_x, label_y)
                self._scene.addItem(label)
                self._arrow_items.append(label)
            else:
                line = ArrowLineItem(
                    start.x(), start.y(), end.x(), end.y()
                )
                line.setPen(pen)
                line.setData(0, fwd)
                tooltip_parts = []
                if fwd.annotation:
                    tooltip_parts.append(fwd.annotation)
                if rev and rev.annotation:
                    tooltip_parts.append(rev.annotation)
                if tooltip_parts:
                    line.setToolTip("\n".join(tooltip_parts))
                self._scene.addItem(line)
                self._arrow_items.append(line)

    # ── Nesting helpers ──

    def _has_children(self, box_id: str) -> bool:
        if not self._board:
            return False
        return any(b.parent == box_id for b in self._board.boxes)

    def _descendants(self, box_id: str) -> list[BoxItem]:
        """Return all BoxItems that are descendants of box_id."""
        result = []
        for bid, item in self._box_items.items():
            if item.box.parent == box_id:
                result.append(item)
                result.extend(self._descendants(bid))
        return result

    def _box_depth(self, box_id: str) -> int:
        depth = 0
        current = box_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            box = self._board.box_by_id(current) if self._board else None
            if not box or not box.parent:
                break
            depth += 1
            current = box.parent
        return depth

    def _update_z_values(self):
        max_depth = 0
        for box_id, item in self._box_items.items():
            d = self._box_depth(box_id)
            item.setZValue(d)
            if d > max_depth:
                max_depth = d
        note_z = max_depth + 1
        for item in self._note_items:
            item.setZValue(note_z)
        arrow_z = max_depth + 2
        for item in self._arrow_items:
            item.setZValue(arrow_z)

    def _refresh_auto_layout(self, box_id: str):
        """Refresh auto-layout for a box when its children change."""
        if box_id in self._box_items:
            self._box_items[box_id].refresh_auto_layout()

    def _check_nesting(self, item: BoxItem):
        """Update parent of a box after it has been moved or resized."""
        if not self._board:
            return
        box = item.box
        box_rect = QRectF(box.x, box.y, box.w, box.h)
        desc_ids = {d.box.id for d in self._descendants(box.id)}

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == box.id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(box_rect):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_id

        old_parent = box.parent
        if best_parent:
            box.parent = best_parent
        elif box.parent:
            parent_box = self._board.box_by_id(box.parent)
            if parent_box:
                parent_rect = QRectF(
                    parent_box.x, parent_box.y,
                    parent_box.w, parent_box.h,
                )
                if not parent_rect.contains(box_rect):
                    box.parent = ""
            else:
                box.parent = ""

        if box.parent != old_parent:
            self._update_z_values()
            if old_parent:
                self._refresh_auto_layout(old_parent)
            if box.parent:
                self._refresh_auto_layout(box.parent)
            self.mark_dirty()

    def _update_reparent_highlight(self):
        """Highlight potential parent box during drag."""
        selected = [i for i in self._scene.selectedItems() if isinstance(i, BoxItem)]
        if len(selected) != 1:
            self._clear_reparent_highlight()
            return

        item = selected[0]
        box = item.box
        box_rect = QRectF(box.x, box.y, box.w, box.h)
        desc_ids = {d.box.id for d in self._descendants(box.id)}

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == box.id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(box_rect):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_item

        if best_parent is self._highlight_parent:
            return

        self._clear_reparent_highlight()
        if best_parent:
            self._highlight_orig_pen = best_parent.pen()
            pen = QPen(QColor("#2F5D5C"), 3, Qt.PenStyle.DashLine)
            best_parent.setPen(pen)
            self._highlight_parent = best_parent

    def _clear_reparent_highlight(self):
        if self._highlight_parent and self._highlight_orig_pen is not None:
            self._highlight_parent.setPen(self._highlight_orig_pen)
            self._highlight_parent = None
            self._highlight_orig_pen = None

    # ── Undo / Redo ──

    def _push_undo(self):
        """Save current board state to undo stack (call before mutation)."""
        if not self._board:
            return
        self._undo_stack.append(serialize(self._board))
        self._redo_stack.clear()
        if len(self._undo_stack) > _UNDO_LIMIT:
            self._undo_stack.pop(0)

    def _save_pre_action_snapshot(self):
        """Save snapshot before a drag/resize gesture."""
        if self._board:
            self._pre_move_snapshot = serialize(self._board)

    def _commit_pre_action_snapshot(self):
        """Push pre-action snapshot to undo stack if state changed."""
        if self._board and self._pre_move_snapshot:
            current = serialize(self._board)
            if current != self._pre_move_snapshot:
                self._undo_stack.append(self._pre_move_snapshot)
                self._redo_stack.clear()
                if len(self._undo_stack) > _UNDO_LIMIT:
                    self._undo_stack.pop(0)
            self._pre_move_snapshot = ""

    def _undo(self):
        if not self._undo_stack or not self._board:
            return
        self._redo_stack.append(serialize(self._board))
        text = self._undo_stack.pop()
        self._board = parse(text)
        self._rebuild_scene()
        window = self.window()
        if isinstance(window, MainWindow):
            window._board = self._board
        self.mark_dirty()

    def _redo(self):
        if not self._redo_stack or not self._board:
            return
        self._undo_stack.append(serialize(self._board))
        text = self._redo_stack.pop()
        self._board = parse(text)
        self._rebuild_scene()
        window = self.window()
        if isinstance(window, MainWindow):
            window._board = self._board
        self.mark_dirty()

    # ── Copy / Paste ──

    def _copy_selected(self):
        self._clipboard_boxes.clear()
        self._clipboard_notes.clear()
        self._clipboard_arrows.clear()

        selected_box_ids = set()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                self._clipboard_boxes.append(copy.deepcopy(item.box))
                selected_box_ids.add(item.box.id)
            elif isinstance(item, NoteItem):
                self._clipboard_notes.append(copy.deepcopy(item.note))

        if self._board:
            for arrow in self._board.arrows:
                if arrow.from_id in selected_box_ids and arrow.to_id in selected_box_ids:
                    self._clipboard_arrows.append(copy.deepcopy(arrow))

    def _paste(self):
        cursor_viewport = self.mapFromGlobal(self.cursor().pos())
        cursor_scene = self.mapToScene(cursor_viewport)
        self._paste_at(cursor_scene)

    def _paste_at(self, center: QPointF):
        if not (self._clipboard_boxes or self._clipboard_notes) or not self._board:
            return
        self._push_undo()

        # Compute bounding box center of clipboard items
        all_xs: list[float] = []
        all_ys: list[float] = []
        for b in self._clipboard_boxes:
            all_xs += [b.x, b.x + b.w]
            all_ys += [b.y, b.y + b.h]
        for n in self._clipboard_notes:
            all_xs.append(n.x)
            all_ys.append(n.y)
        clip_cx = (min(all_xs) + max(all_xs)) / 2
        clip_cy = (min(all_ys) + max(all_ys)) / 2
        dx = center.x() - clip_cx
        dy = center.y() - clip_cy

        id_map: dict[str, str] = {}
        clipboard_box_ids = {b.id for b in self._clipboard_boxes}

        for orig_box in self._clipboard_boxes:
            new_box = copy.deepcopy(orig_box)
            new_id = self._board.next_box_id()
            id_map[orig_box.id] = new_id
            new_box.id = new_id
            new_box.x += dx
            new_box.y += dy
            self._board.add_box(new_box)

        # Fix parent references to use new IDs
        for box in self._board.boxes:
            if box.id in id_map.values() and box.parent in id_map:
                box.parent = id_map[box.parent]
            elif box.id in id_map.values() and box.parent and box.parent not in clipboard_box_ids:
                pass  # Keep original parent if it exists in the board
            elif box.id in id_map.values() and box.parent in clipboard_box_ids:
                box.parent = id_map.get(box.parent, "")

        for orig_note in self._clipboard_notes:
            new_note = copy.deepcopy(orig_note)
            new_note.x += dx
            new_note.y += dy
            self._board.add_note(new_note)

        for orig_arrow in self._clipboard_arrows:
            new_arrow = copy.deepcopy(orig_arrow)
            new_arrow.from_id = id_map.get(orig_arrow.from_id, orig_arrow.from_id)
            new_arrow.to_id = id_map.get(orig_arrow.to_id, orig_arrow.to_id)
            self._board.add_arrow(new_arrow)

        self._rebuild_scene()

        # Select newly pasted items
        new_ids = set(id_map.values())
        for bid, item in self._box_items.items():
            if bid in new_ids:
                item.setSelected(True)

        self.mark_dirty()

    # ── Property shortcuts ──

    def _cycle_color(self, direction: int):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.color
                idx = _COLOR_VALUES.index(cur) if cur in _COLOR_VALUES else 0
                idx = (idx + direction) % len(_COLOR_VALUES)
                item.set_color(_COLOR_VALUES[idx])
            elif isinstance(item, NoteItem):
                cur = item.note.color
                idx = _COLOR_VALUES.index(cur) if cur in _COLOR_VALUES else 0
                idx = (idx + direction) % len(_COLOR_VALUES)
                item.set_color(_COLOR_VALUES[idx])
        self.mark_dirty()

    def _cycle_textsize(self, direction: int):
        """direction: +1 = increase (toward large), -1 = decrease (toward small)."""
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1  # default to medium
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
            elif isinstance(item, NoteItem):
                cur = item.note.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
        self.mark_dirty()

    def _cycle_anchor(self):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.anchor
                if cur in _ANCHOR_CYCLE:
                    idx = _ANCHOR_CYCLE.index(cur)
                else:
                    idx = 0
                idx = (idx + 1) % len(_ANCHOR_CYCLE)
                item.set_anchor(_ANCHOR_CYCLE[idx])
        self.mark_dirty()

    def _cycle_style(self):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.style
                seq = _BOX_STYLE_CYCLE
                idx = seq.index(cur) if cur in seq else 0
                item.set_style(seq[(idx + 1) % len(seq)])
            elif isinstance(item, NoteItem):
                cur = item.note.style
                seq = _NOTE_STYLE_CYCLE
                idx = seq.index(cur) if cur in seq else 0
                item.set_style(seq[(idx + 1) % len(seq)])
        self.mark_dirty()

    def _snap_to_grid(self):
        self._push_undo()
        spacing = self.GRID_SPACING
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                item.box.x = round(item.box.x / spacing) * spacing
                item.box.y = round(item.box.y / spacing) * spacing
                item.setPos(item.box.x, item.box.y)
            elif isinstance(item, NoteItem):
                item.note.x = round(item.note.x / spacing) * spacing
                item.note.y = round(item.note.y / spacing) * spacing
                item.setPos(item.note.x, item.note.y)
        self.arrow_update_needed.emit()
        self.mark_dirty()

    # ── Inline text editing ──

    def _start_editing(self, target: BoxItem | NoteItem):
        self._commit_editor()
        self._edit_target = target

        if isinstance(target, BoxItem):
            text = target.box.label
            pos = target.scenePos()
            rect = target.rect()
            font = target._box_font()
            target._label.setVisible(False)
        else:
            text = target.note.text
            font = target._note_font()
            target.setVisible(False)

        editor = QGraphicsTextItem(text)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        br = editor.boundingRect()

        if isinstance(target, BoxItem):
            anchor = target._get_effective_anchor()
            if anchor == "topleft":
                editor.setPos(pos.x() + 8, pos.y() + 8)
            elif anchor == "topcenter":
                editor.setPos(
                    pos.x() + (rect.width() - br.width()) / 2,
                    pos.y() + 8,
                )
            else:
                editor.setPos(
                    pos.x() + rect.width() / 2 - br.width() / 2,
                    pos.y() + rect.height() / 2 - br.height() / 2,
                )
        else:
            editor.setPos(target.scenePos())

        self._scene.addItem(editor)
        editor.setZValue(1000)
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        self._editor = editor

    def _commit_editor(self):
        if not self._editor or not self._edit_target:
            return
        self._push_undo()
        text = self._editor.toPlainText().strip()
        if text:
            if isinstance(self._edit_target, BoxItem):
                self._edit_target.update_label(text)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.update_text(text)
            self.mark_dirty()
        if isinstance(self._edit_target, BoxItem):
            self._edit_target._label.setVisible(True)
        elif isinstance(self._edit_target, NoteItem):
            self._edit_target.setVisible(True)
        self._scene.removeItem(self._editor)
        self._editor = None
        self._edit_target = None

    def _cancel_editor(self):
        if self._editor:
            if isinstance(self._edit_target, BoxItem):
                self._edit_target._label.setVisible(True)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.setVisible(True)
            self._scene.removeItem(self._editor)
            self._editor = None
            self._edit_target = None

    # ── Delete selected ──

    def _delete_selected(self):
        if not self._board:
            return
        self._push_undo()
        deleted = False
        former_parents: set[str] = set()
        for item in list(self._scene.selectedItems()):
            if isinstance(item, BoxItem):
                box_id = item.box.id
                # Unparent direct children and track former parent
                for other in self._board.boxes:
                    if other.parent == box_id:
                        other.parent = ""
                if item.box.parent:
                    former_parents.add(item.box.parent)
                # Remove connected arrows
                for arrow in list(self._board.arrows):
                    if arrow.from_id == box_id or arrow.to_id == box_id:
                        self._board.remove_arrow(arrow)
                self._board.remove_box(item.box)
                self._box_items.pop(box_id, None)
                self._scene.removeItem(item)
                deleted = True
            elif isinstance(item, NoteItem):
                self._board.remove_note(item.note)
                self._note_items.remove(item)
                self._scene.removeItem(item)
                deleted = True
        if deleted:
            self._update_z_values()
            self._redraw_arrows()
            for pid in former_parents:
                self._refresh_auto_layout(pid)
            self.mark_dirty()

    # ── Status bar helpers ──

    def _current_zoom(self) -> float:
        return self.transform().m11()

    def _update_status_zoom(self):
        window = self.window()
        if isinstance(window, MainWindow):
            pct = round(self._current_zoom() * 100)
            window._status_zoom.setText(f"{pct}%")

    def _on_selection_changed(self):
        window = self.window()
        if isinstance(window, MainWindow):
            count = len(self._scene.selectedItems())
            window._status_sel.setText(f"{count} selected" if count else "")

    # ── Pan / Zoom ──

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._update_status_zoom()

    def mousePressEvent(self, event):
        # Middle-click pan always works
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        # If editor is active, consume clicks outside it
        if self._editor:
            editor_rect = self._editor.sceneBoundingRect()
            scene_pos = self.mapToScene(event.position().toPoint())
            if not editor_rect.contains(scene_pos):
                event.accept()
                return

        if self._mode == Mode.SELECT:
            # Save snapshot before potential move
            self._save_pre_action_snapshot()
            self._press_select(event)
        elif self._mode == Mode.PAN:
            self._press_pan(event)
        elif self._mode == Mode.RECT:
            self._press_rect(event)
        elif self._mode == Mode.TEXT:
            self._press_text(event)
        elif self._mode == Mode.CONNECT:
            self._press_connect(event)

    def mouseMoveEvent(self, event):
        # Update status bar position
        scene_pos = self.mapToScene(event.position().toPoint())
        window = self.window()
        if isinstance(window, MainWindow):
            window._status_pos.setText(
                f"{int(scene_pos.x())}, {int(scene_pos.y())}"
            )

        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return

        if self._mode == Mode.SELECT:
            if self._connect_source and self._connect_line:
                src = self._connect_source
                center = QPointF(
                    src.box.x + src.box.w / 2,
                    src.box.y + src.box.h / 2,
                )
                self._connect_line.setLine(
                    center.x(), center.y(), scene_pos.x(), scene_pos.y()
                )
                event.accept()
                return
            super().mouseMoveEvent(event)
            self._update_reparent_highlight()
        elif self._mode == Mode.PAN:
            self._move_pan(event)
        elif self._mode == Mode.RECT:
            self._move_rect(event)
        elif self._mode == Mode.CONNECT:
            self._move_connect(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            if self._mode == Mode.PAN:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._mode == Mode.SELECT:
            if self._connect_source and event.button() == Qt.MouseButton.LeftButton:
                # Finish shift+drag connector
                if self._connect_line:
                    self._scene.removeItem(self._connect_line)
                    self._connect_line = None
                scene_pos = self.mapToScene(event.position().toPoint())
                item = self._scene.itemAt(scene_pos, self.transform())
                if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
                    item = item.parentItem()
                if (isinstance(item, BoxItem)
                        and item is not self._connect_source
                        and self._board):
                    existing = self._find_existing_arrow(
                        self._connect_source.box.id, item.box.id,
                    )
                    if existing:
                        self._select_arrow(existing)
                    else:
                        self._push_undo()
                        arrow = Arrow(
                            from_id=self._connect_source.box.id,
                            to_id=item.box.id,
                        )
                        self._board.add_arrow(arrow)
                        self._redraw_arrows()
                        self.mark_dirty()
                self._connect_source = None
                event.accept()
                return
            self._clear_reparent_highlight()
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                for item in self._scene.selectedItems():
                    if isinstance(item, BoxItem):
                        self._check_nesting(item)
                self._commit_pre_action_snapshot()
        elif self._mode == Mode.PAN:
            self._release_pan(event)
        elif self._mode == Mode.RECT:
            self._release_rect(event)
        elif self._mode == Mode.CONNECT:
            self._release_connect(event)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        if self._mode != Mode.SELECT:
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        # Resolve child items to their parent BoxItem
        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if isinstance(item, BoxItem):
            self._start_editing(item)
            event.accept()
            return
        if isinstance(item, NoteItem):
            self._start_editing(item)
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        # Editor key handling
        if self._editor:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_editor()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._commit_editor()
                event.accept()
                return
            # Let the editor handle the key
            super().keyPressEvent(event)
            return

        # Jump mode handling
        if self._jump_active:
            self._handle_jump_key(event)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Escape:
            if self._selected_arrow:
                self._deselect_arrow()
                event.accept()
                return
            self._scene.clearSelection()
            self.set_mode(Mode.SELECT)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_arrow:
                self._push_undo()
                self._board.remove_arrow(self._selected_arrow)
                self._selected_arrow = None
                self._selected_arrow_items.clear()
                self._redraw_arrows()
                self.mark_dirty()
                event.accept()
                return
            self._delete_selected()
            event.accept()
            return

        # Arrow editing with cursor keys when arrow is selected
        if self._selected_arrow:
            no_mod_check = not (event.modifiers() & _SIGNIFICANT_MODS)
            if no_mod_check and event.key() in (
                Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Up, Qt.Key.Key_Down,
            ):
                self._push_undo()
                arrow = self._selected_arrow
                if event.key() == Qt.Key.Key_Left:
                    arrow.head_from = not arrow.head_from
                elif event.key() == Qt.Key.Key_Right:
                    arrow.head_to = not arrow.head_to
                elif event.key() == Qt.Key.Key_Up:
                    idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                    arrow.style = _ARROW_STYLE_CYCLE[(idx + 1) % len(_ARROW_STYLE_CYCLE)]
                elif event.key() == Qt.Key.Key_Down:
                    idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                    arrow.style = _ARROW_STYLE_CYCLE[(idx - 1) % len(_ARROW_STYLE_CYCLE)]
                self._redraw_arrows()
                self._select_arrow(arrow)
                self.mark_dirty()
                event.accept()
                return

        mods = event.modifiers()
        has_selection = bool(self._scene.selectedItems())
        no_mod = not (mods & _SIGNIFICANT_MODS)

        # Zoom with +/-
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.scale(1.15, 1.15)
            self._update_status_zoom()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Minus:
            self.scale(1 / 1.15, 1 / 1.15)
            self._update_status_zoom()
            event.accept()
            return

        # Ctrl+J — jump mode
        if (event.key() == Qt.Key.Key_J
                and mods & _CTRL_MOD):
            self._start_jump_mode()
            event.accept()
            return

        # Ctrl+Arrow — create adjacent box
        if mods & _CTRL_MOD:
            arrow_dirs = {
                Qt.Key.Key_Right: "right",
                Qt.Key.Key_Left: "left",
                Qt.Key.Key_Up: "up",
                Qt.Key.Key_Down: "down",
            }
            if event.key() in arrow_dirs:
                self._create_adjacent_box(arrow_dirs[event.key()])
                event.accept()
                return

        # Shift+H — cheatsheet
        if (event.key() == Qt.Key.Key_H
                and mods & Qt.KeyboardModifier.ShiftModifier):
            self._show_cheatsheet()
            event.accept()
            return

        # Property shortcuts — SELECT mode with selection, no modifiers
        if self._mode == Mode.SELECT and has_selection and no_mod:
            if event.key() == Qt.Key.Key_H:
                self._cycle_color(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_L:
                self._cycle_color(1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_J:
                self._cycle_textsize(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_K:
                self._cycle_textsize(1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_T:
                self._cycle_style()
                event.accept()
                return
            if event.key() == Qt.Key.Key_E:
                for item in self._scene.selectedItems():
                    if isinstance(item, (BoxItem, NoteItem)):
                        self._start_editing(item)
                        break
                event.accept()
                return

        # Shift+A — cycle anchor (SELECT mode with selection)
        if (event.key() == Qt.Key.Key_A
                and mods & Qt.KeyboardModifier.ShiftModifier
                and self._mode == Mode.SELECT and has_selection):
            self._cycle_anchor()
            event.accept()
            return

        # Shift+G — snap to grid (SELECT mode with selection)
        if (event.key() == Qt.Key.Key_G
                and mods & Qt.KeyboardModifier.ShiftModifier
                and self._mode == Mode.SELECT and has_selection):
            self._snap_to_grid()
            event.accept()
            return

        # G without shift — toggle grid
        if event.key() == Qt.Key.Key_G and no_mod:
            self.toggle_grid()
            event.accept()
            return

        # Arrow key panning (no modifiers, SELECT mode, no selection)
        if no_mod and self._mode == Mode.SELECT and not has_selection:
            PAN_STEP = 50
            pan_keys = {
                Qt.Key.Key_Right: (PAN_STEP, 0),
                Qt.Key.Key_Left: (-PAN_STEP, 0),
                Qt.Key.Key_Up: (0, -PAN_STEP),
                Qt.Key.Key_Down: (0, PAN_STEP),
            }
            if event.key() in pan_keys:
                dx, dy = pan_keys[event.key()]
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() + dx
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() + dy
                )
                event.accept()
                return

        # Mode switching shortcuts (no modifiers)
        if no_mod:
            mode_keys = {
                Qt.Key.Key_V: Mode.SELECT,
                Qt.Key.Key_H: Mode.PAN,
                Qt.Key.Key_R: Mode.RECT,
                Qt.Key.Key_T: Mode.TEXT,
                Qt.Key.Key_C: Mode.CONNECT,
            }
            if event.key() in mode_keys:
                self.set_mode(mode_keys[event.key()])
                event.accept()
                return

        super().keyPressEvent(event)

    # ── SELECT mode ──

    def _press_select(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())
        # Resolve child items to parent BoxItem/NoteItem
        resolved = item
        if isinstance(resolved, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(resolved.parentItem(), (BoxItem, NoteItem)):
            resolved = resolved.parentItem()

        # Shift+click toggles selection on individual items
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if isinstance(resolved, (BoxItem, NoteItem)):
                resolved.setSelected(not resolved.isSelected())
                event.accept()
                return
            # Shift+click on empty space: preserve current selection
            event.accept()
            return

        # Alt+click on a BoxItem starts connector drag
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and isinstance(resolved, BoxItem):
            self._connect_source = resolved
            center = QPointF(
                resolved.box.x + resolved.box.w / 2,
                resolved.box.y + resolved.box.h / 2,
            )
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
            event.accept()
            return

        # Alt+click on empty space: paste clipboard at position
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and not isinstance(resolved, BoxItem):
            if self._clipboard_boxes or self._clipboard_notes:
                self._paste_at(scene_pos)
                event.accept()
                return

        # Check if clicked on an arrow graphics item
        if isinstance(item, (ArrowLineItem, QGraphicsLineItem, QGraphicsPolygonItem, QGraphicsSimpleTextItem)):
            arrow_data = item.data(0)
            if isinstance(arrow_data, Arrow):
                self._select_arrow(arrow_data)
                event.accept()
                return
        # Clicking elsewhere deselects arrow
        self._deselect_arrow()
        super().mousePressEvent(event)

    # ── PAN mode ──

    def _press_pan(self, event):
        self._panning = True
        self._pan_start = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _move_pan(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _release_pan(self, event):
        self._panning = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    # ── RECT mode ──

    def _press_rect(self, event):
        if not self._board:
            return
        self._rect_origin = self.mapToScene(event.position().toPoint())
        pen = QPen(BOX_BORDER, 1, Qt.PenStyle.DashLine)
        self._rect_preview = self._scene.addRect(
            QRectF(self._rect_origin, self._rect_origin), pen
        )
        self._rect_preview.setBrush(QBrush(QColor(0x2F, 0x34, 0x37, 30)))
        event.accept()

    def _move_rect(self, event):
        if self._rect_preview and self._rect_origin:
            current = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._rect_origin, current).normalized()
            self._rect_preview.setRect(rect)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _release_rect(self, event):
        if not self._rect_preview or not self._rect_origin or not self._board:
            super().mouseReleaseEvent(event)
            return

        rect = self._rect_preview.rect()
        self._scene.removeItem(self._rect_preview)
        self._rect_preview = None

        w = max(rect.width(), MIN_BOX_SIZE)
        h = max(rect.height(), MIN_BOX_SIZE)

        # If just a click (tiny drag), use default size
        if w < MIN_BOX_SIZE + 5 and h < MIN_BOX_SIZE + 5:
            w = DEFAULT_BOX_W
            h = DEFAULT_BOX_H
            x = self._rect_origin.x() - w / 2
            y = self._rect_origin.y() - h / 2
        else:
            x = rect.x()
            y = rect.y()

        self._rect_origin = None

        self._push_undo()
        box_id = self._board.next_box_id()
        box = Box(id=box_id, label="", x=x, y=y, w=w, h=h)
        self._board.add_box(box)

        item = BoxItem(box)
        self._scene.addItem(item)
        self._box_items[box_id] = item
        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        item.setSelected(True)
        self._start_editing(item)
        event.accept()

    # ── TEXT mode ──

    def _press_text(self, event):
        if not self._board:
            return
        self._push_undo()
        scene_pos = self.mapToScene(event.position().toPoint())
        note = Note(x=scene_pos.x(), y=scene_pos.y(), text="Note")
        self._board.add_note(note)

        item = NoteItem(note)
        self._scene.addItem(item)
        self._note_items.append(item)
        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        item.setSelected(True)
        self._start_editing(item)
        event.accept()

    # ── CONNECT mode ──

    def _press_connect(self, event):
        if not self._board:
            return

        # Remove preview line before itemAt() so it doesn't block target
        saved_line = self._connect_line
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        # Click on child item → get parent BoxItem
        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if not isinstance(item, BoxItem):
            # Restore preview line if we had one and missed a target
            if saved_line and self._connect_source:
                self._connect_line = saved_line
                self._scene.addItem(self._connect_line)
            event.accept()
            return

        if not self._connect_source:
            # First click — set source
            self._connect_source = item
            center = QPointF(
                item.box.x + item.box.w / 2,
                item.box.y + item.box.h / 2,
            )
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
        else:
            # Second click — create arrow or select existing
            if item is not self._connect_source:
                existing = self._find_existing_arrow(
                    self._connect_source.box.id, item.box.id,
                )
                if existing:
                    self.set_mode(Mode.SELECT)
                    self._select_arrow(existing)
                else:
                    self._push_undo()
                    arrow = Arrow(
                        from_id=self._connect_source.box.id,
                        to_id=item.box.id,
                    )
                    self._board.add_arrow(arrow)
                    self._redraw_arrows()
                    self.mark_dirty()

            self._connect_source = None

        event.accept()

    def _move_connect(self, event):
        if self._connect_line and self._connect_source:
            scene_pos = self.mapToScene(event.position().toPoint())
            src = self._connect_source
            center = QPointF(
                src.box.x + src.box.w / 2,
                src.box.y + src.box.h / 2,
            )
            self._connect_line.setLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y()
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _release_connect(self, event):
        if not self._connect_source:
            event.accept()
            return

        # Remove preview line first so it doesn't intercept itemAt()
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if (isinstance(item, BoxItem)
                and item is not self._connect_source
                and self._board):
            existing = self._find_existing_arrow(
                self._connect_source.box.id, item.box.id,
            )
            if existing:
                self.set_mode(Mode.SELECT)
                self._select_arrow(existing)
            else:
                self._push_undo()
                arrow = Arrow(
                    from_id=self._connect_source.box.id,
                    to_id=item.box.id,
                )
                self._board.add_arrow(arrow)
                self._redraw_arrows()
                self.mark_dirty()

        self._connect_source = None
        event.accept()

    # ── Jump-to mode (Ctrl+J) ──

    def _start_jump_mode(self):
        if not self._board:
            return
        self._clear_jump_labels()

        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        # Collect jump targets: boxes, notes, and arrows (with midpoints)
        targets: list[tuple[BoxItem | NoteItem | Arrow, QPointF]] = []
        for item in self._box_items.values():
            if viewport_rect.intersects(item.sceneBoundingRect()):
                targets.append((item, item.sceneBoundingRect().center()))
        for item in self._note_items:
            if viewport_rect.intersects(item.sceneBoundingRect()):
                targets.append((item, item.sceneBoundingRect().center()))
        # Arrow midpoints
        for arrow in self._board.arrows:
            from_box = self._board.box_by_id(arrow.from_id)
            to_box = self._board.box_by_id(arrow.to_id)
            if from_box and to_box:
                mid = QPointF(
                    (from_box.x + from_box.w / 2 + to_box.x + to_box.w / 2) / 2,
                    (from_box.y + from_box.h / 2 + to_box.y + to_box.h / 2) / 2,
                )
                if viewport_rect.contains(mid):
                    targets.append((arrow, mid))

        if not targets:
            return

        count = len(targets)
        labels: list[str] = []
        if count <= 26:
            for i in range(count):
                labels.append(chr(ord("a") + i))
        else:
            for i in range(count):
                first = chr(ord("a") + i // 26)
                second = chr(ord("a") + i % 26)
                labels.append(first + second)

        self._jump_map = {}
        font = QFont(FONT_FAMILY, 14)
        font.setBold(True)

        for label_text, (target, center) in zip(labels, targets):
            self._jump_map[label_text] = target

            text_item = QGraphicsSimpleTextItem(label_text)
            text_item.setFont(font)
            text_item.setBrush(QBrush(QColor("#FFFFFF")))
            tr = text_item.boundingRect()

            pad = 3
            bg = QGraphicsRectItem(
                center.x() - tr.width() / 2 - pad,
                center.y() - tr.height() / 2 - pad,
                tr.width() + 2 * pad,
                tr.height() + 2 * pad,
            )
            bg.setBrush(QBrush(QColor("#C1086D")))
            bg.setPen(QPen(Qt.PenStyle.NoPen))
            bg.setZValue(1000)
            self._scene.addItem(bg)
            self._jump_labels.append(bg)

            text_item.setPos(
                center.x() - tr.width() / 2,
                center.y() - tr.height() / 2,
            )
            text_item.setZValue(1001)
            self._scene.addItem(text_item)
            self._jump_labels.append(text_item)

        self._jump_active = True
        self._jump_prefix = ""

    def _handle_jump_key(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._clear_jump_labels()
            return

        text = event.text().lower()
        if not text or not text.isalpha():
            self._clear_jump_labels()
            return

        self._jump_prefix += text

        if self._jump_prefix in self._jump_map:
            target = self._jump_map[self._jump_prefix]
            self._clear_jump_labels()
            self._scene.clearSelection()
            if isinstance(target, Arrow):
                self._select_arrow(target)
                from_box = self._board.box_by_id(target.from_id) if self._board else None
                to_box = self._board.box_by_id(target.to_id) if self._board else None
                if from_box and to_box:
                    mid = QPointF(
                        (from_box.x + from_box.w / 2 + to_box.x + to_box.w / 2) / 2,
                        (from_box.y + from_box.h / 2 + to_box.y + to_box.h / 2) / 2,
                    )
                    self.centerOn(mid)
            else:
                target.setSelected(True)
                self.centerOn(target)
            return

        has_match = any(
            lbl.startswith(self._jump_prefix) for lbl in self._jump_map
        )
        if not has_match:
            self._clear_jump_labels()

    def _clear_jump_labels(self):
        for item in self._jump_labels:
            self._scene.removeItem(item)
        self._jump_labels.clear()
        self._jump_map.clear()
        self._jump_prefix = ""
        self._jump_active = False

    # ── Keyboard box creation (Ctrl+Arrow) ──

    def _create_adjacent_box(self, direction: str):
        if not self._board:
            return
        self._push_undo()

        gap = 40
        anchor_item = None
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                anchor_item = item
                break

        if anchor_item:
            box = anchor_item.box
            w, h = box.w, box.h
            if direction == "right":
                x = box.x + box.w + gap
                y = box.y
            elif direction == "left":
                x = box.x - w - gap
                y = box.y
            elif direction == "up":
                x = box.x
                y = box.y - h - gap
            else:
                x = box.x
                y = box.y + box.h + gap
        else:
            center = self.mapToScene(self.viewport().rect().center())
            w = DEFAULT_BOX_W
            h = DEFAULT_BOX_H
            x = center.x() - w / 2
            y = center.y() - h / 2

        box_id = self._board.next_box_id()
        new_box = Box(id=box_id, label="", x=x, y=y, w=w, h=h)
        self._board.add_box(new_box)

        new_item = BoxItem(new_box)
        self._scene.addItem(new_item)
        self._box_items[box_id] = new_item

        if anchor_item:
            arrow = Arrow(from_id=anchor_item.box.id, to_id=box_id)
            self._board.add_arrow(arrow)
            self._redraw_arrows()

        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        self._scene.clearSelection()
        new_item.setSelected(True)

    # ── Cheatsheet (Shift+H) ──

    def _show_cheatsheet(self):
        shortcuts = [
            ("V", "Select mode"),
            ("R", "Create box (one-shot)"),
            ("T", "Create note (one-shot)"),
            ("C", "Connect arrow (one-shot)"),
            ("H", "Pan mode (no selection)"),
            ("h / l", "Cycle color (with selection)"),
            ("j / k", "Cycle text size (with selection)"),
            ("Shift+A", "Cycle anchor"),
            ("Shift+G", "Snap to grid"),
            ("G", "Toggle grid"),
            ("+ / -", "Zoom in / out"),
            ("Arrow keys", "Pan viewport"),
            ("Ctrl+Arrow", "Create adjacent box"),
            ("Ctrl+J", "Jump to shape / arrow"),
            ("\u2190 / \u2192", "Toggle arrowheads (arrow selected)"),
            ("\u2191 / \u2193", "Cycle arrow style (arrow selected)"),
            ("Shift+H", "This cheatsheet"),
            ("E", "Edit selected element"),
            ("Delete", "Delete selected / arrow"),
            ("Shift+Click", "Toggle selection"),
            ("Alt+Drag", "Connect boxes (from SELECT)"),
            ("Alt+Click", "Paste at position"),
            ("Double-click", "Edit text"),
            ("Enter", "Accept edit"),
            ("Escape", "Cancel edit / back to SELECT"),
        ]
        rows = "".join(
            f"<tr><td style='padding-right:16px'><b>{key}</b></td>"
            f"<td>{desc}</td></tr>"
            for key, desc in shortcuts
        )
        html = f"<table cellpadding='2'>{rows}</table>"
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.exec()


# ── Main window ─────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, file_path: str | None = None):
        super().__init__()
        self.setWindowTitle("Whiteboard")
        self.resize(1200, 800)

        self._view = WhiteboardView(self)
        self.setCentralWidget(self._view)

        self._file_path: Path | None = None
        self._board: Board | None = None
        self._watcher: JsonSafeWatcher | None = None

        self._autosave_timer = QTimer(self)

        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._autosave)
        self._last_written = ""

        self._setup_toolbar()
        self._setup_actions()
        self._setup_status_bar()

        self._pending_zoom_fit = bool(file_path)

        if file_path:
            self._open_file(Path(file_path))

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending_zoom_fit:
            self._pending_zoom_fit = False
            QTimer.singleShot(0, self._zoom_fit)

    def _title_for_path(self, path: Path | None, dirty: bool = False) -> str:
        if path is None:
            return "Whiteboard — untitled"
        label = f"{path.parent.name}/{path.name}"
        return f"Whiteboard — {label}{'*' if dirty else ''}"

    def _setup_toolbar(self):
        toolbar = QToolBar("Tools", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        group = QActionGroup(self)
        group.setExclusive(True)

        modes = [
            ("Select (V)", Mode.SELECT),
            ("Pan (H)", Mode.PAN),
            ("Rect (R)", Mode.RECT),
            ("Text (T)", Mode.TEXT),
            ("Connect (C)", Mode.CONNECT),
        ]

        self._mode_actions: dict[Mode, QAction] = {}
        for label, mode in modes:
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=mode: self._view.set_mode(m))
            group.addAction(action)
            toolbar.addAction(action)
            self._mode_actions[mode] = action

        self._mode_actions[Mode.SELECT].setChecked(True)

        toolbar.addSeparator()

        # Color button
        self._color_action = QAction("Color", self)
        color_menu = QMenu(self)
        for name, color_str in COLOR_PALETTE:
            action = color_menu.addAction(name)
            hex_color = _resolve_color(color_str)
            if hex_color:
                px = QPixmap(16, 16)
                px.fill(QColor(hex_color))
                action.setIcon(QIcon(px))
            action.triggered.connect(
                lambda checked, c=color_str: self._apply_color_to_selected(c)
            )
        self._color_action.setMenu(color_menu)
        toolbar.addAction(self._color_action)

        # Anchor dropdown
        self._anchor_action = QAction("Anchor", self)
        anchor_menu = QMenu(self)
        for name, value in [("Center", ""), ("Top Left", "topleft"), ("Top Center", "topcenter")]:
            action = anchor_menu.addAction(name)
            action.triggered.connect(
                lambda checked, a=value: self._apply_anchor_to_selected(a)
            )
        self._anchor_action.setMenu(anchor_menu)
        toolbar.addAction(self._anchor_action)

        # Size dropdown
        self._textsize_action = QAction("Size", self)
        textsize_menu = QMenu(self)
        for name, value in [("Small", "small"), ("Medium", ""), ("Large", "large"), ("XL", "xlarge"), ("XXL", "xxlarge")]:
            action = textsize_menu.addAction(name)
            action.triggered.connect(
                lambda checked, s=value: self._apply_textsize_to_selected(s)
            )
        self._textsize_action.setMenu(textsize_menu)
        toolbar.addAction(self._textsize_action)

        # Sync toolbar checkmarks when mode changes programmatically
        self._view.mode_changed.connect(self._on_mode_changed)

    def _on_mode_changed(self, mode: Mode):
        action = self._mode_actions.get(mode)
        if action:
            action.setChecked(True)
        self._status_mode.setText(mode.value.upper())

    def _apply_color_to_selected(self, color: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_color(color)
            elif isinstance(item, NoteItem):
                item.set_color(color)
        self._view.mark_dirty()

    def _apply_anchor_to_selected(self, anchor: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_anchor(anchor)
        self._view.mark_dirty()

    def _apply_textsize_to_selected(self, textsize: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_textsize(textsize)
            elif isinstance(item, NoteItem):
                item.set_textsize(textsize)
        self._view.mark_dirty()

    def _setup_actions(self):
        menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_file)
        menu.addAction(new_action)

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_dialog)
        menu.addAction(open_action)

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_file)
        menu.addAction(save_action)

        menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        # Edit menu
        edit_menu = self.menuBar().addMenu("&Edit")

        undo_action = QAction("&Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self._view._undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("&Redo", self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self._view._redo)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        copy_action = QAction("&Copy", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self._view._copy_selected)
        edit_menu.addAction(copy_action)

        paste_action = QAction("&Paste", self)
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.triggered.connect(self._view._paste)
        edit_menu.addAction(paste_action)

        # View menu
        view_menu = self.menuBar().addMenu("&View")

        grid_action = QAction("Show &Grid", self)
        grid_action.setCheckable(True)
        grid_action.setChecked(True)
        grid_action.triggered.connect(self._view.toggle_grid)
        view_menu.addAction(grid_action)

        # Zoom shortcuts
        zoom_in = QAction("Zoom In", self)
        zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in.triggered.connect(self._zoom_in)
        self.addAction(zoom_in)

        zoom_out = QAction("Zoom Out", self)
        zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out.triggered.connect(self._zoom_out)
        self.addAction(zoom_out)

        zoom_fit = QAction("Zoom to Fit", self)
        zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        zoom_fit.triggered.connect(self._zoom_fit)
        self.addAction(zoom_fit)

    def _zoom_in(self):
        self._view.scale(1.15, 1.15)
        self._view._update_status_zoom()

    def _zoom_out(self):
        self._view.scale(1 / 1.15, 1 / 1.15)
        self._view._update_status_zoom()

    def _zoom_fit(self):
        if self._board and (self._board.boxes or self._board.notes):
            self._view.fitInView(
                self._view.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self._view._update_status_zoom()

    def _setup_status_bar(self):
        self._status_mode = QLabel("SELECT")
        self._status_zoom = QLabel("100%")
        self._status_pos = QLabel("0, 0")
        self._status_sel = QLabel("")

        self.statusBar().addWidget(self._status_mode)
        self.statusBar().addPermanentWidget(self._status_sel)
        self.statusBar().addPermanentWidget(self._status_pos)
        self.statusBar().addPermanentWidget(self._status_zoom)

    def _new_file(self):
        if self._view.dirty and not self._confirm_discard():
            return
        self._board = Board()
        self._file_path = None
        self._stop_watching()
        self._view.load_board(self._board)
        self._view.mark_clean()
        self.setWindowTitle(self._title_for_path(None))

    def _open_dialog(self):
        if self._view.dirty and not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Board", "", "Board Files (*.board);;All Files (*)"
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path):
        if not path.exists():
            # Create an empty board file
            path.write_text("# Untitled Board\n")

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")
            return

        self._file_path = path
        self._board = parse(text)
        self._view.load_board(self._board)
        self._view.mark_clean()
        self.setWindowTitle(self._title_for_path(path))
        self._start_watching()

    def _schedule_autosave(self):
        if self._file_path:
            self._autosave_timer.start()

    def _autosave(self):
        if self._board and self._file_path:
            self._write_file()

    def _write_file(self):
        if not self._board or not self._file_path:
            return
        text = serialize(self._board)
        self._last_written = text
        self._file_path.write_text(text, encoding="utf-8")
        self._view._dirty = False
        if self._file_path:
            self.setWindowTitle(self._title_for_path(self._file_path))

    def _save_file(self):
        if not self._board:
            return
        if not self._file_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Board", "", "Board Files (*.board);;All Files (*)"
            )
            if not path:
                return
            self._file_path = Path(path)
            self._start_watching()

        self._write_file()

    def _start_watching(self):
        self._stop_watching()
        if not self._file_path:
            return
        self._watcher = JsonSafeWatcher(str(self._file_path))
        self._watcher.file_changed.connect(self._on_file_changed)
        self._watcher.start()

    def _stop_watching(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _on_file_changed(self):
        if not self._file_path or not self._file_path.exists():
            return
        try:
            text = self._file_path.read_text(encoding="utf-8")
        except OSError:
            return
        if text == self._last_written:
            return

        new_board = parse(text)

        # Smart merge: keep local positions for boxes that exist in both,
        # pick up new elements and drop removed ones from the file.
        if self._board:
            old_positions = {
                b.id: (b.x, b.y) for b in self._board.boxes
            }
            for box in new_board.boxes:
                if box.id in old_positions:
                    box.x, box.y = old_positions[box.id]

        self._board = new_board
        self._view.load_board(self._board)
        self._view.mark_clean()

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self._view.dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._stop_watching()
        super().closeEvent(event)


# ── Entry point ─────────────────────────────────────────────────

def _register_bundled_fonts():
    fonts_dir = Path(__file__).parent / "fonts"
    for name in ("PatrickHand-Regular.ttf", "JetBrainsMonoNerdFont-Regular.ttf"):
        path = fonts_dir / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Whiteboard")
    _register_bundled_fonts()

    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(file_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
