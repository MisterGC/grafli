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
