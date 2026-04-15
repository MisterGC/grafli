"""Tests for code-mode note detection, body extraction, and tokenization."""

from __future__ import annotations

from grafli.code_note import code_body, is_code_note, tokenize_line


# ── Detection ──────────────────────────────────────────────────


def test_detects_basic_prefix():
    assert is_code_note("code: foo")


def test_detects_prefix_on_own_line():
    assert is_code_note("code:\nfoo\nbar")


def test_detects_prefix_with_leading_blank_lines():
    assert is_code_note("\n\ncode:\nbody")


def test_rejects_plain_note():
    assert not is_code_note("hello world")


def test_rejects_prefix_later_in_note():
    assert not is_code_note("hello\ncode: not this")


def test_rejects_empty_note():
    assert not is_code_note("")


# ── Body extraction ────────────────────────────────────────────


def test_body_strips_prefix_line():
    assert code_body("code:\nfoo\nbar") == "foo\nbar"


def test_body_keeps_content_on_prefix_line():
    assert code_body("code: fn: parseInput(raw)") == "fn: parseInput(raw)"


def test_body_strips_leading_blanks_before_prefix():
    assert code_body("\n\ncode:\nx") == "x"


# ── Tokenizer ──────────────────────────────────────────────────


def _concat(runs):
    return "".join(t for _, t in runs)


def test_tokenize_plain_line_has_no_keywords():
    runs = tokenize_line("log.emit(x)")
    assert all(k == "text" for k, _ in runs)
    assert _concat(runs) == "log.emit(x)"


def test_tokenize_fn_keyword():
    runs = tokenize_line("fn: parseInput(raw) -> Result")
    assert runs[0] == ("kw", "fn:")
    assert _concat(runs) == "fn: parseInput(raw) -> Result"


def test_tokenize_if_keyword():
    runs = tokenize_line("if: raw.isEmpty")
    assert ("kw", "if:") in runs


def test_tokenize_then_else_return_err():
    for kw in ("then", "else", "return", "err"):
        runs = tokenize_line(f"{kw}: something")
        assert runs[0] == ("kw", f"{kw}:")


def test_tokenize_set_assignment():
    runs = tokenize_line("set: tokens = raw.split(x)")
    assert runs[0] == ("kw", "set:")


def test_tokenize_for_iteration():
    runs = tokenize_line("for: t in tokens")
    assert runs[0] == ("kw", "for:")


def test_tokenize_keyword_with_indent():
    runs = tokenize_line("  then: stack.push(t)")
    # indent preserved as text, then keyword, then rest
    assert runs[0] == ("text", "  ")
    assert runs[1] == ("kw", "then:")
    assert _concat(runs) == "  then: stack.push(t)"


def test_non_keyword_colon_word_is_text():
    # Only the predefined keywords are highlighted
    runs = tokenize_line("banana: yellow")
    assert all(k == "text" for k, _ in runs)


def test_keyword_must_end_with_colon_and_space_or_eol():
    # "fn:foo" (no space after colon) does NOT match keyword pattern
    runs = tokenize_line("fn:foo")
    assert all(k == "text" for k, _ in runs)


def test_bare_keyword_with_no_rest():
    runs = tokenize_line("return:")
    assert runs == [("kw", "return:")]


def test_tokenize_reference_in_body():
    runs = tokenize_line("do: log.emit(x) @parser.py:120")
    assert any(k == "kw" and t == "@parser.py:120" for k, t in runs)
    assert _concat(runs) == "do: log.emit(x) @parser.py:120"


def test_tokenize_reference_on_plain_line():
    runs = tokenize_line("log.emit(x) @parser.py:12")
    assert any(k == "kw" and t == "@parser.py:12" for k, t in runs)


def test_tokenize_comment_at_end():
    runs = tokenize_line("return: out  # fallthrough")
    assert runs[-1] == ("comment", " # fallthrough")
    assert any(k == "kw" and t == "return:" for k, t in runs)


def test_tokenize_leading_comment():
    runs = tokenize_line("# just a note")
    assert runs == [("comment", "# just a note")]


def test_tokenize_roundtrip_preserves_content():
    line = "  if: t.startsWith(x)  # guard"
    assert _concat(tokenize_line(line)) == line
