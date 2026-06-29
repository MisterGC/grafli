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


def _map(rendered, source, sub):
    """Map the first occurrence of ``sub`` in ``rendered`` back to source."""
    r0 = rendered.index(sub)
    r1 = r0 + len(sub)
    return mc.map_rendered_span(rendered, source, r0, r1)


def test_map_plain_prose_is_exact():
    src = ren = "the quick brown fox"
    assert _map(ren, src, "brown") == (src.index("brown"), src.index("brown") + 5)


def test_map_skips_heading_marker():
    src = "# Title\n\nthe quick fox"
    ren = "Title\nthe quick fox"           # '# ' consumed by the renderer
    s0, s1 = _map(ren, src, "quick")
    assert src[s0:s1] == "quick"


def test_map_excludes_trailing_bold_markers():
    src = "a **bold** b"
    ren = "a bold b"
    s0, s1 = _map(ren, src, "bold")
    assert src[s0:s1] == "bold"            # not "bold**"


def test_map_span_keeps_inline_markup_inside():
    src = "quick **brown** fox"
    ren = "quick brown fox"
    s0, s1 = _map(ren, src, "quick brown fox")
    assert src[s0:s1] == "quick **brown** fox"
    # wrapping it round-trips: the rendered span text equals the selection
    wrapped = mc.wrap(src, s0, s1, "c")
    (cmt,) = mc.parse(wrapped)
    assert cmt.span == "quick **brown** fox"


def test_map_ignores_existing_comment_body_as_noise():
    # the body 'note' contains letters that also start later words; the strip
    # step removes it so the alignment can't drift into it.
    src = "x {==hi==}{>>note<<} the fox"
    ren = "x hi the fox"
    s0, s1 = _map(ren, src, "fox")
    assert src[s0:s1] == "fox"


def test_map_through_link_text():
    src = "see [docs](http://x) now"
    ren = "see docs now"
    s0, s1 = _map(ren, src, "docs")
    assert src[s0:s1] == "docs"


def test_map_empty_selection_is_none():
    assert mc.map_rendered_span("abc", "abc", 2, 2) is None


def test_overlap_inside_existing_span():
    src = "a {==bcd==}{>>note<<} e"
    bs = src.index("bcd")
    assert mc.classify_overlap(src, bs, bs + 2) == ("inside", 0)   # 'bc' within span


def test_overlap_partial_straddle_refused():
    src = "a {==bcd==}{>>note<<} e"
    bs = src.index("bcd")
    # starts before the construct, ends inside the span → straddles the markup
    assert mc.classify_overlap(src, 0, bs + 1) == ("partial", 0)


def test_overlap_clear_selection_is_none():
    src = "a {==bcd==}{>>note<<} eee"
    es = src.index("eee")
    assert mc.classify_overlap(src, es, es + 3) is None


def test_overlap_none_without_comments():
    assert mc.classify_overlap("plain text here", 0, 5) is None


# ── code regions and robustness ──

def test_inline_code_example_is_not_a_comment():
    src = "The syntax is `{==span==}{>>body<<}` in code."
    assert mc.parse(src) == []
    assert mc.strip(src) == src              # left literal


def test_fenced_code_example_is_not_a_comment():
    src = "Example:\n\n```\nThe {==quarterly==}{>>q?<<} numbers\n```\n\ndone"
    assert mc.parse(src) == []
    assert mc.strip(src) == src


def test_real_comment_outside_code_still_parses_next_to_examples():
    src = "Use `{==x==}{>>y<<}` then a real {==span==}{>>note<<} here."
    comments = mc.parse(src)
    assert [(c.span, c.body) for c in comments] == [("span", "note")]


def test_map_position_round_trips_between_views():
    src = "# Title\n\nThe **quick** brown fox and a [link](http://x) here.\n"
    rendered = mc.strip(src).replace("**", "").replace("# ", "")  # ~Qt render
    rendered = rendered.replace("[link](http://x)", "link")
    sp = src.index("brown")
    rp = mc.map_position(src, rendered, sp)
    assert rendered[rp:rp + 5] == "brown"
    # and back
    sp2 = mc.map_position(rendered, src, rp)
    assert src[sp2:sp2 + 5] == "brown"


def test_map_position_no_shared_words_is_zero():
    assert mc.map_position("", "abc", 0) == 0
    assert mc.map_position("abc", "", 0) == 0


def test_contains_markup_detects_delimiters():
    assert mc.contains_markup("a {== b") is True
    assert mc.contains_markup("a ==} b") is True
    assert mc.contains_markup("a {>> b") is True
    assert mc.contains_markup("a <<} b") is True
    assert mc.contains_markup("plain prose, nothing here") is False


def test_tempered_span_does_not_swallow_next_comment():
    # a stray '{==' must not let one comment consume the next one's opening
    src = "a {==one==}{>>first<<} b {==two==}{>>second<<} c"
    assert [(c.span, c.body) for c in mc.parse(src)] == [
        ("one", "first"), ("two", "second"),
    ]


def test_map_is_robust_when_render_drops_content():
    # Regression: the greedy char aligner drifted on real docs (every word
    # mapped to the end). Here the "rendered" view drops link URLs (as Qt's
    # setMarkdown does), so the word sequences differ — the word-diff stays exact.
    import re
    src = "\n\n".join(
        f"## Section {i}\n\nSee [marker{i}](https://example.com/very/long/path/{i}) now."
        for i in range(40)
    )
    rendered = re.sub(r"^## ", "", re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", src),
                      flags=re.M)
    for i in (0, 20, 39):
        tok = f"marker{i}"
        r0 = rendered.index(tok)
        s0, s1 = mc.map_rendered_span(rendered, src, r0, r0 + len(tok))
        assert src[s0:s1] == tok


def test_real_sentinels_are_private_use():
    # default sentinels must be the private-use code points the read view scans
    assert mc.SENTINEL_START == "\uE000"
    assert mc.SENTINEL_END == "\uE001"
    md, _ = mc.to_sentineled("x {==y==}{>>z<<}")
    assert mc.SENTINEL_START in md and mc.SENTINEL_END in md
    assert "{==" not in md and "{>>" not in md
