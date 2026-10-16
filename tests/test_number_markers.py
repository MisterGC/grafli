"""Filled number markers and `0` (#208): `*solid-<n>` draws a filled disc
with the digits knocked out, `*0` an outlined zero, on the canvas, in
`grafli render` and in the SVG and PDF exports. `*1`…`*99` keep their
outlined circle."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import iconset, theme
from grafli.format import parse

INK = QColor("#2D3033")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _paint(name: str, color: QColor = INK) -> QImage:
    _app()
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    iconset.paint_icon(p, name, QRectF(0, 0, 64, 64), color)
    p.end()
    return img


def _inked(img: QImage) -> int:
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if img.pixelColor(x, y).alpha() > 0)


def test_number_badge_names():
    assert iconset.number_badge("3") == ("3", False)
    assert iconset.number_badge("0") == ("0", False)
    assert iconset.number_badge("solid-12") == ("12", True)
    assert iconset.number_badge("solid-07") == ("7", True)
    assert iconset.number_badge("gear") is None
    assert iconset.number_badge("solid-100") is None


def test_a_filled_marker_fills_its_disc_and_knocks_out_the_digits():
    solid = _paint("solid-3")
    outlined = _paint("3")
    assert _inked(solid) > 2 * _inked(outlined)
    # a point inside the disc, clear of the digit, is the marker colour
    assert solid.pixelColor(32, 10).rgb() == INK.rgb()
    assert outlined.pixelColor(32, 10).alpha() == 0
    # the digit itself is drawn in the ink that reads on the disc
    on = theme.ink_on(INK).rgb()
    assert any(solid.pixelColor(x, y).rgb() == on
               for y in range(20, 44) for x in range(24, 40))


def test_two_digit_and_zero_markers_draw():
    assert _inked(_paint("solid-12")) > 0
    assert _inked(_paint("0")) > 0
    assert _paint("solid-12") != _paint("solid-13")


ONE = '@ box s "Step" 0,0 120x120 *{}\n'


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _scene_image(text: str) -> QImage:
    scene = _view(text)._scene
    rect = scene.itemsBoundingRect()
    img = QImage(int(rect.width()), int(rect.height()),
                 QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    p = QPainter(img)
    scene.render(p, QRectF(img.rect()), rect)
    p.end()
    return img


def test_the_canvas_draws_filled_twelve_and_zero():
    outlined = _scene_image(ONE.format("12"))
    solid = _scene_image('#!grafli v4\n' + ONE.format("solid-12"))
    zero = _scene_image('#!grafli v4\n' + ONE.format("0"))
    blank = _scene_image('@ box s "Step" 0,0 120x120\n')
    assert _inked_dark(solid) > _inked_dark(outlined) > _inked_dark(blank)
    assert _inked_dark(zero) > _inked_dark(blank)


def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_filled_twelve_and_zero(tmp_path: Path):
    _app()
    outlined = _render(tmp_path, "outlined", "#!grafli v1\n" + ONE.format("3"))
    solid = _render(tmp_path, "solid", "#!grafli v4\n" + ONE.format("solid-3"))
    twelve = _render(tmp_path, "twelve",
                     "#!grafli v4\n" + ONE.format("solid-12"))
    zero = _render(tmp_path, "zero", "#!grafli v4\n" + ONE.format("0"))
    assert outlined.size() == solid.size() == twelve.size() == zero.size()
    images = [outlined, solid, twelve, zero]
    assert all(a != b for i, a in enumerate(images) for b in images[i + 1:])
    assert _inked_dark(solid) > _inked_dark(outlined)


def _inked_dark(img: QImage) -> int:
    """Opaque dark pixels (sampled every 2 px) — the PDF stop raster has a
    transparent ground, so transparent pixels must not count as dark."""
    return sum(1 for y in range(0, img.height(), 2)
               for x in range(0, img.width(), 2)
               if img.pixelColor(x, y).alpha() > 200
               and img.pixelColor(x, y).lightness() < 100)


def test_the_svg_export_carries_the_filled_disc():
    solid = bytes(_view('#!grafli v4\n' + ONE.format("solid-3"))
                  ._render_svg_bytes()).decode()
    outlined = bytes(_view(ONE.format("3"))._render_svg_bytes()).decode()
    assert solid != outlined
    assert solid.count('fill="none"') < outlined.count('fill="none"')


def _stop_raster(view, board, out: Path) -> QImage:
    """The board raster the PDF export paints for the flow's one stop."""
    from grafli.pdfexport import export_flow_to_pdf
    shots: list[QImage] = []
    scene = view._scene
    original = scene.render

    def capture(painter, target, source, *args):
        original(painter, target, source, *args)
        shots.append(QImage(painter.device()))

    scene.render = capture
    try:
        export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    finally:
        del scene.render
    assert out.read_bytes().startswith(b"%PDF")
    assert len(shots) == 1
    return shots[0]


TOUR = ('@ bookmark bm "Step" @s\n'
        '@ flow tour "Tour" bm\n')


def test_the_pdf_export_draws_the_filled_marker(tmp_path: Path):
    text = '#!grafli v4\n' + ONE.format("solid-3") + TOUR
    solid = _stop_raster(_view(text), parse(text), tmp_path / "solid.pdf")
    plain = '#!grafli v2\n' + ONE.format("3") + TOUR
    outlined = _stop_raster(_view(plain), parse(plain),
                            tmp_path / "outlined.pdf")
    assert solid.size() == outlined.size()
    assert _inked_dark(solid) > _inked_dark(outlined)
