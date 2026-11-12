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


def test_the_four_fills_draw_no_plate_in_the_light_theme():
    view = _view(_fills_board())
    for name in FILLS:
        item = view._box_items[name]
        assert not item._label_on_plate(), name
        assert _plate_pixel(view, item).rgb() == item.brush().color().rgb(), name


def test_a_large_label_takes_the_lower_aa_ratio():
    # The board ink reads at 4.2:1 on the light %accent: AA for large text.
    view = _view(_board('@ box big "Big" 0,0 300x100 %accent ~xlarge',
                        '@ box small "Small" 0,200 300x100 %accent'))
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


# A label over an image keeps its plate: the ink cannot be checked against a
# picture, so the plate is near opaque and the ink reads on any (#325).
def _image_view(tmp_path, colour: str, *lines: str):
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    img.save(str(tmp_path / "picture.png"))
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    path = tmp_path / "board.grafli"
    view.load_board(parse(_board('@ image pic "picture.png" 0,0 400x300',
                                 *lines)), path)
    return view


@pytest.mark.parametrize("name, picture", (("light", "#000000"),
                                           ("dark", "#FFFFFF")))
def test_a_coloured_label_over_an_image_keeps_a_plate_its_ink_reads_on(
        tmp_path, name, picture):
    theme.set_theme(name)
    view = _image_view(tmp_path, picture,
                       '@ box cpu "CPU" 40,40 200x80 %soft')
    item = view._box_items["cpu"]
    assert not item._fill_needs_plate()   # %soft alone draws no plate
    assert item._label_on_plate()
    ink = QColor(theme.INK)
    assert theme.contrast_ratio(ink, _plate_pixel(view, item)) >= 4.5


def test_a_plain_label_over_an_image_takes_the_plate(tmp_path):
    view = _image_view(tmp_path, "#000000", '@ box ram "RAM" 40,40 200x80')
    item = view._box_items["ram"]
    assert item._label_on_plate()
    assert (theme.contrast_ratio(QColor(theme.INK), _plate_pixel(view, item))
            >= 4.5)


def test_a_label_beside_the_image_keeps_the_fill_rule(tmp_path):
    view = _image_view(tmp_path, "#000000",
                       '@ box soft "Soft" 500,40 200x80 %soft',
                       '@ box plain "Plain" 500,200 200x80')
    assert not view._box_items["soft"]._label_on_plate()
    assert not view._box_items["plain"]._label_on_plate()


def test_an_opaque_box_drawn_above_the_image_keeps_the_fill_rule(tmp_path):
    # Two levels deep, a leaf box draws above an unparented image, so its
    # own fill hides the picture under its label.
    view = _image_view(tmp_path, "#000000",
                       '@ box outer "Outer" -100,-100 700x600',
                       '@ box mid "Mid" -80,-40 640x500 >outer',
                       '@ box leaf "Leaf" 40,100 200x80 %soft >mid')
    leaf = view._box_items["leaf"]
    assert leaf.zValue() > view._image_items["pic"].zValue()
    assert not leaf._label_on_plate()


def test_an_ink_label_over_an_image_takes_no_plate(tmp_path):
    view = _image_view(tmp_path, "#000000",
                       '@ box ink "Ink" 40,40 200x80 %soft !ink')
    assert not view._box_items["ink"]._label_on_plate()
