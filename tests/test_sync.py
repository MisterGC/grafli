"""Headless tests for the persistence + merge core (grafli/sync.py).

No PySide / GUI — this is the part a hosted server would reuse, so it must
be testable on its own. Covers atomic writes, 3-way doc-body text merge,
and the id-keyed field-level board merge (including the AI-writes-while-
human-drags race that motivated the work).
"""

from __future__ import annotations

import os
import threading

from grafli.format import parse, serialize
from grafli.sync import (
    Conflict,
    atomic_write,
    merge3_text,
    merge_boards,
)


def _board(src: str):
    return parse("#!grafli v1\n" + src)


# ── atomic_write ────────────────────────────────────────────────

def test_atomic_write_roundtrips(tmp_path):
    p = tmp_path / "a.grafli"
    atomic_write(p, "hello\nworld\n")
    assert p.read_text() == "hello\nworld\n"


def test_atomic_write_overwrites_and_leaves_no_temp(tmp_path):
    p = tmp_path / "a.grafli"
    atomic_write(p, "one")
    atomic_write(p, "two")
    assert p.read_text() == "two"
    # No stray .tmp siblings left behind.
    assert [f.name for f in tmp_path.iterdir()] == ["a.grafli"]


def test_atomic_write_never_observed_partial(tmp_path):
    """A concurrent reader always sees a complete version, never a
    half-written file — the whole point of the temp+replace dance."""
    p = tmp_path / "a.grafli"
    atomic_write(p, "x" * 10000)
    full = {"x" * 10000, "y" * 10000}
    seen = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                seen.append(p.read_text())
            except OSError:
                pass

    t = threading.Thread(target=reader)
    t.start()
    for i in range(200):
        atomic_write(p, ("x" if i % 2 else "y") * 10000)
    stop.set()
    t.join()
    assert all(s in full for s in seen)


# ── merge3_text (doc bodies) ────────────────────────────────────

def test_text_merge_local_unchanged_takes_remote():
    base = "a\nb\nc"
    assert merge3_text(base, base, "a\nB\nc") == ("a\nB\nc", False)


def test_text_merge_remote_unchanged_takes_local():
    base = "a\nb\nc"
    assert merge3_text(base, "a\nB\nc", base) == ("a\nB\nc", False)


def test_text_merge_same_edit_both_sides():
    base = "a\nb\nc"
    assert merge3_text(base, "a\nX\nc", "a\nX\nc") == ("a\nX\nc", False)


def test_text_merge_disjoint_edits_combine_cleanly():
    # Different paragraphs, an unchanged line between them as an anchor.
    base = "intro\n\npoint one\n\npoint two\n\nend"
    local = "intro\n\npoint one EDITED\n\npoint two\n\nend"
    remote = "intro\n\npoint one\n\npoint two EDITED\n\nend"
    merged, conflict = merge3_text(base, local, remote)
    assert not conflict
    assert "point one EDITED" in merged
    assert "point two EDITED" in merged


def test_text_merge_overlapping_edits_conflict_not_lost():
    base = "a\nb\nc"
    local = "a\nLOCAL\nc"
    remote = "a\nREMOTE\nc"
    merged, conflict = merge3_text(base, local, remote)
    assert conflict
    # Neither side's content is silently dropped.
    assert "LOCAL" in merged and "REMOTE" in merged


def test_text_merge_pure_append_each_side():
    base = "line1\n"
    local = "line1\nlocal-add\n"
    remote = "line1\nremote-add\n"
    merged, conflict = merge3_text(base, local, remote)
    # Both appends land (separated by the trailing-newline anchor) or, in
    # the worst case, conflict — but never lose one.
    assert "local-add" in merged and "remote-add" in merged


# ── merge_boards ────────────────────────────────────────────────

def test_board_merge_drag_vs_content_edit_both_survive():
    # The motivating race: human dragged a box in-app (local), AI edited a
    # different box's label on disk (remote). Both must survive.
    base = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    local = _board('@ box a "A" 50,50 100x100\n@ box b "B" 200,0 100x100\n')   # a dragged
    remote = _board('@ box a "A" 0,0 100x100\n@ box b "Renamed" 200,0 100x100\n')  # b relabelled
    merged, conflicts = merge_boards(base, local, remote)
    assert not conflicts
    assert merged.box_by_id("a").x == 50 and merged.box_by_id("a").y == 50
    assert merged.box_by_id("b").label == "Renamed"


def test_board_merge_local_add_carried_in():
    base = _board('@ box a "A" 0,0 100x100\n')
    local = _board('@ box a "A" 0,0 100x100\n@ box new "New" 300,0 100x100\n')
    remote = _board('@ box a "Edited" 0,0 100x100\n')
    merged, conflicts = merge_boards(base, local, remote)
    assert not conflicts
    assert merged.box_by_id("new") is not None
    assert merged.box_by_id("a").label == "Edited"
    # Serializes to a valid board (no markers) with the added box present.
    assert "New" in serialize(merged)


def test_board_merge_remote_add_kept():
    base = _board('@ box a "A" 0,0 100x100\n')
    local = _board('@ box a "A" 0,0 100x100\n')
    remote = _board('@ box a "A" 0,0 100x100\n@ box r "Remote" 300,0 100x100\n')
    merged, conflicts = merge_boards(base, local, remote)
    assert not conflicts
    assert merged.box_by_id("r") is not None


def test_board_merge_honours_clean_delete():
    base = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    local = _board('@ box a "A" 0,0 100x100\n')  # b deleted locally
    remote = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')  # untouched
    merged, conflicts = merge_boards(base, local, remote)
    assert not conflicts
    assert merged.box_by_id("b") is None
    # The deleted element is gone from the line order too, so it won't reappear on serialize.
    assert "@ box b " not in serialize(merged)


def test_board_merge_modify_delete_conflict_keeps_modification():
    base = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    local = _board('@ box a "A" 0,0 100x100\n')  # b deleted locally
    remote = _board('@ box a "A" 0,0 100x100\n@ box b "B EDITED" 200,0 100x100\n')  # b modified remotely
    merged, conflicts = merge_boards(base, local, remote)
    assert any(c.detail == "modify/delete" for c in conflicts)
    # Modification wins over the delete — the edit is not lost.
    assert merged.box_by_id("b") is not None
    assert merged.box_by_id("b").label == "B EDITED"


def test_board_merge_true_field_conflict_prefers_remote_and_reports():
    base = _board('@ box a "Base" 0,0 100x100\n')
    local = _board('@ box a "Local" 0,0 100x100\n')
    remote = _board('@ box a "Remote" 0,0 100x100\n')
    merged, conflicts = merge_boards(base, local, remote, prefer="remote")
    assert merged.box_by_id("a").label == "Remote"
    assert conflicts == [Conflict("box", "a", "label")]


def test_board_merge_arrows_keyed_by_endpoints():
    base = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    local = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n@ arrow a -> b "call"\n')
    remote = _board('@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    merged, conflicts = merge_boards(base, local, remote)
    assert not conflicts
    assert any(ar.from_id == "a" and ar.to_id == "b" for ar in merged.arrows)


def test_board_merge_result_serializes_and_reparses():
    base = _board('@ box a "A" 0,0 100x100\n')
    local = _board('@ box a "A" 50,0 100x100\n@ note n1 0,200 "hi"\n')
    remote = _board('@ box a "A" 0,0 100x100\n@ box c "C" 300,0 100x100\n')
    merged, _ = merge_boards(base, local, remote)
    reparsed = parse(serialize(merged))
    ids = {b.id for b in reparsed.boxes}
    assert ids == {"a", "c"}
    assert reparsed.box_by_id("a").x == 50
    assert reparsed.note_by_id("n1") is not None
