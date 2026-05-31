"""Tests for Markdown-mode note detection and body extraction."""

from __future__ import annotations

from grafli.md_note import is_md_note, md_body


# ── Detection ──────────────────────────────────────────────────


def test_detects_md_prefix():
    assert is_md_note("md: hello")


def test_detects_markdown_alias():
    assert is_md_note("markdown:\n# Title")


def test_detects_prefix_on_own_line():
    assert is_md_note("md:\n# Title\nbody")


def test_detects_prefix_with_leading_blank_lines():
    assert is_md_note("\n\nmd:\nbody")


def test_rejects_plain_note():
    assert not is_md_note("hello world")


def test_rejects_prefix_later_in_note():
    assert not is_md_note("hello\nmd: not this")


def test_rejects_empty_note():
    assert not is_md_note("")


def test_does_not_confuse_with_other_prefixes():
    assert not is_md_note("model: something")


# ── Body extraction ────────────────────────────────────────────


def test_body_strips_prefix_line():
    assert md_body("md:\n# Title\nbody") == "# Title\nbody"


def test_body_keeps_content_on_prefix_line():
    assert md_body("md: # Inline title") == "# Inline title"


def test_body_strips_markdown_alias():
    assert md_body("markdown:\n- a\n- b") == "- a\n- b"


def test_body_strips_leading_blanks_before_prefix():
    assert md_body("\n\nmd:\nx") == "x"


def test_body_preserves_blank_lines_within_body():
    assert md_body("md:\npara one\n\npara two") == "para one\n\npara two"
