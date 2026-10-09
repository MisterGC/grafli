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


def test_build_reads_up_to_v3_today():
    assert supported_version() == 3
    assert not is_newer(parse('#!grafli v3\n'))
    assert not is_newer(parse('# no header\n'))
    assert is_newer(parse('#!grafli v4\n'))


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
