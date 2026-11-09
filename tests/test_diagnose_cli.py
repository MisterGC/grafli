"""`grafli diagnose` CLI: gateable exit codes (#131).

0 when no gated findings, 1 when errors are present (with --strict also
on warnings), 2 for usage/IO problems — so agent loops and CI can run
"fix until diagnose passes" without parsing output.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from grafli.app import _cmd_diagnose

CLEAN = """#!grafli v1
# Clean board
@ box a "Alpha" 0,0 200x100
@ box b "Beta" 300,0 200x100
@ arrow a -> b
"""

# A malformed directive demotes to a comment -> parse-error (severity error).
WITH_ERROR = """#!grafli v1
@ box a 0,0 200x100 "Alpha"
"""

# Unknown %color is a warning-severity finding on an otherwise valid board.
WITH_WARNING = """#!grafli v1
@ box a "Alpha" 0,0 200x100 %green
"""


def _write(tmp_path, text):
    p = tmp_path / "board.grafli"
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_board_exits_zero(tmp_path):
    p = _write(tmp_path, CLEAN)
    assert _cmd_diagnose([str(p)]) == 0
    assert _cmd_diagnose([str(p), "--strict"]) == 0


def test_errors_exit_one(tmp_path):
    p = _write(tmp_path, WITH_ERROR)
    assert _cmd_diagnose([str(p)]) == 1


def test_warnings_pass_unless_strict(tmp_path):
    p = _write(tmp_path, WITH_WARNING)
    assert _cmd_diagnose([str(p)]) == 0
    assert _cmd_diagnose([str(p), "--strict"]) == 1


def test_json_output_carries_the_same_exit_code(tmp_path):
    p = _write(tmp_path, WITH_ERROR)
    assert _cmd_diagnose([str(p), "--json"]) == 1


def test_missing_input_exits_two(tmp_path):
    assert _cmd_diagnose([str(tmp_path / "nope.grafli")]) == 2


# Two labelled arrows that cross: the canvas centres both labels on the
# crossing point (#192). The a/b pair is two-way and draws one label.
CROSSING = """#!grafli v1
@ box a "A" 0,0 100x60
@ box b "B" 400,0 100x60
@ box c "C" 0,300 100x60
@ box d "D" 400,300 100x60
@ arrow a -> d "goes down"
@ arrow c -> b "goes up"
@ arrow a -> b "there"
@ arrow b -> a "back"
"""


def test_crossing_arrow_labels_are_reported(tmp_path, capsys):
    import json
    p = _write(tmp_path, CROSSING)
    assert _cmd_diagnose([str(p), "--json"]) == 0
    found = [d for d in json.loads(capsys.readouterr().out)
             if d["code"] == "arrow-labels-overlap"]
    assert len(found) == 1
    assert found[0]["item_ids"] == ["a", "d", "c", "b"]
    assert "'a' -> 'd'" in found[0]["message"]
    assert "'c' -> 'b'" in found[0]["message"]


def test_offset_arrow_label_clears_the_overlap(tmp_path, capsys):
    p = _write(tmp_path, CROSSING.replace('"goes up"', '"goes up" @0,40'))
    assert _cmd_diagnose([str(p), "--json"]) == 0
    assert "arrow-labels-overlap" not in capsys.readouterr().out
