"""Graphics items for grafli: boxes, notes, labels, arrows, handles."""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAbstractTextDocumentLayout, QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPalette, QPen, QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextOption
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from grafli.constants import (
    BOX_BORDER_WIDTH,
    BOX_FONT_SIZES,
    BOX_RADIUS,
    DEFAULT_BOX_H,
    DEFAULT_BOX_W,
    DISCUSSION_COLORS,
    FONT_FAMILY,
    NOTE_FONT_FAMILY,
    HANDLE_SIZE,
    MIN_BOX_SIZE,
    NOTE_PEN_COLOR,
    NOTE_QUESTION_COLOR,
    NOTE_TASK_COLOR,
    resolve_textsize_px,
    SCENE_BG,
    _resolve_color,
)
from grafli.edge_label import EDGE_KIND_COLORS, parse_edge_label

_RE_SPEAKER = re.compile(r"^([A-Z][A-Za-z0-9_-]{0,15}): ")

# Task/question prefixes — accept short and long forms, any case.
# Rendered badge is always normalised to "T:" / "Q:" for consistency.
_RE_TASK_PREFIX = re.compile(r"^(?:T|TODO):\s", re.IGNORECASE)
_RE_QUESTION_PREFIX = re.compile(r"^(?:Q|QUESTION):\s", re.IGNORECASE)


def note_prefix(text: str) -> tuple[str, str] | None:
    """Detect a task or question prefix at the start of *text*.

    Returns ``("T:", body)`` for any of ``T:`` / ``t:`` / ``TODO:`` /
    ``todo:`` (case-insensitive); ``("Q:", body)`` for any of ``Q:`` /
    ``q:`` / ``QUESTION:`` / ``question:``. Returns ``None`` if no
    recognised prefix is present.
    """
    m = _RE_TASK_PREFIX.match(text)
    if m:
        return "T:", text[m.end():]
    m = _RE_QUESTION_PREFIX.match(text)
    if m:
        return "Q:", text[m.end():]
    return None
from grafli.code_note import is_code_note, split_signature, tokenize_line
from grafli.md_note import note_is_md, note_md_body
from grafli.format import Box, Image, Note
from grafli import iconset


def _attach_tooltip(el) -> str:
    """Human-readable tooltip for an element's attachment."""
    if el.attach_kind in ("doc", "graph"):
        return f"{el.attach_kind}:{el.url}" if el.url else el.attach_kind
    return el.url or ""

# Code-note palette — deliberately minimal so the snippet doesn't fight
# the surrounding graph. Two accents only, plus muted comments:
#   keyword     #2B6CB0  blue   bold     control / effect — flow markers
#   contract    #C53030  red    bold     pre / post / risk — review focus
#   ref         #2B6CB0  blue   underlined  clickable @path:line link
#   comment     #8A8580  grey   italic   skim-past prose
#   value       (text colour)             "...", #hex, 42, true — self-marked
#   text        #2F3437  near-black
NOTE_CODE_BG_COLOR = QColor("#F2F0EB")
NOTE_CODE_BORDER_COLOR = QColor("#CDC8BF")
NOTE_CODE_KW_COLOR = QColor("#2B6CB0")
NOTE_CODE_KW_CONTRACT_COLOR = QColor("#C53030")
NOTE_CODE_REF_COLOR = QColor("#2B6CB0")
NOTE_CODE_COMMENT_COLOR = QColor("#8A8580")
NOTE_CODE_TEXT_COLOR = QColor("#2F3437")
NOTE_CODE_INDENT_GUIDE_COLOR = QColor("#B5B0A8")

# Markdown-note styling. Qt's setMarkdown only honours *font* properties
# (size / weight) from the default stylesheet; text colour comes from the
# paint-context palette (near-black body, blue links — see _paint_markdown)
# and code-span backgrounds are applied as char formats (_style_code_spans),
# because colour / background CSS rules are ignored on a Markdown import.
NOTE_MD_CODE_BG_COLOR = QColor("#E7E3DA")


def _md_stylesheet(base_pt: float) -> str:
    """Font-only CSS applied to a Markdown note's QTextDocument.

    Heading sizes are relative to the note's base point size so ``~size``
    still scales the whole note. Tuned so an ``md:`` note reads at the same
    visual weight as neighbouring notes when zoomed out.
    """
    if base_pt <= 0:
        base_pt = 13.0
    h1 = base_pt * 1.45
    h2 = base_pt * 1.25
    h3 = base_pt * 1.1
    return f"""
        h1 {{ font-size: {h1:.1f}pt; font-weight: bold; }}
        h2 {{ font-size: {h2:.1f}pt; font-weight: bold; }}
        h3, h4, h5, h6 {{ font-size: {h3:.1f}pt; font-weight: bold; }}
    """


_CODE_BOLD_KINDS = {"kw_struct", "kw_effect", "kw_contract", "ref"}
_CODE_KIND_COLORS = {
    "kw_struct": NOTE_CODE_KW_COLOR,
    "kw_effect": NOTE_CODE_KW_COLOR,
    "kw_contract": NOTE_CODE_KW_CONTRACT_COLOR,
    "ref": NOTE_CODE_REF_COLOR,
    "string": NOTE_CODE_TEXT_COLOR,
    "hex": NOTE_CODE_TEXT_COLOR,
    "number": NOTE_CODE_TEXT_COLOR,
    "bool": NOTE_CODE_TEXT_COLOR,
    "comment": NOTE_CODE_COMMENT_COLOR,
    "text": NOTE_CODE_TEXT_COLOR,
}


def _paint_link_glyph(painter: QPainter, rect: QRectF):
    """Paint a link icon at the top-right of *rect*, on a small label-style
    plate so it stays legible regardless of box fill color.
    """
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Plate — mirrors BoxLabelItem's background plate.
    plate = QRectF(rect.right() - 17, rect.top() + 2, 14, 11)
    bg = QColor("#F2F0EB")
    bg.setAlphaF(0.6)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(bg))
    painter.drawRoundedRect(plate, 4, 4)

    # Chain glyph — same color as label text, full alpha (plate carries contrast).
    painter.setPen(QPen(QColor("#2F3437"), 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = plate.center().x()
    cy = plate.center().y()
    r1 = QRectF(cx - 4, cy - 3, 6, 4)
    r2 = QRectF(cx - 2, cy - 1, 6, 4)
    painter.drawRoundedRect(r1, 1.5, 1.5)
    painter.drawRoundedRect(r2, 1.5, 1.5)

# ── Handle IDs ───────────────────────────────────────────────────

_CORNER_TL = 0
_CORNER_TR = 1
_CORNER_BL = 2
_CORNER_BR = 3
_EDGE_T = 4
_EDGE_R = 5
_EDGE_B = 6
_EDGE_L = 7

_CORNERS = (_CORNER_TL, _CORNER_TR, _CORNER_BL, _CORNER_BR)
_EDGES = (_EDGE_T, _EDGE_R, _EDGE_B, _EDGE_L)
_ALL_HANDLES = _CORNERS + _EDGES

MIN_SCALE_FONT_PT = 6   # font floor when scaling a node down

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


def _view_scale(item) -> float:
    """Current canvas zoom (scene units per pixel inverse), or 1.0."""
    view = _get_view(item)
    if view is not None:
        m = view.transform().m11()
        if m:
            return abs(m)
    return 1.0


def _apply_emphasis(font: QFont, emphasis: str) -> QFont:
    """Layer bold/italic onto ``font`` from an element's ``emphasis`` string."""
    if "bold" in emphasis:
        font.setBold(True)
    if "italic" in emphasis:
        font.setItalic(True)
    return font


def _draw_text(painter: QPainter, point: QPointF, text: str,
               font: QFont, color: QColor, emphasis: str = "") -> None:
    """Draw ``text`` at a baseline ``point`` in ``color``.

    Handles the display text styles that can't be expressed through a plain
    ``QFont``:

    * **faux-bold** — the handwritten face (Patrick Hand) ships no bold weight,
      so a plain ``setBold`` only yields weak synthetic emboldening; for that
      family we thicken by stroking the glyph outline.
    * **outline** (``emphasis`` contains ``outline``) — hollow letters: the
      glyph path is stroked, not filled.
    * **shadow** (``emphasis`` contains ``shadow``) — an offset dark copy of
      the glyphs is laid down first, giving depth.

    The mono UI font has a real Bold, so it takes the plain text path unless a
    display style is requested.
    """
    outline = "outline" in emphasis
    shadow = "shadow" in emphasis
    faux_bold = font.bold() and font.family() == NOTE_FONT_FAMILY
    if not (outline or shadow or faux_bold):
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(point, text)
        return

    path = QPainterPath()
    path.addText(point, font, text)
    painter.save()
    if shadow:
        offset = max(1.5, font.pointSizeF() * 0.06)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 90)))
        painter.translate(offset, offset)
        painter.drawPath(path)
        painter.translate(-offset, -offset)
    if outline:
        pen = QPen(color, max(0.8, font.pointSizeF() * 0.05))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    else:
        painter.setBrush(QBrush(color))
        if faux_bold:
            pen = QPen(color, max(0.5, font.pointSizeF() * 0.04))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(path)
    painter.restore()


def _begin_drag_guides(item):
    """Tell the view a free-move drag is starting (gathers alignment refs)."""
    view = _get_view(item)
    if view is not None and hasattr(view, "begin_drag_guides"):
        view.begin_drag_guides(item)


def _end_drag_guides(item):
    """Tell the view a free-move drag ended (clears live guides)."""
    view = _get_view(item)
    if view is not None and hasattr(view, "end_drag_guides"):
        view.end_drag_guides()


_HANDLE_GRAB_PX = HANDLE_SIZE / 2 + 5   # forgiving grab radius around a handle


def _handle_points(rect: QRectF, handle_ids):
    """Map of handle id → its anchor point on ``rect`` (corner or edge mid)."""
    cx = (rect.left() + rect.right()) / 2
    cy = (rect.top() + rect.bottom()) / 2
    pts = {
        _CORNER_TL: rect.topLeft(),
        _CORNER_TR: rect.topRight(),
        _CORNER_BL: rect.bottomLeft(),
        _CORNER_BR: rect.bottomRight(),
        _EDGE_T: QPointF(cx, rect.top()),
        _EDGE_B: QPointF(cx, rect.bottom()),
        _EDGE_L: QPointF(rect.left(), cy),
        _EDGE_R: QPointF(rect.right(), cy),
    }
    return {h: pts[h] for h in handle_ids}


def _handle_hit(rect: QRectF, handle_ids, pos: QPointF, scale: float):
    """Nearest handle whose square ``pos`` falls within, else None.

    The grab radius is constant in *screen* pixels (handles are drawn at a
    fixed size regardless of zoom), so it is divided by the canvas scale.
    """
    radius = _HANDLE_GRAB_PX / max(scale, 1e-6)
    best, best_d = None, radius
    for hid, pt in _handle_points(rect, handle_ids).items():
        d = ((pos.x() - pt.x()) ** 2 + (pos.y() - pt.y()) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = hid, d
    return best


# ── Graphics items ───────────────────────────────────────────────


class ResizeHandle(QGraphicsRectItem):
    """Grab square at a node's corner or edge midpoint.

    The handle owns its own hover feedback (it lights up and grows so it is
    obvious a drag will resize) and its own drag, delegating the actual
    geometry change to the parent node's ``_begin/_update/_finish_handle_drag``.
    """

    _HOVER_GROW = 4
    _IDLE_FILL = QColor("#FFFFFF")
    _IDLE_PEN = QColor("#2F5D5C")
    _HOVER_FILL = QColor("#2F5D5C")
    _HOVER_PEN = QColor("#FFFFFF")

    def __init__(self, handle_id: int, parent: QGraphicsRectItem):
        hs = HANDLE_SIZE
        super().__init__(-hs / 2, -hs / 2, hs, hs, parent)
        self.corner = handle_id
        self._hovered = False
        self._dragging = False
        self.setPen(QPen(self._IDLE_PEN, 1))
        self.setBrush(QBrush(self._IDLE_FILL))
        self.setCursor(_HANDLE_CURSORS[handle_id])
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        # Draw at a constant screen size regardless of canvas zoom, and keep
        # the squares above the node and its selection outline.
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True
        )
        self.setZValue(10)
        self.setVisible(False)

    def _set_hover(self, on: bool):
        if on == self._hovered:
            return
        self._hovered = on
        hs = HANDLE_SIZE + (self._HOVER_GROW if on else 0)
        self.prepareGeometryChange()
        self.setRect(-hs / 2, -hs / 2, hs, hs)
        if on:
            self.setBrush(QBrush(self._HOVER_FILL))
            self.setPen(QPen(self._HOVER_PEN, 1.5))
        else:
            self.setBrush(QBrush(self._IDLE_FILL))
            self.setPen(QPen(self._IDLE_PEN, 1))

    def hoverEnterEvent(self, event):
        self._set_hover(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if not self._dragging:
            self._set_hover(False)
        super().hoverLeaveEvent(event)

    def _parent_node(self):
        parent = self.parentItem()
        if parent is not None and hasattr(parent, "_begin_handle_drag"):
            return parent
        return None

    def mousePressEvent(self, event):
        parent = self._parent_node()
        if (event.button() == Qt.MouseButton.LeftButton
                and parent is not None and parent.isSelected()):
            parent._begin_handle_drag(self.corner, event.scenePos())
            self._dragging = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        parent = self._parent_node()
        if self._dragging and parent is not None:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            parent._update_handle_drag(event.scenePos(), shift)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        parent = self._parent_node()
        if self._dragging and parent is not None:
            self._dragging = False
            parent._finish_handle_drag()
            self._set_hover(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ResizeForeshadow(QGraphicsItem):
    """Translucent preview drawn while resizing/scaling a box.

    Shows where the box's *frame* will land (dashed outline) and where its
    *content* will sit after scaling (a filled occupied-area rect). When the
    box has aspect-lock on, a small corner glyph signals the ratio is held.
    The real size/font mutation happens on release; this only foreshadows it.
    """

    _OUTLINE = QColor("#2F5D5C")
    _FILL = QColor("#2F5D5C")
    _GLYPH_BG = QColor("#2F3437")
    _GLYPH_FG = QColor("#ECECEC")

    def __init__(self):
        super().__init__()
        self._frame = QRectF()
        self._content = QRectF()
        self._locked = False
        self.setZValue(10001)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def set_preview(self, frame: QRectF, content: QRectF | None, locked: bool):
        self.prepareGeometryChange()
        self._frame = QRectF(frame)
        self._content = QRectF(content) if content is not None else QRectF()
        self._locked = bool(locked)
        self.update()

    def boundingRect(self):
        r = QRectF(self._frame)
        if not self._content.isEmpty():
            r = r.united(self._content)
        return r.adjusted(-12, -12, 12, 12)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Content-occupied area (filled, faint).
        if not self._content.isEmpty():
            fill = QColor(self._FILL)
            fill.setAlphaF(0.18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawRect(self._content)
        # Target frame outline (dashed).
        pen = QPen(self._OUTLINE, 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._frame)
        # Lock indicator: a small badge in the top-left of the frame.
        if self._locked:
            self._paint_lock_badge(painter)

    def _paint_lock_badge(self, painter: QPainter):
        size = 18.0
        r = QRectF(self._frame.left() + 4, self._frame.top() + 4, size, size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._GLYPH_BG))
        painter.drawRoundedRect(r, 4, 4)
        # Simple padlock: shackle arc + body.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._GLYPH_FG, 1.6))
        cx = r.center().x()
        arc = QRectF(cx - 3.5, r.top() + 4, 7, 7)
        painter.drawArc(arc, 0, 180 * 16)
        body = QRectF(cx - 4.5, r.top() + 7.5, 9, 7)
        painter.setBrush(QBrush(self._GLYPH_FG))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(body, 1.5, 1.5)


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
        # No caption (e.g. a glyph box cleared to fill with its icon) → draw
        # nothing, so the contrast plate doesn't linger as an empty strip.
        if not self._box_item.box.label:
            return
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
        self._scaling = False
        self._is_parent = False
        # Level-of-Detail: when the view zooms out far enough that this box's
        # label would be illegible, the view marks it simplified — the box
        # paints as a bare coloured shell (no icon; its label item is hidden).
        self._lod_simplified = False
        # When this box is a collapsed container, the view sets a (headline,
        # count) tuple; paint() then draws a counter-scaled headline + count
        # badge in place of the hidden children, and the normal label is hidden.
        self._lod_tile: tuple[str, int] | None = None

        self._label = BoxLabelItem(self)
        self._label.setFont(self._box_font())
        self._label.setDefaultTextColor(QColor("#2F3437"))
        self._label.setPlainText(box.label)
        self._label.setTextWidth(self._label_width_for(box.w))
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

    def set_icon(self, name: str, placement: str = ""):
        self.box.icon = name
        self.box.icon_placement = placement
        self._auto_grow()
        self._position_label()
        self.update()

    def set_emphasis(self, emphasis: str):
        self.box.emphasis = emphasis
        self._label.setFont(self._box_font())
        self._auto_grow()
        self._position_label()
        self.update()

    def _lead_icon_side(self) -> float:
        """Small leading-icon size, scaled to the box's text."""
        is_parent = self._is_parent
        px = resolve_textsize_px(self.box.textsize,
                                 "small" if is_parent else "")
        return max(14.0, min(px * 1.7, self.box.h - 8))

    def _has_lead_icon(self) -> bool:
        return (bool(self.box.icon) and self.box.icon_placement == "lead"
                and iconset.has_icon(self.box.icon))

    def _label_width_for(self, w: float) -> float:
        """Wrap width for the label — leaves room for a lead-icon gutter so
        the text never runs past the box edge."""
        if self._has_lead_icon():
            return w - (self._lead_icon_side() + 24.0)
        return w - 16.0

    def _paint_icon(self, painter: QPainter):
        """Draw the visual-vocabulary glyph. ``fill`` (default): big icon, the
        label is a caption (positioned by _position_label). ``lead``: a small
        icon at the left, the label keeps its normal weight beside it."""
        w, h = self.box.w, self.box.h
        color = QColor("#2F3437")
        if self.box.icon_placement == "lead":
            side = self._lead_icon_side()
            iconset.paint_icon(painter, self.box.icon,
                               QRectF(8.0, (h - side) / 2, side, side), color)
            return
        pad = 10.0
        cap_h = (self._label.boundingRect().height() + 6
                 if self.box.label else 0.0)
        avail_h = h - 2 * pad - cap_h
        side = max(8.0, min(w - 2 * pad, avail_h))
        ix = (w - side) / 2
        iy = pad + (avail_h - side) / 2
        iconset.paint_icon(painter, self.box.icon,
                           QRectF(ix, iy, side, side), color)

    def set_style(self, style: str):
        self.box.style = style
        self._apply_color()
        self.update()

    def _update_url_indicator(self):
        """Refresh tooltip based on the attachment."""
        self.setToolTip(_attach_tooltip(self.box))

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
        view = _get_view(self)
        is_parent = bool(view and hasattr(view, '_has_children')
                         and view._has_children(self.box.id))
        # Unset size: a parent defaults to the small header, a normal node to
        # medium. An explicit size (numeric or named) is always honoured — so
        # a parent can be set to the same size as any other node.
        px = resolve_textsize_px(self.box.textsize, "small" if is_parent else "")
        return _apply_emphasis(QFont(FONT_FAMILY, px), self.box.emphasis)

    def _position_label(self):
        self._label.setTextWidth(self._label_width_for(self.box.w))
        br = self._label.boundingRect()
        w = self.box.w
        h = self.box.h
        bx = self.pos().x()
        by = self.pos().y()
        doc = self._label.document()
        # Glyph box. ``lead``: a small icon sits at the left and the label
        # keeps its weight beside it. ``fill``: the icon fills the body, so the
        # label rides at the bottom as a caption.
        if self.box.icon and iconset.has_icon(self.box.icon):
            if self.box.icon_placement == "lead":
                gutter = 8.0 + self._lead_icon_side() + 8.0
                opt = QTextOption()
                opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
                doc.setDefaultTextOption(opt)
                self._label.setPos(bx + gutter, by + (h - br.height()) / 2)
                return
            opt = QTextOption()
            opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            doc.setDefaultTextOption(opt)
            self._label.setPos(bx + (w - br.width()) / 2,
                               by + h - br.height() - 6)
            return
        anchor = self._get_effective_anchor()
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
        self._label.setTextWidth(self._label_width_for(self.box.w))
        self._auto_grow()
        self._position_label()

    def set_geometry(self, x: float, y: float, w: float, h: float):
        """Set the box's full geometry and refresh dependent visuals."""
        self.box.x = x
        self.box.y = y
        self.box.w = w
        self.box.h = h
        self._min_h = h
        self.setPos(x, y)
        self.setRect(0, 0, w, h)
        self._label.setTextWidth(self._label_width_for(w))
        self._update_handles()
        self._position_label()
        view = _get_view(self)
        if view and hasattr(view, 'arrow_update_needed'):
            view.arrow_update_needed.emit()
            view.mark_dirty()

    def _fit_to_label(self):
        """Shrink the box down to comfortably fit its text label.

        Used when a node stops being a parent (its last child was dragged
        out) so it doesn't keep the enlarged container size and leave a big
        empty box. Floors at the default node size, never grows beyond the
        current size, and collapses around the box centre so the label
        stays roughly in place.
        """
        cx = self.box.x + self.box.w / 2
        cy = self.box.y + self.box.h / 2

        self._label.setFont(self._box_font())
        # Natural (unwrapped) label width, then height wrapped at the new width.
        self._label.setTextWidth(-1)
        natural_w = self._label.boundingRect().width()
        new_w = min(self.box.w, max(DEFAULT_BOX_W, natural_w + 32))
        self._label.setTextWidth(self._label_width_for(new_w))
        needed_h = self._label.boundingRect().height() + 16
        new_h = min(self.box.h, max(DEFAULT_BOX_H, needed_h))

        self.box.w = new_w
        self.box.h = new_h
        self.box.x = cx - new_w / 2
        self.box.y = cy - new_h / 2
        self._min_h = new_h
        self.setPos(self.box.x, self.box.y)
        self.setRect(0, 0, new_w, new_h)
        self._update_handles()
        self._position_label()
        view = _get_view(self)
        if view and hasattr(view, 'arrow_update_needed'):
            view.arrow_update_needed.emit()
            view.mark_dirty()

    def _auto_grow(self):
        self._label.setTextWidth(self._label_width_for(self.box.w))
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
        for handle in self._handles:
            handle.setVisible(visible)

    def _handle_at(self, pos: QPointF) -> int | None:
        return _handle_hit(self.rect(), _ALL_HANDLES, pos, _view_scale(self))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = _get_view(self)
            if view is not None and hasattr(view, 'snap_drag_pos'):
                return view.snap_drag_pos(self, value)
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
        m = 6 if self.isSelected() else 0
        if self._lod_tile is not None:
            # The "stacked edges" mark peeks up and to the right of the tile.
            return r.adjusted(-m, -m - 64, m + 64, m)
        if m:
            return r.adjusted(-m, -m, m, m)
        return r

    def mousePressEvent(self, event):
        # Presses on the box body within a handle's grab ring still start a
        # resize; presses on a handle square are driven by the handle itself.
        if event.button() == Qt.MouseButton.LeftButton:
            corner = self._handle_at(event.pos())
            # A collapsed tile is read-only — no resize (it would desync the
            # hidden children); the press just selects (for navigation).
            if (corner is not None and self.isSelected()
                    and self._lod_tile is None):
                self._begin_handle_drag(corner, event.scenePos())
                event.accept()
                return
        _begin_drag_guides(self)
        super().mousePressEvent(event)

    # ── Handle drag: corners scale the selection, edges stretch one axis ──

    def _begin_handle_drag(self, corner: int, scene_pos: QPointF):
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        view = _get_view(self)
        if view and hasattr(view, '_save_pre_action_snapshot'):
            view._save_pre_action_snapshot()
        if corner in _CORNERS:
            self._begin_scale(corner, scene_pos)
        else:
            self._resizing = True
            self._resize_corner = corner
            self._resize_origin = self.mapFromScene(scene_pos)

    def _update_handle_drag(self, scene_pos: QPointF, shift: bool):
        if self._scaling:
            # Corners keep the aspect ratio by default; Shift frees it.
            keep = not shift
            self._scale_fx, self._scale_fy = self._scale_factors_for(
                scene_pos, keep)
            view = _get_view(self)
            if view and hasattr(view, '_show_resize_foreshadow'):
                view._show_resize_foreshadow(
                    self._projected_bbox(), content=None, locked=keep)
        elif self._resizing:
            local = self.mapFromScene(scene_pos)
            dx = local.x() - self._resize_origin.x()
            dy = local.y() - self._resize_origin.y()
            self._resize_origin = local
            corner = self._resize_corner
            # Edge handles always stretch a single axis (Shift has no effect).
            self._apply_resize_delta(dx, dy, corner, False)
            scene = self.scene()
            if scene:
                for item in scene.selectedItems():
                    if isinstance(item, BoxItem) and item is not self:
                        item._apply_resize_delta(dx, dy, corner, False)
            view = _get_view(self)
            if view and hasattr(view, 'arrow_update_needed'):
                view.arrow_update_needed.emit()

    def _finish_handle_drag(self):
        view = _get_view(self)
        if self._scaling:
            self._scaling = False
            self._commit_scale()
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            if view and hasattr(view, '_clear_resize_foreshadow'):
                view._clear_resize_foreshadow()
            if view and hasattr(view, '_commit_pre_action_snapshot'):
                view._commit_pre_action_snapshot()
                view.mark_dirty()
            if view and hasattr(view, 'arrow_update_needed'):
                view.arrow_update_needed.emit()
        elif self._resizing:
            self._resizing = False
            self._min_h = self.box.h
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            if view and hasattr(view, '_commit_pre_action_snapshot'):
                view._commit_pre_action_snapshot()
                view.mark_dirty()

    # ── Corner-drag scale (whole selection; Shift keeps aspect ratio) ──

    def _begin_scale(self, corner: int, scene_pos: QPointF):
        """Start scaling the whole selection about its bounding box.

        Inkscape-style: a corner drag scales every selected item (boxes, notes,
        images) around the opposite corner of the selection's bounds, so the
        group keeps its relative layout. Font scales with the geometry.
        """
        self._scaling = True
        self._scale_corner = corner
        self._scale_fx = self._scale_fy = 1.0
        scene = self.scene()
        sel = ([i for i in scene.selectedItems()
                if isinstance(i, (BoxItem, NoteItem, ImageItem))]
               if scene else [])
        if self not in sel:
            sel.append(self)
        self._scale_members = []
        bbox = None
        for item in sel:
            r = self._member_rect(item)
            self._scale_members.append((item, r, self._member_font_px(item)))
            bbox = r if bbox is None else bbox.united(r)
        self._scale_bbox = bbox or self._member_rect(self)
        self._scale_pivot = self._corner_anchor(self._scale_bbox, corner)

    @staticmethod
    def _member_rect(item) -> QRectF:
        if isinstance(item, BoxItem):
            b = item.box
            return QRectF(b.x, b.y, b.w, b.h)
        if isinstance(item, ImageItem):
            im = item.image
            return QRectF(im.x, im.y, im.w, im.h)
        sr = item.sceneBoundingRect()
        return QRectF(sr.x(), sr.y(), sr.width(), sr.height())

    @staticmethod
    def _member_font_px(item):
        if isinstance(item, BoxItem):
            return item._box_font().pointSizeF()
        if isinstance(item, NoteItem):
            return item._note_font().pointSizeF()
        return None

    @staticmethod
    def _corner_anchor(rect: QRectF, corner: int) -> QPointF:
        """The fixed point (opposite the grabbed corner) during a scale."""
        if corner == _CORNER_TL:
            return rect.bottomRight()
        if corner == _CORNER_TR:
            return rect.bottomLeft()
        if corner == _CORNER_BL:
            return rect.topRight()
        return rect.topLeft()                       # _CORNER_BR

    @staticmethod
    def _scaled_frame(anchor: QPointF, corner: int, w: float, h: float) -> QRectF:
        """Frame of size w×h keeping ``anchor`` fixed for the given corner."""
        if corner == _CORNER_TL:
            return QRectF(anchor.x() - w, anchor.y() - h, w, h)
        if corner == _CORNER_TR:
            return QRectF(anchor.x(), anchor.y() - h, w, h)
        if corner == _CORNER_BL:
            return QRectF(anchor.x() - w, anchor.y(), w, h)
        return QRectF(anchor.x(), anchor.y(), w, h)  # _CORNER_BR

    def _scale_factors_for(self, scene_pos: QPointF, keep_ratio: bool):
        """(fx, fy) so the dragged corner of the selection follows the cursor."""
        pivot = self._scale_pivot
        w0, h0 = self._scale_bbox.width(), self._scale_bbox.height()
        fx = abs(scene_pos.x() - pivot.x()) / w0 if w0 else 1.0
        fy = abs(scene_pos.y() - pivot.y()) / h0 if h0 else 1.0
        fx, fy = max(fx, 0.05), max(fy, 0.05)
        if keep_ratio:
            fx = fy = max(fx, fy)
        return fx, fy

    def _projected_bbox(self) -> QRectF:
        w = self._scale_bbox.width() * self._scale_fx
        h = self._scale_bbox.height() * self._scale_fy
        return self._scaled_frame(self._scale_pivot, self._scale_corner, w, h)

    def _free_resize_rect(self, dx, dy, corner):
        """New (x, y, w, h) for a free (per-axis) resize."""
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
        return x, y, w, h

    def _apply_resize_delta(self, dx: float, dy: float, corner: int,
                            keep_ratio: bool = False):
        """Apply a single-axis (edge) resize delta for the given handle.

        Corner scaling goes through the selection-scale path; this drives the
        edge handles, which always stretch one axis. ``keep_ratio`` is accepted
        for call-site symmetry but ignored — edges never preserve the ratio.
        """
        x, y, w, h = self._free_resize_rect(dx, dy, corner)

        self.box.x = x
        self.box.y = y
        self.box.w = w
        self.box.h = h
        self.setPos(x, y)
        self.setRect(0, 0, w, h)
        self._label.setTextWidth(self._label_width_for(w))
        self._position_label()
        self._update_handles()

    def mouseMoveEvent(self, event):
        if self._scaling or self._resizing:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._update_handle_drag(event.scenePos(), shift)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        _end_drag_guides(self)
        if self._scaling or self._resizing:
            self._finish_handle_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _commit_scale(self):
        """Scale every selected item about the selection pivot, on release."""
        fx, fy = self._scale_fx, self._scale_fy
        # Corner scaling carries the font: the exact factor when ratio-locked,
        # else the geometric mean of the two axis factors.
        font_factor = fx if abs(fx - fy) < 1e-9 else (fx * fy) ** 0.5
        view = _get_view(self)
        if view and hasattr(view, '_scale_members'):
            view._scale_members(self._scale_members, fx, fy, font_factor,
                                self._scale_pivot)
        self._scale_members = []

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

    def set_lod_simplified(self, simplified: bool) -> None:
        """Mark/clear the zoomed-out simplified state (driven by the view)."""
        if simplified == self._lod_simplified:
            return
        self._lod_simplified = simplified
        self.update()

    def set_lod_tile(self, summary) -> None:
        """Set/clear collapsed-container tile rendering from a ContainerSummary."""
        tile = (summary.label, summary.descendants) if summary else None
        if tile == self._lod_tile:
            return
        self.prepareGeometryChange()   # boundingRect grows for the stack mark
        self._lod_tile = tile
        # A tile is read-only: dragging it would move the container box but
        # leave its absolutely-positioned children behind (desync). Disable the
        # move flag while collapsed; restore it when expanded.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, tile is None)
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._lod_tile is not None:
            self._paint_lod_stack(painter)   # offset edges behind the fill
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        radius = 0 if self.box.style == "flat" or self._is_parent else BOX_RADIUS
        painter.drawRoundedRect(self.rect(), radius, radius)

        if self._lod_tile is not None:
            self._paint_lod_tile(painter)
        elif (not self._lod_simplified
                and self.box.icon and iconset.has_icon(self.box.icon)):
            self._paint_icon(painter)

        if self.box.url:
            _paint_link_glyph(painter, self.rect())

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

    def _paint_lod_stack(self, painter: QPainter):
        """Mark a tile as a LoD summary by stacking it like a few thin notebooks:
        only the *edges* of the layers underneath peek out at the top and right
        (the front cover hides the rest). Counter-scaled so the offset stays a
        small, capped on-screen amount — compact, never bloats the layout."""
        scale = _view_scale(self)
        if scale <= 0:
            return
        off = min(5.0 / scale, 30.0)
        front = self.rect()
        base = QColor(self.brush().color())
        if base.alpha() == 0:
            base = QColor("#C8CCD0")
        base.setAlpha(255)
        front_path = QPainterPath()
        front_path.addRect(front)
        pen = QPen(QColor(0, 0, 0, 70))
        pen.setWidthF(max(0.8, 1.0 / scale))
        # One layer: just the L-shaped sliver of a single notebook behind the
        # cover peeks out at the top and right.
        layer = QPainterPath()
        layer.addRect(front.translated(off, -off))
        visible = layer.subtracted(front_path)
        painter.fillPath(visible, base.darker(122))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(visible)

    def _paint_lod_tile(self, painter: QPainter):
        """Draw a collapsed container as a headline + child-count badge.

        Drawn counter-scaled to the view zoom so the text stays readable as the
        tile shrinks on screen (like a place name on a map), but capped to the
        tile's on-screen size so it never overflows a small tile.
        """
        label, count = self._lod_tile
        rect = self.rect()
        scale = _view_scale(self)
        if scale <= 0:
            return
        on_screen_min = min(rect.width(), rect.height()) * scale
        head_px = max(7.0, min(16.0, on_screen_min * 0.32))

        painter.save()
        painter.translate(rect.center())
        painter.scale(1.0 / scale, 1.0 / scale)   # 1 unit == 1 on-screen px

        head_font = QFont(FONT_FAMILY)
        head_font.setPixelSize(round(head_px))
        head_font.setBold(True)
        painter.setFont(head_font)
        painter.setPen(QColor("#2F3437"))
        fm = QFontMetricsF(head_font)
        gap = head_px * 0.35
        badge_px = max(6.0, head_px * 0.72)
        total_h = fm.height() + gap + badge_px
        top = -total_h / 2
        painter.drawText(
            QRectF(-fm.horizontalAdvance(label), top,
                   2 * fm.horizontalAdvance(label), fm.height()),
            Qt.AlignmentFlag.AlignCenter, label)

        badge_font = QFont(FONT_FAMILY)
        badge_font.setPixelSize(round(badge_px))
        painter.setFont(badge_font)
        painter.setPen(QColor("#2F3437"))
        text = f"{count} node" + ("" if count == 1 else "s")
        bfm = QFontMetricsF(badge_font)
        bw = bfm.horizontalAdvance(text)
        painter.drawText(
            QRectF(-bw, top + fm.height() + gap, 2 * bw, badge_px * 1.6),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)
        painter.restore()


class ClusterHullItem(QGraphicsPathItem):
    """A concave "bubble" enclosing a collapsed parent-less node cluster.

    The outline is a pure-Qt concave hull: the boolean union of each member's
    inflated rounded-rect with a thick-stroked path of the member-to-member
    edges (so the blob follows the graph and never fragments). The cluster has
    no backing element, so it is navigation-only — it carries a hub label and
    node count drawn counter-scaled at the centroid, like a collapsed tile.
    """

    def __init__(self, member_rects, edges, pad: float,
                 label: str, count: int, color: str):
        super().__init__()
        self._label = label
        self._count = count
        path = self._build_path(member_rects, edges, pad)
        self.setPath(path)
        self._centroid = path.boundingRect().center()
        fill = QColor(color)
        fill.setAlphaF(0.16)
        self.setBrush(QBrush(fill))
        pen = QPen(QColor(color))
        pen.setWidthF(2.5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        # Dashed outline marks the hull as a derived boundary (a LoD summary),
        # not an authored shape.
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(-100)   # behind the (hidden) nodes and arrows
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    @staticmethod
    def _build_path(member_rects, edges, pad: float) -> QPainterPath:
        path = QPainterPath()
        centers: dict[str, QPointF] = {}
        for mid, (x, y, w, h) in member_rects.items():
            sub = QPainterPath()
            sub.addRoundedRect(QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad),
                               pad, pad)
            path = path.united(sub)
            centers[mid] = QPointF(x + w / 2, y + h / 2)
        if edges:
            ep = QPainterPath()
            for a, b in edges:
                if a in centers and b in centers:
                    ep.moveTo(centers[a])
                    ep.lineTo(centers[b])
            stroker = QPainterPathStroker()
            stroker.setWidth(2 * pad)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            path = path.united(stroker.createStroke(ep))
        return path.simplified()

    def centroid(self) -> QPointF:
        return QPointF(self._centroid)

    def boundary_point(self, from_pt: QPointF) -> QPointF:
        """Where a line from ``from_pt`` to the centroid crosses the hull
        outline — the attach point for an external arrow into the cluster."""
        path = self.path()
        if path.contains(from_pt):
            return QPointF(self._centroid)
        outside, inside = QPointF(from_pt), QPointF(self._centroid)
        for _ in range(24):
            mid = (outside + inside) / 2
            if path.contains(mid):
                inside = mid
            else:
                outside = mid
        return outside

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)   # fill + concave outline

        scale = _view_scale(self)
        if scale <= 0:
            return
        painter.save()
        painter.translate(self._centroid)
        painter.scale(1.0 / scale, 1.0 / scale)
        head_font = QFont(FONT_FAMILY)
        head_font.setPixelSize(14)
        head_font.setBold(True)
        painter.setFont(head_font)
        painter.setPen(QColor("#2F3437"))
        fm = QFontMetricsF(head_font)
        gap = 5.0
        badge_px = 10.0
        top = -(fm.height() + gap + badge_px) / 2
        painter.drawText(
            QRectF(-fm.horizontalAdvance(self._label), top,
                   2 * fm.horizontalAdvance(self._label), fm.height()),
            Qt.AlignmentFlag.AlignCenter, self._label)
        badge_font = QFont(FONT_FAMILY)
        badge_font.setPixelSize(round(badge_px))
        painter.setFont(badge_font)
        text = f"{self._count} nodes"
        bfm = QFontMetricsF(badge_font)
        bw = bfm.horizontalAdvance(text)
        painter.drawText(
            QRectF(-bw, top + fm.height() + gap, 2 * bw, badge_px * 1.6),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)
        painter.restore()


class NoteItem(QGraphicsSimpleTextItem):
    """A draggable free-text note with Neovim-style badge rendering."""

    _PAD = 6
    _CODE_PAD = 10
    _BADGE_GAP = 5
    _BADGE_HPAD = 5
    _BADGE_RADIUS = 3
    _BG_RADIUS = 4
    _CODE_BG_RADIUS = 6
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
        self.setAcceptHoverEvents(True)
        self._code_ref_rects: list[tuple[QRectF, str]] = []
        self._pending_ref: tuple[str, QPointF] | None = None
        self._update_url_indicator()

    def _ref_at(self, pos: QPointF) -> str | None:
        for rect, ref in self._code_ref_rects:
            if rect.contains(pos):
                return ref
        return None

    _RESIZE_EDGE_PX = 10
    _RESIZE_EDGE_OUTSIDE = 6  # forgiving overshoot when the cursor exits

    def shape(self):
        # QGraphicsSimpleTextItem's default shape is the text outline, so
        # hit-testing only fires on the actual glyphs — that hides the
        # right-edge resize grip and any whitespace inside the note. Return
        # the full painted bounding rect instead.
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def contains(self, point: QPointF) -> bool:
        # QGraphicsSimpleTextItem's C++ hit-test (used by scene.itemAt, clicks,
        # rubber-band, and the Alt-drag connector) is keyed on the base class's
        # *unwrapped* single-line text geometry. Once an explicit width wraps the
        # note that geometry diverges from what we actually paint, leaving the
        # clickable area stuck on the first line. Test against our real shape so
        # the whole visible note responds.
        return self.shape().contains(point)

    def _on_right_edge(self, pos) -> bool:
        br = self.boundingRect()
        if br.isEmpty():
            return False
        # boundingRect() inflates by 4 px when selected (selection halo);
        # subtract that so the detection zone tracks the *visible* right
        # edge regardless of selection state.
        if self.isSelected():
            br = br.adjusted(4, 4, -4, -4)
        return (
            br.right() - self._RESIZE_EDGE_PX
            <= pos.x()
            <= br.right() + self._RESIZE_EDGE_OUTSIDE
            and br.top() <= pos.y() <= br.bottom()
        )

    def hoverMoveEvent(self, event):
        if self._is_code_note() and self._ref_at(event.pos()) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._is_md_note() and self._md_anchor_at(event.pos()) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._is_md_note() and self._md_task_index_at(event.pos()) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._on_right_edge(event.pos()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        self._pending_ref = None
        self._pending_link = None
        self._pending_task = None
        self._resizing = False
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._on_right_edge(event.pos())
        ):
            self._resizing = True
            self._resize_start_x = event.scenePos().x()
            self._resize_start_chars = self.note.wrap_chars
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._is_code_note()
        ):
            ref = self._ref_at(event.pos())
            if ref is not None:
                self._pending_ref = (ref, event.pos())
        elif (
            event.button() == Qt.MouseButton.LeftButton
            and self._is_md_note()
        ):
            href = self._md_anchor_at(event.pos())
            if href is not None:
                self._pending_link = (href, event.pos())
            else:
                idx = self._md_task_index_at(event.pos())
                if idx is not None:
                    self._pending_task = (idx, event.pos())
        _begin_drag_guides(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_resizing", False):
            font = self._note_font()
            char_w = QFontMetricsF(font).averageCharWidth() or 8.0
            delta_px = event.scenePos().x() - self._resize_start_x
            # Continuous pixel target for the visual box — moves with the
            # cursor at sub-character precision so the box doesn't appear
            # to snap word-by-word while dragging.
            start_px = self._resize_start_chars * char_w
            target_px = max(40.0, start_px + delta_px)
            # Integer character count drives text wrap (still word-aligned).
            new_chars = max(10, int(round(target_px / max(1.0, char_w))))
            prev_target = getattr(self, "_resize_target_px", None)
            changed = (
                new_chars != self.note.wrap_chars or target_px != prev_target
            )
            if changed:
                self.prepareGeometryChange()
                self.note.wrap_chars = new_chars
                self.note.wrap_chars_explicit = True
                self._resize_target_px = target_px
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        _end_drag_guides(self)
        if getattr(self, "_resizing", False):
            self._resizing = False
            self._resize_target_px = None
            self.prepareGeometryChange()
            self.update()
            view = _get_view(self)
            if view is not None and hasattr(view, "mark_dirty"):
                view.mark_dirty()
            event.accept()
            return
        pending = self._pending_ref
        self._pending_ref = None
        if (
            pending is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            ref, press_pos = pending
            if (event.pos() - press_pos).manhattanLength() <= 4 \
                    and self._ref_at(event.pos()) == ref:
                view = _get_view(self)
                if view is not None and hasattr(view, "_open_code_ref"):
                    view._open_code_ref(ref)
                    event.accept()
                    super().mouseReleaseEvent(event)
                    return
        pending_link = getattr(self, "_pending_link", None)
        self._pending_link = None
        if (
            pending_link is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            href, press_pos = pending_link
            if (event.pos() - press_pos).manhattanLength() <= 4 \
                    and self._md_anchor_at(event.pos()) == href:
                view = _get_view(self)
                if view is not None and hasattr(view, "_open_url_string"):
                    view._open_url_string(href)
                    event.accept()
                    super().mouseReleaseEvent(event)
                    return
        pending_task = getattr(self, "_pending_task", None)
        self._pending_task = None
        if (
            pending_task is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            idx, press_pos = pending_task
            if (event.pos() - press_pos).manhattanLength() <= 4 \
                    and self._md_task_index_at(event.pos()) == idx:
                view = _get_view(self)
                if view is not None and hasattr(view, "_toggle_md_task"):
                    view._toggle_md_task(self, idx)
                    event.accept()
                    super().mouseReleaseEvent(event)
                    return
        super().mouseReleaseEvent(event)

    def _wrap_cache_key(self) -> tuple:
        # style (mono) and emphasis (bold/italic) change the rendering font,
        # so they must invalidate the wrap / markdown / code layout caches —
        # otherwise toggling them shows no change until the next text edit.
        return (self.note.text, self.note.wrap_chars, self.note.textsize,
                self.note.wrap_chars_explicit, self.note.icon,
                self.note.style, self.note.emphasis)

    def _bbox_cache_key(self, sel: bool) -> tuple:
        # Include the live drag target so the visible box tracks the cursor
        # smoothly (text wrap is still keyed on wrap_chars only).
        return (self._wrap_cache_key(), sel,
                getattr(self, "_resize_target_px", None))

    def set_icon(self, name: str, placement: str = ""):
        self.prepareGeometryChange()
        self.note.icon = name
        self.note.icon_placement = placement
        self._brect_cache = None
        self.update()

    def set_emphasis(self, emphasis: str):
        self.prepareGeometryChange()
        self.note.emphasis = emphasis
        self._brect_cache = None
        self.update()

    def set_flat(self, flat: bool):
        """Toggle the background plate — flat notes draw text on the canvas."""
        self.note.flat = flat
        self.update()

    def _icon_color(self) -> QColor:
        return (QColor(_resolve_color(self.note.color)) if self.note.color
                else QColor("#2F3437"))

    def _icon_side(self) -> float:
        px = resolve_textsize_px(self.note.textsize, "")
        if self.note.icon_placement == "lead":
            return max(16.0, min(px * 1.7, 64.0))
        return max(40.0, min(220.0, px * 3.5))

    def _icon_metrics(self):
        """(side, caption_lines, total_w, total_h) for a glyph note —
        ``fill`` stacks icon over caption, ``lead`` sets icon left of text."""
        pad = self._PAD
        side = self._icon_side()
        lead = self.note.icon_placement == "lead"
        lines: list[str] = []
        text_w = text_h = 0.0
        if self.note.text:
            font = self._note_font()
            fm = QFontMetricsF(font)
            wrap_w = self._wrap_width_px(font) if lead else max(side, 80.0)
            lines = self._wrap_text_to_width(self.note.text, font, wrap_w)
            text_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0.0)
            text_h = len(lines) * fm.height()
        if lead:
            gap = 6.0 if lines else 0.0
            total_w = pad + side + gap + text_w + pad
            total_h = pad + max(side, text_h) + pad
        else:
            cap_h = text_h + 4 if lines else 0.0
            total_w = pad + max(side, text_w) + pad
            total_h = pad + side + cap_h + pad
        return side, lines, total_w, total_h

    def _paint_icon_note(self, painter: QPainter):
        """A borderless floating glyph. ``fill``: big icon with the text as a
        caption beneath. ``lead``: a small icon left of the text."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side, lines, total_w, total_h = self._icon_metrics()
        pad = self._PAD
        color = self._icon_color()
        font = self._note_font()
        fm = QFontMetricsF(font)
        if self.note.icon_placement == "lead":
            iconset.paint_icon(painter, self.note.icon,
                               QRectF(pad, (total_h - side) / 2, side, side),
                               color)
            painter.setFont(font)
            painter.setPen(color)
            if lines:
                x = pad + side + 6
                y = (total_h - len(lines) * fm.height()) / 2 + fm.ascent()
                for ln in lines:
                    painter.drawText(QPointF(x, y), ln)
                    y += fm.height()
        else:
            iconset.paint_icon(painter, self.note.icon,
                               QRectF((total_w - side) / 2, pad, side, side),
                               color)
            painter.setFont(font)
            painter.setPen(color)
            if lines:
                y = pad + side + fm.ascent() + 2
                for ln in lines:
                    tw = fm.horizontalAdvance(ln)
                    painter.drawText(QPointF((total_w - tw) / 2, y), ln)
                    y += fm.height()
        if self.isSelected():
            painter.setPen(QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, total_w, total_h).adjusted(-3, -3, 3, 3))

    def _wrap_width_px(self, font: QFont) -> float:
        """Pixel width corresponding to ``note.wrap_chars`` for *font*."""
        fm = QFontMetricsF(font)
        # Average char width tracks proportional fonts; floor at a small
        # value so a degenerate metric never produces a zero-width target.
        return max(40.0, fm.averageCharWidth() * self.note.wrap_chars)

    @staticmethod
    def _wrap_text_to_width(
        text: str, font: QFont, max_w: float,
    ) -> list[str]:
        """Pure soft-wrap. Preserves \\n, blank lines, leading indent."""
        fm = QFontMetricsF(font)
        out: list[str] = []
        for raw_line in text.split("\n"):
            if not raw_line.strip():
                out.append(raw_line)
                continue
            indent_len = len(raw_line) - len(raw_line.lstrip())
            indent = raw_line[:indent_len]
            words = raw_line[indent_len:].split(" ")
            cur = ""
            for w in words:
                trial = (cur + " " + w) if cur else w
                if fm.horizontalAdvance(indent + trial) <= max_w or not cur:
                    cur = trial
                else:
                    out.append(indent + cur)
                    cur = w
            out.append(indent + cur)
        return out

    def _wrap_lines(self, text: str, font: QFont) -> list[str]:
        """Soft-wrap ``text`` for plain-text notes (cached)."""
        cache = getattr(self, "_plain_wrap_cache", None)
        key = (text, self._wrap_cache_key())
        if cache is not None and cache[0] == key:
            return cache[1]
        max_w = self._wrap_width_px(font)
        fm = QFontMetricsF(font)
        out: list[str] = []
        for raw_line in text.split("\n"):
            if not raw_line.strip():
                out.append(raw_line)
                continue
            indent_len = len(raw_line) - len(raw_line.lstrip())
            indent = raw_line[:indent_len]
            words = raw_line[indent_len:].split(" ")
            cur = ""
            for w in words:
                trial = (cur + " " + w) if cur else w
                if fm.horizontalAdvance(indent + trial) <= max_w or not cur:
                    cur = trial
                else:
                    out.append(indent + cur)
                    cur = w
            out.append(indent + cur)
        self._plain_wrap_cache = (key, out)
        return out

    def _parse_note(self):
        """Extract badge prefix, body text, and accent color."""
        p = note_prefix(self.note.text)
        if p is None:
            return "", self.note.text, NOTE_PEN_COLOR
        badge, body = p
        accent = NOTE_TASK_COLOR if badge == "T:" else NOTE_QUESTION_COLOR
        return badge, body, accent

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

    def _wrapped_discussion(self, blocks):
        """Wrap each speaker block's lines to fit the wrap budget. Cached.

        Returns ``(wrapped_blocks, max_badge_w, line_h, total_w, total_h)``
        where ``wrapped_blocks`` is the same shape as the parsed blocks
        but with each line softly wrapped to the body-area budget.
        """
        cache = getattr(self, "_discussion_cache", None)
        key = self._wrap_cache_key()
        if cache is not None and cache[0] == key:
            return cache[1]
        font = self._note_font()
        fm = QFontMetricsF(font)
        bold_font = QFont(font)
        bold_font.setBold(True)
        bfm = QFontMetricsF(bold_font)
        pad = self._PAD
        line_h = fm.height()

        max_badge_w = max(
            bfm.horizontalAdvance(sp) + self._BADGE_HPAD * 2
            for sp, _, _ in blocks
        )
        target_total_w = self._wrap_width_px(font) + 2 * pad
        body_area_w = max(
            80.0,
            target_total_w - 2 * pad - max_badge_w - self._BADGE_GAP,
        )

        wrapped_blocks = []
        longest_body_w = 0.0
        for sp, lns, color in blocks:
            wrapped: list[str] = []
            for ln in lns:
                wrapped.extend(
                    self._wrap_text_to_width(ln, font, body_area_w)
                )
            wrapped_blocks.append((sp, wrapped, color))
            for ln in wrapped:
                longest_body_w = max(longest_body_w, fm.horizontalAdvance(ln))

        total_lines = sum(len(lns) for _, lns, _ in wrapped_blocks)
        gap_h = (len(wrapped_blocks) - 1) * self._BLOCK_GAP
        content_total_w = (
            pad + max_badge_w + self._BADGE_GAP + longest_body_w + pad
        )
        if self.note.wrap_chars_explicit:
            total_w = max(content_total_w, target_total_w)
        else:
            total_w = content_total_w
        total_h = pad + total_lines * line_h + gap_h + pad
        result = (wrapped_blocks, max_badge_w, line_h, total_w, total_h)
        self._discussion_cache = (key, result)
        return result

    def _discussion_metrics(self, blocks):
        """Backwards-compatible shim — delegates to wrapped layout."""
        _, max_badge_w, line_h, total_w, total_h = self._wrapped_discussion(blocks)
        body_w = total_w - 2 * self._PAD - max_badge_w - self._BADGE_GAP
        return max_badge_w, body_w, line_h, total_w, total_h

    _CODE_DIVIDER_GAP = 6

    def _is_code_note(self) -> bool:
        return is_code_note(self.note.text)

    def _is_md_note(self) -> bool:
        return note_is_md(self.note)

    def _md_document(self) -> QTextDocument:
        """Build (cached) a laid-out QTextDocument for a Markdown note.

        Keyed on the same wrap cache key as the other note modes — Qt
        re-queries geometry and repaints constantly during drag, and
        re-parsing Markdown every frame is wasteful.
        """
        cache = getattr(self, "_md_doc_cache", None)
        key = self._wrap_cache_key()
        if cache is not None and cache[0] == key:
            return cache[1]
        font = self._note_font()
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDefaultStyleSheet(_md_stylesheet(font.pointSizeF()))
        doc.setDocumentMargin(0)
        # GitHub-flavoured: task lists, strikethrough, tables. We document
        # a smaller recommended subset; extras degrade rather than break.
        doc.setMarkdown(
            note_md_body(self.note),
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub,
        )
        doc.setTextWidth(self._wrap_width_px(font))
        self._style_code_spans(doc)
        self._md_doc_cache = (key, doc)
        return doc

    @staticmethod
    def _style_code_spans(doc: QTextDocument):
        """Give inline code and fenced blocks a muted plate.

        The note font is already monospace, so code spans would otherwise
        be invisible. Background brushes (unlike text colour) do render via
        the document layout, so we set them directly on the char formats
        Qt marked as fixed-pitch during the Markdown import.
        """
        bg = QBrush(NOTE_MD_CODE_BG_COLOR)
        cursor = QTextCursor(doc)
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().fontFixedPitch():
                    fmt = QTextCharFormat()
                    fmt.setBackground(bg)
                    cursor.setPosition(frag.position())
                    cursor.setPosition(
                        frag.position() + frag.length(),
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    cursor.mergeCharFormat(fmt)
                it += 1
            block = block.next()

    def _md_metrics(self):
        """Return ``(content_w, total_w, total_h)`` for a Markdown note."""
        doc = self._md_document()
        pad = self._PAD
        # idealWidth is the width the laid-out text actually used, so a
        # short note doesn't stretch to the full wrap budget.
        content_w = doc.idealWidth()
        total_w = pad + content_w + pad
        total_h = pad + doc.size().height() + pad
        if self.note.wrap_chars_explicit:
            total_w = max(total_w, self._wrap_width_px(self._note_font()) + 2 * pad)
        return content_w, total_w, total_h

    def _md_anchor_at(self, pos: QPointF) -> str | None:
        """Return the link href under *pos* (item coords), or None."""
        if not self._is_md_note():
            return None
        doc = self._md_document()
        layout = doc.documentLayout()
        href = layout.anchorAt(QPointF(pos.x() - self._PAD, pos.y() - self._PAD))
        return href or None

    def _md_task_index_at(self, pos: QPointF) -> int | None:
        """Return the 0-based index of the task-list item whose line is under
        *pos* (item coords) among all checkbox items, or None.

        The whole rendered line is the hit zone (not just the marker glyph),
        and the index counts checkbox blocks in document order — the same
        order ``md_note.toggle_task`` walks the source, so they stay aligned.
        """
        if not self._is_md_note():
            return None
        doc = self._md_document()
        layout = doc.documentLayout()
        y = pos.y() - self._PAD
        idx = 0
        block = doc.begin()
        while block.isValid():
            marker = block.blockFormat().marker()
            if marker in (QTextBlockFormat.MarkerType.Checked,
                          QTextBlockFormat.MarkerType.Unchecked):
                rect = layout.blockBoundingRect(block)
                if rect.top() <= y <= rect.bottom():
                    return idx
                idx += 1
            block = block.next()
        return None

    def _code_lines(self) -> tuple[int | None, list[str]]:
        return split_signature(self.note.text)

    def _visual_code_lines(self):
        """Expand logical code lines to wrapped visual lines.

        Returns ``(visual_sig_idx, visual_lines)`` where each entry of
        ``visual_lines`` is ``(text, is_sig, indent_cols)``. Continuations
        of a wrapped logical line use a hanging indent of two spaces;
        ``indent_cols`` carries the *original* indent so the indent
        guides stay vertically aligned to the source's block level.
        Memoised against the wrap cache key.
        """
        cache = getattr(self, "_code_wrap_cache", None)
        key = self._wrap_cache_key()
        if cache is not None and cache[0] == key:
            return cache[1]
        sig_idx, logical = self._code_lines()
        font = self._code_font()
        bold_font = self._code_signature_font()
        fm = QFontMetricsF(font)
        bfm = QFontMetricsF(bold_font)
        max_content_w = max(
            40.0,
            self._wrap_width_px(font) - 2 * self._CODE_PAD,
        )

        def line_w(text: str, is_sig: bool) -> float:
            w = 0.0
            for kind, t in tokenize_line(text):
                if is_sig or kind in _CODE_BOLD_KINDS:
                    w += bfm.horizontalAdvance(t)
                else:
                    w += fm.horizontalAdvance(t)
            return w

        visual: list[tuple[str, bool, int]] = []
        new_sig_idx: int | None = None
        for li, line in enumerate(logical):
            is_sig = (li == sig_idx)
            indent_cols = len(line) - len(line.lstrip(" "))
            if not line.strip():
                visual.append((line, is_sig, indent_cols))
                if is_sig:
                    new_sig_idx = len(visual) - 1
                continue
            if line_w(line, is_sig) <= max_content_w:
                visual.append((line, is_sig, indent_cols))
                if is_sig:
                    new_sig_idx = len(visual) - 1
                continue
            indent = line[:indent_cols]
            cont_indent = indent + "  "
            words = line[indent_cols:].split(" ")
            cur: list[str] = []
            first = True
            for word in words:
                lead = indent if first else cont_indent
                trial = cur + [word]
                trial_text = lead + " ".join(trial)
                if line_w(trial_text, is_sig) <= max_content_w or not cur:
                    cur = trial
                else:
                    visual.append(((indent if first else cont_indent)
                                  + " ".join(cur), is_sig, indent_cols))
                    first = False
                    cur = [word]
            if cur:
                visual.append(((indent if first else cont_indent)
                              + " ".join(cur), is_sig, indent_cols))
            if is_sig:
                new_sig_idx = len(visual) - 1
        result = (new_sig_idx, visual)
        self._code_wrap_cache = (key, result)
        return result

    def _code_font(self) -> QFont:
        return self._note_font()

    def _code_signature_font(self) -> QFont:
        f = QFont(self._code_font())
        f.setBold(True)
        return f

    def _code_metrics(self, visual_lines):
        """Compute width/height/etc for already-wrapped visual lines.

        Memoised against the wrap cache key — Qt asks for boundingRect
        and paints constantly during drag, so re-tokenising every visual
        line every frame visibly slows things down on big notes.
        """
        cache = getattr(self, "_code_metrics_cache", None)
        key = self._wrap_cache_key()
        if cache is not None and cache[0] == key:
            return cache[1]
        font = self._code_font()
        bold_font = QFont(font)
        bold_font.setBold(True)
        fm = QFontMetricsF(font)
        bfm = QFontMetricsF(bold_font)
        pad = self._CODE_PAD
        line_h = fm.height()
        has_sig = any(is_sig for _, is_sig, _ in visual_lines)
        divider_gap = self._CODE_DIVIDER_GAP if has_sig else 0

        def _line_w(line: str, is_sig: bool) -> float:
            w = 0.0
            for kind, text in tokenize_line(line):
                if is_sig or kind in _CODE_BOLD_KINDS:
                    w += bfm.horizontalAdvance(text)
                else:
                    w += fm.horizontalAdvance(text)
            return w

        body_w = max((_line_w(ln, sig) for ln, sig, _ in visual_lines),
                     default=0.0)
        total_w = pad + body_w + pad
        total_h = pad + len(visual_lines) * line_h + divider_gap + pad
        result = (body_w, line_h, divider_gap, total_w, total_h)
        self._code_metrics_cache = (key, result)
        return result

    def boundingRect(self):
        sel = self.isSelected()
        cache = getattr(self, "_brect_cache", None)
        cache_key = self._bbox_cache_key(sel)
        if cache is not None and cache[0] == cache_key:
            return cache[1]
        target_px = getattr(self, "_resize_target_px", None)
        if self.note.icon and iconset.has_icon(self.note.icon):
            _, _, tw, th = self._icon_metrics()
            r = QRectF(0, 0, tw, th)
        elif self._is_code_note():
            _, visual = self._visual_code_lines()
            _, _, _, tw, th = self._code_metrics(visual)
            if self.note.wrap_chars_explicit:
                min_w = self._wrap_width_px(self._code_font()) + 2 * self._CODE_PAD
                tw = max(tw, min_w)
            if target_px is not None:
                tw = max(tw, target_px)
            r = QRectF(0, 0, tw, th)
        elif self._is_md_note():
            _, tw, th = self._md_metrics()
            if target_px is not None:
                tw = max(tw, target_px)
            r = QRectF(0, 0, tw, th)
        else:
            discussion = self._parse_discussion()
            if discussion:
                _, _, _, tw, th = self._discussion_metrics(discussion)
                if target_px is not None:
                    tw = max(tw, target_px)
                r = QRectF(0, 0, tw, th)
            else:
                prefix, body, _ = self._parse_note()
                font = self._note_font()
                fm = QFontMetricsF(font)
                pad = self._PAD
                body_font = QFont(font)
                body_fm = QFontMetricsF(body_font)
                lines = self._wrap_lines(body, body_font)
                body_w = max(
                    (body_fm.horizontalAdvance(ln) for ln in lines),
                    default=0,
                )
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
                if self.note.wrap_chars_explicit:
                    min_w = self._wrap_width_px(body_font) + 2 * pad
                    total_w = max(total_w, min_w)
                if target_px is not None:
                    total_w = max(total_w, target_px)
                total_h = pad + n_lines * line_h + pad
                r = QRectF(0, 0, total_w, total_h)
        if sel:
            r = r.adjusted(-4, -4, 4, 4)
        self._brect_cache = (cache_key, r)
        return r

    def paint(self, painter: QPainter, option, widget=None):
        if self.note.icon and iconset.has_icon(self.note.icon):
            self._paint_icon_note(painter)
            return

        if self._is_code_note():
            self._paint_code(painter)
            return

        if self._is_md_note():
            self._paint_markdown(painter)
            return

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
        body_fm = QFontMetricsF(body_font)
        lines = self._wrap_lines(body, body_font)
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

        if self.note.wrap_chars_explicit:
            min_w = self._wrap_width_px(body_font) + 2 * pad
            total_w = max(total_w, min_w)
        target_px = getattr(self, "_resize_target_px", None)
        if target_px is not None:
            total_w = max(total_w, target_px)
        total_h = pad + n_lines * line_h + pad
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Light background
        if not self.note.flat:
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
            _draw_text(painter, QPointF(pad + self._BADGE_HPAD, text_y),
                       prefix, bold_font, QColor("#FFFFFF"))

            # Body lines in accent color
            body_x = pad + badge_w + self._BADGE_GAP
            for i, ln in enumerate(lines):
                _draw_text(painter, QPointF(body_x, text_y + i * line_h),
                           ln, body_font, accent, self.note.emphasis)
        else:
            # Plain note: accent-colored text, no badge
            for i, ln in enumerate(lines):
                _draw_text(painter, QPointF(pad, text_y + i * line_h),
                           ln, body_font, accent, self.note.emphasis)

        if self.note.url:
            _paint_link_glyph(painter, bg_rect)

        # Selection indicator + always-visible resize grip
        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)
            self._paint_resize_grip(painter, total_w, total_h)

    def _paint_markdown(self, painter: QPainter):
        doc = self._md_document()
        pad = self._PAD
        _, total_w, total_h = self._md_metrics()
        target_px = getattr(self, "_resize_target_px", None)
        if target_px is not None:
            total_w = max(total_w, target_px)
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.note.flat:
            bg = QColor("#F2F0EB")
            bg.setAlphaF(0.85)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(bg_rect, self._BG_RADIUS, self._BG_RADIUS)

        painter.save()
        painter.translate(pad, pad)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        # Markdown notes are a sibling of code notes — a formatted block on
        # the beige plate — so they share the near-black body text, with
        # links picked out in the plain-note blue.
        ctx.palette.setColor(QPalette.ColorRole.Text, NOTE_CODE_TEXT_COLOR)
        ctx.palette.setColor(QPalette.ColorRole.Link, NOTE_PEN_COLOR)
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

        if self.note.url:
            _paint_link_glyph(painter, bg_rect)

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)
            self._paint_resize_grip(painter, total_w, total_h)

    def _paint_discussion(self, painter: QPainter, blocks):
        """Render a multi-speaker discussion note (with auto-wrapped lines)."""
        font = self._note_font()
        fm = QFontMetricsF(font)
        pad = self._PAD
        bold_font = QFont(font)
        bold_font.setBold(True)

        wrapped_blocks, max_badge_w, line_h, total_w, total_h = (
            self._wrapped_discussion(blocks)
        )
        target_px = getattr(self, "_resize_target_px", None)
        if target_px is not None:
            total_w = max(total_w, target_px)
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.note.flat:
            bg = QColor("#F2F0EB")
            bg.setAlphaF(0.85)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(bg_rect, self._BG_RADIUS, self._BG_RADIUS)

        body_x = pad + max_badge_w + self._BADGE_GAP
        y = pad

        for blk_idx, (speaker, lines, color) in enumerate(wrapped_blocks):
            # Speaker badge on first line
            bfm = QFontMetricsF(bold_font)
            badge_w = bfm.horizontalAdvance(speaker) + self._BADGE_HPAD * 2
            badge_rect = QRectF(pad, y, badge_w, line_h)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                badge_rect, self._BADGE_RADIUS, self._BADGE_RADIUS
            )

            _draw_text(painter, QPointF(pad + self._BADGE_HPAD, y + fm.ascent()),
                       speaker, bold_font, QColor("#FFFFFF"))

            # Body lines (already wrapped)
            for ln in lines:
                _draw_text(painter, QPointF(body_x, y + fm.ascent()), ln,
                           font, color, self.note.emphasis)
                y += line_h

            if blk_idx < len(wrapped_blocks) - 1:
                y += self._BLOCK_GAP

        if self.note.url:
            _paint_link_glyph(painter, bg_rect)

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)
            self._paint_resize_grip(painter, total_w, total_h)

    def _paint_code(self, painter: QPainter):
        new_sig_idx, visual = self._visual_code_lines()
        font = self._code_font()
        bold_font = QFont(font)
        bold_font.setBold(True)
        ref_font = QFont(bold_font)
        ref_font.setUnderline(True)
        comment_font = QFont(font)
        comment_font.setItalic(True)
        sig_font = self._code_signature_font()
        sig_ref_font = QFont(sig_font)
        sig_ref_font.setUnderline(True)
        fm = QFontMetricsF(font)
        bfm = QFontMetricsF(bold_font)
        pad = self._CODE_PAD
        indent_w = fm.horizontalAdvance("  ")

        _, line_h, divider_gap, total_w, total_h = self._code_metrics(visual)
        if self.note.wrap_chars_explicit:
            min_w = self._wrap_width_px(self._code_font()) + 2 * self._CODE_PAD
            total_w = max(total_w, min_w)
        target_px = getattr(self, "_resize_target_px", None)
        if target_px is not None:
            total_w = max(total_w, target_px)
        bg_rect = QRectF(0, 0, total_w, total_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.note.flat:
            bg = QColor(NOTE_CODE_BG_COLOR)
            bg.setAlphaF(0.85)
            border_color = NOTE_CODE_BORDER_COLOR
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(
                bg_rect.adjusted(0.5, 0.5, -0.5, -0.5),
                self._CODE_BG_RADIUS, self._CODE_BG_RADIUS,
            )

        # Per-visual-line top offsets, with a divider gap after the LAST
        # visual line that traces back to the signature (handles wrap of
        # the signature itself).
        line_tops: list[float] = []
        y_acc = pad
        for i in range(len(visual)):
            line_tops.append(y_acc)
            y_acc += line_h
            if i == new_sig_idx:
                y_acc += divider_gap

        # Divider rule under the signature
        if new_sig_idx is not None:
            div_y = line_tops[new_sig_idx] + line_h + divider_gap / 2
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(
                QPointF(pad, div_y),
                QPointF(total_w - pad, div_y),
            )

        # Indent guides — drawn at each visual line's *original* indent,
        # so a wrapped continuation aligns with its source block.
        guide_color = QColor(NOTE_CODE_INDENT_GUIDE_COLOR)
        guide_color.setAlphaF(0.5)
        guide_pen = QPen(guide_color, 1)
        for i, (_, _, indent_cols) in enumerate(visual):
            levels = indent_cols // 2
            if levels <= 0:
                continue
            y_top = line_tops[i]
            y_bot = y_top + line_h
            painter.setPen(guide_pen)
            for lvl in range(1, levels + 1):
                x = pad + (lvl - 0.5) * indent_w
                painter.drawLine(QPointF(x, y_top), QPointF(x, y_bot))

        ref_rects: list[tuple[QRectF, str]] = []
        for i, (line, is_sig, _) in enumerate(visual):
            x = pad
            y = line_tops[i] + fm.ascent()
            for kind, text in tokenize_line(line):
                if is_sig:
                    chosen_font = sig_ref_font if kind == "ref" else sig_font
                    metrics = bfm
                elif kind == "ref":
                    chosen_font = ref_font
                    metrics = bfm
                elif kind in _CODE_BOLD_KINDS:
                    chosen_font = bold_font
                    metrics = bfm
                elif kind == "comment":
                    chosen_font = comment_font
                    metrics = fm
                else:
                    chosen_font = font
                    metrics = fm
                painter.setFont(chosen_font)
                advance = metrics.horizontalAdvance(text)
                # On the signature line, everything reads as the title
                # (plain text colour); refs keep their link tone.
                if is_sig and kind != "ref":
                    color = NOTE_CODE_TEXT_COLOR
                else:
                    color = _CODE_KIND_COLORS.get(kind, NOTE_CODE_TEXT_COLOR)
                painter.setPen(color)
                painter.drawText(QPointF(x, y), text)
                if kind == "ref":
                    rect = QRectF(
                        x, y - fm.ascent() - 1,
                        advance, line_h + 2,
                    )
                    ref_rects.append((rect, text))
                x += advance

        self._code_ref_rects = ref_rects

        if self.note.url:
            _paint_link_glyph(painter, bg_rect)

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = bg_rect.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)
            self._paint_resize_grip(painter, total_w, total_h)

    def _paint_resize_grip(
        self, painter: QPainter, total_w: float, total_h: float,
    ) -> None:
        """Draw a clear, always-visible resize affordance on the right edge.

        Two vertical grip lines on top of a faint coloured band. Spans the
        full height of the note so the user can grab it from any vertical
        position regardless of where text wrapping landed.
        """
        band_w = 8
        if total_w < 2 * band_w or total_h < 8:
            return
        accent = QColor("#2F5D5C")
        # Faint background band
        bg = QColor(accent)
        bg.setAlphaF(0.10)
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        band_rect = QRectF(total_w - band_w, 0, band_w, total_h)
        painter.drawRect(band_rect)
        # Two vertical grip lines for clarity
        line = QColor(accent)
        line.setAlphaF(0.55)
        painter.setPen(QPen(line, 1.4))
        margin_y = max(4.0, min(8.0, total_h * 0.12))
        for offset in (3, 6):
            x = total_w - offset
            painter.drawLine(
                QPointF(x, margin_y),
                QPointF(x, total_h - margin_y),
            )

    def _apply_color(self):
        self.update()

    def _note_font(self) -> QFont:
        # Freeform notes are handwritten (Patrick Hand); code notes and notes
        # explicitly set to !mono use the monospace face.
        mono = self.note.style == "mono" or self._is_code_note()
        family = FONT_FAMILY if mono else NOTE_FONT_FAMILY
        return _apply_emphasis(
            QFont(family, resolve_textsize_px(self.note.textsize, "")),
            self.note.emphasis)

    def set_text_mono(self, mono: bool):
        """Switch a note between the monospace and handwritten face."""
        self.prepareGeometryChange()
        self.note.style = "mono" if mono else ""
        self._brect_cache = None
        self.update()

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
        """Refresh tooltip based on the attachment."""
        self.setToolTip(_attach_tooltip(self.note))
        self.update()

    def update_text(self, text: str):
        self.note.text = text
        self.setText(text)
        self.prepareGeometryChange()
        self._apply_color()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = _get_view(self)
            if view is not None and hasattr(view, 'snap_drag_pos'):
                return view.snap_drag_pos(self, value)
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
            ResizeHandle(h, self) for h in _ALL_HANDLES
        ]
        self._update_handles()
        self._update_url_indicator()

    def _update_url_indicator(self):
        """Refresh tooltip based on the attachment."""
        self.setToolTip(_attach_tooltip(self.image))

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
        r = QRectF(0, 0, self.image.w, self.image.h)
        points = _handle_points(r, _ALL_HANDLES)
        visible = self.isSelected()
        for handle in self._handles:
            pt = points.get(handle.corner)
            if pt is not None:
                handle.setPos(pt)
            handle.setVisible(visible)

    def _handle_at(self, pos: QPointF) -> int | None:
        r = QRectF(0, 0, self.image.w, self.image.h)
        return _handle_hit(r, _ALL_HANDLES, pos, _view_scale(self))

    def _apply_resize_delta(self, dx: float, dy: float, corner: int,
                            keep_ratio: bool = True):
        """Resize the image from a handle.

        Corners keep the image's aspect ratio by default (``keep_ratio``);
        Shift frees them for a non-uniform resize. Edge handles always stretch
        a single axis. The side opposite the dragged handle stays anchored.
        """
        if corner in _CORNERS and keep_ratio:
            x, y, w, h = self._prop_corner_rect(dx, dy, corner)
        else:
            x, y, w, h = self._free_resize_rect(dx, dy, corner)

        self.image.x = x
        self.image.y = y
        self.image.w = w
        self.image.h = h
        self.setPos(x, y)
        self.prepareGeometryChange()
        self._update_handles()
        self.update()

    def _prop_corner_rect(self, dx, dy, corner):
        """Aspect-locked corner resize; width drives, height follows."""
        x, y, w, h = self.image.x, self.image.y, self.image.w, self.image.h
        ar = self._aspect_ratio or (w / h if h else 1.0)
        dw = -dx if corner in (_CORNER_TL, _CORNER_BL) else dx
        new_w = max(self._MIN_SIZE, w + dw)
        new_h = new_w / ar
        if corner in (_CORNER_TL, _CORNER_BL):
            x -= new_w - w
        if corner in (_CORNER_TL, _CORNER_TR):
            y -= new_h - h
        return x, y, new_w, new_h

    def _free_resize_rect(self, dx, dy, corner):
        """Per-axis resize (free corner or single-axis edge)."""
        x, y, w, h = self.image.x, self.image.y, self.image.w, self.image.h
        left = corner in (_CORNER_TL, _CORNER_BL, _EDGE_L)
        right = corner in (_CORNER_TR, _CORNER_BR, _EDGE_R)
        top = corner in (_CORNER_TL, _CORNER_TR, _EDGE_T)
        bottom = corner in (_CORNER_BL, _CORNER_BR, _EDGE_B)

        new_w, new_h = w, h
        if left:
            new_w = max(self._MIN_SIZE, w - dx)
            x -= new_w - w
        elif right:
            new_w = max(self._MIN_SIZE, w + dx)
        if top:
            new_h = max(self._MIN_SIZE, h - dy)
            y -= new_h - h
        elif bottom:
            new_h = max(self._MIN_SIZE, h + dy)
        return x, y, new_w, new_h

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

        if self.image.url:
            _paint_link_glyph(painter, target)

        if self.isSelected():
            sel_pen = QPen(QColor("#2F5D5C"), 2, Qt.PenStyle.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = target.adjusted(-3, -3, 3, 3)
            painter.drawRect(sel_rect)

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

    def _begin_handle_drag(self, corner: int, scene_pos: QPointF):
        self._resizing = True
        self._resize_corner = corner
        self._resize_origin = self.mapFromScene(scene_pos)
        view = _get_view(self)
        if view and hasattr(view, '_save_pre_action_snapshot'):
            view._save_pre_action_snapshot()

    def _update_handle_drag(self, scene_pos: QPointF, shift: bool):
        if not self._resizing:
            return
        local = self.mapFromScene(scene_pos)
        dx = local.x() - self._resize_origin.x()
        dy = local.y() - self._resize_origin.y()
        self._resize_origin = local
        # Corners keep aspect by default; Shift frees them. Edges: single axis.
        self._apply_resize_delta(dx, dy, self._resize_corner, not shift)
        view = _get_view(self)
        if view and hasattr(view, 'arrow_update_needed'):
            view.arrow_update_needed.emit()
        if view and hasattr(view, 'mark_dirty'):
            view.mark_dirty()

    def _finish_handle_drag(self):
        if not self._resizing:
            return
        self._resizing = False
        view = _get_view(self)
        if view and hasattr(view, '_commit_pre_action_snapshot'):
            view._commit_pre_action_snapshot()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected():
            corner = self._handle_at(event.pos())
            if corner is not None:
                self._begin_handle_drag(corner, event.scenePos())
                event.accept()
                return
        _begin_drag_guides(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._update_handle_drag(event.scenePos(), shift)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        _end_drag_guides(self)
        if self._resizing:
            self._finish_handle_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            view = _get_view(self)
            if view is not None and hasattr(view, 'snap_drag_pos'):
                return view.snap_drag_pos(self, value)
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

    _PAD = 4
    _BADGE_HPAD = 5
    _BADGE_RADIUS = 3
    _GAP = 5
    _LINE_GAP = 2
    _BG_RADIUS = 4

    def __init__(self, text: str = "", parent=None):
        self._raw_text = text
        super().__init__(self._display_text(text), parent)

    @staticmethod
    def _display_text(text: str) -> str:
        lines = []
        for line in text.split("\n"):
            parsed = parse_edge_label(line)
            lines.append(parsed.body if parsed.kind else line)
        return "\n".join(lines)

    def setText(self, text: str):
        self._raw_text = text
        super().setText(self._display_text(text))

    def _line_runs(self):
        lines = self._raw_text.split("\n")
        return [(line, parse_edge_label(line)) for line in lines]

    def _metrics(self):
        font = self.font()
        fm = QFontMetricsF(font)
        bold = QFont(font)
        bold.setBold(True)
        bfm = QFontMetricsF(bold)
        line_h = fm.height()
        widths = []
        for raw, parsed in self._line_runs():
            if parsed.kind:
                badge_w = bfm.horizontalAdvance(parsed.kind) + self._BADGE_HPAD * 2
                body_w = fm.horizontalAdvance(parsed.body)
                widths.append(badge_w + (self._GAP + body_w if parsed.body else 0))
            else:
                widths.append(fm.horizontalAdvance(raw))
        total_w = max(widths, default=0)
        total_h = len(widths) * line_h + max(0, len(widths) - 1) * self._LINE_GAP
        return fm, bfm, line_h, total_w, total_h

    def boundingRect(self):
        _, _, _, total_w, total_h = self._metrics()
        return QRectF(0, 0, total_w, total_h)

    def paint(self, painter: QPainter, option, widget=None):
        pad = self._PAD
        fm, bfm, line_h, total_w, total_h = self._metrics()
        bg_rect = QRectF(0, 0, total_w, total_h).adjusted(-pad, -pad, pad, pad)
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.6)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bg_rect, self._BG_RADIUS, self._BG_RADIUS)

        font = self.font()
        bold = QFont(font)
        bold.setBold(True)
        body_color = self.brush().color()
        y = fm.ascent()

        for raw, parsed in self._line_runs():
            x = 0.0
            if parsed.kind:
                badge_w = bfm.horizontalAdvance(parsed.kind) + self._BADGE_HPAD * 2
                badge_rect = QRectF(x, y - fm.ascent(), badge_w, line_h)
                painter.setPen(Qt.PenStyle.NoPen)
                chip_color = EDGE_KIND_COLORS.get(parsed.kind, QColor("#6A9FB5"))
                painter.setBrush(QBrush(chip_color))
                painter.drawRoundedRect(
                    badge_rect, self._BADGE_RADIUS, self._BADGE_RADIUS
                )
                painter.setFont(bold)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QPointF(x + self._BADGE_HPAD, y), parsed.kind)
                x += badge_w + self._GAP
                text = parsed.body
            else:
                text = raw

            if text:
                painter.setFont(font)
                painter.setPen(body_color)
                painter.drawText(QPointF(x, y), text)
            y += line_h + self._LINE_GAP


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
