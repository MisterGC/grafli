"""Sketchnote symbol set for grafli (visual vocabulary, issue #120).

Symbols are authored as one SVG sheet — ``assets/sketchnote_symbols.svg``,
hand-tweakable in Inkscape — and rendered by element id via QSvgRenderer, so
the set stays vector-crisp at any zoom and editable without code changes.
Boxes and notes reference symbols by name via the ``*name`` sigil (see
grafli.format). Tinting substitutes the sheet's canonical ink colour in the
SVG source; one renderer is cached per tint.

Number badges (``*1`` … ``*99``) are composed at paint time (circle + digit)
— a static sheet can't carry every number. ``money`` and ``link`` predate the
sheet and remain hand-drawn painters until it gains them.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from grafli.constants import NOTE_FONT_FAMILY
from grafli.format import ICON_ALIASES

_SHEET = Path(__file__).parent / "assets" / "sketchnote_symbols.svg"
# Canonical ink colour of the sheet; tinting substitutes this in the source.
_SHEET_INK = "#2d3033"

# Display order for the picker grid; also the set of valid (non-digit) names.
SEMANTIC_NAMES = [
    "person", "robot", "gear", "database", "document", "cloud", "globe",
    "target", "lightbulb", "question", "warning", "check", "cross", "flag",
    "clock", "calendar", "magnifier", "puzzle", "lock", "plant",
]
EMPHASIS_NAMES = [
    "star", "heart", "flame", "exclamation", "brain", "lightning",
    "repeat", "exercise", "performance",
]
LEGACY_NAMES = ["money", "link"]
# Legacy names group with the semantic block (they are semantic symbols).
ICON_NAMES = SEMANTIC_NAMES + LEGACY_NAMES + EMPHASIS_NAMES

_SHEET_NAMES = frozenset(SEMANTIC_NAMES + EMPHASIS_NAMES)

_sheet_bytes: bytes | None = None
_renderers: dict[int, QSvgRenderer] = {}
_pixmap_cache: dict[tuple, QPixmap] = {}


def resolve_icon(name: str) -> str:
    """Canonical name for ``name`` — alias-aware (``bulb`` → ``lightbulb``);
    digit badges 1–99 pass through zero-stripped. "" if unknown."""
    name = ICON_ALIASES.get(name, name)
    if name in _SHEET_NAMES or name in _LEGACY_PAINTERS:
        return name
    if name.isdigit() and 1 <= int(name) <= 99:
        return str(int(name))
    return ""


def has_icon(name: str) -> bool:
    return bool(resolve_icon(name))


def _element_id(name: str) -> str:
    return name.capitalize()


def _renderer_for(color: QColor) -> QSvgRenderer:
    """A renderer of the sheet tinted to ``color`` (cached per tint)."""
    global _sheet_bytes
    key = color.rgba()
    renderer = _renderers.get(key)
    if renderer is None:
        if _sheet_bytes is None:
            _sheet_bytes = _SHEET.read_bytes()
        data = _sheet_bytes
        tint = color.name().encode()
        if tint != _SHEET_INK.encode():
            data = data.replace(_SHEET_INK.encode(), tint)
        renderer = QSvgRenderer(QByteArray(data))
        _renderers[key] = renderer
    return renderer


def icon_aspect(name: str) -> float:
    """Width/height ratio of the symbol's drawing (1.0 for digits/legacy) —
    for layout that reserves non-square room (e.g. the lead gutter)."""
    name = resolve_icon(name)
    if name in _SHEET_NAMES:
        b = _renderer_for(QColor(_SHEET_INK)).boundsOnElement(_element_id(name))
        if b.height() > 0:
            return b.width() / b.height()
    return 1.0


def paint_icon(painter: QPainter, name: str, rect: QRectF,
               color: QColor) -> None:
    """Draw ``name`` aspect-fitted and centred into ``rect`` in the painter's
    current coordinate system. Resolution-independent — stays crisp at any
    zoom (use this on the canvas; a cached pixmap would pixelate)."""
    name = resolve_icon(name)
    if not name or rect.width() <= 0 or rect.height() <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if name.isdigit():
        _paint_number(painter, name, rect, color)
    elif name in _LEGACY_PAINTERS:
        _paint_legacy(painter, name, rect, color)
    else:
        renderer = _renderer_for(color)
        eid = _element_id(name)
        bounds = renderer.boundsOnElement(eid)
        if bounds.width() > 0 and bounds.height() > 0:
            s = min(rect.width() / bounds.width(),
                    rect.height() / bounds.height())
            w, h = bounds.width() * s, bounds.height() * s
            target = QRectF(rect.left() + (rect.width() - w) / 2,
                            rect.top() + (rect.height() - h) / 2, w, h)
            renderer.render(painter, eid, target)
    painter.restore()


def icon_pixmap(name: str, color: QColor, size: float,
                dpr: float = 1.0) -> QPixmap | None:
    """Return a cached, tinted pixmap for ``name`` at ``size`` logical px.

    For fixed-size UI (the picker grid); on the canvas use ``paint_icon`` so
    the symbol stays vector-crisp under zoom.
    """
    if not has_icon(name):
        return None
    name = resolve_icon(name)
    size = max(4.0, float(size))
    key = (name, color.rgba(), round(size, 1), round(dpr, 2))
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached

    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    # The pixmap carries the dpr, so the painter works in logical units.
    paint_icon(p, name, QRectF(0, 0, size, size), color)
    p.end()

    _pixmap_cache[key] = pm
    return pm


def paint_badge(painter: QPainter, name: str, rect: QRectF,
                color: QColor) -> None:
    """Corner-badge rendering (``*badge:`` placement, issue #122): the symbol
    sits on a soft paper disc so it stays legible on any node fill."""
    if not has_icon(name) or rect.width() <= 0 or rect.height() <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    plate = QColor("#F7F5F0")
    plate.setAlphaF(0.95)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(plate)
    painter.drawEllipse(rect)
    painter.restore()
    inset = min(rect.width(), rect.height()) * 0.16
    paint_icon(painter, name, rect.adjusted(inset, inset, -inset, -inset),
               color)


# ── number badges (composed: circle + digit) ──

def _paint_number(p: QPainter, digits: str, rect: QRectF, color: QColor):
    side = min(rect.width(), rect.height())
    stroke = max(1.2, side * 0.055)
    square = QRectF(rect.left() + (rect.width() - side) / 2,
                    rect.top() + (rect.height() - side) / 2, side, side)
    inset = stroke / 2 + side * 0.02
    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(square.adjusted(inset, inset, -inset, -inset))
    font = QFont(NOTE_FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, round(side * (0.52 if len(digits) == 1 else 0.42))))
    p.setFont(font)
    p.drawText(square, Qt.AlignmentFlag.AlignCenter, digits)


# ── legacy painters (24-unit viewBox) — until the sheet gains these ──

_VIEWBOX = 24.0
_STROKE = 1.8


def _dot(p: QPainter, cx: float, cy: float, r: float):
    """A small filled disc in the current pen colour."""
    color = p.pen().color()
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    p.restore()


def _money(p: QPainter):
    # banknote: rounded rect + a centre coin
    p.drawRoundedRect(QRectF(2.5, 7.0, 19.0, 10.0), 2.0, 2.0)
    p.drawEllipse(QRectF(10.0, 9.5, 4.0, 4.0))
    _dot(p, 5.6, 12.0, 0.7)
    _dot(p, 18.4, 12.0, 0.7)


def _link(p: QPainter):
    p.drawRoundedRect(QRectF(3.5, 9.0, 10.0, 6.0), 3.0, 3.0)
    p.drawRoundedRect(QRectF(10.5, 9.0, 10.0, 6.0), 3.0, 3.0)


_LEGACY_PAINTERS = {"money": _money, "link": _link}


def _paint_legacy(p: QPainter, name: str, rect: QRectF, color: QColor):
    side = min(rect.width(), rect.height())
    p.translate(rect.left() + (rect.width() - side) / 2,
                rect.top() + (rect.height() - side) / 2)
    p.scale(side / _VIEWBOX, side / _VIEWBOX)
    pen = QPen(color, _STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _LEGACY_PAINTERS[name](p)
