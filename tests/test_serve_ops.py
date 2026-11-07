"""The small edits a live tab sends (grafli.serve.ops), on parsed boards."""

from __future__ import annotations

import pytest

from grafli.format import parse, serialize
from grafli.serve.ops import NEW_BOX_H, NEW_BOX_W, OpError, apply_op

BOARD = """#!grafli v1
@ box lane "Lane" 0,0 400x200
@ box a "A" 20,40 100x60 >lane
@ box b "B" 200,40 100x60
@ note n1 20,300 "a note" >lane
@ arrow a -> b "calls"
"""


def board():
    return parse(BOARD)


def test_new_box_size_is_the_apps():
    from grafli.constants import DEFAULT_BOX_H, DEFAULT_BOX_W
    assert (NEW_BOX_W, NEW_BOX_H) == (DEFAULT_BOX_W, DEFAULT_BOX_H)


def test_move_a_box():
    b = board()
    assert apply_op(b, {"op": "move", "id": "b", "x": 250, "y": 90}) == {"id": "b"}
    assert (b.box_by_id("b").x, b.box_by_id("b").y) == (250, 90)


def test_move_a_container_carries_what_it_holds():
    b = board()
    apply_op(b, {"op": "move", "id": "lane", "x": 10, "y": -20})
    assert (b.box_by_id("a").x, b.box_by_id("a").y) == (30, 20)
    assert (b.note_by_id("n1").x, b.note_by_id("n1").y) == (30, 280)
    assert b.box_by_id("b").x == 200


def test_move_changes_only_that_line():
    b = board()
    apply_op(b, {"op": "move", "id": "b", "x": 210, "y": 40})
    before, after = BOARD.splitlines(), serialize(b).splitlines()
    assert [i for i, (x, y) in enumerate(zip(before, after)) if x != y] == [3]


def test_rename_box_note_and_arrow():
    b = board()
    apply_op(b, {"op": "rename", "id": "a", "label": "Api"})
    apply_op(b, {"op": "rename", "id": "n1", "label": "Q: why?"})
    apply_op(b, {"op": "rename", "id": "a->b", "label": "reads"})
    assert b.box_by_id("a").label == "Api"
    assert b.note_by_id("n1").text == "Q: why?"
    assert b.arrows[0].label == "reads"


def test_add_box_takes_the_next_id_and_the_apps_size():
    b = board()
    assert apply_op(b, {"op": "add_box", "label": "Cache", "x": 5, "y": 6}) == {"id": "box1"}
    box = b.box_by_id("box1")
    assert (box.label, box.x, box.y, box.w, box.h) == ("Cache", 5, 6, NEW_BOX_W, NEW_BOX_H)
    assert '@ box box1 "Cache" 5,6 160x80' in serialize(b)


def test_add_box_into_a_container():
    b = board()
    apply_op(b, {"op": "add_box", "id": "c", "label": "C", "x": 0, "y": 0,
                 "parent": "lane"})
    assert b.box_by_id("c").parent == "lane"


def test_connect():
    b = board()
    assert apply_op(b, {"op": "connect", "from": "b", "to": "a",
                        "label": "answers"}) == {"id": "b->a"}
    assert '@ arrow b -> a "answers"' in serialize(b)


def test_delete_a_box_takes_its_arrows_and_lets_go_of_children():
    b = board()
    apply_op(b, {"op": "delete", "id": "lane"})
    assert b.box_by_id("lane") is None
    assert b.box_by_id("a").parent == "" and b.note_by_id("n1").parent == ""
    apply_op(b, {"op": "delete", "id": "a"})
    assert b.arrows == []
    assert "@ arrow a -> b" not in serialize(b)


def test_delete_an_arrow():
    b = board()
    apply_op(b, {"op": "delete", "id": "a->b"})
    assert b.arrows == []


@pytest.mark.parametrize("op, message", [
    ({"op": "fly"}, "unknown edit"),
    ("move", "JSON object"),
    ({"op": "move", "id": "zz", "x": 0, "y": 0}, "no box, note or image 'zz'"),
    ({"op": "move", "id": "a", "x": "1", "y": 0}, "'x' must be a number"),
    ({"op": "rename", "id": "a", "label": 3}, "'label' must be a string"),
    ({"op": "rename", "id": "a", "label": "x" * 501}, "longer than"),
    ({"op": "add_box", "id": "a", "label": "A", "x": 0, "y": 0}, "already exists"),
    ({"op": "add_box", "label": "A", "x": 0, "y": 0, "w": 0}, "positive size"),
    ({"op": "add_box", "label": "A", "x": 0, "y": 0, "parent": "zz"}, "no box 'zz'"),
    ({"op": "connect", "from": "a", "to": "b"}, "already connected"),
    ({"op": "connect", "from": "a", "to": "a"}, "two different ends"),
    ({"op": "delete", "id": "zz"}, "no element 'zz'"),
])
def test_edits_that_do_not_fit_say_why(op, message):
    b = board()
    with pytest.raises(OpError, match=message):
        apply_op(b, op)
    assert serialize(b) == BOARD


@pytest.mark.parametrize("bad_id", ["my box", "two\nlines", "tab\there", " "])
def test_a_new_box_id_must_be_one_token(bad_id):
    """The format reads a box id as one ``\\S+`` token; anything else would
    write a line no reader takes."""
    b = board()
    with pytest.raises(OpError, match="not an id"):
        apply_op(b, {"op": "add_box", "id": bad_id, "label": "New", "x": 0, "y": 0})
    assert serialize(b) == BOARD


@pytest.mark.parametrize("field", ["x", "y", "w", "h"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numbers_must_be_finite(field, value):
    b = board()
    op = {"op": "add_box", "label": "New", "x": 0, "y": 0, field: value}
    with pytest.raises(OpError, match=f"'{field}' must be a finite number"):
        apply_op(b, op)
    if field in ("x", "y"):
        with pytest.raises(OpError, match="finite"):
            apply_op(b, {"op": "move", "id": "a", "x": 0, "y": 0, field: value})
    assert serialize(b) == BOARD


def test_a_doc_note_is_not_renamed_in_place():
    b = parse('#!grafli v1\n@ note d 0,0 &doc\n')
    with pytest.raises(OpError, match="keeps its text in a doc"):
        apply_op(b, {"op": "rename", "id": "d", "label": "x"})


# ── A new box beside the selection (the tab's o / O / Ctrl+arrow) ──

# A container and, outside it, one box on its own.
SPACED = """#!grafli v1
@ box lane "Lane" 0,0 400x400
@ box a "A" 20,40 100x60 >lane
@ box b "B" 600,40 100x60
@ note n1 20,300 "a note" >lane
"""


def spaced():
    return parse(SPACED)

def test_a_box_beside_takes_the_apps_spot_size_and_parent():
    b = spaced()
    assert apply_op(b, {"op": "add_box", "label": "C", "beside": "a",
                        "connect": True}) == {"id": "box1"}
    c = b.box_by_id("box1")
    # 40 below a, a's size, in a's container, as the app's o places it.
    assert (c.x, c.y, c.w, c.h, c.parent) == (20, 140, 100, 60, "lane")
    assert any(x.from_id == "a" and x.to_id == "box1" for x in b.arrows)


@pytest.mark.parametrize("side, spot", [
    ("below", (600, 140)), ("above", (600, -60)),
    ("right", (740, 40)), ("left", (460, 40)),
])
def test_a_box_beside_on_each_side(side, spot):
    b = spaced()
    apply_op(b, {"op": "add_box", "label": "C", "beside": "b", "side": side})
    c = b.box_by_id("box1")
    assert (c.x, c.y) == spot
    assert not any(x.to_id == "box1" for x in b.arrows)


def test_a_second_box_beside_the_same_one_does_not_cover_the_first():
    b = spaced()
    apply_op(b, {"op": "add_box", "label": "C", "beside": "b"})
    apply_op(b, {"op": "add_box", "label": "D", "beside": "b"})
    assert (b.box_by_id("box1").y, b.box_by_id("box2").y) == (140, 240)


def test_five_connected_boxes_one_beside_the_last():
    b = parse('#!grafli v1\n@ box s "Start" 0,0 160x80\n')
    last = "s"
    for label in "ABCD":
        last = apply_op(b, {"op": "add_box", "label": label, "beside": last,
                            "connect": True})["id"]
    assert [x.label for x in b.boxes] == ["Start", "A", "B", "C", "D"]
    assert [(x.from_id, x.to_id) for x in b.arrows] == [
        ("s", "box1"), ("box1", "box2"), ("box2", "box3"), ("box3", "box4")]


@pytest.mark.parametrize("op, message", [
    ({"op": "add_box", "label": "C", "beside": "zz"}, "no box, note or image 'zz'"),
    ({"op": "add_box", "label": "C", "beside": "a", "side": "up"}, "'side' is one of"),
    ({"op": "add_box", "label": "C"}, "'x' must be a number"),
])
def test_a_box_beside_that_does_not_fit_says_why(op, message):
    b = spaced()
    with pytest.raises(OpError, match=message):
        apply_op(b, op)
    assert serialize(b) == SPACED


# ── Lines typed on the tab's ':' command line ──

def test_a_box_line_without_a_place_goes_below_the_selection():
    b = spaced()
    out = apply_op(b, {"op": "lines", "text": '@ box cache "Cache"',
                       "beside": "b"})
    assert out == {"id": "cache", "ids": ["cache"]}
    assert '@ box cache "Cache" 600,140 100x60' in serialize(b)


def test_a_box_line_without_a_place_and_no_selection_goes_to_x_y():
    b = spaced()
    apply_op(b, {"op": "lines", "text": 'box cache "Cache" %accent',
                 "x": 500, "y": 300})
    assert '@ box cache "Cache" 420,260 160x80 %accent' in serialize(b)


def test_lines_add_boxes_and_the_arrow_between_them_at_once():
    b = spaced()
    apply_op(b, {"op": "lines", "beside": "b", "text":
                 '@ box cache "Cache"\nbox db "DB"\n'
                 '@ arrow cache -> db "reads"'})
    assert (b.box_by_id("cache").y, b.box_by_id("db").y) == (140, 240)
    assert '@ arrow cache -> db "reads"' in serialize(b)


def test_a_line_restates_the_element_with_its_id():
    b = spaced()
    apply_op(b, {"op": "lines", "text": '@ box a "Api" %accent'})
    a = b.box_by_id("a")
    # No place on the line: the box keeps its place and its container.
    assert (a.label, a.color, a.x, a.y, a.parent) == ("Api", "%accent", 20, 40, "lane")
    apply_op(b, {"op": "lines", "text": '@ arrow a -> b "calls"'})
    apply_op(b, {"op": "lines", "text": '@ arrow a -> b "reads" !dashed'})
    assert len(b.arrows) == 1 and b.arrows[0].label == "reads"
    assert b.arrows[0].style == "dashed"


def test_a_full_line_is_taken_as_written():
    b = spaced()
    apply_op(b, {"op": "lines", "text": '@ box q "Queue" 600,0 120x60 >lane'})
    q = b.box_by_id("q")
    assert (q.x, q.y, q.w, q.h, q.parent) == (600, 0, 120, 60, "lane")
    apply_op(b, {"op": "lines", "text": '@ note 0,500 "Q: why a queue?"\n'
                                        '@ note 0,600 "Q: and who reads it?"'})
    assert [n.text for n in b.notes[-2:]] == ["Q: why a queue?",
                                             "Q: and who reads it?"]
    assert len({n.id for n in b.notes}) == len(b.notes)


@pytest.mark.parametrize("text, message", [
    ("add a cache between api and db", "takes box, arrow, note and image lines"),
    ("@ flow f \"F\"", "takes box, arrow, note and image lines"),
    ("", "nothing to add"),
    ("# only a comment", "nothing to add"),
    ('@ box x "X" 0,0 10x10 nonsense', "not a grafli line"),
    ("@ arrow a -> zz", "no box, note or image 'zz'"),
    ('@ box x "X" >nowhere', "no box 'nowhere'"),
    ('@ box n1 "X"', "already on the board, and not as a box"),
])
def test_command_lines_that_do_not_fit_say_why(text, message):
    b = board()
    with pytest.raises(OpError, match=message):
        apply_op(b, {"op": "lines", "text": text})
    assert serialize(b) == BOARD
