"""Tests for bookmark/flow directives (grafli format v2)."""

from grafli.format import (
    HEADER,
    HEADER_V2,
    Board,
    Bookmark,
    Flow,
    FlowStep,
    _parse_flow_rest,
    parse,
    serialize,
)

V2_SAMPLE = """\
#!grafli v2
@ box auth "Auth" 0,0 100x50
@ box db "DB" 200,0 100x50
@ bookmark bm1 "Overview" @auth,db ~pad=80 "Two parts."
@ bookmark bm2 "Auth only" @auth "Entry point."
@ flow flow1 "Tour" bm1 bm2:6 "Start wide then zoom."
"""


def test_parse_bookmarks():
    board = parse(V2_SAMPLE)
    assert [bm.id for bm in board.bookmarks] == ["bm1", "bm2"]
    bm1 = board.bookmark_by_id("bm1")
    assert bm1.label == "Overview"
    assert bm1.focus == ["auth", "db"]
    assert bm1.pad == 80
    assert bm1.description == "Two parts."
    bm2 = board.bookmark_by_id("bm2")
    assert bm2.focus == ["auth"]
    assert bm2.pad == 0
    assert bm2.description == "Entry point."


def test_parse_flow_with_dwell():
    board = parse(V2_SAMPLE)
    flow = board.flow_by_id("flow1")
    assert flow.label == "Tour"
    assert [(s.ref, s.dwell) for s in flow.steps] == [("bm1", None), ("bm2", 6.0)]
    assert flow.description == "Start wide then zoom."


def test_v2_round_trip_byte_stable():
    board = parse(V2_SAMPLE)
    assert serialize(board) == V2_SAMPLE


def test_v1_stays_v1_without_bookmarks():
    v1 = "#!grafli v1\n@ box a \"A\" 0,0 100x50\n"
    board = parse(v1)
    out = serialize(board)
    assert out.splitlines()[0] == HEADER
    assert out == v1


def test_adding_bookmark_upgrades_header_to_v2():
    board = Board()
    board.add_bookmark(Bookmark(id="", label="X", focus=["a"]))
    out = serialize(board)
    assert out.splitlines()[0] == HEADER_V2
    # auto-assigned id
    assert board.bookmarks[0].id == "bm1"


def test_next_id_helpers():
    board = Board()
    board.add_bookmark(Bookmark(id="bm1", label="a", focus=["x"]))
    board.add_bookmark(Bookmark(id="bm5", label="b", focus=["y"]))
    assert board.next_bookmark_id() == "bm6"
    board.add_flow(Flow(id="flow2", label="f"))
    assert board.next_flow_id() == "flow3"


def test_parse_flow_rest_variants():
    steps, desc = _parse_flow_rest('a b:3 c:4s "hello world"')
    assert [(s.ref, s.dwell) for s in steps] == [("a", None), ("b", 3.0), ("c", 4.0)]
    assert desc == "hello world"

    steps, desc = _parse_flow_rest("only refs here")
    assert [s.ref for s in steps] == ["only", "refs", "here"]
    assert desc == ""

    steps, desc = _parse_flow_rest('"just a description"')
    assert steps == []
    assert desc == "just a description"


def test_remove_bookmark_and_flow_update_lines():
    board = parse(V2_SAMPLE)
    bm = board.bookmark_by_id("bm1")
    board.remove_bookmark(bm)
    flow = board.flow_by_id("flow1")
    board.remove_flow(flow)
    out = serialize(board)
    assert "bm1" not in out
    assert "flow1" not in out
    # other bookmark survives, header stays v2
    assert "bm2" in out
    assert out.splitlines()[0] == HEADER_V2


def test_viewport_bookmark_round_trip():
    src = (
        '#!grafli v2\n'
        '@ box a "A" 0,0 50x50\n'
        '@ bookmark bm1 "Exact" ~view=100,200,640,360 "hand tuned"\n'
    )
    board = parse(src)
    bm = board.bookmark_by_id("bm1")
    assert bm.focus == []
    assert bm.view == (100.0, 200.0, 640.0, 360.0)
    assert bm.description == "hand tuned"
    assert serialize(board) == src


def test_focus_and_view_are_mutually_optional():
    # focus only
    b1 = parse('#!grafli v2\n@ box a "A" 0,0 50x50\n@ bookmark x "L" @a\n')
    assert b1.bookmark_by_id("x").view is None
    # view only
    b2 = parse('#!grafli v2\n@ bookmark y "L" ~view=0,0,100,100\n')
    assert b2.bookmark_by_id("y").focus == []
    assert b2.bookmark_by_id("y").view == (0.0, 0.0, 100.0, 100.0)


def test_bookmark_without_description_or_pad():
    board = parse('#!grafli v2\n@ box a "A" 0,0 50x50\n@ bookmark b1 "Plain" @a\n')
    bm = board.bookmark_by_id("b1")
    assert bm.focus == ["a"]
    assert bm.pad == 0
    assert bm.description == ""
    assert serialize(board).rstrip().endswith('@ bookmark b1 "Plain" @a')
