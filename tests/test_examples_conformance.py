"""Conformance sweep over the shipped example boards (#133).

The boards under examples/ are the exemplars agents learn from — a
format change that breaks one must fail CI loudly, not wait for the
next agent to trip over it. Every board must parse without dropped
lines, diagnose clean of error-severity findings (the #131 exit-code
gate), and render headless without exceptions. Warnings and infos are
allowed: showcase boards deliberately contain guidance-class findings.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from grafli.format import parse

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_BOARDS = sorted(EXAMPLES_DIR.rglob("*.grafli"))


def _rel(p: Path) -> str:
    return str(p.relative_to(EXAMPLES_DIR))


def test_sweep_actually_found_boards():
    # Guard the guard: an empty glob would green-light everything.
    assert len(EXAMPLE_BOARDS) >= 10


@pytest.mark.parametrize("board", EXAMPLE_BOARDS, ids=_rel)
def test_example_parses_without_dropped_lines(board):
    parsed = parse(board.read_text(encoding="utf-8"))
    dropped = [f"line {w.line}: {w.reason}" for w in parsed.parse_warnings]
    assert not dropped, f"{_rel(board)} drops lines: {dropped}"


@pytest.mark.parametrize("board", EXAMPLE_BOARDS, ids=_rel)
def test_example_diagnoses_clean_of_errors(board):
    from grafli.app import _cmd_diagnose
    assert _cmd_diagnose([str(board)]) == 0


@pytest.mark.parametrize("board", EXAMPLE_BOARDS, ids=_rel)
def test_example_renders_headless(board, tmp_path):
    from grafli.app import _cmd_render
    out = tmp_path / (board.stem + ".png")
    assert _cmd_render([str(board), str(out)]) == 0
    assert out.exists() and out.stat().st_size > 0
