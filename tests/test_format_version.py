"""The `#!grafli vN` header: parsed into Board.version, written from the
features a board uses (VERSION_FEATURES), and newer than the build means
the board opens read-only (#158)."""

import pytest

from grafli import format as fmt
from grafli.format import is_newer, parse, required_version, serialize, \
    supported_version


@pytest.fixture
def v4_feature(monkeypatch):
    """Register a stand-in v4 feature: a board uses it when it has a box
    labelled "v4". Later issues register their real syntax the same way."""
    features = dict(fmt.VERSION_FEATURES)
    features["test-v4"] = (4, lambda b: any(x.label == "v4" for x in b.boxes))
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)


def test_header_version_is_parsed():
    assert parse('#!grafli v1\n@ box a "A" 0,0 10x10\n').version == 1
    assert parse('#!grafli v2\n').version == 2
    assert parse('#!grafli v17\n').version == 17
    assert parse('@ box a "A" 0,0 10x10\n').version == 0


def test_newer_header_is_not_a_comment():
    board = parse('#!grafli v4\n# title\n')
    assert board.had_header
    assert board.comments == ["# title"]
    assert not board.parse_warnings


def test_build_reads_up_to_v4_today():
    assert supported_version() == 4
    assert not is_newer(parse('#!grafli v4\n'))
    assert not is_newer(parse('# no header\n'))
    assert is_newer(parse('#!grafli v5\n'))


def test_newer_header_is_not_duplicated_on_save():
    # Before #158 a v3 header was kept as a comment and a v2 header was
    # written above it.
    text = '#!grafli v4\n@ box a "A" 0,0 10x10\n'
    out = serialize(parse(text))
    assert out.count("#!grafli") == 1


def test_plain_and_tour_boards_keep_their_header():
    v1 = '#!grafli v1\n@ box a "A" 0,0 10x10\n'
    v2 = ('#!grafli v2\n@ box a "A" 0,0 10x10\n'
          '@ bookmark bm1 "Start" @a\n')
    assert serialize(parse(v1)) == v1
    assert serialize(parse(v2)) == v2


def test_registered_v4_feature_writes_v4(v4_feature):
    board = parse('#!grafli v1\n@ box a "v4" 0,0 10x10\n')
    assert required_version(board) == 4
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_boards_without_the_v4_feature_keep_their_header(v4_feature):
    v1 = '#!grafli v1\n@ box a "A" 0,0 10x10\n'
    v2 = '#!grafli v2\n@ box a "A" 0,0 10x10\n@ bookmark bm1 "S" @a\n'
    assert serialize(parse(v1)) == v1
    assert serialize(parse(v2)) == v2


def test_registering_v4_makes_v4_readable(v4_feature):
    assert supported_version() == 4
    assert not is_newer(parse('#!grafli v4\n'))
    assert is_newer(parse('#!grafli v5\n'))


@pytest.mark.parametrize("attach", [
    "&graph:combat#blow",
    "&link:../System.grafli#impact",
    "&link:https://example.com/map.grafli#impact",
])
def test_a_board_fragment_writes_v3(attach):
    board = parse(f'#!grafli v1\n@ box a "A" 0,0 10x10 {attach}\n')
    out = serialize(board)
    assert out.splitlines()[0] == "#!grafli v3"
    assert attach in out


@pytest.mark.parametrize("attach", [
    "&graph:combat",
    "&link:../System.grafli",
    "&link:notes.md#intro",
    "&link:https://example.com/#top",
])
def test_links_without_a_board_fragment_stay_v1(attach):
    text = f'#!grafli v1\n@ box a "A" 0,0 10x10 {attach}\n'
    assert serialize(parse(text)) == text


def test_a_board_fragment_on_a_connector_writes_v3():
    text = ('#!grafli v1\n@ box a "A" 0,0 10x10\n@ box b "B" 50,0 10x10\n'
            '@ arrow a -> b &graph:combat#blow\n')
    assert serialize(parse(text)).splitlines()[0] == "#!grafli v3"


def test_an_arrow_id_writes_v3():
    text = ('#!grafli v1\n@ box a "A" 0,0 10x10\n@ box b "B" 50,0 10x10\n'
            '@ arrow a -> b ~id=call\n')
    out = serialize(parse(text))
    assert out.splitlines()[0] == "#!grafli v3"
    assert "@ arrow a -> b ~id=call" in out


def test_arrows_without_ids_stay_v1():
    text = ('#!grafli v1\n@ box a "A" 0,0 10x10\n@ box b "B" 50,0 10x10\n'
            '@ arrow a -> b "call" ~kind=graph\n')
    assert serialize(parse(text)) == text


def test_a_stop_in_another_board_writes_v3():
    text = ('#!grafli v2\n@ box a "A" 0,0 10x10\n'
            '@ bookmark bm1 "A" @a\n'
            '@ flow tour "Tour" bm1 combat#blow:3 ../other.grafli#hit\n')
    out = serialize(parse(text))
    assert out.splitlines()[0] == "#!grafli v3"
    assert "@ flow tour \"Tour\" bm1 combat#blow:3 ../other.grafli#hit" in out


def test_a_tour_on_its_own_board_stays_v2():
    text = ('#!grafli v2\n@ box a "A" 0,0 10x10\n'
            '@ bookmark bm1 "A" @a\n'
            '@ flow tour "Tour" bm1:3\n')
    assert serialize(parse(text)) == text


def test_a_step_ref_splits_into_board_and_bookmark():
    assert fmt.split_step_ref("bm1") == ("", "bm1")
    assert fmt.split_step_ref("combat#blow") == ("combat", "blow")
    assert fmt.split_step_ref("../x.grafli#hit") == ("../x.grafli", "hit")


CARD = ('#!grafli v4\n@ box c "Card" 0,0 200x150 !card\n'
        '@ note n 20,60 "body" >c\n')


def test_a_card_box_round_trips_and_writes_v4():
    board = parse(CARD)
    assert board.box_by_id("c").style == "card"
    assert required_version(board) == 4
    assert serialize(board) == CARD


def test_a_card_written_on_a_v1_board_lifts_it_to_v4():
    board = parse('#!grafli v1\n@ box c "Card" 0,0 200x150\n')
    board.box_by_id("c").style = "card"
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_a_card_board_as_newer(monkeypatch):
    # A build from before v4 registers no v4 feature, so it reads up to
    # v3 and the card board is newer than it.
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(CARD))


INK = ('#!grafli v4\n@ box b "Dark" 0,0 200x80 %primary !ink\n'
       '@ note n 0,120 "rose text" %rose !ink\n')


def test_ink_on_a_box_and_a_note_round_trips_and_writes_v4():
    board = parse(INK)
    assert board.box_by_id("b").ink
    assert board.notes[0].ink
    assert required_version(board) == 4
    assert serialize(board) == INK


def test_ink_writes_beside_the_other_flags():
    text = ('#!grafli v4\n@ box b "Dark" 0,0 200x80 %primary !flat !ink !bold\n'
            '@ note n 0,120 "x" %rose !flat !mono !ink !italic\n')
    assert serialize(parse(text)) == text


def test_ink_on_a_v1_note_lifts_the_board_to_v4():
    board = parse('#!grafli v1\n@ note n 0,0 "x" %rose\n')
    assert required_version(board) == 1
    board.notes[0].ink = True
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_an_ink_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(INK))


SANS = '#!grafli v4\n@ box b "Title" 0,0 200x80 %primary !sans\n'


def test_sans_on_a_box_round_trips_and_writes_v4():
    board = parse(SANS)
    assert board.box_by_id("b").sans
    assert required_version(board) == 4
    assert serialize(board) == SANS


def test_sans_writes_beside_the_other_flags():
    text = ('#!grafli v4\n'
            '@ box b "Title" 0,0 200x80 %primary !card !ink !sans !bold\n')
    assert serialize(parse(text)) == text


def test_sans_on_a_v1_box_lifts_the_board_to_v4():
    board = parse('#!grafli v1\n@ box b "Title" 0,0 200x80\n')
    assert required_version(board) == 1
    board.boxes[0].sans = True
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_a_sans_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(SANS))


SANS_NOTE = '#!grafli v4\n@ note n 0,0 "A sans note" %rose !sans\n'


def test_sans_on_a_note_round_trips_and_writes_v4():
    board = parse(SANS_NOTE)
    assert board.notes[0].style == "sans"
    assert required_version(board) == 4
    assert serialize(board) == SANS_NOTE


def test_sans_on_a_block_note_round_trips():
    text = ('#!grafli v4\n@ note n 0,0 """\nTwo\nlines\n""" !flat !sans !ink\n')
    board = parse(text)
    assert board.notes[0].style == "sans"
    assert serialize(board) == text


def test_mono_and_handwritten_notes_stay_below_v4():
    board = parse('#!grafli v1\n@ note n 0,0 "Mono" !mono\n'
                  '@ note h 0,50 "Hand"\n')
    assert [n.style for n in board.notes] == ["mono", ""]
    assert required_version(board) == 1


def test_a_v3_build_reads_a_sans_note_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert is_newer(parse(SANS_NOTE))


OUTLINES = ('#!grafli v4\n@ box later "Later" 0,0 200x80 !dashed\n'
            '@ box maybe "Maybe" 0,120 200x80 %accent !dotted\n')


def test_dashed_and_dotted_boxes_round_trip_and_write_v4():
    board = parse(OUTLINES)
    assert board.box_by_id("later").border == "dashed"
    assert board.box_by_id("maybe").border == "dotted"
    assert required_version(board) == 4
    assert serialize(board) == OUTLINES


def test_an_outline_writes_beside_the_other_flags():
    text = ('#!grafli v4\n'
            '@ box b "Title" 0,0 200x80 %primary !card !ink !sans !dashed !bold\n')
    assert serialize(parse(text)) == text


def test_a_solid_box_stays_v1():
    board = parse('#!grafli v1\n@ box b "Title" 0,0 200x80\n')
    assert board.boxes[0].border == ""
    assert required_version(board) == 1


def test_an_outline_on_a_v1_box_lifts_the_board_to_v4():
    board = parse('#!grafli v1\n@ box b "Title" 0,0 200x80\n')
    board.boxes[0].border = "dotted"
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_an_outline_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(OUTLINES))


MARKERS = ('#!grafli v4\n@ box s "Step" 0,0 80x80 *solid-3\n'
           '@ box z "Start" 0,120 80x80 *lead:0\n'
           '@ note n 0,240 "twelfth" *badge:solid-12\n')


def test_filled_and_zero_markers_round_trip_and_write_v4():
    board = parse(MARKERS)
    assert board.box_by_id("s").icon == "solid-3"
    assert (board.box_by_id("z").icon, board.box_by_id("z").icon_placement) \
        == ("0", "lead")
    assert (board.notes[0].icon, board.notes[0].icon_placement) \
        == ("solid-12", "badge")
    assert required_version(board) == 4
    assert serialize(board) == MARKERS


def test_number_markers_zero_strip():
    board = parse('@ box a "A" 0,0 80x80 *solid-07\n'
                  '@ box b "B" 0,120 80x80 *00\n')
    assert [b.icon for b in board.boxes] == ["solid-7", "0"]


def test_outlined_markers_one_to_ninety_nine_stay_v1():
    board = parse('#!grafli v1\n@ box a "A" 0,0 80x80 *3\n'
                  '@ box b "B" 0,120 80x80 *badge:99\n')
    assert required_version(board) == 1


def test_a_v3_build_reads_a_marker_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(MARKERS))


SIDES = ('#!grafli v4\n@ box a "A" 0,0 200x80\n@ box b "B" 0,200 200x80\n'
         '@ arrow a -> b "back" !ortho ~kind=graph ~from=right ~to=right '
         '~id=back\n'
         '@ arrow b -> a ~to=bottom\n')


def test_connector_sides_round_trip_and_write_v4():
    board = parse(SIDES)
    assert [(a.from_side, a.to_side) for a in board.arrows] == \
        [("right", "right"), ("", "bottom")]
    assert board.arrows[0].id == "back"
    assert required_version(board) == 4
    assert serialize(board) == SIDES


def test_an_unpinned_arrow_stays_v1():
    board = parse('#!grafli v1\n@ box a "A" 0,0 200x80\n'
                  '@ box b "B" 0,200 200x80\n@ arrow a -> b !ortho\n')
    assert (board.arrows[0].from_side, board.arrows[0].to_side) == ("", "")
    assert required_version(board) == 1


def test_a_side_on_a_v1_arrow_lifts_the_board_to_v4():
    board = parse('#!grafli v1\n@ box a "A" 0,0 200x80\n'
                  '@ box b "B" 0,200 200x80\n@ arrow a -> b\n')
    board.arrows[0].from_side = "left"
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_an_unknown_side_is_not_a_connector_side():
    board = parse('@ box a "A" 0,0 200x80\n@ box b "B" 0,200 200x80\n'
                  '@ arrow a -> b ~from=north\n')
    assert board.arrows == []
    assert board.parse_warnings


def test_a_v3_build_reads_a_sides_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(SIDES))


DOTS = ('#!grafli v4\n@ box a "A" 0,0 200x80\n@ box b "B" 0,200 200x80\n'
        '@ arrow a <-> b "joins" !dotted !ortho !dot\n'
        '@ arrow b -> a\n')


def test_dot_ends_round_trip_and_write_v4():
    board = parse(DOTS)
    assert [a.head_shape for a in board.arrows] == ["dot", ""]
    assert [(a.style, a.routing) for a in board.arrows] == \
        [("dotted", "ortho"), ("", "")]
    assert required_version(board) == 4
    assert serialize(board) == DOTS


def test_dot_is_read_in_any_flag_order():
    board = parse('@ box a "A" 0,0 200x80\n@ box b "B" 0,200 200x80\n'
                  '@ arrow a -> b !dot !thick !dashed\n')
    a = board.arrows[0]
    assert (a.head_shape, a.thickness, a.style) == ("dot", "thick", "dashed")


def test_a_dot_on_a_v1_arrow_lifts_the_board_to_v4():
    board = parse('#!grafli v1\n@ box a "A" 0,0 200x80\n'
                  '@ box b "B" 0,200 200x80\n@ arrow a -> b\n')
    assert required_version(board) == 1
    board.arrows[0].head_shape = "dot"
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_a_dot_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(DOTS))
