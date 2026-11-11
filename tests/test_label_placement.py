"""#303: an arrow label goes into free space along its arrow — never on a
box, never on another label."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from grafli.arrows import LABEL_PAD, label_ground, label_plate, place_label
from grafli.format import parse
from grafli.items import LabelItem


# A fan-out of four labelled arrows from one box, close enough that the
# labels at their middles run into each other, and two labelled arrows that
# cross on a box in the middle — both labels centred on it, on each other.
BOARD = """#!grafli v1
@ box hub "Dispatcher" 230,0 160x60
@ box w1 "Parser" 0,150 120x60
@ box w2 "Validator" 165,150 120x60
@ box w3 "Planner" 330,150 120x60
@ box w4 "Emitter" 495,150 120x60
@ arrow hub -> w1 "tokens"
@ arrow hub -> w2 "schema check"
@ arrow hub -> w3 "plan request"
@ arrow hub -> w4 "output stream"
@ box a "Client" 0,300 120x60
@ box b "Cache" 495,300 120x60
@ box c "Store" 0,520 120x60
@ box d "Audit" 495,520 120x60
@ box m "Broker" 247,410 120x60
@ arrow a -> d "writes through"
@ arrow c -> b "reads back"
"""


def _app():
    """The app with grafli's own fonts, as the canvas and `grafli render`
    set labels in them — the placement depends on the labels' widths."""
    from grafli.app import _register_bundled_fonts
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    return app


def _view(text: str = BOARD):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _labels(view) -> dict[str, QRectF]:
    """'from->to' → the plate of the label the canvas drew."""
    out = {}
    for item in view._arrow_items:
        if isinstance(item, LabelItem):
            arrow = item.data(0)
            out[f"{arrow.from_id}->{arrow.to_id}"] = item.sceneBoundingRect(
            ).adjusted(-LABEL_PAD, -LABEL_PAD, LABEL_PAD, LABEL_PAD)
    return out


def _clashes(view) -> list[str]:
    """Every label plate that touches a box or another label's plate."""
    board = view._board
    labels = _labels(view)
    found = []
    arrows = {f"{a.from_id}->{a.to_id}": a for a in board.arrows}
    for key, plate in labels.items():
        a = arrows[key]
        ground = label_ground(board, a.from_id, a.to_id)
        for box in board.boxes:
            if box.id not in ground and plate.intersects(
                    QRectF(box.x, box.y, box.w, box.h)):
                found.append(f"{key} on box {box.id}")
    keys = list(labels)
    for i, k in enumerate(keys):
        for other in keys[i + 1:]:
            if labels[k].intersects(labels[other]):
                found.append(f"{k} on label {other}")
    return found


def _distance_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy)
                     / (dx * dx + dy * dy)))
    return math.hypot(p.x() - a.x() - t * dx, p.y() - a.y() - t * dy)


# ── place_label ────────────────────────────────────────────────────

def _line(x1, y1, x2, y2) -> QPainterPath:
    path = QPainterPath(QPointF(x1, y1))
    path.lineTo(x2, y2)
    return path


def test_a_free_anchor_keeps_the_label():
    anchor = QPointF(100, 0)
    assert place_label(_line(0, 0, 200, 0), 40, 16, anchor, []) == anchor


def test_a_blocked_label_slides_along_its_line():
    blocked = [QRectF(90, -30, 40, 60)]          # a box on the anchor
    centre = place_label(_line(0, 0, 300, 0), 40, 16, QPointF(100, 0), blocked)
    assert centre.y() == 0
    assert not label_plate(centre, 40, 16).intersects(blocked[0])
    # The nearest free spot: the box reaches further right of the anchor
    # than left of it, so the label slides left, just clear of it.
    assert 60 <= centre.x() < 90


def test_a_label_with_no_room_on_its_line_goes_beside_it():
    # Thin bars cover the whole line except gaps too short for the label.
    blocked = [QRectF(0, -2, 95, 4), QRectF(105, -2, 95, 4)]
    centre = place_label(_line(0, 0, 200, 0), 40, 16, QPointF(100, 0), blocked)
    plate = label_plate(centre, 40, 16)
    assert not any(plate.intersects(r) for r in blocked)
    assert centre.y() < 0                         # above, the first side tried
    assert plate.bottom() < 0                     # clear of the line itself


def test_a_label_with_no_room_anywhere_stays_at_its_anchor():
    blocked = [QRectF(-100, -100, 400, 200)]
    anchor = QPointF(100, 0)
    assert place_label(_line(0, 0, 200, 0), 40, 16, anchor, blocked) == anchor


def test_label_ground_is_every_container_around_either_end():
    board = parse("""#!grafli v1
@ box outer "Outer" 0,0 600x400
@ box left "Left" 20,40 200x300 >outer
@ box a "A" 40,80 100x60 >left
@ box b "B" 400,80 100x60 >outer
@ box x "X" 700,0 100x60
""")
    assert label_ground(board, "a", "b") == {"left", "outer"}
    assert label_ground(board, "b", "x") == {"outer"}
    assert label_ground(board, "x", "x") == set()


# ── the board in the app and in grafli render ──────────────────────

def test_the_board_draws_no_label_on_a_box_or_a_label():
    assert _clashes(_view()) == []


def test_the_board_renders_headless_with_no_label_on_a_box_or_a_label(tmp_path):
    from grafli.view import GrafliView
    _app()
    path = tmp_path / "labels.grafli"
    path.write_text(BOARD)
    view = GrafliView()                           # as `grafli render` sets it up
    view.base_dir = str(tmp_path)
    view.render_headless(path)
    view.load_board(parse(BOARD))
    assert _clashes(view) == []


def test_the_render_command_writes_the_board(tmp_path):
    from grafli.app import _cmd_render
    path = tmp_path / "labels.grafli"
    path.write_text(BOARD)
    out = tmp_path / "labels.png"
    assert _cmd_render([str(path), str(out)]) == 0
    assert out.stat().st_size > 0


def test_the_placement_on_the_board():
    """Labels with room stay at their middle; the ones that had none move
    along their own arrow to the nearest free spot."""
    view = _view()
    labels = _labels(view)
    boxes = {b.id: QRectF(b.x, b.y, b.w, b.h) for b in view._board.boxes}
    for arrow in view._board.arrows:
        key = f"{arrow.from_id}->{arrow.to_id}"
        start, end, _path = view._arrow_label_geometry[id(arrow)]
        centre = labels[key].center()
        middle = (start + end) / 2
        on_line = _distance_to_segment(centre, start, end)
        if key in ("hub->w1", "hub->w2", "hub->w3"):
            assert (centre - middle).manhattanLength() < 0.5, key
        else:
            assert (centre - middle).manhattanLength() > 5, key
            assert on_line < 1, (key, on_line)    # still on its own arrow
    # The fan's last label slid down its arrow, past the one beside it.
    assert labels["hub->w4"].center().y() > labels["hub->w3"].center().y()
    # The crossing pair parted, each along its own arrow past the Broker
    # toward its target: Client -> Audit below it, Store -> Cache above.
    broker = boxes["m"]
    assert labels["a->d"].top() >= broker.bottom()
    assert labels["c->b"].bottom() <= broker.top()


def test_the_board_has_nothing_to_report_about_label_overlaps(tmp_path, capsys):
    from grafli.app import _cmd_diagnose
    path = tmp_path / "labels.grafli"
    path.write_text(BOARD)
    assert _cmd_diagnose([str(path), "--json"]) == 0
    codes = {d["code"] for d in json.loads(capsys.readouterr().out)}
    assert not codes & {"arrow-label-crowded", "arrow-labels-overlap",
                        "arrow-label-covers-head"}, codes


def test_the_board_before_its_labels_move_is_reported(tmp_path, capsys):
    """Pinned to the middle by an offset, the same labels are reported —
    on the Broker and on each other — so the clean run above means
    something."""
    from grafli.app import _cmd_diagnose
    pinned = (BOARD.replace('"writes through"', '"writes through" @0,1')
              .replace('"reads back"', '"reads back" @0,1'))
    path = tmp_path / "labels.grafli"
    path.write_text(pinned)
    assert _cmd_diagnose([str(path), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    crowded = [d for d in found if d["code"] == "arrow-label-crowded"]
    assert {tuple(d["item_ids"]) for d in crowded} == {("a", "d", "m"),
                                                       ("c", "b", "m")}
    assert [d["item_ids"] for d in found
            if d["code"] == "arrow-labels-overlap"] == [["a", "d", "c", "b"]]


# ── what an author placed ──────────────────────────────────────────

def test_an_offset_label_stays_where_its_author_put_it():
    view = _view(BOARD.replace('"reads back"', '"reads back" @0,1'))
    arrow = next(a for a in view._board.arrows if a.to_id == "b")
    start, end, _path = view._arrow_label_geometry[id(arrow)]
    centre = _labels(view)["c->b"].center()
    assert (centre - ((start + end) / 2 + QPointF(0, 1))).manhattanLength() < 0.5


def test_a_label_without_an_offset_keeps_off_an_offset_one():
    """The authored label is placed first, so the other moves, not it."""
    view = _view(BOARD.replace('"reads back"', '"reads back" @0,-60'))
    labels = _labels(view)
    assert not labels["a->d"].intersects(labels["c->b"])


# ── editing a moved label ──────────────────────────────────────────

def test_the_editor_and_a_drag_start_where_a_moved_label_is():
    view = _view()
    arrow = next(a for a in view._board.arrows if a.from_id == "a")
    centre = _labels(view)["a->d"].center()
    assert (view._arrow_label_midpoint(arrow) - centre).manhattanLength() < 0.5
    dx, dy = view._label_drag_offset(arrow)
    start, end, _path = view._arrow_label_geometry[id(arrow)]
    assert ((start + end) / 2 + QPointF(dx, dy) - centre).manhattanLength() < 0.5


def test_a_drag_of_an_offset_label_starts_from_its_offset():
    view = _view(BOARD.replace('"reads back"', '"reads back" @3,4'))
    arrow = next(a for a in view._board.arrows if a.to_id == "b")
    assert view._label_drag_offset(arrow) == (3.0, 4.0)
