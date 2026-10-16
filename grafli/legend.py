"""The map palette's legend: a swatch and a label per palette entry.

The legend lists the entries of the map's palette (``grafli.map_palette``)
that the board colours something with, in the palette file's order. One
layout serves every surface: a card on the canvas (``Shift+M``), a band
below the board in ``render --legend`` and the SVG/PNG exports, and a band at
the bottom of a PDF or PPTX diagram slide. A board that uses no palette entry has no
legend, so nothing changes on it.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen

from grafli import theme
from grafli.constants import FONT_FAMILY
from grafli.format import Board


def used_entries(board: Board | None, entries: list) -> list:
    """The palette *entries* whose ``%name`` colours a box, a status label, a
    note or a connector of *board*, in the palette's order."""
    if board is None or not entries:
        return []
    colors = {*(x.color for x in board.boxes),
              *(x.status_color for x in board.boxes),
              *(x.color for x in board.notes),
              *(x.color for x in board.arrows)}
    return [e for e in entries if f"%{e.name}" in colors]


def _font(px: float) -> QFont:
    font = QFont(FONT_FAMILY, -1)
    font.setPixelSize(max(1, round(px)))
    return font


def _chips(entries: list, px: float, width: float
           ) -> tuple[list[tuple[float, float, object]], float]:
    """Lay the entries out in rows no wider than *width*: each chip's top-left
    offset, and the height of all rows."""
    if not entries:
        return [], 0.0
    fm = QFontMetricsF(_font(px))
    swatch, gap, spacing = px, px * 0.45, px * 1.4
    line_h = fm.height() * 1.35
    placed: list[tuple[float, float, object]] = []
    x = y = 0.0
    for entry in entries:
        chip_w = swatch + gap + fm.horizontalAdvance(entry.label)
        if x > 0 and x + chip_w > width:
            x, y = 0.0, y + line_h
        placed.append((x, y, entry))
        x += chip_w + spacing
    return placed, (y + line_h if placed else 0.0)


def legend_chips(entries: list, px: float, width: float
                 ) -> tuple[list[tuple[float, float, object]], float]:
    """Each entry's chip offset (its swatch's left, its row's top) in rows no
    wider than *width* at text size *px*, and the height of all rows; for a
    surface that draws the chips itself (the PPTX export)."""
    return _chips(entries, px, width)


def legend_height(entries: list, px: float, width: float) -> float:
    """The height the legend of *entries* takes at text size *px* within
    *width*; 0 without entries."""
    return _chips(entries, px, width)[1]


def legend_width(entries: list, px: float) -> float:
    """The width of the legend of *entries* laid out on one row."""
    placed, _ = _chips(entries, px, float("inf"))
    if not placed:
        return 0.0
    x, _, last = placed[-1]
    fm = QFontMetricsF(_font(px))
    return x + px * 1.45 + fm.horizontalAdvance(last.label)


def draw_legend(painter: QPainter, rect: QRectF, entries: list, px: float,
                ink: QColor | None = None) -> None:
    """Draw the legend of *entries* into *rect* from its top-left corner, text
    at size *px* in *ink* (board ink by default)."""
    if not entries:
        return
    ink = QColor(ink if ink is not None else theme.INK)
    font = _font(px)
    fm = QFontMetricsF(font)
    placed, _ = _chips(entries, px, rect.width())
    line_h = fm.height() * 1.35
    border = QColor(ink)
    border.setAlphaF(0.35)
    painter.save()
    painter.setFont(font)
    for x, y, entry in placed:
        left, top = rect.left() + x, rect.top() + y
        swatch = QRectF(left, top + (line_h - px) / 2, px, px)
        painter.setPen(QPen(border, max(1.0, px / 14)))
        painter.setBrush(QBrush(QColor(theme.resolve_color(f"%{entry.name}")
                                       or theme.INK_FAINT)))
        painter.drawRoundedRect(swatch, px * 0.2, px * 0.2)
        painter.setPen(QPen(ink))
        baseline = top + (line_h - fm.height()) / 2 + fm.ascent()
        painter.drawText(QPointF(left + px * 1.45, baseline), entry.label)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.restore()
