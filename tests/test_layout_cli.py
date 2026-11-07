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
    "data": (40, 940, 1100, 320),
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
