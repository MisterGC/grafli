"""Tests for grafli.diagnostics — static layout checks."""

import os
import tempfile
from pathlib import Path

from grafli.diagnostics import (
    Diagnostic,
    check_arrow_label_covers_head,
    check_arrow_label_crowded,
    check_child_outside_parent,
    check_cramped_container,
    check_label_truncated,
    check_missing_resource,
    check_sibling_overlap,
    check_unknown_color,
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


# ── arrow label crowding ───────────────────────────────────────

def _fixed_size(w: float, h: float):
    """Stub size provider — returns the same (w, h) for any arrow."""
    return lambda _arrow: (w, h)


def test_arrow_label_crowded_with_adjacent_boxes():
    """The Stage1→Stage2 case: 20px gap, label wider than gap."""
    a = Box(id="a", label="A", x=0, y=0, w=160, h=80)
    b = Box(id="b", label="B", x=180, y=0, w=160, h=80)  # 20px gap
    arr = Arrow(from_id="a", to_id="b", label="in")
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_crowded(board, arrow_label_size=_fixed_size(30, 12))
    assert len(diags) == 1
    assert diags[0].code == "arrow-label-crowded"
    assert set(diags[0].item_ids) == {"a", "b"}


def test_arrow_label_clean_with_wide_gap():
    a = Box(id="a", label="A", x=0, y=0, w=100, h=80)
    b = Box(id="b", label="B", x=400, y=0, w=100, h=80)  # 300px gap
    arr = Arrow(from_id="a", to_id="b", label="in")
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_crowded(board, arrow_label_size=_fixed_size(30, 12))
    assert diags == []


def test_arrow_label_checks_skipped_without_provider():
    a = Box(id="a", label="A", x=0, y=0, w=160, h=80)
    b = Box(id="b", label="B", x=180, y=0, w=160, h=80)
    arr = Arrow(from_id="a", to_id="b", label="in")
    board = _make_board(boxes=[a, b], arrows=[arr])
    assert check_arrow_label_crowded(board) == []
    assert check_arrow_label_covers_head(board) == []


def test_arrow_label_unlabeled_arrows_skipped():
    a = Box(id="a", label="A", x=0, y=0, w=160, h=80)
    b = Box(id="b", label="B", x=180, y=0, w=160, h=80)
    arr = Arrow(from_id="a", to_id="b", label="")
    board = _make_board(boxes=[a, b], arrows=[arr])
    assert check_arrow_label_crowded(board, arrow_label_size=_fixed_size(30, 12)) == []


def test_arrow_label_offset_via_dx_dy_clears_overlap():
    """Author used @dx,dy to push the label off the line — no warning."""
    a = Box(id="a", label="A", x=0, y=0, w=160, h=80)
    b = Box(id="b", label="B", x=180, y=0, w=160, h=80)
    arr = Arrow(from_id="a", to_id="b", label="in", label_dy=-100)
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_crowded(board, arrow_label_size=_fixed_size(30, 12))
    assert diags == []


def test_arrow_label_covers_head_long_label_short_arrow():
    """Label wider than the visible segment but doesn't overlap endpoints
    (e.g. offset above) — still flags the lost arrowhead."""
    a = Box(id="a", label="A", x=0, y=0, w=80, h=80)
    b = Box(id="b", label="B", x=120, y=0, w=80, h=80)  # 40px gap
    # Label offset above, so it doesn't overlap endpoints; but its width
    # still exceeds the visible 40px segment.
    arr = Arrow(from_id="a", to_id="b", label="long", label_dy=-80)
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_covers_head(
        board, arrow_label_size=_fixed_size(60, 12),
    )
    assert len(diags) == 1
    assert diags[0].code == "arrow-label-covers-head"


def test_arrow_label_covers_head_skipped_when_no_head():
    """No arrowhead → no direction to obscure."""
    a = Box(id="a", label="A", x=0, y=0, w=80, h=80)
    b = Box(id="b", label="B", x=120, y=0, w=80, h=80)
    arr = Arrow(
        from_id="a", to_id="b", label="long",
        head_to=False, head_from=False,
    )
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_covers_head(
        board, arrow_label_size=_fixed_size(60, 12),
    )
    assert diags == []


def test_qt_arrow_label_provider_catches_test_grafli_pipeline_case():
    """End-to-end: replicate the user's 160px Stage1/2 with 20px gap and
    a real Qt-measured 'in' label — must surface arrow-label-crowded."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from grafli.app import (
        _register_bundled_fonts, _make_arrow_label_size_provider,
    )
    _register_bundled_fonts()

    a = Box(id="s1", label="Stage 1", x=-720, y=290, w=160, h=80)
    b = Box(id="s2", label="Stage 2", x=-540, y=290, w=160, h=80)
    arr = Arrow(from_id="s1", to_id="s2", label="in")
    board = _make_board(boxes=[a, b], arrows=[arr])
    diags = check_arrow_label_crowded(
        board, arrow_label_size=_make_arrow_label_size_provider(),
    )
    assert any(d.code == "arrow-label-crowded" for d in diags)


# ── parse-error surfacing (run_all includes dropped lines) ─────────


def test_parse_errors_reported_by_run_all():
    from grafli.diagnostics import check_parse_errors, run_all
    from grafli.format import parse

    text = (
        '@ box ok "Fine" 0,0 200x100\n'
        '@ box bad "Broken" 0,200 200x100 *lead:gear !bold\n'
    )
    board = parse(text)
    diags = check_parse_errors(board)
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "parse-error"
    assert d.severity == "error"
    assert "line 2" in d.message
    # run_all sorts errors first, so the dropped line leads the report.
    all_diags = run_all(board)
    assert all_diags and all_diags[0].code == "parse-error"


def test_parse_errors_flag_unterminated_block():
    from grafli.diagnostics import check_parse_errors
    from grafli.format import parse

    board = parse('@ note nb 0,0 """\ncode:\nnever closed\n')
    diags = check_parse_errors(board)
    assert any("line 1" in d.message for d in diags)


def test_clean_board_has_no_parse_errors():
    from grafli.diagnostics import check_parse_errors
    from grafli.format import parse

    board = parse('@ box a "A" 0,0 200x100\n@ arrow a -> a\n')
    assert check_parse_errors(board) == []


# ── unknown-color ──────────────────────────────────────────────

def test_unknown_color_flagged_with_suggestion():
    box = Box(id="b", label="B", x=0, y=0, w=100, h=100, color="%green")
    diags = check_unknown_color(_make_board(boxes=[box]))
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "unknown-color"
    assert d.severity == "warning"
    assert d.item_ids == ["b"]
    # %green is closest to %forest — the suggestion should surface it.
    assert "%forest" in d.message


def test_known_color_and_hex_are_clean():
    box = Box(id="b", label="B", x=0, y=0, w=100, h=100, color="%forest")
    note = Note(id="n", x=0, y=0, text="N", color="#A1B2C3")
    plain = Box(id="p", label="P", x=0, y=0, w=100, h=100)
    diags = check_unknown_color(_make_board(boxes=[box, plain], notes=[note]))
    assert diags == []


def test_unknown_color_on_note_and_arrow():
    note = Note(id="n", x=0, y=0, text="N", color="%blue")
    arrow = Arrow(from_id="a", to_id="b", color="%blue")
    diags = check_unknown_color(_make_board(notes=[note], arrows=[arrow]))
    codes = [d.code for d in diags]
    assert codes == ["unknown-color", "unknown-color"]
    ids = [d.item_ids[0] for d in diags]
    assert "n" in ids and "a->b" in ids


def test_unknown_color_reported_by_run_all():
    from grafli.format import parse

    board = parse('@ box b "B" 0,0 200x100 %green\n')
    codes = [d.code for d in run_all(board)]
    assert "unknown-color" in codes
