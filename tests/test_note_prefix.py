"""Tests for task/question prefix detection on notes."""

from __future__ import annotations

from grafli.items import note_prefix


# ── Task prefixes ──────────────────────────────────────────────


def test_task_short_uppercase():
    assert note_prefix("T: do this") == ("T:", "do this")


def test_task_short_lowercase():
    assert note_prefix("t: do this") == ("T:", "do this")


def test_task_long_uppercase():
    assert note_prefix("TODO: do this") == ("T:", "do this")


def test_task_long_lowercase():
    assert note_prefix("todo: do this") == ("T:", "do this")


def test_task_long_mixed_case():
    assert note_prefix("Todo: do this") == ("T:", "do this")


# ── Question prefixes ──────────────────────────────────────────


def test_question_short_uppercase():
    assert note_prefix("Q: why?") == ("Q:", "why?")


def test_question_short_lowercase():
    assert note_prefix("q: why?") == ("Q:", "why?")


def test_question_long_uppercase():
    assert note_prefix("QUESTION: why?") == ("Q:", "why?")


def test_question_long_lowercase():
    assert note_prefix("question: why?") == ("Q:", "why?")


def test_question_long_mixed_case():
    assert note_prefix("Question: why?") == ("Q:", "why?")


# ── Negative cases ─────────────────────────────────────────────


def test_no_prefix_plain_text():
    assert note_prefix("just a note") is None


def test_no_prefix_unrelated_keyword():
    assert note_prefix("Topic: foo") is None


def test_no_prefix_missing_space():
    # The colon must be followed by whitespace
    assert note_prefix("T:no_space") is None
    assert note_prefix("TODO:no_space") is None


def test_no_prefix_empty():
    assert note_prefix("") is None


def test_only_prefix_with_no_body():
    # "T: " with empty body still detected; body is ""
    assert note_prefix("T: ") == ("T:", "")


def test_prefix_in_middle_not_detected():
    assert note_prefix("see T: above") is None
