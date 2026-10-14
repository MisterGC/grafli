"""`~from=` / `~to=` (#209): a connector can pin the side it leaves its from
element by and the side it enters its to element at. A pinned end sits on the
middle of its side; a U-turn (both ends on the same side) draws for direct,
spline and stair routing; connectors without a pin route as they always have.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.items import ArrowLineItem
from grafli.view import GrafliView, Mode

SIDES = ("top", "right", "bottom", "left")
ROUTINGS = ("", " !spline", " !ortho")

# Two boxes standing diagonally apart, so no side is the geometric choice
# for every pin.
A = (0.0, 0.0, 200.0, 100.0)
B = (600.0, 300.0, 200.0, 100.0)
PAIR = ('#!grafli v4\n'
        '@ box a "A" 0,0 200x100\n'
        '@ box b "B" 600,300 200x100\n')


def _view(text: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _midpoint(rect: tuple, side: str) -> QPointF:
    x, y, w, h = rect
    return {"top": QPointF(x + w / 2, y), "bottom": QPointF(x + w / 2, y + h),
            "left": QPointF(x, y + h / 2),
            "right": QPointF(x + w, y + h / 2)}[side]


def _polyline(view: GrafliView) -> list[QPointF]:
    """The drawn connector's points, from its first end to its last."""
    lines = [g for g in view._arrow_items if isinstance(g, ArrowLineItem)]
    assert len(lines) == 1
    return [p for poly in lines[0].path().toSubpathPolygons()
            for p in list(poly)]


def _close(p: QPointF, q: QPointF) -> bool:
    return abs(p.x() - q.x()) < 0.01 and abs(p.y() - q.y()) < 0.01


# ── Each side value pins the start and the end ─────────────────────

@pytest.mark.parametrize("routing", ROUTINGS)
@pytest.mark.parametrize("side", SIDES)
def test_from_pins_the_start_to_that_sides_midpoint(side, routing):
    pts = _polyline(_view(PAIR + f'@ arrow a -> b{routing} ~from={side}\n'))
    assert _close(pts[0], _midpoint(A, side))


@pytest.mark.parametrize("routing", ROUTINGS)
@pytest.mark.parametrize("side", SIDES)
def test_to_pins_the_end_to_that_sides_midpoint(side, routing):
    pts = _polyline(_view(PAIR + f'@ arrow a -> b{routing} ~to={side}\n'))
    assert _close(pts[-1], _midpoint(B, side))


@pytest.mark.parametrize("routing", ROUTINGS)
def test_from_and_to_together_pin_both_ends(routing):
    pts = _polyline(_view(PAIR + f'@ arrow a -> b{routing} '
                                 '~from=bottom ~to=left\n'))
    assert _close(pts[0], _midpoint(A, "bottom"))
    assert _close(pts[-1], _midpoint(B, "left"))


def test_pinned_ends_sharing_a_side_are_spread_apart():
    view = _view(PAIR + '@ box c "C" 600,600 200x100\n'
                        '@ arrow a -> b ~from=right\n'
                        '@ arrow a -> c ~from=right\n')
    render_list = [(a.from_id, a.to_id, a.head_to, a.head_from, a, None)
                   for a in view.board.arrows]
    to_b, to_c = (v[0] for v in view._connector_anchors(render_list).values())
    assert round(to_b.x(), 3) == round(to_c.x(), 3) == 200.0
    assert to_b.y() < to_c.y()       # b lies above c, so its end sits higher


# ── A U-turn renders for every routing ─────────────────────────────

# Stacked boxes, the lower one sticking out further right: the loop has to
# step out past it rather than cut its corner.
STACK = ('#!grafli v4\n'
         '@ box a "A" 0,0 200x100\n'
         '@ box b "B" 0,300 300x100\n')


@pytest.mark.parametrize("routing", ROUTINGS)
def test_a_same_side_u_turn_leaves_and_enters_on_the_right(routing):
    view = _view(STACK + f'@ arrow a -> b{routing} ~from=right ~to=right\n')
    pts = _polyline(view)
    assert _close(pts[0], _midpoint((0, 0, 200, 100), "right"))
    assert _close(pts[-1], _midpoint((0, 300, 300, 100), "right"))
    # It leaves rightward and comes back in leftward ...
    assert pts[1].x() > pts[0].x()
    assert pts[-2].x() > pts[-1].x()
    # ... and the whole loop stays right of both boxes' left halves: nothing
    # of it runs back across either box.
    assert min(p.x() for p in pts) >= 200.0 - 0.01
    assert all(p.x() >= 300.0 - 0.01 for p in pts if 300 < p.y() < 400)
    # The arrowhead points into B, leftward.
    heads = [g for g in view._arrow_items
             if g.__class__.__name__ == "QGraphicsPolygonItem"]
    assert len(heads) == 1
    assert min(p.x() for p in heads[0].polygon()) >= 300.0 - 0.01


@pytest.mark.parametrize("routing", ROUTINGS)
def test_a_u_turn_over_the_top_renders(routing):
    pts = _polyline(_view(PAIR + f'@ arrow a -> b{routing} '
                                 '~from=top ~to=top\n'))
    assert _close(pts[0], _midpoint(A, "top"))
    assert _close(pts[-1], _midpoint(B, "top"))
    assert min(p.y() for p in pts) < 0.0


def test_a_stair_u_turn_turns_only_at_right_angles():
    """Measured on the corner points, before the corners are rounded."""
    from PySide6.QtCore import QRectF

    from grafli import arrows
    pts = arrows.ortho_points(QPointF(200, 50), "e", QPointF(300, 350), "e",
                              [], (QRectF(0, 0, 200, 100),
                                   QRectF(0, 300, 300, 100)))
    assert len(pts) == 4                    # out, down, back in
    for p, q in zip(pts, pts[1:]):
        assert abs(p.x() - q.x()) < 0.01 or abs(p.y() - q.y()) < 0.01
    assert pts[1].x() == pts[2].x() == 300 + arrows.PINNED_STUB


def test_a_stair_between_facing_pinned_sides_keeps_the_plain_route():
    """A pin on the side the stair would have used anyway changes nothing."""
    from PySide6.QtCore import QRectF

    from grafli import arrows
    start, end = QPointF(200, 50), QPointF(600, 350)
    plain = arrows.ortho_points(start, "e", end, "w", [])
    pinned = arrows.ortho_points(start, "e", end, "w", [],
                                 (QRectF(*A), QRectF(*B)))
    assert [(p.x(), p.y()) for p in pinned] == [(p.x(), p.y()) for p in plain]


def test_a_back_facing_pin_steps_out_before_it_turns():
    """B lies right of A, but the connector is pinned to A's left side."""
    pts = _polyline(_view(PAIR + '@ arrow a -> b ~from=left ~to=left\n'))
    assert _close(pts[0], _midpoint(A, "left"))
    assert pts[1].x() < 0.0                 # out of the left side first
    assert _close(pts[-1], _midpoint(B, "left"))


def test_a_pinned_self_loop_uses_its_pinned_sides():
    view = _view(PAIR + '@ arrow a -> a ~from=right ~to=right\n')
    pts = _polyline(view)
    assert abs(pts[0].x() - 200.0) < 0.01 and abs(pts[-1].x() - 200.0) < 0.01
    assert pts[0].y() != pts[-1].y()
    assert max(p.x() for p in pts) > 200.0


# ── Unpinned connectors route as today ─────────────────────────────

@pytest.mark.parametrize("routing", ROUTINGS)
def test_an_unpinned_connector_draws_exactly_as_before(routing):
    src = PAIR + f'@ arrow a -> b{routing}\n'
    plain = _polyline(_view(src))
    # The same board with a pin added and cleared must not differ — the
    # unpinned path is the one every board already draws.
    view = _view(src)
    view.board.arrows[0].from_side = "top"
    view._redraw_arrows()
    view.board.arrows[0].from_side = ""
    view._redraw_arrows()
    again = _polyline(view)
    assert [(p.x(), p.y()) for p in plain] == [(p.x(), p.y()) for p in again]


def test_a_pinned_pair_is_not_merged_into_one_line():
    """A -> B and B -> A normally draw as one two-headed line; with a pin each
    direction keeps its own sides."""
    view = _view(PAIR + '@ arrow a -> b ~from=right ~to=left\n'
                        '@ arrow b -> a ~from=top ~to=bottom\n')
    lines = [g for g in view._arrow_items if isinstance(g, ArrowLineItem)]
    assert len(lines) == 2


def test_a_pinned_direct_connector_does_not_bow_beside_a_sibling():
    view = _view(PAIR + '@ arrow a -> b ~from=bottom ~to=top\n'
                        '@ arrow b -> a !ortho ~from=left ~to=left\n')
    lines = [g for g in view._arrow_items if isinstance(g, ArrowLineItem)
             and g.data(0) is view.board.arrows[0]]
    pts = [p for g in lines for poly in g.path().toSubpathPolygons()
           for p in list(poly)]
    assert len(pts) == 2                    # one straight run, no curve


# ── Style mode `s` `e` ─────────────────────────────────────────────

def _overlay_view(src: str) -> GrafliView:
    view = _view("#!grafli v1\n" + src)
    view.resize(900, 600)
    view._mode = Mode.SELECT
    view._select_arrow(view.board.arrows[0])
    return view


def _press(view, *keys):
    from PySide6.QtTest import QTest
    for key in keys:
        QTest.keyClick(view, key)


def _row(view, label: str) -> int:
    return next(i for i, a in enumerate(view._elem_overlay_axes)
                if a["label"] == label)


def test_s_e_offers_leaves_from_and_enters_at_rows():
    view = _overlay_view('@ box a "A" 0,0 200x100\n'
                         '@ box b "B" 600,300 200x100\n'
                         '@ arrow a -> b\n')
    _press(view, Qt.Key.Key_S, Qt.Key.Key_E)
    assert view._elem_overlay_active
    for label in ("Leaves from", "Enters at"):
        axis = view._elem_overlay_axes[_row(view, label)]
        assert axis["options"] == [("Auto", ""), ("Top", "top"),
                                   ("Right", "right"), ("Bottom", "bottom"),
                                   ("Left", "left")]
        assert axis["get"]() == ""


def test_s_e_pins_both_sides_previews_and_saves_v4():
    view = _overlay_view('@ box a "A" 0,0 200x100\n'
                         '@ box b "B" 600,300 200x100\n'
                         '@ arrow a -> b\n')
    _press(view, Qt.Key.Key_S, Qt.Key.Key_E)
    view._elem_overlay_row = _row(view, "Leaves from")
    _press(view, Qt.Key.Key_L, Qt.Key.Key_L)          # Auto -> Top -> Right
    assert _close(_polyline(view)[0], _midpoint(A, "right"))   # live preview
    _press(view, Qt.Key.Key_J)
    assert view._elem_overlay_axes[view._elem_overlay_row]["label"] == \
        "Enters at"
    _press(view, Qt.Key.Key_L, Qt.Key.Key_L, Qt.Key.Key_L, Qt.Key.Key_L)
    _press(view, Qt.Key.Key_Return)
    arrow = view.board.arrows[0]
    assert (arrow.from_side, arrow.to_side) == ("right", "left")
    out = serialize(view.board)
    assert out.startswith("#!grafli v4\n")
    assert "@ arrow a -> b ~from=right ~to=left" in out


def test_side_cancel_reverts_and_commit_is_undoable():
    view = _overlay_view('@ box a "A" 0,0 200x100\n'
                         '@ box b "B" 600,300 200x100\n'
                         '@ arrow a -> b\n')
    plain = [(p.x(), p.y()) for p in _polyline(view)]
    view._open_element_overlay()
    view._elem_overlay_row = _row(view, "Enters at")
    view._elem_overlay_cycle(1)                       # live preview -> Top
    assert view.board.arrows[0].to_side == "top"
    view._cancel_element_overlay()
    assert view.board.arrows[0].to_side == ""
    assert [(p.x(), p.y()) for p in _polyline(view)] == plain
    before = len(view._undo_stack)
    view._open_element_overlay()
    view._elem_overlay_row = _row(view, "Enters at")
    view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    assert view.board.arrows[0].to_side == "top"
    assert len(view._undo_stack) == before + 1
    view._undo()
    assert view.board.arrows[0].to_side == ""
    assert serialize(view.board).startswith("#!grafli v1\n")
