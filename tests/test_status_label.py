"""`~status=<text>[:%color]` (#211): a box carries a short status label, a
pill on its bottom edge, on the canvas, in `grafli render` and in the PDF
export. Style mode `s` `s` types it and then colours it in the colour grid.
Boxes without one draw exactly as before.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from grafli import theme
from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

BOARD = ('#!grafli v4\n'
         '@ box api "API" 0,0 200x100 ~status=open\n'
         '@ box db "Store" 400,0 200x100 %primary ~status=designed:%rose\n'
         '@ box ui "UI" 800,0 200x100\n')


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _pill_pixels(view: GrafliView, box_id: str) -> QImage:
    """The scene as drawn over one box's status pill."""
    item = view._box_items[box_id]
    source = item.mapRectToScene(item.status_rect())
    img = QImage(int(source.width()), int(source.height()),
                 QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    view._scene.render(painter, QRectF(0, 0, img.width(), img.height()),
                       source)
    painter.end()
    return img


def _share(img: QImage, color: QColor) -> float:
    """Fraction of *img*'s pixels within a few levels of *color*."""
    hits = 0
    for y in range(img.height()):
        for x in range(img.width()):
            p = img.pixelColor(x, y)
            if (abs(p.red() - color.red()) <= 6
                    and abs(p.green() - color.green()) <= 6
                    and abs(p.blue() - color.blue()) <= 6):
                hits += 1
    return hits / (img.width() * img.height())


# ── Where the pill sits ───────────────────────────────────────────

def test_the_pill_straddles_the_bottom_edge_right_aligned():
    item = _view(BOARD)._box_items["api"]
    pill = item.status_rect()
    assert pill.top() < 100 < pill.bottom()
    assert abs(pill.center().y() - 100) < 0.01
    assert pill.right() == 200 - item._STATUS_INSET
    assert item.boundingRect().contains(pill)


def test_a_box_without_a_status_has_no_pill():
    item = _view(BOARD)._box_items["ui"]
    assert item.status_rect().isEmpty()
    assert item.boundingRect() == QGraphicsRectItem.boundingRect(item)


def test_a_longer_status_makes_a_wider_pill():
    view = _view(BOARD)
    short = view._box_items["api"].status_rect().width()
    view._box_items["api"].set_status("in-review")
    assert view._box_items["api"].status_rect().width() > short


# ── On the canvas ─────────────────────────────────────────────────

def test_the_canvas_draws_a_coloured_pill_in_its_colour():
    view = _view(BOARD)
    rose = QColor(theme.resolve_color("%rose"))
    assert _share(_pill_pixels(view, "db"), rose) > 0.3


def test_the_canvas_draws_a_plain_pill_on_the_surface_colour():
    view = _view(BOARD)
    assert _share(_pill_pixels(view, "api"), QColor(theme.SURFACE)) > 0.3


def test_the_pill_ink_follows_its_fill():
    view = _view(BOARD)
    item = view._box_items["db"]
    item.set_status("designed", "%primary")
    fill = QColor(theme.resolve_color("%primary"))
    ink = theme.ink_on(fill)
    other = QColor(theme.INK_ON_LIGHT_FILL
                   if ink == QColor(theme.INK_ON_DARK_FILL)
                   else theme.INK_ON_DARK_FILL)
    pixels = _pill_pixels(view, "db")
    assert _share(pixels, ink) > 0.005
    assert _share(pixels, ink) > 4 * _share(pixels, other)


# ── Render and export ─────────────────────────────────────────────

def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_the_status_label(tmp_path: Path):
    _app()
    plain = '#!grafli v1\n@ box api "API" 0,0 200x100\n'
    status = _render(tmp_path, "status",
                     plain.replace("v1", "v4").rstrip("\n")
                     + " ~status=open:%rose\n")
    none = _render(tmp_path, "none", plain)
    assert status != none
    rose = QColor(theme.resolve_color("%rose"))
    assert _share(status, rose) > 0.001
    assert _share(none, rose) == 0


def test_a_box_renders_the_same_next_to_a_cleared_status(tmp_path: Path):
    """Setting a status and clearing it again leaves the render unchanged,
    pixel for pixel: a board without one draws as before."""
    _app()
    view = _view('#!grafli v1\n@ box api "API" 0,0 200x100\n'
                 '@ box db "Store" 400,0 200x100 %primary\n')
    before = view._render_png_image(scale=1)
    view._box_items["db"].set_status("open", "%rose")
    assert view._render_png_image(scale=1) != before
    view._box_items["db"].set_status("")
    assert view._render_png_image(scale=1) == before


TOUR = ('@ bookmark bm "A" @api,db\n'
        '@ flow tour "Tour" bm\n')


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


def test_the_pdf_export_draws_the_status_label(tmp_path: Path):
    text = BOARD + TOUR
    status = _stop_raster(_view(text), parse(text), tmp_path / "status.pdf")
    plain_text = (text.replace(" ~status=open", "")
                  .replace(" ~status=designed:%rose", "")
                  .replace("v4", "v2"))
    plain = _stop_raster(_view(plain_text), parse(plain_text),
                         tmp_path / "plain.pdf")
    assert status != plain
    rose = QColor(theme.resolve_color("%rose"))
    assert _share(status, rose) > 0.0005
    assert _share(plain, rose) == 0


# ── Style mode `s` `s` ─────────────────────────────────────────────

def _select(text: str, box_id: str, answer: tuple[str, bool]) -> GrafliView:
    view = _view(text)
    view.resize(900, 600)
    view._mode = Mode.SELECT
    view._box_items[box_id].setSelected(True)
    view._status_dialog = lambda current: answer
    return view


def _press(view, *keys):
    from PySide6.QtTest import QTest
    for key in keys:
        QTest.keyClick(view, key)


PLAIN = '#!grafli v1\n@ box api "API" 0,0 200x100\n@ note n 0,200 "hi"\n'


def test_s_s_types_a_status_then_colours_it_and_saves_v4():
    view = _select(PLAIN, "api", ("in review", True))
    asked = []
    view._status_dialog = lambda current: (asked.append(current)
                                           or ("in review", True))
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S)
    assert asked == [""]
    box = view.board.box_by_id("api")
    assert box.status == "in-review"
    assert view._color_picker_active
    assert view._color_picker_targets()[0] == "status"
    _press(view, Qt.Key.Key_L)                          # Default -> Base
    assert box.status_color == "%base"                  # live preview
    assert box.color == ""                              # the fill is untouched
    _press(view, Qt.Key.Key_Return)
    assert not view._color_picker_active
    assert box.status_color == "%base"
    out = serialize(view.board)
    assert out.startswith("#!grafli v4\n")
    assert '@ box api "API" 0,0 200x100 ~status=in-review:%base' in out


def test_s_s_prefills_the_current_status():
    view = _select(BOARD, "db", ("done", True))
    asked = []
    view._status_dialog = lambda current: (asked.append(current)
                                           or ("done", True))
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S)
    assert asked == ["designed"]
    assert view.board.box_by_id("db").status_color == "%rose"


def test_esc_in_the_grid_keeps_the_colour_and_undo_restores_the_text():
    view = _select(BOARD, "db", ("done", True))
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S, Qt.Key.Key_H)
    box = view.board.box_by_id("db")
    assert box.status_color != "%rose"
    _press(view, Qt.Key.Key_Escape)
    assert (box.status, box.status_color) == ("done", "%rose")
    view._undo()
    box = view.board.box_by_id("db")
    assert (box.status, box.status_color) == ("designed", "%rose")


def test_an_empty_status_clears_it_without_the_grid():
    view = _select(BOARD, "api", ("  ", True))
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S)
    assert view.board.box_by_id("api").status == ""
    assert not view._color_picker_active
    assert view._box_items["api"].status_rect().isEmpty()


def test_a_cancelled_prompt_changes_nothing():
    view = _select(BOARD, "api", ("done", False))
    before = len(view._undo_stack)
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S)
    assert view.board.box_by_id("api").status == "open"
    assert len(view._undo_stack) == before


def test_colons_and_spaces_become_one_token():
    assert GrafliView._status_token(" needs  a:review ") == "needs-a-review"


def test_s_s_on_a_note_says_only_boxes_carry_one():
    view = _view(PLAIN)
    view.resize(900, 600)
    view._mode = Mode.SELECT
    view._note_items["n"].setSelected(True)
    view._status_dialog = lambda current: ("x", True)
    _press(view, Qt.Key.Key_S, Qt.Key.Key_S)
    assert "Only boxes" in view._toast_text


def test_the_help_sheet_names_the_key():
    from grafli.view.overlays import OverlaysMixin
    source = inspect.getsource(OverlaysMixin._show_cheatsheet)
    assert '("  s", "Status label on a box (~status=)' in source
