"""Tests for grafli.diagnostics — static layout checks."""

import os
import tempfile
from pathlib import Path

from grafli.diagnostics import (
    Diagnostic,
    check_child_outside_parent,
    check_cramped_container,
    check_label_truncated,
    check_missing_resource,
    check_sibling_overlap,
    run_all,
)
from grafli.format import Arrow, Board, Box, Image, Note


def _make_board(boxes=(), notes=(), arrows=(), images=()):
    return Board(
        boxes=list(boxes),
        notes=list(notes),
        arrows=list(arrows),
        images=list(images),
    )


# ── child-outside-parent ───────────────────────────────────────

def test_child_inside_parent_is_clean():
    parent = Box(id="p", label="P", x=0, y=0, w=400, h=400)
    child = Box(id="c", label="C", x=50, y=50, w=100, h=100, parent="p")
    diags = check_child_outside_parent(_make_board(boxes=[parent, child]))
    assert diags == []


def test_child_outside_parent_flagged():
    parent = Box(id="p", label="P", x=0, y=0, w=200, h=200)
    child = Box(id="c", label="C", x=300, y=300, w=50, h=50, parent="p")
    diags = check_child_outside_parent(_make_board(boxes=[parent, child]))
    codes = [d.code for d in diags]
    assert "child-outside-parent" in codes
    flagged = next(d for d in diags if d.code == "child-outside-parent")
    assert flagged.item_ids == ["c", "p"]


def test_invalid_parent_ref_is_error():
    child = Box(id="c", label="C", x=0, y=0, w=10, h=10, parent="ghost")
    diags = check_child_outside_parent(_make_board(boxes=[child]))
    assert len(diags) == 1
    assert diags[0].code == "invalid-parent-ref"
    assert diags[0].severity == "error"


# ── sibling-overlap ────────────────────────────────────────────

def test_non_overlapping_siblings_are_clean():
    a = Box(id="a", label="A", x=0, y=0, w=100, h=100)
    b = Box(id="b", label="B", x=200, y=0, w=100, h=100)
    diags = check_sibling_overlap(_make_board(boxes=[a, b]))
    assert diags == []


def test_overlapping_siblings_flagged():
    a = Box(id="a", label="A", x=0, y=0, w=100, h=100)
    b = Box(id="b", label="B", x=50, y=50, w=100, h=100)
    diags = check_sibling_overlap(_make_board(boxes=[a, b]))
    assert len(diags) == 1
    assert diags[0].code == "sibling-overlap"
    assert set(diags[0].item_ids) == {"a", "b"}


def test_overlap_only_within_same_parent():
    p1 = Box(id="p1", label="P1", x=0, y=0, w=100, h=100)
    p2 = Box(id="p2", label="P2", x=200, y=0, w=100, h=100)
    # Children that would overlap *if* they shared a parent, but don't.
    a = Box(id="a", label="A", x=10, y=10, w=20, h=20, parent="p1")
    b = Box(id="b", label="B", x=210, y=10, w=20, h=20, parent="p2")
    diags = check_sibling_overlap(_make_board(boxes=[p1, p2, a, b]))
    # p1, p2 don't overlap; a/b are in different parents.
    assert diags == []


# ── cramped-container ──────────────────────────────────────────

def test_roomy_container_is_clean():
    parent = Box(id="p", label="P", x=0, y=0, w=400, h=400)
    child = Box(id="c", label="C", x=100, y=100, w=100, h=100, parent="p")
    diags = check_cramped_container(_make_board(boxes=[parent, child]))
    assert diags == []


def test_cramped_container_flagged():
    parent = Box(id="p", label="P", x=0, y=0, w=200, h=200)
    # child sits 5px from each inner edge — well below LAYOUT_PADDING (20)
    child = Box(id="c", label="C", x=5, y=5, w=190, h=190, parent="p")
    diags = check_cramped_container(_make_board(boxes=[parent, child]))
    assert len(diags) == 1
    assert diags[0].code == "cramped-container"
    assert diags[0].item_ids == ["p"]


# ── label-truncated ────────────────────────────────────────────

def test_short_label_is_clean():
    b = Box(id="b", label="OK", x=0, y=0, w=160, h=80)
    diags = check_label_truncated(_make_board(boxes=[b]))
    assert diags == []


def test_long_label_in_narrow_box_flagged():
    long_label = "this is a very long label that will not fit a tiny box"
    b = Box(id="b", label=long_label, x=0, y=0, w=60, h=40)
    diags = check_label_truncated(_make_board(boxes=[b]))
    assert len(diags) == 1
    assert diags[0].code == "label-truncated"
    assert diags[0].item_ids == ["b"]


def test_label_uses_longest_line_for_multiline():
    # Short first line, long second line — should still flag.
    b = Box(id="b", label="ok\n" + "x" * 200, x=0, y=0, w=80, h=80)
    diags = check_label_truncated(_make_board(boxes=[b]))
    assert any(d.code == "label-truncated" for d in diags)


# ── missing-resource ───────────────────────────────────────────

def test_missing_image_path_flagged(tmp_path):
    im = Image(id="i", image_path="nope.png", x=0, y=0, w=10, h=10)
    diags = check_missing_resource(_make_board(images=[im]), tmp_path)
    assert len(diags) == 1
    assert diags[0].code == "missing-resource"
    assert diags[0].fixable is False


def test_existing_image_is_clean(tmp_path):
    (tmp_path / "ok.png").write_bytes(b"\x89PNG fake")
    im = Image(id="i", image_path="ok.png", x=0, y=0, w=10, h=10)
    diags = check_missing_resource(_make_board(images=[im]), tmp_path)
    assert diags == []


def test_at_path_ref_flagged_when_missing(tmp_path):
    n = Note(id="n", x=0, y=0, text="see @docs/missing.md:42 for details")
    diags = check_missing_resource(_make_board(notes=[n]), tmp_path)
    assert any(d.code == "missing-resource" and "n" in d.item_ids for d in diags)


def test_at_path_ref_clean_when_exists(tmp_path):
    target = tmp_path / "docs"
    target.mkdir()
    (target / "guide.md").write_text("hello")
    n = Note(id="n", x=0, y=0, text="see @docs/guide.md:42")
    diags = check_missing_resource(_make_board(notes=[n]), tmp_path)
    assert diags == []


def test_resource_check_is_noop_without_base_dir():
    n = Note(id="n", x=0, y=0, text="see @does/not/matter.md")
    assert check_missing_resource(_make_board(notes=[n]), None) == []


# ── run_all ────────────────────────────────────────────────────

def test_run_all_returns_sorted_by_severity(tmp_path):
    # An error (invalid parent) and a warning (overlap) — error first.
    parent = Box(id="p", label="P", x=0, y=0, w=100, h=100)
    a = Box(id="a", label="A", x=0, y=0, w=50, h=50)
    b = Box(id="b", label="B", x=20, y=20, w=50, h=50)
    ghost = Box(id="g", label="G", x=300, y=300, w=10, h=10, parent="ghost")
    diags = run_all(_make_board(boxes=[parent, a, b, ghost]), tmp_path)
    severities = [d.severity for d in diags]
    # First diagnostic should be the error.
    assert severities[0] == "error"
    # Sorted: errors before warnings.
    assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])


def test_diagnostic_to_dict_is_json_safe():
    d = Diagnostic(code="x", severity="info", message="m", item_ids=["a"])
    assert d.to_dict() == {
        "code": "x",
        "severity": "info",
        "message": "m",
        "item_ids": ["a"],
        "fixable": True,
    }


# ── Qt-backed: note rect provider ──────────────────────────────

def _qt_note_rect_provider():
    """Real provider using NoteItem — matches CLI behavior."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from grafli.app import _register_bundled_fonts
    from grafli.items import NoteItem
    _register_bundled_fonts()

    def provider(note):
        item = NoteItem(note)
        br = item.boundingRect()
        return (note.x, note.y, note.x + br.width(), note.y + br.height())

    return provider


def test_note_overlap_with_box_detected_via_provider():
    # Note placed on top of a box. Without a provider, overlap is
    # invisible to the checker; with the provider, it's flagged.
    box = Box(id="b", label="B", x=0, y=0, w=200, h=200)
    note = Note(id="n", x=50, y=50, text="T: a sticky on the box")
    board = _make_board(boxes=[box], notes=[note])

    # Without provider — note is skipped.
    assert check_sibling_overlap(board) == []

    # With provider — note rect is real, overlap surfaces.
    diags = check_sibling_overlap(board, note_rect=_qt_note_rect_provider())
    assert any(
        d.code == "sibling-overlap" and set(d.item_ids) == {"b", "n"}
        for d in diags
    )


def test_note_outside_parent_detected_via_provider():
    parent = Box(id="p", label="P", x=0, y=0, w=100, h=100)
    # Note positioned at (500, 500) — clearly outside the parent box.
    note = Note(id="n", x=500, y=500, text="far away", parent="p")
    board = _make_board(boxes=[parent], notes=[note])

    # Without provider — invisible.
    assert check_child_outside_parent(board) == []

    # With provider — flagged.
    diags = check_child_outside_parent(
        board, note_rect=_qt_note_rect_provider()
    )
    assert any(d.code == "child-outside-parent" and "n" in d.item_ids for d in diags)
