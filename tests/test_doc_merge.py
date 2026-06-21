"""Concurrency tests for vault doc bodies (resources.load_docs / save_docs):
atomic writes, the skip-unchanged guard, and the 3-way merge that lets a
zen-editor edit and an external (AI) .md edit survive together.
"""

from __future__ import annotations

from grafli.format import Note, Board
from grafli.resources import load_docs, save_docs, doc_path, ensure_res_dir


def _doc_note(note_id: str, name: str = "") -> Note:
    n = Note(id=note_id, x=0, y=0, text="")
    n.attach_kind = "doc"
    n.url = name   # bare &doc names after the note id when url is empty
    return n


def _board_with_doc(note_id="d1", name=""):
    b = Board()
    b.notes.append(_doc_note(note_id, name))
    return b


def test_load_then_save_roundtrips(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    doc_path(gp, "d1").write_text("hello\nworld\n")
    board = _board_with_doc("d1")
    load_docs(gp, board)
    assert board.notes[0].text == "hello\nworld\n"


def test_save_is_atomic_and_skips_unchanged(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    doc_path(gp, "d1").write_text("body\n")
    board = _board_with_doc("d1")
    load_docs(gp, board)
    # Unchanged body → no write, and no stray temp files in the vault.
    written = save_docs(gp, board)
    assert written == []
    res_files = [f.name for f in (tmp_path / "b-res").iterdir()]
    assert res_files == ["d1.md"]


def test_external_md_edit_with_no_local_edit_reloads(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    doc_path(gp, "d1").write_text("v1\n")
    board = _board_with_doc("d1")
    load_docs(gp, board)                       # base = "v1\n"
    doc_path(gp, "d1").write_text("v2\n")      # external (AI) edit
    load_docs(gp, board)                       # reload
    assert board.notes[0].text == "v2\n"


def test_concurrent_zen_edit_and_md_edit_both_survive_on_reload(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    base = "# Title\n\npara one\n\npara two\n"
    doc_path(gp, "d1").write_text(base)
    board = _board_with_doc("d1")
    load_docs(gp, board)                       # base recorded
    # Human edits paragraph one in the zen editor (in-memory only).
    board.notes[0].text = "# Title\n\npara one EDITED\n\npara two\n"
    # AI edits paragraph two directly in the .md.
    doc_path(gp, "d1").write_text("# Title\n\npara one\n\npara two EDITED\n")
    load_docs(gp, board)                       # reload merges both
    assert "para one EDITED" in board.notes[0].text
    assert "para two EDITED" in board.notes[0].text


def test_save_does_not_clobber_external_md_edit(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    base = "alpha\n\nbeta\n"
    doc_path(gp, "d1").write_text(base)
    board = _board_with_doc("d1")
    load_docs(gp, board)                       # base recorded
    # Human edits alpha in-memory; AI edits beta on disk; then app autosaves.
    board.notes[0].text = "alpha EDITED\n\nbeta\n"
    doc_path(gp, "d1").write_text("alpha\n\nbeta EDITED\n")
    save_docs(gp, board)                       # must merge, not clobber
    final = doc_path(gp, "d1").read_text()
    assert "alpha EDITED" in final and "beta EDITED" in final


def test_transclusion_siblings_still_reconcile(tmp_path):
    gp = tmp_path / "b.grafli"
    ensure_res_dir(gp)
    doc_path(gp, "shared").write_text("orig\n")
    board = Board()
    board.notes.append(_doc_note("a", "shared"))
    board.notes.append(_doc_note("b", "shared"))
    load_docs(gp, board)
    board.notes[0].text = "edited\n"           # one sibling edited
    save_docs(gp, board)
    assert doc_path(gp, "shared").read_text() == "edited\n"
    assert board.notes[1].text == "edited\n"   # other synced to it
