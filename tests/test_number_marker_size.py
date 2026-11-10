"""Number markers read at board zoom (#305): on a 200x70 box at 100% zoom,
the digits of `*badge:<n>`, `*<n>` and `*lead:<n>` stand at least as tall
as the label's capitals. A fill number that cannot reach that size above
its caption sits left of the label instead."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import iconset
from grafli.format import parse

SCALE = 4


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _box(icon: str, size: str = "200x70", label: str = "groundwork"):
    view = _view(f'@ box s "{label}" 0,0 {size} %teal *{icon}\n')
    return view, view._box_items["s"]


def _icon_image(item) -> QImage:
    """The box's glyph alone, painted at SCALE x in item coordinates."""
    img = QImage(int(item.box.w * SCALE), int(item.box.h * SCALE),
                 QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.scale(SCALE, SCALE)
    item._paint_icon(p)
    p.end()
    return img


def _dark(img: QImage, x: int, y: int) -> bool:
    c = img.pixelColor(x, y)
    return c.alpha() > 128 and c.lightness() < 100


def _digit_height(img: QImage, area: QRectF) -> float:
    """Height in item pixels of the dark ink inside the ring drawn in
    *area*: the digits. The ring is found from the image (its topmost and
    bottommost dark rows on the centre column), and only ink well inside
    its inner edge counts."""
    cx = int(area.center().x() * SCALE)
    ys = range(int(area.top() * SCALE), int(area.bottom() * SCALE))
    column = [y for y in ys if _dark(img, cx, y)]
    assert column, "no ring drawn"
    top, bottom = column[0], column[-1]
    diameter = bottom - top + 1
    stroke = max(1.2 * SCALE, diameter * 0.055)
    inner = diameter / 2 - stroke - SCALE
    cy = (top + bottom) / 2
    rows = [y for y in range(int(cy - inner), int(cy + inner) + 1)
            if any(_dark(img, x, y)
                   and (x - cx) ** 2 + (y - cy) ** 2 < inner ** 2
                   for x in range(int(cx - inner), int(cx + inner) + 1))]
    return (rows[-1] - rows[0] + 1) / SCALE if rows else 0.0


def _cap(item) -> float:
    return QFontMetricsF(item._label.font()).capHeight()


def test_a_badge_number_draws_its_digit_as_tall_as_the_label_caps():
    _view_, item = _box("badge:1")
    rect = item._badge_rect()
    assert _digit_height(_icon_image(item), rect) >= _cap(item)
    assert item.box.h == 70


def test_a_two_digit_badge_number_reads_too():
    _view_, item = _box("badge:12", label="step")
    rect = item._badge_rect()
    assert _digit_height(_icon_image(item), rect) >= _cap(item)


def test_a_badge_number_keeps_clear_of_the_label():
    _view_, item = _box("badge:1")
    label = item._label
    plate = label.mapRectToScene(label._plate_rect())
    assert not plate.intersects(item.mapRectToScene(item._badge_rect()))


def test_a_filled_badge_number_sizes_its_digits_to_the_label_caps():
    _view_, item = _box("badge:solid-3")
    side = item._badge_rect().width() * (1 - 2 * iconset._NUMBER_BADGE_INSET)
    font = iconset._digit_font(side * iconset._DIGIT_SCALE[1])
    assert QFontMetricsF(font).capHeight() >= _cap(item)


def test_a_fill_number_on_a_short_box_sits_left_of_the_label():
    _view_, item = _box("1", label="build")
    assert item.box.icon_placement == ""
    assert item._has_lead_icon()
    rect = item._lead_layout()[0]
    label_left = item._label.pos().x() - item.pos().x()
    assert rect.right() <= label_left
    assert _digit_height(_icon_image(item), rect) >= _cap(item)


def test_a_fill_number_on_a_tall_box_keeps_its_caption_layout():
    _view_, item = _box("5", size="140x140", label="big")
    assert not item._has_lead_icon()
    img = _icon_image(item)
    side = min(item.box.w - 20, item.box.h - 20
               - item._label.boundingRect().height() - 6)
    rect = QRectF((item.box.w - side) / 2, 10, side, side)
    assert _digit_height(img, rect) >= _cap(item)


def test_a_lead_number_draws_its_digit_as_tall_as_the_label_caps():
    _view_, item = _box("lead:4", label="harvest")
    rect = item._lead_layout()[0]
    assert _digit_height(_icon_image(item), rect) >= _cap(item)


def test_a_symbol_badge_keeps_its_compact_size():
    _view_, item = _box("badge:star")
    assert item._badge_icon_side() == item._compact_badge_side()


def test_a_note_badge_number_reads_beside_its_text():
    view = _view('@ note n 0,0 "review order" *badge:2\n')
    note = view._note_items["n"]
    cap = QFontMetricsF(note._note_font()).capHeight()
    side = note._badge_icon_side() * (1 - 2 * iconset._NUMBER_BADGE_INSET)
    font = iconset._digit_font(side * iconset._DIGIT_SCALE[1])
    assert QFontMetricsF(font).capHeight() >= cap
    assert note._badge_icon_side() > note._BADGE_ICON_SIDE


def test_number_side_is_zero_for_symbols():
    _app()
    assert iconset.number_badge_side("star", 12.0) == 0.0
    assert iconset.number_badge_side("7", 12.0) > 0.0
