"""Tests for code-mode note detection, body extraction, and tokenization."""

from __future__ import annotations

from grafli.code_note import (
    code_body,
    is_code_note,
    split_signature,
    tokenize_line,
)


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


def test_tokenize_if_keyword():
    runs = tokenize_line("if: raw.isEmpty")
    assert ("kw_struct", "if:") in runs


def test_tokenize_keyword_without_colon():
    runs = tokenize_line("if raw.isEmpty")
    assert runs[0] == ("kw_struct", "if")


def test_tokenize_then_else_return_struct():
    for kw in ("then", "else", "return"):
        runs = tokenize_line(f"{kw} something")
        assert runs[0] == ("kw_struct", kw)


def test_tokenize_err_is_contract():
    runs = tokenize_line("err BadInput")
    assert runs[0] == ("kw_contract", "err")


def test_set_is_no_longer_a_keyword():
    runs = tokenize_line("set: tokens = raw.split(x)")
    assert all(k == "text" for k, _ in runs)


def test_note_is_no_longer_a_keyword():
    runs = tokenize_line("note: skip whitespace")
    assert all(k == "text" for k, _ in runs)


def test_fn_is_no_longer_a_keyword():
    # fn is now implicit on the signature line — not a keyword
    runs = tokenize_line("fn: parseInput(raw) -> Result")
    assert all(k == "text" for k, _ in runs)


def test_tokenize_struct_keywords():
    for kw in ("try", "catch"):
        runs = tokenize_line(f"{kw} something")
        assert runs[0] == ("kw_struct", kw)


def test_tokenize_effect_keywords():
    for kw in ("call", "await", "emit", "state"):
        runs = tokenize_line(f"{kw} something")
        assert runs[0] == ("kw_effect", kw)


def test_tokenize_contract_keywords():
    for kw in ("assert", "pre", "post", "verify", "risk"):
        runs = tokenize_line(f"{kw} something")
        assert runs[0] == ("kw_contract", kw)


def test_tokenize_for_iteration():
    runs = tokenize_line("for t in tokens")
    assert runs[0] == ("kw_struct", "for")


def test_tokenize_keyword_with_indent():
    runs = tokenize_line("  then stack.push(t)")
    # indent preserved as text, then keyword, then rest
    assert runs[0] == ("text", "  ")
    assert runs[1] == ("kw_struct", "then")
    assert _concat(runs) == "  then stack.push(t)"


def test_non_keyword_colon_word_is_text():
    # Only the predefined keywords are highlighted
    runs = tokenize_line("banana: yellow")
    assert all(k == "text" for k, _ in runs)


def test_keyword_glued_to_token_is_text():
    # "ifoo" should not match as `if`+`oo`; needs space or colon boundary
    runs = tokenize_line("ifoo")
    assert all(k == "text" for k, _ in runs)


def test_bare_keyword_with_no_rest():
    assert tokenize_line("return:") == [("kw_struct", "return:")]
    assert tokenize_line("return") == [("kw_struct", "return")]


def test_tokenize_reference_in_body():
    runs = tokenize_line("do: log.emit(x) @parser.py:120")
    assert any(k == "ref" and t == "@parser.py:120" for k, t in runs)
    assert _concat(runs) == "do: log.emit(x) @parser.py:120"


def test_tokenize_reference_on_plain_line():
    runs = tokenize_line("log.emit(x) @parser.py:12")
    assert any(k == "ref" and t == "@parser.py:12" for k, t in runs)


def test_tokenize_string_literal():
    runs = tokenize_line('post: audit trail includes "order.created"')
    assert any(k == "string" and t == '"order.created"' for k, t in runs)
    assert _concat(runs) == 'post: audit trail includes "order.created"'


def test_tokenize_comment_at_end():
    runs = tokenize_line("return out  # fallthrough")
    assert runs[-1] == ("comment", " # fallthrough")
    assert any(k == "kw_struct" and t == "return" for k, t in runs)


def test_tokenize_integer_value():
    runs = tokenize_line("retry = 3")
    assert any(k == "number" and t == "3" for k, t in runs)


def test_tokenize_float_value():
    runs = tokenize_line("alpha = 0.85")
    assert any(k == "number" and t == "0.85" for k, t in runs)


def test_tokenize_negative_number():
    runs = tokenize_line("offset = -12")
    assert any(k == "number" and t == "-12" for k, t in runs)


def test_tokenize_bool_lowercase():
    runs = tokenize_line("done = false")
    assert any(k == "bool" and t == "false" for k, t in runs)


def test_tokenize_bool_capitalised():
    runs = tokenize_line("done = True")
    assert any(k == "bool" and t == "True" for k, t in runs)


def test_tokenize_hex_color():
    runs = tokenize_line("bg = #F2F0EB")
    assert any(k == "hex" and t == "#F2F0EB" for k, t in runs)


def test_tokenize_hex_with_alpha():
    runs = tokenize_line("tint = #F2F0EBAA")
    assert any(k == "hex" and t == "#F2F0EBAA" for k, t in runs)


def test_hex_not_treated_as_comment():
    # ``#F2F0EB`` after whitespace must be a hex literal, not a comment
    runs = tokenize_line("bg = #F2F0EB")
    assert all(k != "comment" for k, _ in runs)


def test_trailing_comment_after_hex_still_works():
    runs = tokenize_line("bg = #F2F0EB  # warm paper")
    kinds = [k for k, _ in runs]
    assert "hex" in kinds
    assert kinds[-1] == "comment"


def test_number_inside_word_not_highlighted():
    # ``v2`` and ``MAX42`` are identifiers, not numbers
    runs = tokenize_line("name = v2")
    assert all(k != "number" for k, _ in runs)


def test_string_with_digits_not_split():
    runs = tokenize_line('msg = "code 42 ok"')
    # The digits inside the string stay part of the string run
    assert any(k == "string" and t == '"code 42 ok"' for k, t in runs)
    assert all(k != "number" for k, _ in runs)


# ── Signature detection ────────────────────────────────────────


def test_signature_first_line_when_not_keyword():
    idx, lines = split_signature("code:\ntokenize(raw) -> [Token]\nif foo")
    assert idx == 0
    assert lines[0] == "tokenize(raw) -> [Token]"


def test_signature_legacy_fn_prefix_stripped():
    idx, lines = split_signature("code:\nfn: tokenize(raw)\nif foo")
    assert idx == 0
    assert lines[0] == "tokenize(raw)"


def test_signature_legacy_fn_no_colon_stripped():
    idx, lines = split_signature("code:\nfn tokenize(raw)\nif foo")
    assert idx == 0
    assert lines[0] == "tokenize(raw)"


def test_no_signature_when_first_line_is_keyword():
    idx, lines = split_signature("code:\npre user is authenticated\nverify auth.py:1")
    assert idx is None
    assert lines[0] == "pre user is authenticated"


def test_signature_skips_leading_blank():
    idx, lines = split_signature("code:\n\ntokenize()\n")
    assert idx == 1
    assert lines[1] == "tokenize()"


def test_signature_preserves_indent_when_stripping_fn():
    idx, lines = split_signature("code:\n  fn: foo()\n")
    assert idx == 0
    assert lines[0] == "  foo()"


def test_tokenize_leading_comment():
    runs = tokenize_line("# just a note")
    assert runs == [("comment", "# just a note")]


def test_tokenize_roundtrip_preserves_content():
    line = "  if: t.startsWith(x)  # guard"
    assert _concat(tokenize_line(line)) == line
