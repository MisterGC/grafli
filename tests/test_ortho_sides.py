"""Right-angle arrows sharing a side of a box (#306).

Several `!ortho` arrows leaving one side of a box start at their own points
and turn on their own lines, so no two share a run until they split. That
holds on the canvas and in what `grafli render` writes.
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from grafli import arrows
from grafli.format import parse
from grafli.items import ArrowLineItem

# A box with four below it: the arrows to the outer two turn far, the inner
# two turn near, and D overlaps A enough for the straight shortcut.
FAN = """#!grafli v4
@ box a "A" 0,0 200x80
@ box b "B" -300,250 120x60
@ box c "C" -100,250 120x60
@ box d "D" 100,250 120x60
@ box e "E" 300,250 120x60
@ arrow a -> b !ortho
@ arrow a -> c !ortho
@ arrow a -> d !ortho
@ arrow a -> e !ortho
"""

# The same fan out of the right side, two going up and two going down.
FAN_RIGHT = """#!grafli v4
@ box a "A" 0,0 120x200
@ box b "B" 640,-230 120x60
@ box c "C" 640,-80 120x60
@ box d "D" 640,220 120x60
@ box e "E" 640,370 120x60
@ arrow a -> b !ortho
@ arrow a -> c !ortho
@ arrow a -> d !ortho
@ arrow a -> e !ortho
"""

# All four pinned to the bottom: the pins share the side's middle, so it is
# the spread and the turn lines alone that keep them apart.
FAN_PINNED = FAN.replace(" !ortho\n", " !ortho ~from=bottom ~to=top\n")

FANS = {"fan": FAN, "fan-right": FAN_RIGHT, "fan-pinned": FAN_PINNED}

def _view(text: str):
    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


Run = tuple[QPointF, QPointF]


def _runs_of_path(path: QPainterPath) -> list[Run]:
    """The straight runs of a drawn connector, without its eased corners."""
    runs: list[Run] = []
    cur = None
    i = 0
    while i < path.elementCount():
        el = path.elementAt(i)
        pt = QPointF(el.x, el.y)
        if el.isLineTo() and cur is not None:
            runs.append((cur, pt))
        if el.isCurveTo():
            last = path.elementAt(i + 2)
            pt = QPointF(last.x, last.y)
            i += 2
        cur = pt
        i += 1
    return runs


def _canvas_arrows(view) -> list[list[Run]]:
    return [_runs_of_path(g.path()) for g in view._arrow_items
            if isinstance(g, ArrowLineItem)]


def _svg_arrows(svg: str) -> list[list[Run]]:
    """The straight runs of every connector line in a rendered SVG.

    A connector is the one open path the render draws in scene
    coordinates; boxes and arrowheads are closed.
    """
    out = []
    for d in re.findall(r'<path [^>]*\bd="([^"]*)"', svg):
        if "Z" in d:
            continue
        runs: list[Run] = []
        cur = None
        for cmd, args in re.findall(r"([MLC])([^MLC]*)", d):
            nums = [float(v) for v in re.findall(r"-?[\d.]+(?:e-?\d+)?", args)]
            pt = QPointF(nums[-2], nums[-1])
            if cmd == "L" and cur is not None:
                runs.append((cur, pt))
            cur = pt
        out.append(runs)
    return out


def _rendered(tmp_path, text: str) -> list[list[Run]]:
    from grafli.app import _cmd_render
    board = tmp_path / "board.grafli"
    board.write_text(text)
    out = tmp_path / "board.svg"
    assert _cmd_render([str(board), str(out)]) == 0
    return _svg_arrows(out.read_text(encoding="utf-8"))


def _flat(a: Run) -> bool:
    return abs(a[0].y() - a[1].y()) < 0.5


def _shared(a: Run, b: Run) -> bool:
    """Whether two runs lie on one line and overlap along it."""
    if _flat(a) != _flat(b):
        return False
    if _flat(a):
        if abs(a[0].y() - b[0].y()) > 1.0:
            return False
        lo = max(min(a[0].x(), a[1].x()), min(b[0].x(), b[1].x()))
        hi = min(max(a[0].x(), a[1].x()), max(b[0].x(), b[1].x()))
    else:
        if abs(a[0].x() - b[0].x()) > 1.0:
            return False
        lo = max(min(a[0].y(), a[1].y()), min(b[0].y(), b[1].y()))
        hi = min(max(a[0].y(), a[1].y()), max(b[0].y(), b[1].y()))
    return hi - lo > 1.0


def _crosses(a: Run, b: Run) -> bool:
    """Whether a flat run and an upright one cross inside both."""
    if _flat(a) == _flat(b):
        return False
    flat, up = (a, b) if _flat(a) else (b, a)
    x, y = up[0].x(), flat[0].y()
    return (min(flat[0].x(), flat[1].x()) + 0.5 < x
            < max(flat[0].x(), flat[1].x()) - 0.5
            and min(up[0].y(), up[1].y()) + 0.5 < y
            < max(up[0].y(), up[1].y()) - 0.5)


def _fan_ok(routes: list[list[Run]]) -> None:
    assert len(routes) == 4
    starts = [r[0][0] for r in routes]
    for i, p in enumerate(starts):
        for q in starts[i + 1:]:
            assert (abs(p.x() - q.x()) + abs(p.y() - q.y())) > 10.0, \
                "two arrows leave from one point"
    for i, ra in enumerate(routes):
        for rb in routes[i + 1:]:
            for a in ra:
                for b in rb:
                    assert not _shared(a, b), f"shared run {a} / {b}"
                    assert not _crosses(a, b), f"crossing {a} / {b}"


# ── four arrows out of one side ────────────────────────────────────

@pytest.mark.parametrize("name", FANS)
def test_four_arrows_out_of_one_side_keep_apart_on_the_canvas(name):
    _fan_ok(_canvas_arrows(_view(FANS[name])))


@pytest.mark.parametrize("name", FANS)
def test_four_arrows_out_of_one_side_keep_apart_in_grafli_render(
        tmp_path, name):
    _fan_ok(_rendered(tmp_path, FANS[name]))


def test_the_arrows_of_a_fan_each_turn_on_their_own_line():
    turns = set()
    for runs in _canvas_arrows(_view(FAN)):
        flat = [a for a in runs if _flat(a) and abs(a[0].x() - a[1].x()) > 1]
        assert len(flat) == 1
        turns.add(round(flat[0][0].y()))
    assert len(turns) == 2              # two going left, two going right


def test_an_aligned_target_keeps_its_place_among_the_others():
    """D overlaps A, so its straight shortcut puts its end right of where
    E's ray leaves; ranked by where each goes, D still starts left of E."""
    starts = sorted((r[0][0].x(), r[-1][1].x())
                    for r in _canvas_arrows(_view(FAN)))
    ends = [end for _start, end in starts]
    assert ends == sorted(ends)


# ── turn_lines ─────────────────────────────────────────────────────

def _down(x0: float, x1: float, y1: float = 300.0):
    return (QPointF(x0, 100), "s", QPointF(x1, y1), "n")


def test_the_arrow_furthest_out_turns_nearest_the_box():
    lines = arrows.turn_lines([_down(120, -100), _down(100, -300)])
    assert lines[1] < lines[0]
    assert lines[0] - lines[1] == pytest.approx(arrows.ORTHO_TURN_SEP)
    assert (lines[0] + lines[1]) / 2 == pytest.approx(200.0)


def test_arrows_turning_apart_keep_their_own_middle():
    lines = arrows.turn_lines([_down(90, -100), _down(110, 300)])
    assert lines == [None, None]


def test_a_lone_arrow_an_l_and_a_straight_run_keep_their_own_line():
    assert arrows.turn_lines([_down(100, -100)]) == [None]
    l_shape = (QPointF(100, 100), "s", QPointF(300, 300), "w")
    straight = _down(110, 110)
    assert arrows.turn_lines([_down(100, -100), l_shape, straight]) == \
        [None, None, None]


def test_a_tight_gap_squeezes_the_lines_inside_it():
    routes = [_down(100 + 10 * k, -100 - 100 * k, 140.0) for k in range(4)]
    lines = arrows.turn_lines(routes)
    assert all(100 < v < 140 for v in lines)
    assert lines == sorted(lines)       # the one furthest out turns first
    assert len(set(lines)) == 4

