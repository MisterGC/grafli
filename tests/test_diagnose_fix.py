"""`diagnose --fix` (#132): fix plans on diagnostics + the mechanical applier.

Checks that can compute a concrete edit attach a ``fix`` plan
({action, id, old, new}); ``apply_fixes`` applies plans to the Board and
skips stale ones; the CLI rewrites the file (preserving comments) and
gates on what remains.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from grafli.constants import LAYOUT_PADDING
from grafli.diagnostics import (
    apply_fixes,
    check_child_outside_parent,
    check_cramped_container,
    check_label_truncated,
    check_unknown_color,
    check_unknown_icon,
)
from grafli.format import Arrow, Board, Box, parse


def _board(**kw) -> Board:
    return Board(**kw)


# ── fix plans ────────────────────────────────────────────────────────


def test_unknown_color_carries_swap_fix():
    b = _board(boxes=[Box("a", "A", 0, 0, 100, 60, color="%green")])
    (d,) = check_unknown_color(b)
    assert d.fix == {"action": "set-color", "id": "a",
                     "old": "%green", "new": "%forest"}
    assert d.to_dict()["fix"]["new"] == "%forest"


def test_unknown_color_without_suggestion_has_no_fix():
    b = _board(boxes=[Box("a", "A", 0, 0, 100, 60, color="%zzqx")])
    (d,) = check_unknown_color(b)
    assert d.fix is None


def test_unknown_icon_suggests_and_fixes():
    b = _board(boxes=[Box("a", "A", 0, 0, 100, 60, icon="lok")])
    (d,) = check_unknown_icon(b)
    assert "did you mean *lock?" in d.message
    assert d.fix == {"action": "set-icon", "id": "a",
                     "old": "lok", "new": "lock"}


def test_child_outside_parent_clamps_with_padding():
    parent = Box("p", "P", 0, 0, 400, 300)
    child = Box("c", "C", 500, 50, 100, 50, parent="p")
    (d,) = check_child_outside_parent(_board(boxes=[parent, child]))
    assert d.fix["action"] == "move"
    assert d.fix["new"] == {"x": 400 - LAYOUT_PADDING - 100, "y": 50}


def test_child_bigger_than_parent_has_no_fix():
    parent = Box("p", "P", 0, 0, 80, 60)
    child = Box("c", "C", 200, 200, 300, 200, parent="p")
    (d,) = check_child_outside_parent(_board(boxes=[parent, child]))
    assert d.fix is None


def test_cramped_container_grows_but_never_shrinks():
    parent = Box("p", "P", 0, 0, 200, 200)
    child = Box("c", "C", 2, 2, 100, 100, parent="p")
    (d,) = check_cramped_container(_board(boxes=[parent, child]))
    new = d.fix["new"]
    assert d.fix["action"] == "set-rect"
    assert new["x"] == 2 - LAYOUT_PADDING
    assert new["y"] == 2 - LAYOUT_PADDING
    # right/bottom already roomy — the union keeps the old extent
    assert new["x"] + new["w"] == 200
    assert new["y"] + new["h"] == 200


def test_label_truncated_widens_box():
    b = Box("a", "A very long label that cannot fit", 0, 0, 60, 40)
    (d,) = check_label_truncated(_board(boxes=[b]))
    assert d.fix["action"] == "resize"
    assert d.fix["new"]["w"] > 60
    assert d.fix["new"]["h"] == 40


# ── applier ──────────────────────────────────────────────────────────


def test_apply_fixes_mutates_box_and_arrow_colors():
    board = _board(
        boxes=[Box("a", "A", 0, 0, 100, 60, color="%green")],
        arrows=[Arrow("a", "b", color="%blue")],
    )
    applied = apply_fixes(board, check_unknown_color(board))
    assert len(applied) == 2
    assert board.boxes[0].color == "%forest"
    assert board.arrows[0].color == "%primary"


def test_apply_fixes_skips_stale_plan():
    board = _board(boxes=[Box("a", "A", 0, 0, 100, 60, color="%green")])
    diags = check_unknown_color(board)
    board.boxes[0].color = "%teal"  # edited since the plan was computed
    assert apply_fixes(board, diags) == []
    assert board.boxes[0].color == "%teal"


# ── CLI ──────────────────────────────────────────────────────────────

FIXABLE = """#!grafli v1
# My board
@ box a "Alpha" 0,0 200x100 %green
@ box b "Beta" 300,0 200x100
@ arrow a -> b
"""


def test_cli_fix_rewrites_file_and_clears_the_warning(tmp_path):
    from grafli.app import _cmd_diagnose
    p = tmp_path / "board.grafli"
    p.write_text(FIXABLE, encoding="utf-8")
    assert _cmd_diagnose([str(p), "--strict"]) == 1
    assert _cmd_diagnose([str(p), "--fix", "--strict"]) == 0
    text = p.read_text(encoding="utf-8")
    assert "%forest" in text and "%green" not in text
    assert "# My board" in text  # comments survive the rewrite
    board = parse(text)
    assert not board.parse_warnings


def test_cli_dry_run_does_not_write(tmp_path):
    from grafli.app import _cmd_diagnose
    p = tmp_path / "board.grafli"
    p.write_text(FIXABLE, encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert _cmd_diagnose([str(p), "--fix", "--dry-run"]) == 0  # warning-only
    assert p.read_text(encoding="utf-8") == before
