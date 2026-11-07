"""The encoding catalogue's worked examples on grafli's own subject (#261):
examples/layers-map.grafli (layered dependencies), outputs-matrix.grafli
(matrix on two axes) and save-reload-mirror.grafli (mirror). Each opens with
its one-line claim, passes `diagnose --strict` and `fmt --check`, and its
render has no arrow through a box and no two arrows crossing."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QLineF, QPointF, QRectF
from PySide6.QtWidgets import QApplication

from grafli.app import _cmd_diagnose, _cmd_fmt
from grafli.format import parse
from grafli.items import ArrowLineItem, BoxItem

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
BOARDS = (
    EXAMPLES / "layers-map.grafli",
    EXAMPLES / "outputs-matrix.grafli",
    EXAMPLES / "save-reload-mirror.grafli",
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _segments(item: ArrowLineItem) -> list[QLineF]:
    """The straight pieces of one drawn connector piece, in scene space."""
    to_scene = item.sceneTransform()
    out = []
    for poly in item.path().toSubpathPolygons():
        pts = [to_scene.map(poly.at(i)) for i in range(poly.size())]
        out += [QLineF(a, b) for a, b in zip(pts, pts[1:]) if a != b]
    return out


def _hits_rect(seg: QLineF, rect: QRectF) -> bool:
    if rect.contains(seg.p1()) or rect.contains(seg.p2()):
        return True
    corners = [rect.topLeft(), rect.topRight(), rect.bottomRight(),
               rect.bottomLeft()]
    return any(
        seg.intersects(QLineF(a, b))[0] == QLineF.IntersectionType.BoundedIntersection
        for a, b in zip(corners, corners[1:] + corners[:1]))


def _crosses(a: QLineF, b: QLineF) -> bool:
    kind, at = a.intersects(b)
    if kind != QLineF.IntersectionType.BoundedIntersection:
        return False
    # Touching at a shared end point is not a crossing.
    ends = (a.p1(), a.p2(), b.p1(), b.p2())
    return all(QLineF(at, e).length() > 1.0 for e in ends)


def arrow_trouble(path: Path) -> list[str]:
    """Each arrow that runs through a box other than its own ends (or the
    containers they sit in), and each pair of arrows with no end in common
    that cross, as drawn by the canvas at 100 %."""
    from grafli.view import GrafliView
    _app()
    board = parse(path.read_text(encoding="utf-8"))
    view = GrafliView()
    view.base_dir = str(path.parent)
    view.render_headless(path)
    view.load_board(board)
    items = view._scene.items()
    parents = {el.id: el.parent for el in (*board.boxes, *board.notes)}

    def with_ancestors(el_id: str) -> set[str]:
        out = set()
        while el_id and el_id not in out:
            out.add(el_id)
            el_id = parents.get(el_id, "")
        return out

    rects = {it.box.id: it.sceneBoundingRect().adjusted(4, 4, -4, -4)
             for it in items if isinstance(it, BoxItem)}
    arrows: dict[int, tuple[object, list[QLineF]]] = {}
    for it in items:
        if isinstance(it, ArrowLineItem) and it.isVisible():
            arrow = it.data(0)
            arrows.setdefault(id(arrow), (arrow, []))[1].extend(_segments(it))

    def name(a) -> str:
        return f"{a.from_id} -> {a.to_id}"

    trouble = []
    for arrow, segs in arrows.values():
        # An arrow may cross its own ends and the containers they sit in;
        # every other box, a container included, is in its way.
        ends = with_ancestors(arrow.from_id) | with_ancestors(arrow.to_id)
        for box_id, rect in rects.items():
            if box_id not in ends and any(_hits_rect(s, rect) for s in segs):
                trouble.append(f"{name(arrow)} runs through {box_id}")
    pairs = list(arrows.values())
    for i, (a, a_segs) in enumerate(pairs):
        for b, b_segs in pairs[i + 1:]:
            if {a.from_id, a.to_id} & {b.from_id, b.to_id}:
                continue
            if any(_crosses(s, t) for s in a_segs for t in b_segs):
                trouble.append(f"{name(a)} crosses {name(b)}")
    return trouble


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_the_board_opens_with_its_one_line_claim(path: Path):
    board = parse(path.read_text(encoding="utf-8"))
    claim = board.notes[0]
    assert claim.id == "claim", path.name
    assert "\n" not in claim.text and claim.text.strip()
    top = min(el.y for el in (*board.boxes, *board.notes))
    assert claim.y == top, (path.name, claim.y, top)


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_the_board_passes_diagnose_strict_and_fmt(path: Path):
    _app()
    assert _cmd_diagnose(["--strict", str(path)]) == 0
    assert _cmd_fmt(["--check", str(path)]) == 0


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_no_arrow_runs_through_a_box_or_crosses_another(path: Path):
    assert arrow_trouble(path) == []


def test_the_check_sees_an_arrow_through_a_box_and_a_crossing(tmp_path: Path):
    board = tmp_path / "bad.grafli"
    board.write_text(
        "#!grafli v4\n"
        "@ box a \"a\" 0,0 100x60\n"
        "@ box b \"b\" 300,0 100x60\n"
        "@ box c \"c\" 600,0 100x60\n"
        "@ box d \"d\" 300,-200 100x60\n"
        "@ box e \"e\" 300,200 100x60\n"
        "@ arrow a -> c\n"
        "@ arrow d -> e\n", encoding="utf-8")
    trouble = arrow_trouble(board)
    assert "a -> c runs through b" in trouble
    assert "d -> e runs through b" in trouble
    assert ("a -> c crosses d -> e" in trouble
            or "d -> e crosses a -> c" in trouble)


def test_the_check_sees_an_arrow_through_a_container_that_holds_neither_end(
        tmp_path: Path):
    board = tmp_path / "bands.grafli"
    board.write_text(
        "#!grafli v4\n"
        "@ box top \"top\" 0,0 600x180 ^left\n"
        "@ box a \"a\" 200,60 200x80 >top\n"
        "@ box mid \"mid\" 0,300 600x180 ^left\n"
        "@ box m \"m\" 20,360 120x80 >mid\n"
        "@ box bot \"bot\" 0,600 600x180 ^left\n"
        "@ box b \"b\" 200,660 200x80 >bot\n"
        "@ arrow a -> b\n", encoding="utf-8")
    assert arrow_trouble(board) == ["a -> b runs through mid"]
