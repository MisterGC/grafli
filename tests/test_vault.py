"""Tests for typed vault attachments (&doc / &graph / &link) — issue #95.

Covers the format layer (parse/serialize of typed kinds, doc-bodied notes,
undo-snapshot embedding), the vault layer (classification of legacy &url,
doc load/save, md: externalization, inventory), and the markdown typing of
doc-bodied notes.
"""

from __future__ import annotations

from grafli.format import Board, Note, doc_name, parse, serialize, split_attach
from grafli.md_note import note_is_md, note_md_body
from grafli.resources import (
    classify_attachments,
    externalize_md_notes,
    load_docs,
    save_docs,
    vault_docs,
)


# ── split_attach / parse of typed kinds ─────────────────────────


def test_split_attach_forms():
    assert split_attach("link:https://x.io/a?b=1") == ("link", "https://x.io/a?b=1")
    assert split_attach("doc:notes") == ("doc", "notes")
    assert split_attach("graph:auth") == ("graph", "auth")
    assert split_attach("doc") == ("doc", "")
    assert split_attach("res/legacy.md") == ("", "res/legacy.md")


def test_parse_typed_attachments_on_all_elements():
    text = (
        "#!grafli v1\n"
        '@ box a "A" 0,0 100x50 &doc:design\n'
        '@ box b "B" 200,0 100x50 &graph:sub\n'
        '@ arrow a -> b "uses" &link:https://example.com\n'
        '@ image img1 "demo-res/p.png" 0,100 80x60 &doc:shot\n'
        '@ note n1 0,200 "hi" &link:https://example.com\n'
    )
    b = parse(text)
    assert (b.boxes[0].attach_kind, b.boxes[0].url) == ("doc", "design")
    assert (b.boxes[1].attach_kind, b.boxes[1].url) == ("graph", "sub")
    assert (b.arrows[0].attach_kind, b.arrows[0].url) == (
        "link", "https://example.com")
    assert (b.images[0].attach_kind, b.images[0].url) == ("doc", "shot")
    assert (b.notes[0].attach_kind, b.notes[0].url) == (
        "link", "https://example.com")
    assert serialize(b) == text


def test_doc_bodied_note_line_has_no_text_slot():
    b = parse('@ note arch 600,0 ~width=40 &doc >box3\n')
    n = b.notes[0]
    assert n.attach_kind == "doc" and n.url == "" and n.text == ""
    assert doc_name(n) == "arch"
    out = serialize(b)
    assert "@ note arch 600,0 ~width=40 &doc >box3" in out
    # The in-memory body never leaks into the normal serialization.
    n.text = "# Loaded body"
    assert "Loaded body" not in serialize(b)


def test_undo_snapshot_embeds_doc_bodies():
    b = parse("@ note arch 600,0 &doc\n")
    b.notes[0].text = "# Plan\n\n- step"
    snap = serialize(b, embed_doc_bodies=True)
    restored = parse(snap)
    n = restored.notes[0]
    assert n.attach_kind == "doc"
    assert n.text == "# Plan\n\n- step"


def test_named_doc_keeps_explicit_name():
    b = parse("@ note a 0,0 &doc:shared\n@ note b 100,0 &doc:shared\n")
    assert [doc_name(n) for n in b.notes] == ["shared", "shared"]
    out = serialize(b)
    assert out.count("&doc:shared") == 2


# ── legacy classification ───────────────────────────────────────


def _board_path(tmp_path):
    p = tmp_path / "demo.grafli"
    (tmp_path / "demo-res").mkdir(exist_ok=True)
    return p


def test_classify_legacy_urls(tmp_path):
    gp = _board_path(tmp_path)
    b = parse(
        '@ box a "A" 0,0 100x50 &demo-res/design.md\n'
        '@ box b "B" 200,0 100x50 &demo-res/sub.grafli\n'
        '@ box c "C" 400,0 100x50 &https://example.com\n'
        '@ box d "D" 600,0 100x50 &../outside/notes.md\n'
        '@ note n1 0,200 "see doc" &demo-res/n1.md\n'
    )
    assert classify_attachments(gp, b)
    a, bb, c, d = b.boxes
    assert (a.attach_kind, a.url) == ("doc", "design")
    assert (bb.attach_kind, bb.url) == ("graph", "sub")
    assert (c.attach_kind, c.url) == ("link", "https://example.com")
    # Outside the vault: stays a link — content kinds are vault-only.
    assert (d.attach_kind, d.url) == ("link", "../outside/notes.md")
    # A legacy note-& was a clickable reference next to inline text; promoting
    # it to doc would replace that text with the file body — so it stays link.
    n = b.notes[0]
    assert (n.attach_kind, n.url) == ("link", "demo-res/n1.md")
    assert n.text == "see doc"
    # Idempotent: second run changes nothing.
    assert not classify_attachments(gp, b)


# ── externalization (md: → doc-bodied) ──────────────────────────


def test_externalize_md_notes_strips_prefix_and_sets_doc():
    b = parse('@ note plan 0,0 "md:\\n# Title\\n\\n- a"\n')
    assert externalize_md_notes(b) == 1
    n = b.notes[0]
    assert n.attach_kind == "doc" and n.url == ""
    assert n.text == "# Title\n\n- a"
    # Idempotent; handwritten notes untouched.
    assert externalize_md_notes(b) == 0


def test_externalize_skips_notes_with_existing_attachment():
    b = parse('@ note plan 0,0 "md:\\nbody" &link:https://example.com\n')
    assert externalize_md_notes(b) == 0
    assert b.notes[0].attach_kind == "link"


# ── doc load / save ─────────────────────────────────────────────


def test_save_and_load_docs_roundtrip(tmp_path):
    gp = _board_path(tmp_path)
    b = parse("@ note plan 0,0 &doc\n")
    b.notes[0].text = "# Hello\n\nworld"
    assert save_docs(gp, b) == ["plan"]
    assert (tmp_path / "demo-res" / "plan.md").read_text() == "# Hello\n\nworld"
    # Unchanged content writes nothing on the next save.
    assert save_docs(gp, b) == []

    b2 = parse("@ note plan 0,0 &doc\n")
    assert load_docs(gp, b2) == []
    assert b2.notes[0].text == "# Hello\n\nworld"


def test_load_docs_missing_file_reports_and_loads_empty(tmp_path):
    gp = _board_path(tmp_path)
    b = parse("@ note ghost 0,0 &doc\n")
    assert load_docs(gp, b) == ["ghost"]
    assert b.notes[0].text == ""
    # Lazy-create: the untouched empty note never spawns a file...
    assert save_docs(gp, b) == []
    # ...but typing into it self-heals the missing doc.
    b.notes[0].text = "recovered"
    assert save_docs(gp, b) == ["ghost"]
    assert (tmp_path / "demo-res" / "ghost.md").read_text() == "recovered"


def test_shared_doc_edit_wins_and_syncs_siblings(tmp_path):
    gp = _board_path(tmp_path)
    (tmp_path / "demo-res" / "shared.md").write_text("v1", encoding="utf-8")
    b = parse("@ note a 0,0 &doc:shared\n@ note b 100,0 &doc:shared\n")
    load_docs(gp, b)
    assert [n.text for n in b.notes] == ["v1", "v1"]
    # One note edited in-app: its text wins, the stale sibling syncs.
    b.notes[1].text = "v2"
    assert save_docs(gp, b) == ["shared"]
    assert (tmp_path / "demo-res" / "shared.md").read_text() == "v2"
    assert b.notes[0].text == "v2"
    # Nothing edited → nothing written, nothing flips back.
    assert save_docs(gp, b) == []


# ── inventory ───────────────────────────────────────────────────


def test_vault_docs_inventory(tmp_path):
    gp = _board_path(tmp_path)
    rd = tmp_path / "demo-res"
    (rd / "used.md").write_text("x", encoding="utf-8")
    (rd / "orphan.md").write_text("y", encoding="utf-8")
    b = parse('@ note a 0,0 &doc:used\n@ box k "K" 0,0 80x40 &doc:gone\n')
    inv = vault_docs(gp, b)
    assert inv == {"referenced": ["used"], "missing": ["gone"],
                   "unreferenced": ["orphan"]}


# ── markdown typing of doc notes ────────────────────────────────


def test_doc_note_is_markdown_by_definition():
    n = Note(id="plan", x=0, y=0, text="# raw body, no md: prefix",
             attach_kind="doc")
    assert note_is_md(n)
    assert note_md_body(n) == "# raw body, no md: prefix"
    legacy = Note(id="l", x=0, y=0, text="md:\n# body")
    assert note_is_md(legacy)
    assert note_md_body(legacy) == "# body"
    plain = Note(id="p", x=0, y=0, text="just text")
    assert not note_is_md(plain)


def test_full_save_load_cycle_with_externalization(tmp_path):
    """The first-save migration: inline md: note → &doc line + vault file,
    stable from then on."""
    gp = _board_path(tmp_path)
    gp.write_text('#!grafli v1\n@ note story 0,0 "md:\\n# Plan\\n\\n- one"\n',
                  encoding="utf-8")
    board = parse(gp.read_text(encoding="utf-8"))
    classify_attachments(gp, board)
    load_docs(gp, board)
    # Save moment (mirrors MainWindow._write_file).
    assert externalize_md_notes(board) == 1
    classify_attachments(gp, board)
    save_docs(gp, board)
    gp.write_text(serialize(board), encoding="utf-8")

    assert "@ note story 0,0 &doc" in gp.read_text(encoding="utf-8")
    assert (tmp_path / "demo-res" / "story.md").read_text(
        encoding="utf-8") == "# Plan\n\n- one"

    again = parse(gp.read_text(encoding="utf-8"))
    classify_attachments(gp, again)
    load_docs(gp, again)
    n = again.notes[0]
    assert note_is_md(n) and n.text == "# Plan\n\n- one"
    # Second save: fully stable, no rewrites.
    assert externalize_md_notes(again) == 0
    assert save_docs(gp, again) == []
    assert serialize(again) == gp.read_text(encoding="utf-8")
