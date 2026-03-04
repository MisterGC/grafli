"""Tests for whiteboard.format — .board file parsing and serialization."""

import tempfile
from pathlib import Path

from whiteboard.format import (
    Arrow,
    Board,
    Box,
    Note,
    parse,
    parse_file,
    serialize,
    serialize_to_file,
)

SAMPLE = """\
# Project Architecture
# file: arch.board

@ box auth "Auth Service" 100,200 200x100
@ box db "Database" 400,200 200x100
@ box cache "Redis Cache" 250,50 160x80

@ arrow auth -> db "queries"
@ arrow auth -> cache "sessions"
@ arrow db -> cache

@ note n1 300,400 "TODO: Add rate limiting"
"""


def test_parse_boxes():
    board = parse(SAMPLE)
    assert len(board.boxes) == 3
    auth = board.box_by_id("auth")
    assert auth is not None
    assert auth.label == "Auth Service"
    assert auth.x == 100
    assert auth.y == 200
    assert auth.w == 200
    assert auth.h == 100


def test_parse_arrows():
    board = parse(SAMPLE)
    assert len(board.arrows) == 3
    assert board.arrows[0].from_id == "auth"
    assert board.arrows[0].to_id == "db"
    assert board.arrows[0].label == "queries"
    assert board.arrows[2].label == ""


def test_parse_notes():
    board = parse(SAMPLE)
    assert len(board.notes) == 1
    assert board.notes[0].id == "n1"
    assert board.notes[0].x == 300
    assert board.notes[0].y == 400
    assert board.notes[0].text == "TODO: Add rate limiting"


def test_parse_comments():
    board = parse(SAMPLE)
    assert any("Project Architecture" in c for c in board.comments)
    assert any("file: arch.board" in c for c in board.comments)


def test_roundtrip():
    """Parsing then serializing should produce identical output."""
    board = parse(SAMPLE)
    result = serialize(board)
    assert result == SAMPLE


def test_serialize_from_scratch():
    board = Board()
    board.boxes.append(Box(id="a", label="Box A", x=10, y=20, w=100, h=50))
    board.arrows.append(Arrow(from_id="a", to_id="a", label="self"))
    board.notes.append(Note(id="n1", x=0, y=0, text="hello"))
    text = serialize(board)
    assert '@ box a "Box A" 10,20 100x50' in text
    assert '@ arrow a -> a "self"' in text
    assert '@ note n1 0,0 "hello"' in text


def test_file_roundtrip(tmp_path: Path):
    path = tmp_path / "test.board"
    path.write_text(SAMPLE)
    board = parse_file(str(path))
    serialize_to_file(board, str(path))
    assert path.read_text() == SAMPLE


def test_empty_file():
    board = parse("")
    assert board.boxes == []
    assert board.arrows == []
    assert board.notes == []
    assert serialize(board) == "\n"


def test_box_by_id_missing():
    board = parse(SAMPLE)
    assert board.box_by_id("nonexistent") is None


def test_float_coordinates():
    text = '@ box f "Float" 10.5,20.3 100.0x50.0\n'
    board = parse(text)
    assert board.boxes[0].x == 10.5
    assert board.boxes[0].y == 20.3
    # integer-like floats should serialize without decimals
    assert "100x50" in serialize(board)
    # true floats should keep decimals
    assert "10.5,20.3" in serialize(board)


def test_negative_coordinates():
    text = '@ box n "Neg" -50,-100 200x100\n@ note n1 -10,-20 "offscreen"\n'
    board = parse(text)
    assert board.boxes[0].x == -50
    assert board.notes[0].x == -10
    result = serialize(board)
    assert "-50,-100" in result
    assert "-10,-20" in result


# ── Color tests ────────────────────────────────────────────────

def test_parse_box_with_color():
    text = '@ box auth "Auth" 100,200 200x100 #FF6B6B\n'
    board = parse(text)
    assert board.boxes[0].color == "#FF6B6B"


def test_parse_box_without_color():
    text = '@ box auth "Auth" 100,200 200x100\n'
    board = parse(text)
    assert board.boxes[0].color == ""


def test_serialize_box_with_color():
    box = Box(id="a", label="A", x=0, y=0, w=100, h=50, color="#4285F4")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box a "A" 0,0 100x50 #4285F4' in text


def test_color_roundtrip():
    text = '@ box a "A" 10,20 100x50 #AABBCC\n'
    board = parse(text)
    assert serialize(board) == text


# ── next_box_id tests ──────────────────────────────────────────

def test_next_box_id_empty():
    board = Board()
    assert board.next_box_id() == "box1"


def test_next_box_id_existing():
    board = parse(SAMPLE)
    # SAMPLE has auth, db, cache — no boxN IDs
    assert board.next_box_id() == "box1"

    board.add_box(Box(id="box3", label="X", x=0, y=0, w=50, h=50))
    assert board.next_box_id() == "box4"


# ── add/remove tests ──────────────────────────────────────────

def test_add_box():
    board = parse(SAMPLE)
    n = len(board.boxes)
    box = Box(id="new", label="New", x=0, y=0, w=100, h=50)
    board.add_box(box)
    assert len(board.boxes) == n + 1
    assert any(k == "box" and v is box for k, v in board._lines)
    assert '@ box new "New"' in serialize(board)


def test_add_arrow():
    board = parse(SAMPLE)
    n = len(board.arrows)
    arrow = Arrow(from_id="auth", to_id="cache", label="test")
    board.add_arrow(arrow)
    assert len(board.arrows) == n + 1
    assert any(k == "arrow" and v is arrow for k, v in board._lines)


def test_add_note():
    board = parse(SAMPLE)
    n = len(board.notes)
    note = Note(id="", x=500, y=500, text="new note")
    board.add_note(note)
    assert len(board.notes) == n + 1
    assert note.id != ""  # auto-assigned
    assert any(k == "note" and v is note for k, v in board._lines)


def test_remove_box():
    board = parse(SAMPLE)
    box = board.boxes[0]
    board.remove_box(box)
    assert box not in board.boxes
    assert not any(v is box for _, v in board._lines)


def test_remove_arrow():
    board = parse(SAMPLE)
    arrow = board.arrows[0]
    board.remove_arrow(arrow)
    assert arrow not in board.arrows
    assert not any(v is arrow for _, v in board._lines)


def test_remove_note():
    board = parse(SAMPLE)
    note = board.notes[0]
    board.remove_note(note)
    assert note not in board.notes
    assert not any(v is note for _, v in board._lines)


# ── Parent field tests ────────────────────────────────────────

def test_parse_box_with_parent():
    text = '@ box web "Web App" 60,70 180x80 >frontend\n'
    board = parse(text)
    assert board.boxes[0].parent == "frontend"


def test_parse_box_with_color_and_parent():
    text = '@ box web "Web App" 60,70 180x80 #4285F4 >frontend\n'
    board = parse(text)
    assert board.boxes[0].color == "#4285F4"
    assert board.boxes[0].parent == "frontend"


def test_parse_box_without_parent():
    text = '@ box web "Web App" 60,70 180x80\n'
    board = parse(text)
    assert board.boxes[0].parent == ""


def test_serialize_box_with_parent():
    box = Box(id="web", label="Web App", x=60, y=70, w=180, h=80, parent="frontend")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box web "Web App" 60,70 180x80 >frontend' in text


def test_serialize_box_with_color_and_parent():
    box = Box(
        id="web", label="Web App", x=60, y=70, w=180, h=80,
        color="#4285F4", parent="frontend",
    )
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box web "Web App" 60,70 180x80 #4285F4 >frontend' in text


def test_parent_roundtrip():
    text = '@ box web "Web App" 60,70 180x80 >frontend\n'
    board = parse(text)
    assert serialize(board) == text


def test_parent_color_roundtrip():
    text = '@ box web "Web App" 60,70 180x80 #4285F4 >frontend\n'
    board = parse(text)
    assert serialize(board) == text


# ── Anchor field tests ───────────────────────────────────────

def test_parse_box_with_anchor_topleft():
    text = '@ box title "Title" 60,70 180x80 ^topleft\n'
    board = parse(text)
    assert board.boxes[0].anchor == "topleft"


def test_parse_box_with_anchor_topcenter():
    text = '@ box title "Title" 60,70 180x80 ^topcenter\n'
    board = parse(text)
    assert board.boxes[0].anchor == "topcenter"


def test_parse_box_without_anchor():
    text = '@ box title "Title" 60,70 180x80\n'
    board = parse(text)
    assert board.boxes[0].anchor == ""


def test_serialize_box_with_anchor():
    box = Box(id="a", label="A", x=0, y=0, w=100, h=50, anchor="topleft")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box a "A" 0,0 100x50 ^topleft' in text


def test_anchor_roundtrip():
    text = '@ box title "Title" 60,70 180x80 ^topcenter\n'
    board = parse(text)
    assert serialize(board) == text


# ── Textsize field tests ─────────────────────────────────────

def test_parse_box_with_textsize_small():
    text = '@ box title "Title" 60,70 180x80 ~small\n'
    board = parse(text)
    assert board.boxes[0].textsize == "small"


def test_parse_box_with_textsize_large():
    text = '@ box title "Title" 60,70 180x80 ~large\n'
    board = parse(text)
    assert board.boxes[0].textsize == "large"


def test_parse_box_without_textsize():
    text = '@ box title "Title" 60,70 180x80\n'
    board = parse(text)
    assert board.boxes[0].textsize == ""


def test_serialize_box_with_textsize():
    box = Box(id="a", label="A", x=0, y=0, w=100, h=50, textsize="large")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box a "A" 0,0 100x50 ~large' in text


def test_textsize_roundtrip():
    text = '@ box title "Title" 60,70 180x80 ~small\n'
    board = parse(text)
    assert serialize(board) == text


# ── Combined optional field tests ────────────────────────────

def test_parse_all_optional_fields():
    text = '@ box web "Web App" 60,70 180x80 #4285F4 ^topleft ~small >frontend\n'
    board = parse(text)
    box = board.boxes[0]
    assert box.color == "#4285F4"
    assert box.anchor == "topleft"
    assert box.textsize == "small"
    assert box.parent == "frontend"


def test_serialize_all_optional_fields():
    box = Box(
        id="web", label="Web App", x=60, y=70, w=180, h=80,
        color="#4285F4", anchor="topleft", textsize="small", parent="frontend",
    )
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box web "Web App" 60,70 180x80 #4285F4 ^topleft ~small >frontend' in text


def test_all_optional_fields_roundtrip():
    text = '@ box web "Web App" 60,70 180x80 #4285F4 ^topleft ~small >frontend\n'
    board = parse(text)
    assert serialize(board) == text


def test_color_and_anchor_roundtrip():
    text = '@ box a "A" 10,20 100x50 #AABBCC ^topcenter\n'
    board = parse(text)
    assert serialize(board) == text


def test_anchor_and_parent_roundtrip():
    text = '@ box a "A" 10,20 100x50 ^topleft >container\n'
    board = parse(text)
    assert serialize(board) == text


def test_textsize_and_parent_roundtrip():
    text = '@ box a "A" 10,20 100x50 ~large >container\n'
    board = parse(text)
    assert serialize(board) == text


# ── Note color tests ─────────────────────────────────────────

def test_parse_note_with_color():
    text = '@ note n1 100,200 "hello" #FF6B6B\n'
    board = parse(text)
    assert board.notes[0].color == "#FF6B6B"


def test_parse_note_without_color():
    text = '@ note n1 100,200 "hello"\n'
    board = parse(text)
    assert board.notes[0].color == ""


def test_serialize_note_with_color():
    note = Note(id="n1", x=10, y=20, text="hi", color="#4285F4")
    board = Board()
    board.add_note(note)
    text = serialize(board)
    assert '@ note n1 10,20 "hi" #4285F4' in text


def test_note_color_roundtrip():
    text = '@ note n1 10,20 "hi" #FF6B6B\n'
    board = parse(text)
    assert serialize(board) == text


# ── Token color tests ────────────────────────────────────────

def test_parse_box_with_token_color():
    text = '@ box auth "Auth" 100,200 200x100 %primary\n'
    board = parse(text)
    assert board.boxes[0].color == "%primary"


def test_parse_note_with_token_color():
    text = '@ note n1 100,200 "hello" %accent\n'
    board = parse(text)
    assert board.notes[0].color == "%accent"


def test_token_color_roundtrip():
    text = '@ box a "A" 10,20 100x50 %primary\n'
    board = parse(text)
    assert serialize(board) == text


def test_all_fields_with_token_color():
    text = '@ box web "Web App" 60,70 180x80 %secondary ^topleft ~small >frontend\n'
    board = parse(text)
    box = board.boxes[0]
    assert box.color == "%secondary"
    assert box.anchor == "topleft"
    assert box.textsize == "small"
    assert box.parent == "frontend"
    assert serialize(board) == text


def test_note_token_color_roundtrip():
    text = '@ note n1 10,20 "hi" %highlight\n'
    board = parse(text)
    assert serialize(board) == text


# ── Style field tests ───────────────────────────────────────

def test_parse_box_with_style_flat():
    text = '@ box layer "Layer" 0,0 400x300 !flat\n'
    board = parse(text)
    assert board.boxes[0].style == "flat"


def test_parse_box_without_style():
    text = '@ box node "Node" 0,0 160x80\n'
    board = parse(text)
    assert board.boxes[0].style == ""


def test_serialize_box_with_style():
    box = Box(id="a", label="A", x=0, y=0, w=100, h=50, style="flat")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box a "A" 0,0 100x50 !flat' in text


def test_box_style_roundtrip():
    text = '@ box layer "Layer" 0,0 400x300 !flat\n'
    board = parse(text)
    assert serialize(board) == text


def test_box_all_fields_with_style_roundtrip():
    text = '@ box layer "Layer" 0,0 400x300 %muted ^topleft ~small !flat >root\n'
    board = parse(text)
    box = board.boxes[0]
    assert box.color == "%muted"
    assert box.anchor == "topleft"
    assert box.textsize == "small"
    assert box.style == "flat"
    assert box.parent == "root"
    assert serialize(board) == text


def test_parse_note_with_style_mono():
    text = '@ note n1 100,200 "Label" !mono\n'
    board = parse(text)
    assert board.notes[0].style == "mono"


def test_parse_note_without_style():
    text = '@ note n1 100,200 "Annotation"\n'
    board = parse(text)
    assert board.notes[0].style == ""


def test_serialize_note_with_style():
    note = Note(id="n1", x=10, y=20, text="Label", style="mono")
    board = Board()
    board.add_note(note)
    text = serialize(board)
    assert '@ note n1 10,20 "Label" !mono' in text


def test_note_style_roundtrip():
    text = '@ note n1 100,200 "Label" !mono\n'
    board = parse(text)
    assert serialize(board) == text


def test_note_all_fields_with_style_roundtrip():
    text = '@ note n1 100,200 "Label" %accent ~large !mono\n'
    board = parse(text)
    note = board.notes[0]
    assert note.color == "%accent"
    assert note.textsize == "large"
    assert note.style == "mono"
    assert serialize(board) == text


# ── Arrow style tests ──────────────────────────────────────

def test_parse_arrow_dashed():
    text = '@ arrow a -> b "optional" !dashed\n'
    board = parse(text)
    assert board.arrows[0].style == "dashed"
    assert board.arrows[0].label == "optional"
    assert not board.arrows[0].head_from
    assert board.arrows[0].head_to


def test_parse_arrow_dotted():
    text = '@ arrow a -> b !dotted\n'
    board = parse(text)
    assert board.arrows[0].style == "dotted"
    assert board.arrows[0].label == ""


def test_parse_arrow_thick():
    text = '@ arrow a -> b !thick\n'
    board = parse(text)
    assert board.arrows[0].style == "thick"


def test_parse_arrow_bidi():
    text = '@ arrow a <-> b "syncs"\n'
    board = parse(text)
    assert board.arrows[0].head_from is True
    assert board.arrows[0].head_to is True
    assert board.arrows[0].label == "syncs"


def test_parse_arrow_bidi_with_style():
    text = '@ arrow a <-> b "data" !dotted\n'
    board = parse(text)
    assert board.arrows[0].head_from is True
    assert board.arrows[0].head_to is True
    assert board.arrows[0].style == "dotted"
    assert board.arrows[0].label == "data"


def test_parse_arrow_backward():
    text = '@ arrow a <- b "pulls"\n'
    board = parse(text)
    assert board.arrows[0].head_from is True
    assert board.arrows[0].head_to is False
    assert board.arrows[0].label == "pulls"


def test_parse_arrow_no_heads():
    text = '@ arrow a -- b "link"\n'
    board = parse(text)
    assert board.arrows[0].head_from is False
    assert board.arrows[0].head_to is False
    assert board.arrows[0].label == "link"


def test_parse_arrow_bare_forward():
    text = '@ arrow a -> b\n'
    board = parse(text)
    assert board.arrows[0].label == ""
    assert board.arrows[0].style == ""
    assert board.arrows[0].head_from is False
    assert board.arrows[0].head_to is True


def test_serialize_arrow_bidi():
    arrow = Arrow(from_id="a", to_id="b", label="syncs", head_from=True, head_to=True)
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a <-> b "syncs"' in text


def test_serialize_arrow_style():
    arrow = Arrow(from_id="a", to_id="b", label="opt", style="dashed")
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a -> b "opt" !dashed' in text


def test_serialize_arrow_backward():
    arrow = Arrow(from_id="a", to_id="b", label="pulls", head_from=True, head_to=False)
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a <- b "pulls"' in text


def test_serialize_arrow_no_heads():
    arrow = Arrow(from_id="a", to_id="b", label="link", head_from=False, head_to=False)
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a -- b "link"' in text


def test_serialize_arrow_bidi_style():
    arrow = Arrow(from_id="a", to_id="b", style="thick", head_from=True, head_to=True)
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a <-> b !thick' in text


def test_arrow_style_roundtrip():
    text = '@ arrow a -> b "optional" !dashed\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_bidi_roundtrip():
    text = '@ arrow a <-> b "syncs"\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_bidi_style_roundtrip():
    text = '@ arrow a <-> b "data" !dotted\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_bare_style_roundtrip():
    text = '@ arrow a -> b !thick\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_bidi_bare_roundtrip():
    text = '@ arrow a <-> b\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_backward_roundtrip():
    text = '@ arrow a <- b "pulls"\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_backward_bare_roundtrip():
    text = '@ arrow a <- b\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_no_heads_roundtrip():
    text = '@ arrow a -- b "link"\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_no_heads_bare_roundtrip():
    text = '@ arrow a -- b\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_backward_style_roundtrip():
    text = '@ arrow a <- b "pulls" !dashed\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_no_heads_style_roundtrip():
    text = '@ arrow a -- b !dotted\n'
    board = parse(text)
    assert serialize(board) == text


# ── Annotation tests ───────────────────────────────────────

def test_parse_box_annotation():
    text = '@ box b1 "API" 100,200 200x100  # should this be async?\n'
    board = parse(text)
    assert board.boxes[0].annotation == "should this be async?"


def test_parse_box_without_annotation():
    text = '@ box b1 "API" 100,200 200x100\n'
    board = parse(text)
    assert board.boxes[0].annotation == ""


def test_parse_arrow_annotation():
    text = '@ arrow a -> b "calls"  # review direction\n'
    board = parse(text)
    assert board.arrows[0].annotation == "review direction"


def test_parse_note_annotation():
    text = '@ note n1 50,300 "entry"  # move this\n'
    board = parse(text)
    assert board.notes[0].annotation == "move this"


def test_serialize_box_annotation():
    box = Box(id="b1", label="API", x=100, y=200, w=200, h=100,
              annotation="should this be async?")
    board = Board()
    board.add_box(box)
    text = serialize(board)
    assert '@ box b1 "API" 100,200 200x100  # should this be async?' in text


def test_serialize_arrow_annotation():
    arrow = Arrow(from_id="a", to_id="b", label="calls",
                  annotation="review direction")
    board = Board()
    board.add_arrow(arrow)
    text = serialize(board)
    assert '@ arrow a -> b "calls"  # review direction' in text


def test_serialize_note_annotation():
    note = Note(id="n1", x=50, y=300, text="entry", annotation="move this")
    board = Board()
    board.add_note(note)
    text = serialize(board)
    assert '@ note n1 50,300 "entry"  # move this' in text


def test_box_annotation_roundtrip():
    text = '@ box b1 "API" 100,200 200x100  # should this be async?\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_annotation_roundtrip():
    text = '@ arrow a -> b "calls"  # review direction\n'
    board = parse(text)
    assert serialize(board) == text


def test_note_annotation_roundtrip():
    text = '@ note n1 50,300 "entry"  # move this\n'
    board = parse(text)
    assert serialize(board) == text


def test_arrow_bidi_style_annotation_roundtrip():
    text = '@ arrow a <-> b "data" !dotted  # check latency\n'
    board = parse(text)
    arrow = board.arrows[0]
    assert arrow.head_from is True
    assert arrow.head_to is True
    assert arrow.style == "dotted"
    assert arrow.annotation == "check latency"
    assert serialize(board) == text


def test_box_all_fields_with_annotation_roundtrip():
    text = '@ box web "Web" 60,70 180x80 %secondary ^topleft ~small !flat >root  # needs review\n'
    board = parse(text)
    box = board.boxes[0]
    assert box.annotation == "needs review"
    assert serialize(board) == text


def test_note_all_fields_with_annotation_roundtrip():
    text = '@ note n1 100,200 "Label" %accent ~large !mono  # move up\n'
    board = parse(text)
    note = board.notes[0]
    assert note.annotation == "move up"
    assert serialize(board) == text


# ── xxxlarge font tier tests ──────────────────────────────

def test_parse_box_xxxlarge():
    text = '@ box title "Title" 60,70 180x80 ~xxxlarge\n'
    board = parse(text)
    assert board.boxes[0].textsize == "xxxlarge"


def test_parse_note_xxxlarge():
    text = '@ note n1 100,200 "◇" ~xxxlarge\n'
    board = parse(text)
    assert board.notes[0].textsize == "xxxlarge"


def test_box_xxxlarge_roundtrip():
    text = '@ box title "Title" 60,70 180x80 ~xxxlarge\n'
    board = parse(text)
    assert serialize(board) == text


def test_note_xxxlarge_roundtrip():
    text = '@ note n1 100,200 "◇" ~xxxlarge\n'
    board = parse(text)
    assert serialize(board) == text


# ── Note ID tests ───────────────────────────────────────

def test_parse_note_with_id():
    text = '@ note myNote 100,200 "hello"\n'
    board = parse(text)
    assert board.notes[0].id == "myNote"


def test_parse_note_without_id_backfills():
    text = '@ note 100,200 "hello"\n'
    board = parse(text)
    assert board.notes[0].id == "n1"


def test_note_by_id():
    board = parse(SAMPLE)
    note = board.note_by_id("n1")
    assert note is not None
    assert note.text == "TODO: Add rate limiting"
    assert board.note_by_id("nonexistent") is None


def test_next_note_id_empty():
    board = Board()
    assert board.next_note_id() == "n1"


def test_next_note_id_existing():
    board = parse(SAMPLE)
    assert board.next_note_id() == "n2"
    board.add_note(Note(id="n5", x=0, y=0, text="x"))
    assert board.next_note_id() == "n6"


def test_note_id_roundtrip():
    text = '@ note myNote 100,200 "hello"\n'
    board = parse(text)
    assert serialize(board) == text
