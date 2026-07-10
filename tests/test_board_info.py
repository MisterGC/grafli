"""Tests for grafli.board_info — the `grafli inspect` geometry report."""

from grafli.board_info import board_info
from grafli.format import parse


ROW = """\
@ box wrap "Wrap" 0,0 800x200 ~large !flat
@ box a "A" 20,60 200x100 >wrap
@ box b "B" 260,60 200x100 >wrap
"""


def test_row_container_next_slot():
    info = board_info(parse(ROW))
    (c,) = info["containers"]
    assert c["orientation"] == "row"
    assert c["gaps"] == [40.0]
    assert c["top_margin"] == 60.0
    assert c["inner"] == [20.0, 60.0, 760.0, 120.0]
    assert c["next_slot"] == [500.0, 60.0, 200.0, 100.0]
    assert c["next_slot_fits"] is True


def test_row_container_full_slot_does_not_fit():
    text = ROW + '@ box c "C" 500,60 200x100 >wrap\n'
    info = board_info(parse(text))
    (c,) = info["containers"]
    assert c["next_slot"] == [740.0, 60.0, 200.0, 100.0]
    assert c["next_slot_fits"] is False


def test_column_container_orientation():
    text = (
        '@ box wrap "Wrap" 0,0 300x400 !flat\n'
        '@ box a "A" 20,60 200x80 >wrap\n'
        '@ box b "B" 20,170 200x80 >wrap\n'
    )
    info = board_info(parse(text))
    (c,) = info["containers"]
    assert c["orientation"] == "column"
    assert c["gaps"] == [30.0]
    assert c["top_margin"] == 40.0
    assert c["next_slot"] == [20.0, 280.0, 200.0, 80.0]


def test_bounds_and_arrows():
    text = (
        '@ box a "A" 0,0 200x100\n'
        '@ box b "B" 300,0 200x100\n'
        '@ arrow a -> b "calls" !dashed\n'
    )
    info = board_info(parse(text))
    assert info["bounds"] == [0.0, 0.0, 500.0, 100.0]
    (arrow,) = info["arrows"]
    assert arrow["from"] == "a" and arrow["to"] == "b"
    assert arrow["label"] == "calls" and arrow["style"] == "dashed"


def test_notes_report_position_without_qt():
    info = board_info(parse('@ note n1 100,50 "hello world"\n'))
    (n,) = [e for e in info["elements"] if e["type"] == "note"]
    assert n["position"] == [100.0, 50.0]
    assert n["rect"] is None
    assert n["text_head"] == "hello world"


def test_empty_board():
    info = board_info(parse(""))
    assert info["bounds"] is None
    assert info["elements"] == []
    assert info["containers"] == []
