"""`!round` (#307): a box draws as a circle when square and a pill otherwise,
on the canvas, in `grafli render` and in the exports, and every connector
ends on that outline — straight, right-angle and self-loop ones alike."""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from grafli.arrows import onto_round_outline
from grafli.constants import BOX_RADIUS
from grafli.format import parse


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _off_outline(rect: tuple, p: QPointF) -> float:
    """How far ``p`` lies from the round outline of ``rect``."""
    x, y, w, h = rect
    r = min(w, h) / 2
    if w >= h:
        ax, bx = x + r, x + w - r
        cx, cy = min(max(p.x(), ax), bx), y + h / 2
    else:
        ay, by = y + r, y + h - r
        cx, cy = x + w / 2, min(max(p.y(), ay), by)
    return abs(math.hypot(p.x() - cx, p.y() - cy) - r)


def _ends(view, index: int = 0):
    """The start, end and path the view drew for the board's arrow."""
    arrow = view._board.arrows[index]
    return view._arrow_label_geometry[id(arrow)]


def test_a_square_round_box_is_a_circle_and_a_wide_one_a_pill():
    view = _view('#!grafli v4\n'
                 '@ box c "" 0,0 60x60 !round\n'
                 '@ box p "Bubble" 0,100 200x60 !round\n'
                 '@ box t "Tall" 300,0 60x200 !round\n'
                 '@ box b "Box" 300,300 200x60\n')
    items = view._box_items
    assert items["c"].corner_radius(items["c"].rect()) == 30
    assert items["p"].corner_radius(items["p"].rect()) == 30
    assert items["t"].corner_radius(items["t"].rect()) == 30
    assert items["b"].corner_radius(items["b"].rect()) == BOX_RADIUS


def test_a_round_flat_box_or_container_stays_round():
    view = _view('#!grafli v4\n'
                 '@ box f "Band" 0,0 400x80 !flat !round\n'
                 '@ box g "Group" 0,200 300x300 !round\n'
                 '@ box k "Child" 80,280 120x60 >g\n')
    items = view._box_items
    assert items["f"].corner_radius(items["f"].rect()) == 40
    assert items["g"]._container_look()
    assert items["g"].corner_radius(items["g"].rect()) == 150


def test_set_round_switches_the_corners():
    item = _view('@ box b "Box" 0,0 100x100\n')._box_items["b"]
    item.set_round(True)
    assert item.box.round
    assert item.corner_radius(item.rect()) == 50
    item.set_round(False)
    assert item.corner_radius(item.rect()) == BOX_RADIUS


def test_a_point_on_the_straight_part_stays_and_a_corner_point_moves_in():
    rect = (0, 0, 200, 60)
    on_side = QPointF(100, 0)
    assert onto_round_outline(rect, on_side, (0, 1)) == on_side
    corner = onto_round_outline(rect, QPointF(5, 0), (0, 1))
    assert corner.x() == 5 and corner.y() > 0
    assert _off_outline(rect, corner) < 1e-6


def test_a_line_that_misses_the_outline_keeps_its_point():
    p = QPointF(0, 0)
    assert onto_round_outline((0, 0, 60, 60), p, (-1, 0)) == p


def test_a_diagonal_arrow_ends_on_both_circles():
    view = _view('#!grafli v4\n'
                 '@ box a "" 0,0 60x60 !round\n'
                 '@ box b "" 300,300 60x60 !round\n'
                 '@ arrow a -> b "go"\n')
    start, end, _path = _ends(view)
    assert _off_outline((0, 0, 60, 60), start) < 1e-6
    assert _off_outline((300, 300, 60, 60), end) < 1e-6
    # The rectangle's corner would leave a gap of r * (sqrt 2 - 1) to the
    # circle; on the outline the end sits r from the centre.
    assert abs(math.hypot(end.x() - 330, end.y() - 330) - 30) < 1e-6


def test_a_plain_box_keeps_its_rectangle_end():
    view = _view('@ box a "" 0,0 60x60\n'
                 '@ box b "" 300,300 60x60\n'
                 '@ arrow a -> b "go"\n')
    _start, end, _path = _ends(view)
    assert end.x() == 300 or end.y() == 300          # on the rectangle
    assert _off_outline((300, 300, 60, 60), end) > 1   # not on a circle


def test_the_arrowhead_tip_sits_on_the_outline():
    from PySide6.QtWidgets import QGraphicsPolygonItem
    view = _view('#!grafli v4\n'
                 '@ box a "" 0,0 60x60\n'
                 '@ box b "" 300,300 60x60 !round\n'
                 '@ arrow a -> b "go"\n')
    _start, end, _path = _ends(view)
    heads = [it for it in view._arrow_items
             if isinstance(it, QGraphicsPolygonItem)]
    assert heads
    tips = [pt for it in heads for pt in it.polygon()]
    assert any(math.hypot(pt.x() - end.x(), pt.y() - end.y()) < 1e-6
               for pt in tips)


def test_a_right_angle_arrow_ends_on_a_pill():
    view = _view('#!grafli v4\n'
                 '@ box a "Start" 0,0 200x60 !round\n'
                 '@ box b "End" 400,300 200x60 !round\n'
                 '@ arrow a -> b "go" !ortho\n')
    start, end, path = _ends(view)
    assert path is not None
    assert _off_outline((0, 0, 200, 60), start) < 1e-6
    assert _off_outline((400, 300, 200, 60), end) < 1e-6
    first, last = path.elementAt(0), path.elementAt(path.elementCount() - 1)
    assert (first.x, first.y) == (start.x(), start.y())
    assert (last.x, last.y) == (end.x(), end.y())


def test_a_self_loop_leaves_and_reenters_the_circle():
    view = _view('#!grafli v4\n'
                 '@ box s "Wait" 0,0 120x120 !round\n'
                 '@ arrow s -> s "again"\n')
    start, end, path = _ends(view)
    assert path is not None
    assert _off_outline((0, 0, 120, 120), start) < 1e-6
    assert _off_outline((0, 0, 120, 120), end) < 1e-6


def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_a_round_box_differently_from_a_plain_one(tmp_path: Path):
    _app()
    one = '#!grafli v4\n@ box b "" 0,0 120x120 %accent !round\n'
    round_ = _render(tmp_path, "round", one)
    plain = _render(tmp_path, "plain", one.replace(" !round", "")
                    .replace("v4", "v1"))
    assert round_.size() == plain.size()
    assert round_ != plain


def test_the_svg_export_draws_the_curve():
    def svg(text):
        return bytes(_view(text)._render_svg_bytes()).decode()
    round_ = svg('#!grafli v4\n@ box b "" 0,0 120x120 %accent !round\n')
    plain = svg('@ box b "" 0,0 120x120 %accent\n')
    assert round_ != plain


def test_a_small_round_box_without_a_label_stays_a_circle():
    view = _view('#!grafli v4\n'
                 '@ box s "" 0,0 24x24 %primary !round\n'
                 '@ box p "" 0,100 24x24 %primary\n')
    s = view._box_items["s"]
    assert (s.box.w, s.box.h) == (24, 24)
    assert (s.rect().width(), s.rect().height()) == (24, 24)
    # A square-cornered box keeps growing to fit its line as it always has.
    assert view._box_items["p"].box.h > 24


# ── Style mode: `s` then `r` ───────────────────────────────────────

def _style_view(src: str):
    from grafli.view import Mode
    view = _view("#!grafli v1\n" + src)
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


def _press(view, *keys):
    from PySide6.QtTest import QTest
    for key in keys:
        QTest.keyClick(view, key)


def test_s_r_makes_a_box_round_and_again_square():
    from PySide6.QtCore import Qt
    from grafli.format import serialize
    view = _style_view('@ box a "A" 0,0 160x60\n')
    item = view._box_items["a"]
    item.setSelected(True)
    _press(view, Qt.Key.Key_S, Qt.Key.Key_R)
    assert view.board.box_by_id("a").round
    assert item.corner_radius(item.rect()) == 30
    out = serialize(view.board)
    assert '160x60 !round' in out and out.startswith("#!grafli v4\n")
    _press(view, Qt.Key.Key_R)                  # still in style mode
    assert not view.board.box_by_id("a").round
    assert item.corner_radius(item.rect()) == BOX_RADIUS


def test_s_r_is_undoable():
    view = _style_view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    before = len(view._undo_stack)
    view._toggle_round()
    assert view.board.box_by_id("a").round
    assert len(view._undo_stack) == before + 1
    view._undo()
    assert not view.board.box_by_id("a").round


def test_s_r_rounds_the_whole_selection_unless_all_are_round():
    view = _style_view('@ box a "A" 0,0 160x60\n'
                       '@ box b "B" 0,100 60x60 !round\n')
    for key in ("a", "b"):
        view._box_items[key].setSelected(True)
    view._toggle_round()
    assert [b.round for b in view.board.boxes] == [True, True]
    view._toggle_round()
    assert [b.round for b in view.board.boxes] == [False, False]


def test_s_r_moves_the_arrow_ends_onto_the_outline():
    view = _style_view('@ box a "" 0,0 60x60\n'
                       '@ box b "" 300,300 60x60\n'
                       '@ arrow a -> b "go"\n')
    view._box_items["b"].setSelected(True)
    view._toggle_round()
    view._redraw_arrows()
    _start, end, _path = _ends(view)
    assert _off_outline((300, 300, 60, 60), end) < 1e-6
