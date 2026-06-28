"""Unit tests for the inline CriticMarkup comment format (grafli.md_comments)."""

from __future__ import annotations

from grafli import md_comments as mc


def test_no_comments_is_identity():
    src = "# Title\n\nJust plain prose, no annotations."
    assert mc.parse(src) == []
    assert mc.strip(src) == src
    md, comments = mc.to_sentineled(src)
    assert md == src
    assert comments == []


def test_single_comment_parsed():
    src = "The {==quarterly numbers==}{>>are these pre-audit?<<} look off."
    (c,) = mc.parse(src)
    assert c.span == "quarterly numbers"
    assert c.body == "are these pre-audit?"
    # offsets point at the real substring in the source
    assert src[c.span_start:c.span_end] == "quarterly numbers"
    assert src[c.full_start:c.full_end] == "{==quarterly numbers==}{>>are these pre-audit?<<}"


def test_strip_keeps_span_drops_body():
    src = "The {==quarterly numbers==}{>>are these pre-audit?<<} look off."
    assert mc.strip(src) == "The quarterly numbers look off."


def test_to_sentineled_wraps_span_and_drops_body():
    src = "a {==b==}{>>note<<} c"
    md, comments = mc.to_sentineled(src, start="<", end=">")
    assert md == "a <b> c"
    assert [(x.span, x.body) for x in comments] == [("b", "note")]


def test_multiple_comments_in_order():
    src = "{==one==}{>>first<<} and {==two==}{>>second<<}"
    comments = mc.parse(src)
    assert [(c.span, c.body) for c in comments] == [
        ("one", "first"),
        ("two", "second"),
    ]
    assert mc.strip(src) == "one and two"


def test_span_may_contain_markdown():
    src = "see {==**bold** word==}{>>why bold?<<} here"
    (c,) = mc.parse(src)
    assert c.span == "**bold** word"
    assert mc.strip(src) == "see **bold** word here"


def test_multiline_span_and_body():
    src = "{==line one\nline two==}{>>a\nb<<}"
    (c,) = mc.parse(src)
    assert c.span == "line one\nline two"
    assert c.body == "a\nb"


def test_set_body_replaces_only_the_body():
    src = "a {==b==}{>>old<<} c"
    (c,) = mc.parse(src)
    assert mc.set_body(src, c, "new") == "a {==b==}{>>new<<} c"
    (c2,) = mc.parse(mc.set_body(src, c, "new"))
    assert c2.span == "b" and c2.body == "new"


def test_set_body_targets_the_right_comment():
    src = "{==one==}{>>a<<} {==two==}{>>b<<}"
    first, second = mc.parse(src)
    assert mc.set_body(src, second, "B") == "{==one==}{>>a<<} {==two==}{>>B<<}"
    assert mc.set_body(src, first, "A") == "{==one==}{>>A<<} {==two==}{>>b<<}"


def test_remove_unwraps_to_span():
    src = "a {==b==}{>>note<<} c"
    (c,) = mc.parse(src)
    assert mc.remove(src, c) == "a b c"


def test_remove_leaves_other_comments():
    src = "{==one==}{>>a<<} and {==two==}{>>b<<}"
    first, _second = mc.parse(src)
    assert mc.remove(src, first) == "one and {==two==}{>>b<<}"


def test_wrap_creates_a_comment_over_a_slice():
    src = "the quick brown fox"
    start = src.index("quick")
    end = start + len("quick")
    out = mc.wrap(src, start, end, "why quick?")
    assert out == "the {==quick==}{>>why quick?<<} brown fox"
    (c,) = mc.parse(out)
    assert c.span == "quick" and c.body == "why quick?"


def test_real_sentinels_are_private_use():
    # default sentinels must be the private-use code points the read view scans
    assert mc.SENTINEL_START == "\uE000"
    assert mc.SENTINEL_END == "\uE001"
    md, _ = mc.to_sentineled("x {==y==}{>>z<<}")
    assert mc.SENTINEL_START in md and mc.SENTINEL_END in md
    assert "{==" not in md and "{>>" not in md
