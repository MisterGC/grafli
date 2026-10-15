"""The legend card of an overlay file, laid out and painted.

The canvas draws it bottom right while an overlay is shown (``A``); the
``render`` and the PDF/PPTX exports draw the same card next to the board.
The card names the overlay, its producer, whether it is stale, its
categories or scale, the no-data hatch and, on the canvas, the selected
element's reading, note and refs. Sizes are in card units: the canvas paints
them as pixels, an export scales the painter.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen

from grafli import theme
from grafli.constants import FONT_FAMILY

CARD_W = 260
PAD = 10
SWATCH = 10
NOTE_LINES = 3


def legend_rows(reading, elem_id: str = "") -> list[tuple[str, str]]:
    """The legend as (role, text) rows, top to bottom; with *elem_id*, that
    element's reading, note and refs below a rule."""
    legend = reading.legend
    rows = [("title", legend.title)]
    if legend.producer:
        rows.append(("dim", legend.producer))
    if legend.stale:
        rows.append(("stale", "⚠ " + legend.stale))
    if legend.categories:
        rows += [("swatch", label) for label, _ in legend.categories]
    else:
        rows.append(("scale", ""))
    rows.append(("no_data", "no data"))
    if elem_id:
        detail = reading.details.get(elem_id)
        rows.append(("rule", ""))
        if detail is None:
            rows.append(("text", f"{elem_id}: no data"))
        else:
            rows.append(("text", f"{elem_id}: {detail.reading}"))
            if detail.note:
                rows.append(("note", detail.note))
            rows += [("ref", ref) for ref in detail.refs]
    return rows


def canvas_fonts() -> tuple[QFont, QFont, QFont]:
    """The title, body and ref fonts the canvas card uses."""
    title = QFont(FONT_FAMILY, 12, QFont.Weight.Bold)
    body = QFont(FONT_FAMILY, 10)
    ref = QFont(FONT_FAMILY, 10)
    ref.setUnderline(True)
    return title, body, ref


def export_fonts() -> tuple[QFont, QFont, QFont]:
    """The card's fonts sized in card units, so a scaled painter scales them
    with the card on any device."""
    title, body, ref = canvas_fonts()
    title.setPixelSize(12)
    body.setPixelSize(10)
    ref.setPixelSize(10)
    return title, body, ref


def wrap(fm, text: str, width: float) -> list[str]:
    """Word-wrap ``text`` into at most a few lines, the last elided."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if fm.horizontalAdvance(trial) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > NOTE_LINES:
        rest = " ".join(lines[NOTE_LINES - 1:])
        lines = lines[:NOTE_LINES - 1] + [rest]
    return [fm.elidedText(line, Qt.TextElideMode.ElideRight, int(width))
            for line in lines] or [""]


def layout_card(painter: QPainter, rows: list[tuple[str, str]], width: float,
                fonts: tuple[QFont, QFont, QFont]) -> tuple[list, float]:
    """Lay *rows* out in a card *width* wide: the laid rows and the card's
    height, both in card units."""
    title_font, body_font, ref_font = fonts
    inner = width - 2 * PAD
    laid: list[tuple[str, str, list[str], QFont, float]] = []
    for role, text in rows:
        font = (title_font if role == "title"
                else ref_font if role == "ref" else body_font)
        painter.setFont(font)
        fm = painter.fontMetrics()
        if role in ("note", "stale"):
            lines = wrap(fm, text, inner)
        elif role in ("swatch", "no_data"):
            lines = [fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                   inner - SWATCH - 6)]
        else:
            lines = [fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                   inner)]
        h = (SWATCH + 10 if role == "scale"
             else 9 if role == "rule"
             else fm.height() * len(lines) + 2)
        if role == "scale":
            h += fm.height()
        laid.append((role, text, lines, font, h))
    return laid, sum(h for *_, h in laid) + 2 * PAD


def paint_card(painter: QPainter, card: QRectF, laid: list, legend,
               ref_rects: list | None = None) -> None:
    """Paint the laid rows into *card*; each ref's rect and text go into
    *ref_rects* when given."""
    inner = card.width() - 2 * PAD
    painter.setPen(QPen(theme.MINIMAP_BORDER_COLOR, 1))
    painter.setBrush(QBrush(theme.OVERLAY_BG))
    painter.drawRoundedRect(card, 6, 6)

    swatches = iter(legend.categories)
    x = card.left() + PAD
    y = card.top() + PAD
    for role, text, lines, font, h in laid:
        painter.setFont(font)
        fm = painter.fontMetrics()
        ink = theme.overlay_ink(0.6 if role in ("dim", "no_data") else 1.0)
        painter.setPen(QPen(ink))
        if role == "swatch":
            _label, color = next(swatches)
            draw_swatch(painter, x, y + (fm.height() - SWATCH) / 2,
                        QBrush(QColor(theme.resolve_color(color)
                                      or theme.HEATMAP_TEXT_COLOR)))
            painter.setPen(QPen(ink))
            painter.drawText(QPointF(x + SWATCH + 6, y + fm.ascent()),
                             lines[0])
        elif role == "no_data":
            draw_swatch(painter, x, y + (fm.height() - SWATCH) / 2,
                        QBrush(theme.overlay_ink(0.6),
                               Qt.BrushStyle.BDiagPattern))
            painter.setPen(QPen(ink))
            painter.drawText(QPointF(x + SWATCH + 6, y + fm.ascent()),
                             lines[0])
        elif role == "scale":
            bar = QRectF(x, y + 4, inner, SWATCH)
            grad = QLinearGradient(bar.left(), 0, bar.right(), 0)
            for pos, color in theme.HEATMAP_STOPS:
                grad.setColorAt(pos, color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(bar, 2, 2)
            painter.setPen(QPen(theme.overlay_ink(0.6)))
            label_y = bar.bottom() + 4 + fm.ascent()
            painter.drawText(QPointF(x, label_y), legend.low)
            painter.drawText(
                QPointF(x + inner - fm.horizontalAdvance(legend.high),
                        label_y), legend.high)
        elif role == "rule":
            painter.setPen(QPen(theme.overlay_ink(0.25), 1))
            painter.drawLine(QPointF(x, y + 4), QPointF(x + inner, y + 4))
        else:
            if role == "ref":
                painter.setPen(QPen(theme.FLOWS_ACCENT))
                if ref_rects is not None:
                    ref_rects.append(
                        (QRectF(x, y, fm.horizontalAdvance(lines[0]),
                                fm.height()), text))
            for i, line in enumerate(lines):
                painter.drawText(
                    QPointF(x, y + fm.height() * i + fm.ascent()), line)
        y += h


def draw_swatch(painter: QPainter, x: float, y: float, brush: QBrush):
    painter.setPen(QPen(theme.overlay_ink(0.4), 1))
    painter.setBrush(brush)
    painter.drawRoundedRect(QRectF(x, y, SWATCH, SWATCH), 2, 2)
