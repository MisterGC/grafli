"""The `#!grafli vN` header: parsed into Board.version, written from the
features a board uses (VERSION_FEATURES), and newer than the build means
the board opens read-only (#158)."""

import pytest

from grafli import format as fmt
from grafli.format import is_newer, parse, required_version, serialize, \
    supported_version


@pytest.fixture
def v3_feature(monkeypatch):
    """Register a stand-in v3 feature: a board uses it when it has a box
    labelled "v3". Later issues register their real syntax the same way."""
    features = dict(fmt.VERSION_FEATURES)
    features["test-v3"] = (3, lambda b: any(x.label == "v3" for x in b.boxes))
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)


def test_header_version_is_parsed():
    assert parse('#!grafli v1\n@ box a "A" 0,0 10x10\n').version == 1
    assert parse('#!grafli v2\n').version == 2
    assert parse('#!grafli v17\n').version == 17
    assert parse('@ box a "A" 0,0 10x10\n').version == 0


def test_newer_header_is_not_a_comment():
    board = parse('#!grafli v3\n# title\n')
    assert board.had_header
    assert board.comments == ["# title"]
    assert not board.parse_warnings


def test_build_reads_up_to_v2_today():
    assert supported_version() == 2
    assert not is_newer(parse('#!grafli v2\n'))
    assert not is_newer(parse('# no header\n'))
    assert is_newer(parse('#!grafli v3\n'))


def test_newer_header_is_not_duplicated_on_save():
    # Before #158 a v3 header was kept as a comment and a v2 header was
    # written above it.
    text = '#!grafli v3\n@ box a "A" 0,0 10x10\n'
    out = serialize(parse(text))
    assert out.count("#!grafli") == 1


def test_plain_and_tour_boards_keep_their_header():
    v1 = '#!grafli v1\n@ box a "A" 0,0 10x10\n'
    v2 = ('#!grafli v2\n@ box a "A" 0,0 10x10\n'
          '@ bookmark bm1 "Start" @a\n')
    assert serialize(parse(v1)) == v1
    assert serialize(parse(v2)) == v2


def test_registered_v3_feature_writes_v3(v3_feature):
    board = parse('#!grafli v1\n@ box a "v3" 0,0 10x10\n')
    assert required_version(board) == 3
    assert serialize(board).splitlines()[0] == "#!grafli v3"


def test_boards_without_the_v3_feature_keep_their_header(v3_feature):
    v1 = '#!grafli v1\n@ box a "A" 0,0 10x10\n'
    v2 = '#!grafli v2\n@ box a "A" 0,0 10x10\n@ bookmark bm1 "S" @a\n'
    assert serialize(parse(v1)) == v1
    assert serialize(parse(v2)) == v2


def test_registering_v3_makes_v3_readable(v3_feature):
    assert supported_version() == 3
    assert not is_newer(parse('#!grafli v3\n'))
    assert is_newer(parse('#!grafli v4\n'))
