"""Curated visual-vocabulary glyphs for grafli (issue: visual note-taking).

A small, fixed set of monochrome line icons drawn as vector paths in a 24-unit
viewBox, rendered tinted to any colour and cached. Boxes and notes reference
them by name via the ``*name`` sigil (see grafli.format).

These starter icons are hand-drawn in a consistent minimal line style. The
render path is asset-agnostic, so a fuller SVG set (Lucide/Phosphor, etc.) can
replace ``_ICONS`` later without touching callers.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

# Display order for the picker grid; also the set of valid icon names.
ICON_NAMES = [
    "person", "gear", "cloud", "database", "warning", "bulb",
    "check", "cross", "money", "clock", "doc", "lock",
    "flag", "star", "link", "question",
]

_VIEWBOX = 24.0
_STROKE = 1.8

_pixmap_cache: dict[tuple, QPixmap] = {}


# ── individual icon painters (24x24 viewBox, stroke already set) ──

def _person(p: QPainter):
    p.drawEllipse(QRectF(8.8, 4.3, 6.4, 6.4))
    path = QPainterPath()
    path.moveTo(5.5, 19.8)
    path.cubicTo(5.5, 14.6, 18.5, 14.6, 18.5, 19.8)
    p.drawPath(path)


def _gear(p: QPainter):
    c, r_in, r_out = 12.0, 5.6, 8.0
    for k in range(8):
        a = math.radians(k * 45)
        dx, dy = math.cos(a), math.sin(a)
        p.drawLine(QPointF(c + dx * r_in, c + dy * r_in),
                   QPointF(c + dx * r_out, c + dy * r_out))
    p.drawEllipse(QRectF(6.4, 6.4, 11.2, 11.2))
    p.drawEllipse(QRectF(9.6, 9.6, 4.8, 4.8))


def _cloud(p: QPainter):
    path = QPainterPath()
    path.addEllipse(QRectF(3.5, 12.0, 8.0, 8.0))
    path.addEllipse(QRectF(8.5, 8.5, 10.0, 10.0))
    path.addEllipse(QRectF(12.0, 12.0, 7.0, 7.0))
    path.addRect(QRectF(7.0, 16.0, 9.5, 3.5))
    p.drawPath(path.simplified())


def _database(p: QPainter):
    p.drawEllipse(QRectF(5.0, 3.0, 14.0, 5.0))
    p.drawLine(QPointF(5.0, 5.5), QPointF(5.0, 18.5))
    p.drawLine(QPointF(19.0, 5.5), QPointF(19.0, 18.5))
    # mid ring + bottom, as the front halves of two ellipses
    p.drawArc(QRectF(5.0, 9.0, 14.0, 5.0), 180 * 16, 180 * 16)
    p.drawArc(QRectF(5.0, 16.0, 14.0, 5.0), 180 * 16, 180 * 16)


def _warning(p: QPainter):
    path = QPainterPath()
    path.moveTo(12.0, 3.2)
    path.lineTo(21.8, 20.2)
    path.lineTo(2.2, 20.2)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(12.0, 9.5), QPointF(12.0, 14.8))
    _dot(p, 12.0, 17.6, 0.95)


def _bulb(p: QPainter):
    p.drawEllipse(QRectF(6.5, 3.0, 11.0, 11.0))
    p.drawLine(QPointF(9.2, 15.5), QPointF(14.8, 15.5))
    p.drawLine(QPointF(9.8, 18.0), QPointF(14.2, 18.0))
    p.drawLine(QPointF(10.6, 20.4), QPointF(13.4, 20.4))


def _check(p: QPainter):
    path = QPainterPath()
    path.moveTo(4.5, 12.8)
    path.lineTo(9.8, 18.0)
    path.lineTo(19.5, 6.5)
    p.drawPath(path)


def _cross(p: QPainter):
    p.drawLine(QPointF(6.0, 6.0), QPointF(18.0, 18.0))
    p.drawLine(QPointF(18.0, 6.0), QPointF(6.0, 18.0))


def _money(p: QPainter):
    # banknote: rounded rect + a centre coin
    p.drawRoundedRect(QRectF(2.5, 7.0, 19.0, 10.0), 2.0, 2.0)
    p.drawEllipse(QRectF(10.0, 9.5, 4.0, 4.0))
    _dot(p, 5.6, 12.0, 0.7)
    _dot(p, 18.4, 12.0, 0.7)


def _clock(p: QPainter):
    p.drawEllipse(QRectF(3.0, 3.0, 18.0, 18.0))
    p.drawLine(QPointF(12.0, 12.0), QPointF(12.0, 6.8))
    p.drawLine(QPointF(12.0, 12.0), QPointF(16.0, 13.6))


def _doc(p: QPainter):
    path = QPainterPath()
    path.moveTo(6.0, 3.0)
    path.lineTo(14.0, 3.0)
    path.lineTo(18.0, 7.0)
    path.lineTo(18.0, 21.0)
    path.lineTo(6.0, 21.0)
    path.closeSubpath()
    p.drawPath(path)
    fold = QPainterPath()
    fold.moveTo(14.0, 3.0)
    fold.lineTo(14.0, 7.0)
    fold.lineTo(18.0, 7.0)
    p.drawPath(fold)
    p.drawLine(QPointF(8.5, 12.0), QPointF(15.5, 12.0))
    p.drawLine(QPointF(8.5, 15.0), QPointF(15.5, 15.0))
    p.drawLine(QPointF(8.5, 18.0), QPointF(13.0, 18.0))


def _lock(p: QPainter):
    p.drawRoundedRect(QRectF(5.0, 11.0, 14.0, 9.0), 1.6, 1.6)
    shackle = QPainterPath()
    shackle.moveTo(8.0, 11.0)
    shackle.lineTo(8.0, 8.5)
    shackle.arcTo(QRectF(8.0, 4.5, 8.0, 8.0), 180, -180)
    shackle.lineTo(16.0, 11.0)
    p.drawPath(shackle)
    _dot(p, 12.0, 14.4, 0.9)
    p.drawLine(QPointF(12.0, 15.3), QPointF(12.0, 17.2))


def _flag(p: QPainter):
    p.drawLine(QPointF(6.0, 3.0), QPointF(6.0, 21.0))
    flag = QPainterPath()
    flag.moveTo(6.0, 4.0)
    flag.lineTo(19.0, 4.0)
    flag.quadTo(16.0, 7.5, 19.0, 11.0)
    flag.lineTo(6.0, 11.0)
    p.drawPath(flag)


def _star(p: QPainter):
    path = QPainterPath()
    cx = cy = 12.0
    r_out, r_in = 9.2, 3.7
    for k in range(10):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(-90 + k * 36)
        pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
        if k == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)


def _link(p: QPainter):
    p.drawRoundedRect(QRectF(3.5, 9.0, 10.0, 6.0), 3.0, 3.0)
    p.drawRoundedRect(QRectF(10.5, 9.0, 10.0, 6.0), 3.0, 3.0)


def _question(p: QPainter):
    path = QPainterPath()
    path.moveTo(8.4, 9.0)
    path.cubicTo(8.4, 5.2, 15.6, 5.2, 14.6, 9.4)
    path.cubicTo(13.9, 11.6, 12.0, 11.8, 12.0, 14.4)
    p.drawPath(path)
    _dot(p, 12.0, 17.2, 0.95)


def _dot(p: QPainter, cx: float, cy: float, r: float):
    """A small filled disc in the current pen colour."""
    color = p.pen().color()
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    p.restore()


_ICONS = {
    "person": _person, "gear": _gear, "cloud": _cloud, "database": _database,
    "warning": _warning, "bulb": _bulb, "check": _check, "cross": _cross,
    "money": _money, "clock": _clock, "doc": _doc, "lock": _lock,
    "flag": _flag, "star": _star, "link": _link, "question": _question,
}


def has_icon(name: str) -> bool:
    return name in _ICONS


def paint_icon(painter: QPainter, name: str, rect: QRectF,
               color: QColor) -> None:
    """Draw ``name`` as vector paths into ``rect`` in the painter's current
    coordinate system. Resolution-independent — stays crisp at any zoom (use
    this on the canvas; a cached pixmap would pixelate when scaled up)."""
    fn = _ICONS.get(name)
    if fn is None:
        return
    side = min(rect.width(), rect.height())
    if side <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.left() + (rect.width() - side) / 2,
                      rect.top() + (rect.height() - side) / 2)
    painter.scale(side / _VIEWBOX, side / _VIEWBOX)
    pen = QPen(color, _STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    fn(painter)
    painter.restore()


def icon_pixmap(name: str, color: QColor, size: float,
                dpr: float = 1.0) -> QPixmap | None:
    """Return a cached, tinted pixmap for ``name`` at ``size`` logical px.

    For fixed-size UI (the picker grid); on the canvas use ``paint_icon`` so
    the glyph stays vector-crisp under zoom.
    """
    if name not in _ICONS:
        return None
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
