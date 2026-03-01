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
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
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

BOX_FILL = QColor("#F2F0EB")
BOX_BORDER = QColor("#2F3437")
ARROW_COLOR = QColor("#2F3437")
NOTE_COLOR = QColor("#E6B82E")
GRID_COLOR = QColor("#E5E3DD")
SCENE_BG = QColor("#F2F0EB")

FONT_FAMILY = "Marker Felt"

BOX_FONT = QFont(FONT_FAMILY, 13)
NOTE_FONT = QFont(FONT_FAMILY, 11)
LABEL_FONT = QFont(FONT_FAMILY, 10)

BOX_FONT_SIZES = {"": 13, "small": 10, "large": 18, "xlarge": 24, "xxlarge": 32}
NOTE_FONT_SIZES = {"": 11, "small": 9, "large": 15, "xlarge": 21, "xxlarge": 28}

BOX_RADIUS = 8
BOX_BORDER_WIDTH = 2
ARROW_WIDTH = 2
ARROWHEAD_SIZE = 10

DEFAULT_BOX_W = 160
DEFAULT_BOX_H = 80
MIN_BOX_SIZE = 20
HANDLE_SIZE = 8

COLOR_TOKENS = {
    "base": "#F2F0EB",
    "primary": "#2760A1",
    "secondary": "#43BFF2",
    "tertiary": "#97BB13",
    "subtle": "#4A4A4A",
    "accent": "#C1086D",
    "highlight": "#E6B82E",
    "muted": "#B8B3AA",
    "soft": "#AC90E4",
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
_SIZE_SEQUENCE = ["small", "", "large", "xlarge", "xxlarge"]
_ANCHOR_CYCLE = ["", "topleft", "topcenter"]

_SIGNIFICANT_MODS = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
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

        self._update_handles()
        self._resize_corner = -1
        self._resize_origin = QPointF()

    def _apply_color(self):
        hex_color = _resolve_color(self.box.color)
        if hex_color:
            c = QColor(hex_color)
            self.setPen(QPen(c.darker(125), BOX_BORDER_WIDTH))
            self.setBrush(QBrush(c))
            text_color = "#F2F0EB" if c.lightness() < 150 else "#2F3437"
            self._label.setDefaultTextColor(QColor(text_color))
        else:
            self.setPen(QPen(QColor("#2F3437"), BOX_BORDER_WIDTH))
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._label.setDefaultTextColor(QColor("#2F3437"))

    def set_color(self, color: str):
        self.box.color = color
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
        hit = HANDLE_SIZE + 4
        r = self.rect()
        corners = [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]
        for i, cp in enumerate(corners):
            if abs(pos.x() - cp.x()) < hit and abs(pos.y() - cp.y()) < hit:
                return i
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
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
        if (event.button() == Qt.MouseButton.LeftButton
                and self.isSelected()):
            corner = self._corner_at(event.pos())
            if corner is not None:
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
        painter.drawRoundedRect(self.rect(), BOX_RADIUS, BOX_RADIUS)

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = self.rect().adjusted(-3, -3, 3, 3)
            painter.drawRoundedRect(sel_rect, BOX_RADIUS, BOX_RADIUS)


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

    def boundingRect(self):
        r = super().boundingRect()
        if self.isSelected():
            return r.adjusted(-4, -4, 4, 4)
        return r

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
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
        return QFont(FONT_FAMILY, NOTE_FONT_SIZES.get(self.note.textsize, 11))

    def set_color(self, color: str):
        self.note.color = color
        self._apply_color()
        self.update()

    def set_textsize(self, textsize: str):
        self.note.textsize = textsize
        self.setFont(self._note_font())
        self.update()

    def update_text(self, text: str):
        self.note.text = text
        self.setText(text)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.note.x = self.pos().x()
            self.note.y = self.pos().y()
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and isinstance(view, WhiteboardView):
                view.mark_dirty()
        return super().itemChange(change, value)


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

        self.arrow_update_needed.connect(self._redraw_arrows)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if not self._grid_visible:
            return
        spacing = self.GRID_SPACING
        left = int(rect.left()) - (int(rect.left()) % spacing)
        top = int(rect.top()) - (int(rect.top()) % spacing)
        painter.setPen(QPen(QColor("#E5E3DD"), 1.5))
        x = left
        while x <= rect.right():
            y = top
            while y <= rect.bottom():
                painter.drawPoint(int(x), int(y))
                y += spacing
            x += spacing

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
        if self._rect_preview:
            self._scene.removeItem(self._rect_preview)
            self._rect_preview = None
            self._rect_origin = None
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None
            self._connect_source = None
        self._commit_editor()

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self):
        self._dirty = True
        window = self.window()
        if isinstance(window, MainWindow):
            if window._file_path:
                window.setWindowTitle(f"Whiteboard — {window._file_path.name}*")
            window._schedule_autosave()

    def mark_clean(self):
        self._dirty = False
        window = self.window()
        if isinstance(window, MainWindow) and window._file_path:
            window.setWindowTitle(f"Whiteboard — {window._file_path.name}")

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
        self._redraw_arrows()

    def _redraw_arrows(self):
        for item in self._arrow_items:
            self._scene.removeItem(item)
        self._arrow_items.clear()

        if not self._board:
            return

        pen = QPen(ARROW_COLOR, ARROW_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for arrow in self._board.arrows:
            from_box = self._board.box_by_id(arrow.from_id)
            to_box = self._board.box_by_id(arrow.to_id)
            if not from_box or not to_box:
                continue

            from_center = QPointF(
                from_box.x + from_box.w / 2, from_box.y + from_box.h / 2
            )
            to_center = QPointF(
                to_box.x + to_box.w / 2, to_box.y + to_box.h / 2
            )

            start = _box_edge_point(from_box, to_center)
            end = _box_edge_point(to_box, from_center)

            # Arrowhead
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            angle = math.atan2(dy, dx)
            head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle))
            head.setPen(QPen(ARROW_COLOR, 1))
            head.setBrush(QBrush(ARROW_COLOR))
            self._scene.addItem(head)
            self._arrow_items.append(head)

            if arrow.label:
                mid_x = (start.x() + end.x()) / 2
                mid_y = (start.y() + end.y()) / 2
                label = QGraphicsSimpleTextItem(arrow.label)
                label.setFont(LABEL_FONT)
                label.setBrush(QBrush(QColor("#2F3437")))
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

                line1 = self._scene.addLine(
                    start.x(), start.y(), seg1_end.x(), seg1_end.y(), pen
                )
                self._arrow_items.append(line1)
                line2 = self._scene.addLine(
                    seg2_start.x(), seg2_start.y(), end.x(), end.y(), pen
                )
                self._arrow_items.append(line2)

                label.setPos(label_x, label_y)
                self._scene.addItem(label)
                self._arrow_items.append(label)
            else:
                line = self._scene.addLine(
                    start.x(), start.y(), end.x(), end.y(), pen
                )
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
        for box_id, item in self._box_items.items():
            item.setZValue(self._box_depth(box_id))

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
        if not (self._clipboard_boxes or self._clipboard_notes) or not self._board:
            return
        self._push_undo()

        # Compute bounding box of clipboard items
        all_coords: list[tuple[float, float]] = []
        for b in self._clipboard_boxes:
            all_coords.append((b.x, b.y))
        for n in self._clipboard_notes:
            all_coords.append((n.x, n.y))
        origin_x = min(c[0] for c in all_coords)
        origin_y = min(c[1] for c in all_coords)

        # Get mouse cursor position in scene coordinates as paste target
        cursor_viewport = self.mapFromGlobal(self.cursor().pos())
        cursor_scene = self.mapToScene(cursor_viewport)
        dx = cursor_scene.x() - origin_x
        dy = cursor_scene.y() - origin_y

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
            font = NOTE_FONT
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
            center = target.scenePos()
            editor.setPos(center.x() - br.width() / 2, center.y() - br.height() / 2)

        self._scene.addItem(editor)
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

        # If editor is active and click is outside it, commit
        if self._editor:
            editor_rect = self._editor.sceneBoundingRect()
            scene_pos = self.mapToScene(event.position().toPoint())
            if not editor_rect.contains(scene_pos):
                self._commit_editor()

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
            super().mouseMoveEvent(event)
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

        if event.key() == Qt.Key.Key_Escape:
            self.set_mode(Mode.SELECT)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            event.accept()
            return

        mods = event.modifiers()
        has_selection = bool(self._scene.selectedItems())
        no_mod = not (mods & _SIGNIFICANT_MODS)

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

        self._start_editing(item)
        event.accept()

    # ── CONNECT mode ──

    def _press_connect(self, event):
        if not self._board:
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        # Click on child item → get parent BoxItem
        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if not isinstance(item, BoxItem):
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
            # Second click — create arrow
            if item is not self._connect_source:
                self._push_undo()
                arrow = Arrow(
                    from_id=self._connect_source.box.id,
                    to_id=item.box.id,
                )
                self._board.add_arrow(arrow)
                self._redraw_arrows()
                self.mark_dirty()

            if self._connect_line:
                self._scene.removeItem(self._connect_line)
                self._connect_line = None
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

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if (isinstance(item, BoxItem)
                and item is not self._connect_source
                and self._board):
            self._push_undo()
            arrow = Arrow(
                from_id=self._connect_source.box.id,
                to_id=item.box.id,
            )
            self._board.add_arrow(arrow)
            self._redraw_arrows()
            self.mark_dirty()

        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None
        self._connect_source = None
        event.accept()


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

        if file_path:
            self._open_file(Path(file_path))

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
        self.setWindowTitle("Whiteboard — untitled")

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
        self.setWindowTitle(f"Whiteboard — {path.name}")
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
            self.setWindowTitle(f"Whiteboard — {self._file_path.name}")

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

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Whiteboard")

    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(file_path)
    window.show()

    if file_path:
        QTimer.singleShot(100, window._zoom_fit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
