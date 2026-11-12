"""The tour example in the skill's presenting.md (#221): it passes
`export --check`, the overloaded slide the text quotes is what the check
prints for the variant it describes, and the legibility table holds."""

from __future__ import annotations

import contextlib
import io
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.app import _cmd_export

REPO = Path(__file__).resolve().parent.parent
PRESENTING = REPO / "grafli" / "skills" / "grafli" / "references" / "presenting.md"
SECTION = "## Slides from a map — frame, legibility, headline"


def _section() -> str:
    text = PRESENTING.read_text()
    return text.split(SECTION, 1)[1].split("\n## ", 1)[0]


def _check(tmp_path: Path, board: str) -> tuple[int, str]:
    QApplication.instance() or QApplication([])
    path = tmp_path / "map.grafli"
    path.write_text(board)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = _cmd_export([str(path), "--check"])
    return code, out.getvalue()


def test_the_example_tour_passes_export_check(tmp_path: Path):
    board, _finding = re.findall(r"```\n(.*?)```", _section(), re.S)
    code, out = _check(tmp_path, board)
    assert code == 0, out
    assert "No findings." in out


def test_the_quoted_overload_is_what_the_check_prints(tmp_path: Path):
    board, finding = re.findall(r"```\n(.*?)```", _section(), re.S)
    # The variant the text describes: the third stop unscoped, why_same
    # 40 px lower.
    board = board.replace("@ note why_same 560,200", "@ note why_same 560,240")
    board = board.replace("slides,why_same ~iso", "slides,why_same")
    code, out = _check(tmp_path, board)
    assert code == 1
    assert finding.strip() in out


def test_a_default_note_is_legible_up_to_about_1060_px_wide(tmp_path: Path):
    note = ("This note carries a full sentence of explanation, long enough "
            "to count as substance on a slide.")

    def frame(width: int) -> str:
        # The note at the left, a dot at the right: the frame spans `width`.
        return (f'#!grafli v2\n@ note n 0,0 "{note}"\n'
                f'@ box r "" {width - 12},0 10x10\n'
                f'@ bookmark bm "Claim" @n,r ~pad=1\n@ flow f "F" bm\n')

    assert _check(tmp_path, frame(1000))[0] == 0
    code, out = _check(tmp_path, frame(1120))
    assert code == 1 and "note 'n'" in out
