"""A filled box draws its label straight on the fill where the board ink
passes WCAG AA there, and keeps the light plate only below that (#300)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse

FILLS = ("clay", "teal", "soft", "highlight")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _board(*lines: str) -> str:
    return "#!grafli v4\n" + "".join(line + "\n" for line in lines)


def _fills_board() -> str:
    return _board(*(f'@ box {name} "{name.title()}" {i * 220},0 200x80 %{name}'
                    for i, name in enumerate(FILLS)))


def _plate_pixel(view, item) -> QColor:
    """A pixel inside the label plate's top-left corner, clear of glyphs."""
    r = item._label.sceneBoundingRect()
    rect = QRectF(r.left() + 1, r.top() + 1, 3, 3)
    view.scene().clearSelection()
    img = QImage(3, 3, QImage.Format.Format_ARGB32)
    img.fill(QColor(theme.SCENE_BG))
    painter = QPainter(img)
    view.scene().render(painter, QRectF(img.rect()), rect)
    painter.end()
    return img.pixelColor(1, 1)


def test_the_contrast_ratio_runs_from_one_to_twenty_one():
    black, white = QColor("#000000"), QColor("#FFFFFF")
    assert theme.contrast_ratio(black, white) == pytest.approx(21.0)
    assert theme.contrast_ratio(white, black) == pytest.approx(21.0)
    assert theme.contrast_ratio(white, white) == pytest.approx(1.0)


@pytest.mark.parametrize("name", ("light", "dark"))
def test_a_filled_box_keeps_the_plate_only_below_aa(name):
    theme.set_theme(name)
    view = _view(_board(*(f'@ box {tok} "{tok}" {i * 220},0 200x80 %{tok}'
                          for i, tok in enumerate(theme.color_tokens()))))
    for tok, item in view._box_items.items():
        ink = QColor(theme.INK)
        fill = QColor(theme.resolve_color(f"%{tok}"))
        assert item._label_on_plate() == (
            theme.contrast_ratio(ink, fill) < 4.5), tok


def test_the_four_fills_draw_no_plate_in_the_dark_theme():
    theme.set_theme("dark")
    view = _view(_fills_board())
    for name in FILLS:
        item = view._box_items[name]
        assert not item._label_on_plate(), name
        assert _plate_pixel(view, item).rgb() == item.brush().color().rgb(), name


def test_soft_and_highlight_draw_no_plate_in_the_light_theme():
    view = _view(_fills_board())
    for name in ("soft", "highlight"):
        item = view._box_items[name]
        assert not item._label_on_plate(), name
        assert _plate_pixel(view, item).rgb() == item.brush().color().rgb(), name


def test_clay_and_teal_keep_the_plate_in_the_light_theme():
    # The board ink reads at 3.39:1 on %clay and 3.78:1 on %teal, below AA.
    view = _view(_fills_board())
    for name in ("clay", "teal"):
        item = view._box_items[name]
        fill = item.brush().color()
        assert item._label_on_plate(), name
        assert theme.contrast_ratio(QColor(theme.INK), fill) < 4.5
        assert (theme.contrast_ratio(QColor(theme.INK), _plate_pixel(view, item))
                >= 4.5), name


def test_a_large_label_takes_the_lower_aa_ratio():
    view = _view(_board('@ box big "Big" 0,0 300x100 %clay ~xlarge',
                        '@ box small "Small" 0,200 300x100 %clay'))
    assert not view._box_items["big"]._label_on_plate()
    assert view._box_items["small"]._label_on_plate()


def test_a_dark_fill_keeps_the_plate():
    view = _view(_board('@ box b "Dark" 0,0 200x80 %primary'))
    item = view._box_items["b"]
    assert item._label_on_plate()
    assert (_plate_pixel(view, item).lightnessF()
            > item.brush().color().lightnessF() + 0.1)


def test_a_flat_box_reads_its_fill_over_the_canvas():
    # %soft at 70 % over the paper is lighter than %soft, and the ink reads.
    view = _view(_board('@ box f "Flat" 0,0 200x80 %soft !flat'))
    item = view._box_items["f"]
    ground = item._label_ground()
    assert ground.alphaF() == 1.0
    assert ground.lightnessF() > QColor(theme.resolve_color("%soft")).lightnessF()
    assert not item._label_on_plate()


def test_an_ink_box_and_a_plain_box_take_no_plate():
    view = _view(_board('@ box i "Ink" 0,0 200x80 %clay !ink',
                        '@ box p "Plain" 0,120 200x80'))
    assert not view._box_items["i"]._label_on_plate()
    assert not view._box_items["p"]._label_on_plate()


def _assert_plate_reads(view, item):
    assert item._label_on_plate()
    ink = QColor(theme.INK)
    assert theme.contrast_ratio(ink, _plate_pixel(view, item)) >= 4.5


def test_a_teal_container_inside_a_primary_one_keeps_the_plate():
    # Its 70 % teal over the canvas would read at 5.13:1; over the navy
    # it sits in, it reads at 3.38:1.
    view = _view(_board('@ box outer "Outer" 0,0 700x500 %primary',
                        '@ box mid "Teal" 40,60 500x360 %teal >outer',
                        '@ box kid "Kid" 80,160 200x80 >mid'))
    _assert_plate_reads(view, view._box_items["mid"])


def test_a_flat_teal_box_inside_a_primary_container_keeps_the_plate():
    view = _view(_board('@ box outer "Outer" 0,0 500x300 %primary',
                        '@ box f "Flat teal" 40,100 240x100 %teal !flat >outer'))
    _assert_plate_reads(view, view._box_items["f"])
