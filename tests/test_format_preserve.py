"""Syntax this build doesn't know survives a parse/serialize round trip
byte for byte (#158): unknown flow step segments, unknown `~key=` flow
markers, and a `# annotation` behind an attachment."""

from grafli.format import parse, serialize


def _roundtrip(text: str) -> str:
    return serialize(parse(text))


def test_unknown_flow_segment_roundtrips():
    text = ('#!grafli v2\n'
            '@ bookmark bm "B"\n'
            '@ flow f "F" bm:3:zoom=x bm:detail=full:focus=none:lens=a:b\n')
    assert _roundtrip(text) == text
    step = parse(text).flows[0].steps[0]
    assert (step.ref, step.dwell, step.extra) == ("bm", 3.0, ["zoom=x"])


def test_unknown_flow_marker_is_not_a_step():
    text = ('#!grafli v2\n'
            '@ bookmark bm "B"\n'
            '@ flow f "F" bm ~auto=a ~detail=full ~board=other.grafli ~iso '
            '"desc"\n')
    assert _roundtrip(text) == text
    flow = parse(text).flows[0]
    assert [s.ref for s in flow.steps] == ["bm"]
    assert flow.extra == ["~board=other.grafli", "~iso"]


def test_out_of_vocabulary_flow_values_roundtrip():
    text = ('#!grafli v2\n'
            '@ bookmark bm "B"\n'
            '@ flow f "F" bm:detail=deep ~focus=blur\n')
    assert _roundtrip(text) == text


def test_annotation_behind_attachment_roundtrips():
    text = ('#!grafli v1\n'
            '@ box a "A" 0,0 100x60 &link:https://example.com # why A\n'
            '@ box b "B" 200,0 100x60 &doc:spec >a # see spec\n'
            '@ arrow a -> b "uses" &graph:detail ~kind=graph # hot path\n'
            '@ note n1 0,100 "N" &link:https://example.com # note why\n'
            '@ note n2 0,200 """\n'
            'two\n'
            'lines\n'
            '""" &link:https://example.com # block note\n'
            '@ note n3 0,250 &doc # doc-bodied note\n'
            '@ image img1 "pic.png" 0,300 40x40 &link:https://x.org # img\n')
    assert _roundtrip(text) == text


def test_annotation_newline_escape_roundtrips():
    text = '#!grafli v1\n@ box a "A" 0,0 100x60 &doc:a # one\\ntwo\n'
    board = parse(text)
    assert board.boxes[0].annotation == "one\ntwo"
    assert serialize(board) == text
