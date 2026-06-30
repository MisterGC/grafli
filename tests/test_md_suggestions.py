"""Unit tests for the CriticMarkup suggestion marks (track-changes) in
grafli.md_comments — insert / delete / substitute, alongside comments."""

from __future__ import annotations

from grafli import md_comments as mc
from grafli.md_comments import MarkKind as K


# ── parsing each kind ──

def test_parse_insertion():
    src = "the quick {++brown ++}fox"
    (m,) = mc.suggestions(src)
    assert m.kind == K.INSERT
    assert m.added == "brown " and m.removed == ""
    assert src[m.full_start:m.full_end] == "{++brown ++}"


def test_parse_deletion():
    src = "the {--very --}quick fox"
    (m,) = mc.suggestions(src)
    assert m.kind == K.DELETE
    assert m.removed == "very " and m.added == ""


def test_parse_substitution():
    src = "the {~~quick~>swift~~} fox"
    (m,) = mc.suggestions(src)
    assert m.kind == K.SUBSTITUTE
    assert m.removed == "quick" and m.added == "swift"


def test_substitution_new_may_contain_arrow():
    # only the FIRST ~> splits old from new; a later ~> belongs to new
    src = "{~~a~>b ~> c~~}"
    (m,) = mc.suggestions(src)
    assert m.removed == "a" and m.added == "b ~> c"


def test_span_may_contain_markdown():
    src = "see {~~**bold** word~>plain~~} here"
    (m,) = mc.suggestions(src)
    assert m.removed == "**bold** word" and m.added == "plain"


def test_multiline_substitution():
    src = "{~~line one\nline two~>just one~~}"
    (m,) = mc.suggestions(src)
    assert m.removed == "line one\nline two" and m.added == "just one"


# ── marks + comments together, in document order ──

def test_parse_marks_mixes_comments_and_suggestions_in_order():
    src = "{==a==}{>>note<<} then {++b++} then {--c--} then {~~d~>e~~}"
    kinds = [m.kind for m in mc.parse_marks(src)]
    assert kinds == [K.COMMENT, K.INSERT, K.DELETE, K.SUBSTITUTE]


def test_parse_stays_comment_only_back_compat():
    # the original comment API must not start returning suggestions
    src = "{==a==}{>>n<<} and {++added++}"
    assert [c.span for c in mc.parse(src)] == ["a"]
    assert [m.kind for m in mc.suggestions(src)] == [K.INSERT]


# ── code-region exclusion (examples are not marks) ──

def test_inline_code_example_is_not_a_suggestion():
    src = "write `{++like this++}` to insert"
    assert mc.suggestions(src) == []


def test_fenced_code_example_is_not_a_suggestion():
    src = "Example:\n\n```\n{~~old~>new~~} and {--gone--}\n```\n\ndone"
    assert mc.suggestions(src) == []


def test_real_suggestion_next_to_an_example_still_parses():
    src = "Use `{++x++}` then a real {++insert++} here."
    (m,) = mc.suggestions(src)
    assert m.added == "insert"


# ── tempering: a stray opener can't swallow the next mark ──

def test_tempered_insertions_do_not_swallow():
    src = "a {++one++} b {++two++} c"
    assert [m.added for m in mc.suggestions(src)] == ["one", "two"]


def test_overlapping_marks_resolved_left_to_right():
    # comment then an adjacent insertion both parse as separate marks
    src = "{==keep==}{>>why<<}{++ and more++}"
    kinds = [m.kind for m in mc.parse_marks(src)]
    assert kinds == [K.COMMENT, K.INSERT]


# ── projections: accept-all / reject-all ──

def test_accepted_applies_all_suggestions():
    src = "the {--very --}{~~quick~>swift~~} {++brown ++}fox"
    assert mc.accepted(src) == "the swift brown fox"


def test_rejected_reverts_all_suggestions():
    src = "the {--very --}{~~quick~>swift~~} {++brown ++}fox"
    assert mc.rejected(src) == "the very quick fox"


def test_projections_reduce_comments_to_span():
    src = "the {==quick==}{>>q?<<} fox"
    assert mc.accepted(src) == "the quick fox"
    assert mc.rejected(src) == "the quick fox"


# ── single accept / reject ──

def test_accept_single_substitution():
    src = "the {~~quick~>swift~~} fox and {++a ++}hare"
    sub = mc.suggestions(src)[0]
    assert mc.accept(src, sub) == "the swift fox and {++a ++}hare"


def test_reject_single_insertion_leaves_others():
    src = "the {~~quick~>swift~~} fox and {++a ++}hare"
    ins = mc.suggestions(src)[1]
    assert mc.reject(src, ins) == "the {~~quick~>swift~~} fox and hare"


def test_accept_then_reject_round_trip_is_clean():
    src = "x {--y --}z"
    (d,) = mc.suggestions(src)
    assert mc.accept(src, d) == "x z"      # deletion applied
    assert mc.reject(src, d) == "x y z"    # deletion reverted


# ── authoring ──

def test_render_helpers():
    assert mc.render_insert("hi") == "{++hi++}"
    assert mc.render_delete("bye") == "{--bye--}"
    assert mc.render_substitute("a", "b") == "{~~a~>b~~}"


def test_wrap_suggestion_substitution():
    src = "the quick fox"
    s0 = src.index("quick")
    out = mc.wrap_suggestion(src, s0, s0 + len("quick"), "swift")
    assert out == "the {~~quick~>swift~~} fox"
    (m,) = mc.suggestions(out)
    assert m.removed == "quick" and m.added == "swift"


def test_wrap_suggestion_insertion_at_caret():
    src = "the fox"
    pos = src.index("fox")
    out = mc.wrap_suggestion(src, pos, pos, "quick ")
    assert out == "the {++quick ++}fox"
    (m,) = mc.suggestions(out)
    assert m.kind == K.INSERT and m.added == "quick "


def test_wrap_suggestion_deletion_on_empty_replacement():
    src = "the very quick fox"
    s0 = src.index("very ")
    out = mc.wrap_suggestion(src, s0, s0 + len("very "), "")
    assert out == "the {--very --}quick fox"
    (m,) = mc.suggestions(out)
    assert m.kind == K.DELETE and m.removed == "very "


# ── to_rendered: visible text + role-tagged spans ──

def test_to_rendered_drops_markup_and_tags_roles():
    src = "the {--very --}{~~quick~>swift~~} {++brown ++}fox {==n==}{>>b<<}"
    md, spans = mc.to_rendered(src, start="<", end=">")
    # raw CriticMarkup is gone; visible text (struck old + new) is present
    assert "{++" not in md and "~>" not in md and "==}" not in md
    assert "<very >" in md and "<quick> <swift>" in md and "<brown >" in md
    roles = [s.role for s in spans]
    assert roles == ["removed", "removed", "added", "added", "comment"]


def test_to_rendered_substitution_separates_old_and_new():
    md, spans = mc.to_rendered("{~~a~>b~~}", start="<", end=">")
    assert md == "<a> <b>"            # a gap keeps struck-old off handwritten-new


def test_to_rendered_comment_matches_to_sentineled():
    # comment-only docs render exactly as the original comment path did
    src = "x {==y==}{>>z<<} w"
    md_new, _ = mc.to_rendered(src)
    md_old, _ = mc.to_sentineled(src)
    assert md_new == md_old


# ── guard: a span carrying markup can't be re-wrapped ──

def test_contains_markup_detects_suggestion_delimiters():
    assert mc.contains_markup("a {++ b") is True
    assert mc.contains_markup("a --} b") is True
    assert mc.contains_markup("a {~~ b") is True
    assert mc.contains_markup("plain prose") is False
