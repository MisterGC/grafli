"""`!dashed` / `!dotted` (#207): a box's outline is drawn in that pattern on
the canvas, in `grafli render` and in the SVG, HTML and PDF exports. A flat
box or a container, which has no outline, gets one in the pattern. Boxes
without either flag keep their solid outline, or none."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.constants import BOX_BORDER_WIDTH
from grafli.format import parse


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


BOARD = ('#!grafli v4\n'
         '@ box d "Later" 0,0 200x80 !dashed\n'
         '@ box o "Maybe" 0,120 200x80 %accent !dotted\n'
         '@ box s "Now" 0,240 200x80 %accent\n')


def test_a_dashed_box_draws_a_dashed_outline():
    pen = _view(BOARD)._box_items["d"].pen()
    assert pen.style() == Qt.PenStyle.DashLine
    assert pen.color() == QColor(theme.INK)
    assert pen.widthF() == BOX_BORDER_WIDTH


def test_a_dotted_box_draws_round_dots_in_its_border_colour():
    pen = _view(BOARD)._box_items["o"].pen()
    assert pen.style() == Qt.PenStyle.DotLine
    assert pen.capStyle() == Qt.PenCapStyle.RoundCap
    assert pen.color() == QColor(theme.resolve_color("%accent")).darker(125)


def test_a_plain_box_keeps_its_solid_outline():
    pen = _view(BOARD)._box_items["s"].pen()
    assert pen.style() == Qt.PenStyle.SolidLine
    assert pen.capStyle() == Qt.PenCapStyle.SquareCap
    assert pen.widthF() == BOX_BORDER_WIDTH


def test_a_flat_box_gets_an_outline_only_with_a_pattern():
    view = _view('#!grafli v4\n'
                 '@ box f "Band" 0,0 400x80 %primary !flat !dashed\n'
                 '@ box g "Band" 0,120 400x80 %primary !flat\n')
    assert view._box_items["f"].pen().style() == Qt.PenStyle.DashLine
    assert view._box_items["g"].pen().style() == Qt.PenStyle.NoPen


def test_a_container_gets_a_dotted_outline():
    view = _view('#!grafli v4\n'
                 '@ box c "Group" 0,0 400x300 !dotted\n'
                 '@ box k "Child" 40,60 120x60 >c\n')
    assert view._box_items["c"]._container_look()
    assert view._box_items["c"].pen().style() == Qt.PenStyle.DotLine


def test_setting_a_border_and_reapplying_switches_the_pen():
    view = _view(BOARD)
    item = view._box_items["s"]
    item.box.border = "dashed"
    item._apply_color()
    assert item.pen().style() == Qt.PenStyle.DashLine
    item.box.border = ""
    item._apply_color()
    assert item.pen().style() == Qt.PenStyle.SolidLine


def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_dashed_and_dotted_differently_from_solid(tmp_path: Path):
    _app()
    one = '#!grafli v4\n@ box b "Later" 0,0 240x80 !dashed\n'
    dashed = _render(tmp_path, "dashed", one)
    dotted = _render(tmp_path, "dotted", one.replace("!dashed", "!dotted"))
    solid = _render(tmp_path, "solid", one.replace(" !dashed", "")
                    .replace("v4", "v1"))
    assert dashed.size() == dotted.size() == solid.size()
    assert dashed != solid and dotted != solid and dashed != dotted


def test_the_svg_export_carries_the_dash_pattern():
    dashed = bytes(_view('#!grafli v4\n@ box b "Later" 0,0 240x80 !dashed\n')
                   ._render_svg_bytes()).decode()
    solid = bytes(_view('@ box b "Later" 0,0 240x80\n')
                  ._render_svg_bytes()).decode()
    assert "stroke-dasharray" in dashed
    assert "stroke-dasharray" not in solid


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


TOUR = ('@ bookmark bm "Later" @b\n'
        '@ flow tour "Tour" bm\n')


def test_the_pdf_export_draws_the_dashed_outline(tmp_path: Path):
    text = '#!grafli v4\n@ box b "Later" 0,0 240x80 !dashed\n' + TOUR
    dashed = _stop_raster(_view(text), parse(text), tmp_path / "dashed.pdf")
    plain_text = text.replace(" !dashed", "").replace("v4", "v2")
    solid = _stop_raster(_view(plain_text), parse(plain_text),
                         tmp_path / "solid.pdf")
    assert dashed.size() == solid.size()
    assert dashed != solid
