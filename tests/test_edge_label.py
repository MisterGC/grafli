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


# ── cardinality (#260) ─────────────────────────────────────────────


def test_split_cardinality_takes_a_leading_count_off_the_relation():
    from grafli.edge_label import split_cardinality
    assert split_cardinality("N:N included in") == ("N:N", "included in")
    assert split_cardinality("1") == ("1", "")
    assert split_cardinality("N") == ("N", "")
    assert split_cardinality("0..1 owner") == ("0..1", "owner")
    assert split_cardinality("1..* items") == ("1..*", "items")


def test_split_cardinality_leaves_words_alone():
    from grafli.edge_label import split_cardinality
    for text in ("Nodes", "none", "N/A", "2nd step", "depends on", ""):
        assert split_cardinality(text) == ("", text)


def test_a_label_with_a_cardinality_is_as_wide_as_it_is_drawn():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QFontMetricsF
    from PySide6.QtWidgets import QApplication
    from grafli.edge_label import arrow_label_font
    QApplication.instance() or QApplication([])
    font = arrow_label_font()
    bold = QFont(font)
    bold.setBold(True)
    item = LabelItem("N:N included in")
    item.setFont(font)
    expected = (QFontMetricsF(bold).horizontalAdvance("N:N")
                + QFontMetricsF(font).horizontalAdvance(" included in"))
    assert item.boundingRect().width() == expected
