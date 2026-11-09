"""`grafli layout <file>` — the app's layered layout, run headless (#256).

The test on ``examples/architecture.grafli`` pins the layout of a real
board: a change to the layout that moves any of its boxes shows up here.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from grafli import app
from grafli.app import _cmd_layout
from grafli.format import parse

EXAMPLE = Path(__file__).parent.parent / "examples" / "architecture.grafli"

# (x, y, w, h) of every box after one `grafli layout` run.
ARCHITECTURE_LAID_OUT = {
    "clients": (320, 80, 540, 220),
    "web": (360, 140, 220, 80),
    "mobile": (600, 140, 220, 80),
    "api": (340, 360, 500, 220),
    "gateway": (360, 440, 200, 90),
    "graphql": (600, 440, 190, 90),
    "core": (40, 640, 1100, 230),
    "auth": (100, 700, 220, 90),
    "users": (340, 700, 220, 90),
    "orders": (580, 700, 240, 90),
    "catalog": (840, 700, 220, 90),
    "data": (40, 940, 1100, 340),
    "redis": (220, 1000, 220, 85),
    "postgres": (460, 1000, 220, 85),
    "queue": (700, 1000, 240, 85),
    "search": (460, 1160, 220, 85),
}


def _rects(path: Path) -> dict[str, tuple[float, float, float, float]]:
    board = parse(path.read_text(encoding="utf-8"))
    return {b.id: (b.x, b.y, b.w, b.h) for b in board.boxes}


def _overlap(a, b) -> bool:
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


@pytest.fixture
def board(tmp_path: Path) -> Path:
    f = tmp_path / "architecture.grafli"
    shutil.copy(EXAMPLE, f)
    return f


def test_layout_of_the_architecture_example_is_pinned(board: Path, capsys):
    assert _cmd_layout([str(board)]) == 0
    assert f"laid out {board}" in capsys.readouterr().out
    assert _rects(board) == ARCHITECTURE_LAID_OUT


def test_layout_keeps_arrows_and_root_notes(board: Path):
    before = parse(EXAMPLE.read_text(encoding="utf-8"))
    _cmd_layout([str(board)])
    after = parse(board.read_text(encoding="utf-8"))
    assert ([(a.from_id, a.to_id, a.label) for a in after.arrows]
            == [(a.from_id, a.to_id, a.label) for a in before.arrows])
    root_notes = {n.id: (n.x, n.y) for n in before.notes if not n.parent}
    assert {n.id: (n.x, n.y) for n in after.notes if not n.parent} == root_notes


def test_a_second_run_changes_nothing(board: Path):
    assert _cmd_layout([str(board)]) == 0
    text = board.read_text(encoding="utf-8")
    assert _cmd_layout(["--check", str(board)]) == 0
    assert _cmd_layout([str(board)]) == 0
    assert board.read_text(encoding="utf-8") == text


def test_check_reports_and_writes_nothing(board: Path, capsys):
    text = board.read_text(encoding="utf-8")
    assert _cmd_layout(["--check", str(board)]) == 1
    assert f"would lay out {board}" in capsys.readouterr().out
    assert board.read_text(encoding="utf-8") == text


def test_pinned_box_keeps_its_position(board: Path):
    text = board.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("@ box api "))
    board.write_text(text.replace(line, line + " !pin"), encoding="utf-8")
    pinned_at = _rects(board)["api"]

    assert _cmd_layout([str(board)]) == 0
    rects = _rects(board)
    assert rects["api"] == pinned_at
    assert "!pin" in board.read_text(encoding="utf-8")
    for bid in ("clients", "core", "data"):  # api's siblings at the root
        assert not _overlap(rects[bid], pinned_at), bid


def test_direction_flag_sets_every_flow(tmp_path: Path):
    f = tmp_path / "b.grafli"
    f.write_text('#!grafli v1\n'
                 '@ box a "A" 0,0 160x80\n'
                 '@ box b "B" 0,0 160x80\n'
                 '@ arrow a -> b\n', encoding="utf-8")
    assert _cmd_layout(["--direction", "ltr", str(f)]) == 0
    rects = _rects(f)
    assert rects["a"][1] == rects["b"][1]
    assert rects["a"][0] + rects["a"][2] < rects["b"][0]


def test_malformed_board_is_left_untouched(tmp_path: Path, capsys):
    f = tmp_path / "bad.grafli"
    text = ('#!grafli v1\n@ box a "A" 0,0 160x80\n'
            '@ box b "B" 900,900 160x80 >\n@ arrow a -> b\n')
    f.write_text(text, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 2
    assert "left untouched" in capsys.readouterr().err
    assert f.read_text(encoding="utf-8") == text


def test_newer_board_is_left_untouched(tmp_path: Path, capsys):
    f = tmp_path / "new.grafli"
    text = '#!grafli v99\n@ box a "A" 0,0 160x80\n@ box b "B" 0,0 160x80\n'
    f.write_text(text, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 2
    assert "v99" in capsys.readouterr().err
    assert f.read_text(encoding="utf-8") == text


def test_grafli_layout_dispatches(board: Path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["grafli", "layout", "--check", str(board)])
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1


def test_layout_leaves_room_for_an_arrow_label_between_layers(tmp_path: Path):
    """#260: a label between two layers lands in the gap, not on a box."""
    from grafli.app import _make_arrow_label_size_provider
    f = tmp_path / "labels.grafli"
    f.write_text('#!grafli v4\n'
                 '@ box a "A" 0,0 160x80\n'
                 '@ box b "B" 0,0 160x80\n'
                 '@ arrow a -> b "a rather long relation"\n', encoding="utf-8")
    assert _cmd_layout(["--direction", "ltr", str(f)]) == 0
    rects = _rects(f)
    label_w, _ = _make_arrow_label_size_provider()(parse(f.read_text()).arrows[0])
    gap = rects["b"][0] - (rects["a"][0] + rects["a"][2])
    assert gap >= label_w + 8


# ── Right-angle routing (#284) ─────────────────────────────────────

ROUTING = ('#!grafli v4\n'
           '@ box a "A" 0,0 160x80\n'
           '@ box b "B" 0,0 160x80\n'
           '@ box c "C" 0,0 160x80\n'
           '@ box d "D" 0,0 160x80\n'
           '@ box p "P" 600,600 160x80 !pin\n'
           '@ note n 900,0 "aside"\n'
           '@ arrow a -> b\n'
           '@ arrow a -> d\n'
           '@ arrow a -> c !spline\n'
           '@ arrow b -> c !straight\n'
           '@ arrow c -> p\n'
           '@ arrow a -> n\n'
           '@ arrow a -> a\n')

# The test board: `ui -> db` skips the layer of `api` and the layer of
# `auth` and `jobs`, and `api -> db` skips the second of them.
SKIP = ('#!grafli v4\n'
        '@ box ui "UI" 0,0 160x80\n'
        '@ box api "API" 0,0 160x80\n'
        '@ box auth "Auth" 0,0 160x80\n'
        '@ box jobs "Jobs" 0,0 160x80\n'
        '@ box db "Database" 0,0 160x80\n'
        '@ arrow ui -> api\n'
        '@ arrow api -> auth\n'
        '@ arrow api -> jobs\n'
        '@ arrow auth -> db\n'
        '@ arrow jobs -> db\n'
        '@ arrow ui -> db "reads"\n'
        '@ arrow api -> db\n')


def _view_of(path: Path):
    from PySide6.QtWidgets import QApplication

    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(path.read_text(encoding="utf-8")))
    return view


def _drawn(view, from_id: str, to_id: str):
    """The line items drawn for the arrow *from_id* -> *to_id*."""
    from grafli.items import ArrowLineItem
    return [gfx for gfx in view._arrow_items
            if isinstance(gfx, ArrowLineItem)
            and (gfx.data(0).from_id, gfx.data(0).to_id) == (from_id, to_id)]


def _straight_runs(gfx) -> list[tuple[float, float, float, float]]:
    """The straight runs of a drawn path, as (x0, y0, x1, y1); an eased
    corner between two runs is a curve and not among them."""
    from PySide6.QtGui import QPainterPath
    path = gfx.path()
    runs, prev = [], None
    for i in range(path.elementCount()):
        el = path.elementAt(i)
        if el.type == QPainterPath.ElementType.LineToElement and prev:
            runs.append((*prev, el.x, el.y))
        prev = (el.x, el.y)
    return runs


def test_layout_routes_unflagged_arrows_between_placed_boxes(tmp_path: Path):
    f = tmp_path / "routing.grafli"
    f.write_text(ROUTING, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 0
    routing = {(a.from_id, a.to_id): a.routing
               for a in parse(f.read_text(encoding="utf-8")).arrows}
    assert routing == {
        ("a", "b"): "ortho",       # two placed boxes, no flag
        ("a", "d"): "ortho",
        ("a", "c"): "spline",      # a flag of its own stays
        ("b", "c"): "straight",
        ("c", "p"): "",            # the layout does not place a !pin box
        ("a", "n"): "",            # a note is not a box
        ("a", "a"): "",            # a loop keeps its loop
    }


def test_a_placed_arrow_is_drawn_at_right_angles(tmp_path: Path):
    f = tmp_path / "routing.grafli"
    f.write_text(ROUTING, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 0
    view = _view_of(f)
    for to_id in ("b", "d"):
        (line,) = _drawn(view, "a", to_id)
        runs = _straight_runs(line)
        # `b` and `d` share a layer below `a`, so neither sits straight
        # under it: a direct line would be a slant, the stair turns.
        assert len(runs) == 3, to_id
        for x0, y0, x1, y1 in runs:
            assert abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01


def test_straight_keeps_an_arrow_direct_across_layout_runs(tmp_path: Path):
    f = tmp_path / "routing.grafli"
    f.write_text(ROUTING, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 0
    assert _cmd_layout([str(f)]) == 0
    text = f.read_text(encoding="utf-8")
    assert "@ arrow b -> c !straight\n" in text
    (line,) = _drawn(_view_of(f), "b", "c")
    assert len(_straight_runs(line)) == 1


def test_an_arrow_that_skips_a_layer_crosses_no_box(tmp_path: Path):
    from PySide6.QtCore import QLineF, QPointF, QRectF

    from grafli import arrows

    f = tmp_path / "skip.grafli"
    f.write_text(SKIP, encoding="utf-8")
    assert _cmd_layout(["--direction", "ttb", str(f)]) == 0
    rects = {bid: QRectF(*r) for bid, r in _rects(f).items()}
    # The board does what it is for: one layer per row, and a straight
    # line from `ui` to `db` would run through `api`.
    assert (rects["ui"].top() < rects["api"].top() < rects["auth"].top()
            == rects["jobs"].top() < rects["db"].top())
    ray = QLineF(rects["ui"].center(), rects["db"].center())
    assert arrows._crossed([ray.p1(), ray.p2()], [rects["api"]]) == 1

    view = _view_of(f)
    crossings = {}
    for a in parse(f.read_text(encoding="utf-8")).arrows:
        assert a.routing == "ortho"
        lines = _drawn(view, a.from_id, a.to_id)
        assert lines, (a.from_id, a.to_id)
        others = [r for bid, r in rects.items()
                  if bid not in (a.from_id, a.to_id)]
        hit = sum(arrows._crossed([QPointF(p) for p in poly], others)
                  for gfx in lines
                  for poly in gfx.path().toSubpathPolygons())
        if hit:
            crossings[f"{a.from_id} -> {a.to_id}"] = hit
    assert not crossings


def test_a_routed_board_changes_nothing_on_a_second_run(tmp_path: Path):
    f = tmp_path / "skip.grafli"
    f.write_text(SKIP, encoding="utf-8")
    assert _cmd_layout([str(f)]) == 0
    text = f.read_text(encoding="utf-8")
    assert _cmd_layout(["--check", str(f)]) == 0
    assert f.read_text(encoding="utf-8") == text
