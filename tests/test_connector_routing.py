"""Connector routing (#138): side anchors, spreading, and path shape.

The assertions are about *rules* — which side a connector leaves, that a stair
turns at right angles, that shared sides get spread — rather than coordinates,
so a tuning change to the corner radius or spline reach doesn't rewrite them.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from grafli import arrows
from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


_BOARD = """#!grafli v2
@ box a "A" 0,0 200x100
@ box b "B" 600,0 200x100
@ box c "C" 600,300 200x100
@ box d "D" 600,600 200x100
"""


# ── Anchor sides ───────────────────────────────────────────────────

def test_routed_connector_leaves_the_side_a_direct_one_would():
    """Switching a connector to a routing must not teleport its endpoint.

    Both anchor models answer the same question — which edge does the ray to
    the other node cross — so they have to agree on the side, or a board would
    visibly jump when the routing changes.
    """
    rect = (0.0, 0.0, 200.0, 100.0)
    for target in (QPointF(600, 20), QPointF(-400, 20),
                   QPointF(100, 900), QPointF(100, -900)):
        side = arrows.anchor_side(rect, target)
        direct = arrows._rect_edge_point(*rect, target)
        if side == "e":
            assert abs(direct.x() - 200) < 0.01
        elif side == "w":
            assert abs(direct.x() - 0) < 0.01
        elif side == "s":
            assert abs(direct.y() - 100) < 0.01
        else:
            assert abs(direct.y() - 0) < 0.01


def test_point_on_side_lands_on_that_side():
    rect = (10.0, 20.0, 100.0, 50.0)
    assert arrows.point_on_side(rect, "n", 0.5) == QPointF(60, 20)
    assert arrows.point_on_side(rect, "s", 0.5) == QPointF(60, 70)
    assert arrows.point_on_side(rect, "w", 0.5) == QPointF(10, 45)
    assert arrows.point_on_side(rect, "e", 0.5) == QPointF(110, 45)


# ── Spreading ──────────────────────────────────────────────────────

def test_a_lone_connector_keeps_the_side_midpoint():
    """Spreading must not disturb the common case."""
    assert arrows.spread_offsets(1) == [0.5]


def test_connectors_sharing_a_side_are_spread_apart():
    """The whole reason anchors need derivation rather than a fixed midpoint."""
    src = _BOARD + (
        "@ arrow a -> b !ortho\n"
        "@ arrow a -> c !ortho\n"
        "@ arrow a -> d !ortho\n"
    )
    view = _view(src)
    anchors = view._connector_anchors([
        (arw.from_id, arw.to_id, arw.head_to, arw.head_from, arw, None)
        for arw in view.board.arrows])
    starts = [a[0] for a in anchors.values()]
    assert len(anchors) == 3
    # Distinct exit points, all on one box.
    assert len({(round(p.x(), 3), round(p.y(), 3)) for p in starts}) == 3


def test_spreading_is_stable_across_redraws():
    """Same board, same picture — headless render must match the app."""
    src = _BOARD + "@ arrow a -> b !ortho\n@ arrow a -> c !ortho\n"
    view = _view(src)
    render_list = [(a.from_id, a.to_id, a.head_to, a.head_from, a, None)
                   for a in view.board.arrows]
    first = view._connector_anchors(render_list)
    second = view._connector_anchors(render_list)
    assert {k: (v[0].x(), v[0].y()) for k, v in first.items()} == \
           {k: (v[0].x(), v[0].y()) for k, v in second.items()}


# ── Path shape ─────────────────────────────────────────────────────

def test_stair_turns_only_at_right_angles():
    pts = arrows.ortho_points(QPointF(100, 25), "e", QPointF(300, 200), "w")
    for p, q in zip(pts, pts[1:]):
        assert abs(p.x() - q.x()) < 0.01 or abs(p.y() - q.y()) < 0.01


def test_aligned_boxes_give_a_stair_no_bend():
    """Facing sides on the same axis need no corner — a Z would be a wobble."""
    pts = arrows.ortho_points(QPointF(100, 50), "e", QPointF(300, 50), "w")
    assert len(pts) == 2


def test_arrowhead_follows_the_curve_not_the_chord():
    """A spline arrives along its tangent; the chord would point elsewhere."""
    start, end = QPointF(0, 0), QPointF(300, 300)
    path = arrows.routed_path("spline", start, "e", end, "w")
    tangent = arrows.path_end_angle(path, at_end=True)
    assert abs(tangent) < 0.35          # arrives heading east, into the w side


def test_routings_are_deterministic():
    """Same inputs, same path — no randomness, nothing read from app state."""
    args = ("spline", QPointF(0, 0), "e", QPointF(200, 140), "w")
    a, b = arrows.routed_path(*args), arrows.routed_path(*args)
    assert [a.pointAtPercent(i / 20) for i in range(21)] == \
           [b.pointAtPercent(i / 20) for i in range(21)]


# ── Label gap ──────────────────────────────────────────────────────

def test_label_interrupts_a_routed_connector():
    path = arrows.routed_path("ortho", QPointF(0, 0), "e", QPointF(200, 200), "w")
    mid = path.pointAtPercent(0.5)
    gap = QRectF(mid.x() - 20, mid.y() - 12, 40, 24)
    assert len(arrows.split_path_at_rect(path, gap)) == 2


def test_a_label_that_misses_leaves_the_connector_whole():
    path = arrows.routed_path("ortho", QPointF(0, 0), "e", QPointF(200, 200), "w")
    assert len(arrows.split_path_at_rect(path, QRectF(9000, 9000, 20, 20))) == 1


# ── Integration ────────────────────────────────────────────────────

def test_routing_survives_a_redraw():
    view = _view(_BOARD + '@ arrow a -> c "x" !ortho\n')
    view._redraw_arrows()
    assert view.board.arrows[0].routing == "ortho"
    assert view._arrow_items          # something was actually drawn


def test_an_uncrowded_direct_connector_keeps_its_natural_anchor():
    """The no-op guarantee: nothing to separate means nothing is returned."""
    view = _view(_BOARD + "@ arrow a -> b\n")
    render_list = [(a.from_id, a.to_id, a.head_to, a.head_from, a, None)
                   for a in view.board.arrows]
    assert view._connector_anchors(render_list) == {}


def test_a_routed_connector_starts_where_its_target_implies():
    """The showcase bug: a spline left from the middle of the side regardless.

    Allocating a box side once per *kind* meant a routed connector never saw the
    direct one already arriving there, and it threw away the one piece of
    information that would have placed it correctly — where its own centre-ray
    exits. The spline left from the side midpoint, on the wrong side of an
    arrowhead it should have cleared, and crossed it.
    """
    view = _view(_BOARD + "@ arrow b -> a\n@ arrow a -> c !spline\n")
    render_list = [(x.from_id, x.to_id, x.head_to, x.head_from, x, None)
                   for x in view.board.arrows]
    anchors = view._connector_anchors(render_list)
    idx = next(i for i, x in enumerate(view.board.arrows) if x.routing)
    start = anchors[idx][0]
    # Box a spans y=0..100; c sits below-right, so the exit belongs low on the
    # east side — not at the midpoint (y=50) the old routed pass would give.
    assert start.y() > 70.0, "routed connector still leaving from the midpoint"
