"""`grafli fmt` — canonical rewrite for boards that never pass through
the app's save path (issue #20).

Agent- and hand-authored files get the same normalization the app applies
on save: quantized coordinates, canonical token order and spacing — while
line order, comments, and blank lines survive. Malformed files are left
untouched: a blind rewrite would demote their broken lines to comments.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from grafli.app import _cmd_fmt


def test_fmt_quantizes_and_rewrites(tmp_path: Path):
    f = tmp_path / "b.grafli"
    f.write_text('#!grafli v1\n'
                 '# layout notes survive\n'
                 '\n'
                 '@ box a "A" 1476.537054409133,217.99831588774094 200x80\n'
                 '@ arrow a -> a2\n'
                 '@ box a2 "B" 10.0,20.0 120.5x60.4\n')
    assert _cmd_fmt([str(f)]) == 0
    out = f.read_text()
    assert '@ box a "A" 1477,218 200x80' in out
    assert '@ box a2 "B" 10,20 120x60' in out
    # Line order, the comment, and the blank line all survive.
    lines = out.splitlines()
    assert lines[1] == '# layout notes survive'
    assert lines[2] == ''
    assert lines.index('@ arrow a -> a2') < lines.index('@ box a2 "B" 10,20 120x60')


def test_fmt_is_idempotent(tmp_path: Path):
    f = tmp_path / "b.grafli"
    f.write_text('@ box a "A" 3.7,4.2 200x80\n')
    assert _cmd_fmt([str(f)]) == 0
    once = f.read_text()
    assert _cmd_fmt([str(f)]) == 0
    assert f.read_text() == once


def test_fmt_check_reports_without_writing(tmp_path: Path, capsys):
    f = tmp_path / "b.grafli"
    src = '@ box a "A" 3.7,4.2 200x80\n'
    f.write_text(src)
    assert _cmd_fmt(["--check", str(f)]) == 1
    assert f.read_text() == src
    assert "would format" in capsys.readouterr().out


def test_fmt_check_clean_file_exits_zero(tmp_path: Path):
    f = tmp_path / "b.grafli"
    f.write_text('#!grafli v1\n@ box a "A" 0,0 200x80\n')
    assert _cmd_fmt(["--check", str(f)]) == 0
    assert _cmd_fmt([str(f)]) == 0


def test_fmt_refuses_malformed_files(tmp_path: Path, capsys):
    f = tmp_path / "b.grafli"
    src = '#!grafli v1\n@ box bad "B" 0,0 200\n@ box ok "OK" 3.5,0 200x80\n'
    f.write_text(src)
    assert _cmd_fmt([str(f)]) == 2
    assert f.read_text() == src                      # nothing rewritten
    err = capsys.readouterr().err
    assert "malformed @ box" in err
    assert "left untouched" in err


def test_fmt_missing_file_is_a_usage_error(tmp_path: Path):
    assert _cmd_fmt([str(tmp_path / "nope.grafli")]) == 2
