"""Tests for semantic arrow-label prefix parsing."""

from __future__ import annotations

from grafli.edge_label import parse_edge_label
from grafli.items import LabelItem


def test_parse_known_edge_kind():
    parsed = parse_edge_label("data: user_id")
    assert parsed.kind == "data"
    assert parsed.body == "user_id"


def test_parse_known_edge_kind_case_insensitive():
    parsed = parse_edge_label("CALL: validate(input)")
    assert parsed.kind == "call"
    assert parsed.body == "validate(input)"


def test_unknown_colon_prefix_stays_plain():
    parsed = parse_edge_label("latency: p95")
    assert parsed.kind == ""
    assert parsed.body == "latency: p95"


def test_plain_label_stays_plain():
    parsed = parse_edge_label("queries")
    assert parsed.kind == ""
    assert parsed.body == "queries"


def test_label_display_text_strips_known_prefix():
    assert LabelItem._display_text("data: user_id") == "user_id"


def test_label_display_text_keeps_unknown_prefix():
    assert LabelItem._display_text("latency: p95") == "latency: p95"


def test_label_display_text_per_line():
    raw = "call: validate()\nlatency: p95\nqueries"
    assert LabelItem._display_text(raw) == "validate()\nlatency: p95\nqueries"
