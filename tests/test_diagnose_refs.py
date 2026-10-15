"""`diagnose` checks board links and code refs as the app opens them (#218)."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from grafli.diagnostics import check_board_links, check_code_refs
from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_OTHER = """\
#!grafli v3
@ box here "Here" 0,0 120x60
@ box there "There" 200,0 120x60
@ arrow here -> there ~id=hop
@ bookmark spot "Spot" @here
"""


def _board(tmp_path: Path, *lines: str) -> Path:
    board = tmp_path / "map.grafli"
    board.write_text("#!grafli v3\n" + "\n".join(lines) + "\n")
    return board


def _links(board: Path) -> list[tuple[str, str, list[str]]]:
    diags = check_board_links(parse(board.read_text()), board)
    return [(d.code, d.severity, d.item_ids) for d in diags]


def _code_note(*refs: str) -> str:
    body = "\n".join(f"call f()  {ref}" for ref in refs)
    return f'@ note n 0,200 """\ncode:\nf()\n{body}\n"""'


def _refs(board: Path) -> list[str]:
    diags = check_code_refs(parse(board.read_text()), board.parent)
    assert all(d.code == "dangling-code-ref" and d.severity == "error"
               for d in diags)
    return [d.message for d in diags]


# ── board links ────────────────────────────────────────────────────

def test_a_link_to_a_missing_board_is_an_error(tmp_path):
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60 &link:missing.grafli#nope')
    assert _links(board) == [("dangling-board-link", "error", ["a"])]


def test_a_link_to_an_id_the_board_lacks_is_an_error(tmp_path):
    (tmp_path / "other.grafli").write_text(_OTHER)
    board = _board(tmp_path, '@ box a "A" 0,0 120x60 &link:other.grafli#nope')
    diags = check_board_links(parse(board.read_text()), board)
    assert [d.message for d in diags] == [
        "'a' &link:other.grafli#nope: other.grafli has no bookmark, "
        "element or connector 'nope'"]


def test_links_to_a_bookmark_element_or_connector_pass(tmp_path):
    (tmp_path / "other.grafli").write_text(_OTHER)
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60 &link:other.grafli',
                   '@ box b "B" 200,0 120x60 &link:other.grafli#spot',
                   '@ box c "C" 400,0 120x60 &link:other.grafli#there',
                   '@ box d "D" 600,0 120x60 &link:other.grafli#hop')
    assert _links(board) == []


def test_a_graph_sub_board_is_checked_in_the_vault(tmp_path):
    vault = tmp_path / "map-res"
    vault.mkdir()
    (vault / "sub.grafli").write_text(_OTHER)
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60 &graph:sub#spot',
                   '@ box b "B" 200,0 120x60 &graph:sub#nope',
                   '@ box c "C" 400,0 120x60 &graph:gone')
    assert _links(board) == [("dangling-board-link", "error", ["b"]),
                             ("dangling-board-link", "error", ["c"])]


def test_a_link_on_a_connector_names_the_connector(tmp_path):
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60',
                   '@ box b "B" 200,0 120x60',
                   '@ arrow a -> b "go" &link:missing.grafli')
    assert _links(board) == [("dangling-board-link", "error", ["a->b"])]


def test_a_home_link_resolves_in_the_home_folder(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "other.grafli").write_text(_OTHER)
    monkeypatch.setenv("HOME", str(home))
    board = _board(tmp_path, '@ box a "A" 0,0 120x60 &link:~/other.grafli#spot',
                   '@ box b "B" 200,0 120x60 &link:~/other.grafli#nope')
    assert _links(board) == [("dangling-board-link", "error", ["b"])]


def test_web_links_and_other_files_are_no_board_links(tmp_path):
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60 &link:https://example.com/x.grafli',
                   '@ box b "B" 200,0 120x60 &link:notes.md')
    assert _links(board) == []


# ── code refs ──────────────────────────────────────────────────────

def test_a_ref_to_a_missing_file_is_an_error(tmp_path):
    board = _board(tmp_path, _code_note("@src/gone.py:3"))
    assert _refs(board) == [
        f"'n' refs @src/gone.py:3: {tmp_path}/src/gone.py does not exist"]


def test_a_ref_past_the_last_line_is_an_error(tmp_path):
    (tmp_path / "file.py").write_text("a\nb\nc\n")
    board = _board(tmp_path, _code_note("@file.py:99999", "@file.py:0",
                                        "@file.py:3", "@file.py"))
    assert _refs(board) == [
        "'n' refs @file.py:99999: file.py has 3 lines, no line 99999",
        "'n' refs @file.py:0: file.py has 3 lines, no line 0"]


def test_a_last_line_without_a_newline_counts(tmp_path):
    (tmp_path / "file.py").write_text("a\nb")
    board = _board(tmp_path, _code_note("@file.py:2", "@file.py:3"))
    assert _refs(board) == [
        "'n' refs @file.py:3: file.py has 2 lines, no line 3"]


def test_refs_resolve_against_a_home_source_repo(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "repo" / "src").mkdir(parents=True)
    (home / "repo" / "src" / "x.py").write_text("a\nb\nc\n")
    monkeypatch.setenv("HOME", str(home))
    board = _board(tmp_path, "# source: ~/repo", _code_note("@src/x.py:3"))
    assert _refs(board) == []


def test_an_absolute_ref_is_taken_as_is(tmp_path):
    (tmp_path / "file.py").write_text("a\n")
    board = _board(tmp_path, "# source: elsewhere",
                   _code_note(f"@{tmp_path}/file.py:1"))
    assert _refs(board) == []


def test_only_refs_the_app_makes_clickable_are_checked(tmp_path):
    # A plain note or a box label shows `@x.py` as text, and a `# comment`
    # in a code note is not tokenized for refs — no click opens them.
    board = _board(tmp_path,
                   '@ box a "see @gone.py:1" 0,0 120x60',
                   '@ note p 0,100 "see @gone.py:1"',
                   '@ note n 0,200 """\ncode:\nf()\n# @gone.py:1\n"""')
    assert _refs(board) == []


# ── the app and diagnose agree ─────────────────────────────────────

class _Settings:
    def __init__(self, *_args):
        pass

    def value(self, *_args, **_kw):
        return "ed {path}:{line}"


def test_diagnose_checks_the_file_the_app_opens(tmp_path, monkeypatch):
    import grafli.view.resources as res
    from grafli.format import resolve_code_ref
    QApplication.instance() or QApplication([])
    home = tmp_path / "home"
    (home / "repo" / "src").mkdir(parents=True)
    (home / "repo" / "src" / "x.py").write_text("a\nb\nc\n")
    monkeypatch.setenv("HOME", str(home))
    board = _board(tmp_path, "# source: ~/repo @ a1b2c3d",
                   _code_note("@src/x.py:3"))
    view = GrafliView()
    view._file_path = board
    view.load_board(parse(board.read_text()))
    launched: list[list[str]] = []
    monkeypatch.setattr(res, "QSettings", _Settings)
    monkeypatch.setattr(res.subprocess, "Popen",
                        lambda argv, **_kw: launched.append(argv))
    view._open_code_ref("@src/x.py:3")
    path, line = resolve_code_ref(parse(board.read_text()), tmp_path,
                                  "@src/x.py:3")
    assert launched == [["ed", f"{path.resolve()}:{line}"]]
    assert path.resolve() == (home / "repo/src/x.py").resolve()


# ── the CLI ────────────────────────────────────────────────────────

def test_the_cli_exits_one_on_a_dangling_link(tmp_path):
    from grafli.app import _cmd_diagnose
    board = _board(tmp_path,
                   '@ box a "A" 0,0 120x60 &link:missing.grafli#nope')
    assert _cmd_diagnose([str(board)]) == 1
