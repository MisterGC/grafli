"""Connectors that can't be shaped from their own two ends (#139, #140).

A self-connector has one endpoint, so there is no ray between ends to follow;
parallel connectors between one pair have identical ends, so nothing local tells
them apart. Both are pinned here as *rules* — a loop leaves and re-enters on
adjacent sides, a fan separates every member and its label — rather than as
coordinates, so tuning the loop reach or the fan step doesn't rewrite them.
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication, QGraphicsPolygonItem

from grafli import arrows
from grafli.format import parse
from grafli.items import ArrowLineItem, LabelItem
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


def _points(view, label: str) -> list[tuple[float, float]]:
    """Every point of the connector carrying ``label``, in draw order.

    A labelled connector is drawn as two pieces with the caption between them,
    so the pieces are concatenated — the tests care about where the connector
    runs, not how the label interrupted it.
    """
    out: list[tuple[float, float]] = []
    for gfx in view._arrow_items:
        arrow = gfx.data(0)
        if not isinstance(gfx, ArrowLineItem) or arrow is None:
            continue
        if arrow.label != label:
            continue
        for poly in gfx.path().toSubpathPolygons():
            out.extend((round(p.x(), 3), round(p.y(), 3)) for p in poly)
    return out


def _label_rect(view, text: str) -> QRectF:
    for gfx in view._arrow_items:
        if isinstance(gfx, LabelItem) and gfx.text() == text:
            return gfx.sceneBoundingRect()
    raise AssertionError(f"no label {text!r} on the board")


def _heads(view, label: str) -> list[QPointF]:
    """Arrowhead tips on the connector carrying ``label``."""
    tips = []
    for gfx in view._arrow_items:
        arrow = gfx.data(0)
        if isinstance(gfx, QGraphicsPolygonItem) and arrow is not None \
                and arrow.label == label:
            tips.append(gfx.polygon()[0])
    return tips


def _render_list(view):
    return [(a.from_id, a.to_id, a.head_to, a.head_from, a, None)
            for a in view.board.arrows]


_BOARD = """#!grafli v2
@ box a "A" 0,0 200x100
@ box b "B" 600,0 200x100
@ box c "C" 600,400 200x100
"""

_A_RECT = QRectF(0, 0, 200, 100)


# ── Self-connectors (#139) ─────────────────────────────────────────

def test_a_self_connector_draws_a_loop():
    """The bug: both ends resolved to the box centre, so nothing was drawn."""
    view = _view(_BOARD + "@ arrow a -> a\n")
    pts = _points(view, "")
    assert len(pts) > 2                        # a curve, not a zero-length line
    assert max(math.hypot(x - 100, y - 50) for x, y in pts) > 100
    # The loop hangs off the box rather than crossing it.
    assert any(not _A_RECT.contains(QPointF(x, y)) for x, y in pts)


def test_a_loop_leaves_and_re_enters_on_adjacent_sides():
    view = _view(_BOARD + "@ arrow a -> a\n")
    _s, s_side, _e, e_side, _moved = view._connector_anchors(
        _render_list(view))[0]
    assert (s_side, e_side) in arrows.SELF_LOOP_SIDES


def test_the_loops_ends_sit_on_the_element():
    view = _view(_BOARD + "@ arrow a -> a\n")
    start, _ss, end, _es, _moved = view._connector_anchors(_render_list(view))[0]
    for pt in (start, end):
        assert _A_RECT.adjusted(-0.01, -0.01, 0.01, 0.01).contains(pt)
    assert start != end


def test_the_arrowhead_sits_on_the_loop():
    """A loop with its head somewhere else would read as two connectors."""
    view = _view(_BOARD + "@ arrow a -> a\n")
    _s, _ss, end, _es, _moved = view._connector_anchors(_render_list(view))[0]
    tips = _heads(view, "")
    assert len(tips) == 1
    assert abs(tips[0].x() - end.x()) < 0.01
    assert abs(tips[0].y() - end.y()) < 0.01


def test_the_loop_arrives_along_its_own_curve():
    """The head points where the loop is travelling, not along the chord."""
    rect = (0.0, 0.0, 200.0, 100.0)
    start = arrows.point_on_side(rect, "n", 0.78)
    end = arrows.point_on_side(rect, "e", 0.22)
    path = arrows.self_loop_path(rect, start, "n", end, "e")
    # It re-enters the east side heading west, whatever the chord does.
    assert abs(abs(arrows.path_end_angle(path)) - math.pi) < 0.35


def test_a_loop_takes_a_corner_no_other_connector_uses():
    """Preferring a free corner is what keeps a loop off its neighbours."""
    view = _view(_BOARD + "@ arrow a -> b\n@ arrow a -> c\n@ arrow a -> a\n")
    anchors = view._connector_anchors(_render_list(view))
    loop_idx = next(i for i, a in enumerate(view.board.arrows)
                    if a.from_id == a.to_id)
    assert "e" not in {anchors[loop_idx][1], anchors[loop_idx][3]}


def test_side_choice_is_deterministic():
    """Same board, same corner — the app and a headless render must agree."""
    assert arrows.pick_self_loop_sides({}) == arrows.SELF_LOOP_SIDES[0]
    view = _view(_BOARD + "@ arrow a -> b\n@ arrow a -> a\n")
    render_list = _render_list(view)
    first = view._connector_anchors(render_list)
    second = view._connector_anchors(render_list)
    assert [(v[1], v[3]) for v in first.values()] == \
           [(v[1], v[3]) for v in second.values()]


def test_two_loops_on_one_element_take_different_corners():
    view = _view(_BOARD + '@ arrow a -> a "x"\n@ arrow a -> a "y"\n')
    anchors = view._connector_anchors(_render_list(view))
    corners = {(v[1], v[3]) for v in anchors.values()}
    assert len(corners) == 2
    assert _points(view, "x") != _points(view, "y")


def test_a_loops_label_rides_the_loop():
    view = _view(_BOARD + '@ arrow a -> a "retry"\n')
    rect = _label_rect(view, "retry")
    assert not _A_RECT.contains(rect)          # not buried in the box
    pts = _points(view, "retry")
    assert min(math.hypot(x - rect.center().x(), y - rect.center().y())
               for x, y in pts) < 40


def test_notes_and_images_can_loop_back_on_themselves():
    """Every connector endpoint type gained parity in 0.10.0."""
    src = ("#!grafli v2\n"
           '@ note n 0,0 "a note"\n'
           '@ image i "missing.png" 400,0 120x80\n'
           '@ arrow n -> n "note loop"\n'
           '@ arrow i -> i "image loop"\n')
    view = _view(src)
    assert len(_points(view, "note loop")) > 2
    assert len(_points(view, "image loop")) > 2


def test_a_routing_modifier_does_not_replace_the_loop():
    """A loop has no gap between two ends to stair or curve across, so the
    routings have nothing to do with it — it still draws as a loop."""
    view = _view(_BOARD + '@ arrow a -> a "x" !ortho\n')
    assert len(_points(view, "x")) > 2
    assert len(_heads(view, "x")) == 1


def test_a_two_headed_loop_carries_both_heads():
    view = _view(_BOARD + '@ arrow a <-> a "x"\n')
    assert len(_heads(view, "x")) == 2


def test_two_loops_on_one_element_are_not_merged_into_one():
    """The opposite-pair merge reads (a,a) as its own reverse."""
    view = _view(_BOARD + '@ arrow a -> a "x"\n@ arrow a -> a "y"\n')
    assert _label_rect(view, "x") is not None
    assert _label_rect(view, "y") is not None


# ── Parallel connectors (#140) ─────────────────────────────────────

def test_a_lone_connector_is_drawn_exactly_as_before():
    """The no-op guarantee: nothing to fan means the straight run is kept."""
    view = _view(_BOARD + "@ arrow a -> b\n")
    assert _points(view, "") == [(200.0, 50.0), (600.0, 50.0)]
    assert view._parallel_offsets(_render_list(view)) == {}


def test_parallel_connectors_do_not_share_a_path():
    view = _view(_BOARD + '@ arrow a -> b "reads"\n@ arrow a -> b "writes"\n')
    one, two = _points(view, "reads"), _points(view, "writes")
    assert one and two and one != two
    # Separated along their whole run, not just at the ends.
    assert min(abs(p[1] - q[1]) for p, q in zip(one, two)) > 10


def test_parallel_labels_do_not_stack():
    view = _view(_BOARD + '@ arrow a -> b "reads"\n@ arrow a -> b "writes"\n')
    assert not _label_rect(view, "reads").intersects(_label_rect(view, "writes"))


def test_a_merged_pair_plus_a_third_connector_fans():
    """The special case: one entry is already a two-headed merge."""
    view = _view(_BOARD + '@ arrow a -> b "fwd"\n@ arrow b -> a "back"\n'
                          '@ arrow a -> b "third"\n')
    offsets = view._parallel_offsets([
        (a.from_id, a.to_id, a.head_to, a.head_from, a, None)
        for a in view.board.arrows[:1] + view.board.arrows[2:]])
    assert len(offsets) == 2
    # A merged pair shows both captions in one item, stacked.
    assert not _label_rect(view, "fwd\nback").intersects(
        _label_rect(view, "third"))
    assert _points(view, "fwd") != _points(view, "third")


def test_an_opposite_pair_that_cannot_merge_still_fans():
    """Two double-headed connectors stay separate arrows, so they fan."""
    view = _view(_BOARD + '@ arrow a <-> b "sync"\n@ arrow b <-> a "async"\n')
    assert not _label_rect(view, "sync").intersects(_label_rect(view, "async"))


def test_the_fan_order_follows_the_file():
    view = _view(_BOARD + '@ arrow a -> b "first"\n@ arrow a -> b "second"\n')
    offsets = view._parallel_offsets(_render_list(view))
    assert offsets[0] < 0 < offsets[1]
    # The connector written first stays on the same side of the run.
    assert max(y for _x, y in _points(view, "first")) < \
        min(y for _x, y in _points(view, "second"))


def test_fanning_is_stable_across_redraws():
    view = _view(_BOARD + '@ arrow a -> b "one"\n@ arrow a -> b "two"\n')
    before = _points(view, "one")
    view._redraw_arrows()
    assert _points(view, "one") == before


def test_fan_offsets_are_symmetric_and_capped():
    assert arrows.fan_offsets(1) == [0.0]
    two = arrows.fan_offsets(2)
    assert two == [-two[1], two[1]]
    many = arrows.fan_offsets(9)
    assert abs(many[-1] - many[0]) <= arrows.PARALLEL_FAN_MAX_SPAN + 1e-9
    assert many == sorted(many)


def test_a_zero_offset_gives_back_the_straight_run():
    """What makes the fan free for every board that has nothing to separate."""
    start, end = QPointF(0, 0), QPointF(300, 120)
    straight = arrows.bowed_path(start, end, "e", 0.0)
    assert [straight.pointAtPercent(i / 10) for i in range(11)] == \
           [QPointF(30 * i, 12 * i) for i in range(11)]


def test_a_bow_bends_toward_its_own_anchor_order():
    """A bow that crossed to the other side would cut through its sibling.

    Anchors are spread by increasing ``t`` along the side, so a negative offset
    — the first connector's slot — has to bow the way ``t`` decreases.
    """
    start, end = QPointF(200, 50), QPointF(600, 50)
    up = arrows.bowed_path(start, end, "e", -20.0)
    assert up.pointAtPercent(0.5).y() < 50.0
    down = arrows.bowed_path(start, end, "e", 20.0)
    assert down.pointAtPercent(0.5).y() > 50.0


def test_the_bow_apex_carries_the_offset():
    start, end = QPointF(0, 0), QPointF(400, 0)
    apex = arrows.bowed_path(start, end, "e", 25.0).pointAtPercent(0.5)
    assert abs(apex.x() - 200) < 0.01
    assert abs(apex.y() - 25) < 0.01


def test_a_routed_connector_keeps_its_route():
    """A spline is already shaped by its own anchors; bowing it twice would
    fight the spread pass."""
    view = _view(_BOARD + '@ arrow a -> b "one" !spline\n'
                          '@ arrow a -> b "two" !spline\n')
    one, two = _points(view, "one"), _points(view, "two")
    assert one and two and one != two


# ── The connect gesture can author a loop ─────────────────────────


def test_clicking_the_source_again_creates_a_self_connector():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from grafli.constants import Mode

    view = _view('#!grafli v1\n@ box a "A" 0,0 200x100\n')
    view.resize(900, 600)
    view.set_mode(Mode.CONNECT)

    def press(vp_pos: QPointF):
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, vp_pos,
                         view.viewport().mapToGlobal(vp_pos.toPoint()),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        view.mousePressEvent(ev)

    on_box = view.mapFromScene(QPointF(100, 50))
    press(QPointF(on_box))
    press(QPointF(on_box))

    assert [(ar.from_id, ar.to_id) for ar in view.board.arrows] == [("a", "a")]


def test_a_plain_press_release_on_one_element_does_not_loop():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from grafli.constants import Mode

    view = _view('#!grafli v1\n@ box a "A" 0,0 200x100\n')
    view.resize(900, 600)
    view.set_mode(Mode.CONNECT)

    on_box = QPointF(view.mapFromScene(QPointF(100, 50)))
    press = QMouseEvent(QEvent.Type.MouseButtonPress, on_box,
                        view.viewport().mapToGlobal(on_box.toPoint()),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(press)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, on_box,
                          view.viewport().mapToGlobal(on_box.toPoint()),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    view.mouseReleaseEvent(release)

    assert view.board.arrows == []
