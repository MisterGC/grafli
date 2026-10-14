"""`!sans` (#205): a box's label (and its doc line) is set in the bundled
proportional face, Inter, on the canvas, in `grafli render` and in the PDF
export. Without `!sans` a box keeps grafli's mono face."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontInfo, QImage
from PySide6.QtWidgets import QApplication

from grafli.constants import FONT_FAMILY, SANS_FONT_FAMILY
from grafli.format import parse


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    from grafli.fonts import register_bundled_fonts
    register_bundled_fonts()
    return app


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


BOARD = ('#!grafli v4\n'
         '@ box s "Sans title" 0,0 240x80 %primary !sans\n'
         '@ box m "Mono title" 0,120 240x80 %primary\n')


def test_a_sans_box_label_resolves_to_inter_and_a_plain_one_to_mono():
    view = _view(BOARD)
    sans = view._box_items["s"]._label.font()
    mono = view._box_items["m"]._label.font()
    assert QFontInfo(sans).family() == SANS_FONT_FAMILY
    assert QFontInfo(mono).family() == FONT_FAMILY


def test_sans_keeps_the_size_and_emphasis():
    view = _view(BOARD.replace("%primary !sans", "%primary ~large !sans !bold"))
    font = view._box_items["s"]._label.font()
    assert QFontInfo(font).family() == SANS_FONT_FAMILY
    assert font.bold()
    plain = view._box_items["m"]._label.font()
    assert font.pointSizeF() > plain.pointSizeF()


def test_a_sans_box_doc_line_takes_the_sans_face():
    view = _view(BOARD)
    assert view._box_items["s"]._doc_line_font().family() == SANS_FONT_FAMILY
    assert view._box_items["m"]._doc_line_font().family() == FONT_FAMILY


def test_set_sans_switches_the_label_and_back():
    view = _view(BOARD)
    item = view._box_items["m"]
    mono = item._label.font()
    item.set_sans(True)
    assert item.box.sans
    assert item._label.font().family() == SANS_FONT_FAMILY
    item.set_sans(False)
    assert item._label.font() == mono


def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_a_sans_box_differently_from_mono(tmp_path: Path):
    _app()
    one = '#!grafli v4\n@ box s "Sans title" 0,0 240x80 %primary !sans\n'
    sans = _render(tmp_path, "sans", one)
    mono = _render(tmp_path, "mono", one.replace(" !sans", "")
                   .replace("v4", "v1"))
    assert sans.size() == mono.size()
    assert sans != mono


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


TOUR = ('@ bookmark bm "Title" @s\n'
        '@ flow tour "Tour" bm\n')


def test_the_pdf_export_draws_a_sans_box_in_inter(tmp_path: Path):
    text = ('#!grafli v4\n@ box s "Sans title" 0,0 240x80 %primary !sans\n'
            + TOUR)
    board = parse(text)
    view = _view(text)
    fonts: list[str] = []
    label = view._box_items["s"]._label
    original = label.paint

    def paint(painter, *args):
        fonts.append(QFontInfo(label.font()).family())
        original(painter, *args)

    label.paint = paint
    sans = _stop_raster(view, board, tmp_path / "sans.pdf")
    assert fonts and set(fonts) == {SANS_FONT_FAMILY}

    plain_text = text.replace(" !sans", "").replace("v4", "v1")
    plain = parse(plain_text)
    mono = _stop_raster(_view(plain_text), plain, tmp_path / "mono.pdf")
    assert sans.size() == mono.size()
    assert sans != mono
