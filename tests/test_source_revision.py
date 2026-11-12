"""A board's ``# source: <repo> @ <rev>`` names the revision its refs were
read at; diagnose and the app say when the repo's HEAD moved on (#188)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.diagnostics import INFO, WARNING, check_stale_source, run_all
from grafli.format import parse
from grafli.revision import refs_stale_line, revisions_match


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[str, str]:
    """A repo beside the board with two commits: (older, HEAD)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    revs = []
    for text in ("one", "two"):
        (repo / "f.txt").write_text(text)
        _git(repo, "add", "f.txt")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit",
             "-qm", text)
        revs.append(_git(repo, "rev-parse", "HEAD"))
    return revs[0], revs[1]


def _board(source: str) -> str:
    return f"#!grafli v2\n{source}\n@ box a \"A @f.txt:1\" 0,0 160x60\n"


# ── the revision check ─────────────────────────────────────────────

def test_a_short_revision_matches_the_full_head():
    assert revisions_match("A1B2C3D", "a1b2c3d4e5f6")
    assert not revisions_match("a1b2c3e", "a1b2c3d4e5f6")


def test_a_board_read_at_head_is_not_stale(tmp_path):
    _, head = _repo(tmp_path)
    board = parse(_board(f"# source: repo @ {head[:7]}"))
    assert refs_stale_line(board, tmp_path) == ""


def test_a_board_read_at_an_older_revision_is_stale(tmp_path):
    old, head = _repo(tmp_path)
    board = parse(_board(f"# source: repo @ {old[:7]}"))
    assert refs_stale_line(board, tmp_path) == (
        f"refs read at {old[:7]}, repo is at {head[:7]} — "
        "@path:line refs may open moved lines")


def test_without_a_revision_nothing_is_checked(tmp_path):
    _repo(tmp_path)
    assert refs_stale_line(parse(_board("# source: repo")), tmp_path) == ""
    assert refs_stale_line(parse(_board("# a map")), tmp_path) == ""


def test_a_repo_git_cannot_read_says_so(tmp_path):
    (tmp_path / "repo").mkdir()
    board = parse(_board("# source: repo @ a1b2c3d"))
    assert refs_stale_line(board, tmp_path) == (
        "refs stale? cannot read the HEAD of repo")


# ── diagnose ───────────────────────────────────────────────────────

def test_diagnose_warns_when_the_repo_moved_on(tmp_path):
    old, head = _repo(tmp_path)
    board = parse(_board(f"# source: repo @ {old[:7]}"))
    [diag] = check_stale_source(board, tmp_path)
    assert (diag.code, diag.severity, diag.fixable) == (
        "stale-source", WARNING, False)
    assert diag.message.startswith(f"refs read at {old[:7]}, repo is at "
                                   f"{head[:7]}")
    assert [d.code for d in run_all(board, tmp_path)].count(
        "stale-source") == 1


def test_diagnose_is_quiet_at_head_and_info_when_unreadable(tmp_path):
    _, head = _repo(tmp_path)
    assert check_stale_source(
        parse(_board(f"# source: repo @ {head}")), tmp_path) == []
    [diag] = check_stale_source(
        parse(_board("# source: gone @ a1b2c3d")), tmp_path)
    assert diag.severity == INFO
    assert check_stale_source(
        parse(_board(f"# source: repo @ {head}")), None) == []


def test_diagnose_cli_gates_a_stale_board_under_strict(tmp_path, capsys):
    from grafli.app import _cmd_diagnose
    old, _ = _repo(tmp_path)
    path = tmp_path / "map.grafli"
    path.write_text(_board(f"# source: repo @ {old[:7]}"))
    assert _cmd_diagnose([str(path), "--json"]) == 0
    codes = [d["code"] for d in json.loads(capsys.readouterr().out)]
    assert codes == ["stale-source"]
    assert _cmd_diagnose([str(path), "--strict"]) == 1
    assert "[warning] stale-source: refs read at" in capsys.readouterr().out


# ── the app ────────────────────────────────────────────────────────

def _opened(tmp_path: Path, source: str):
    from grafli.app import MainWindow
    QApplication.instance() or QApplication([])
    path = tmp_path / "map.grafli"
    path.write_text(_board(source))
    return MainWindow(str(path))


def test_opening_a_stale_board_shows_the_notice(tmp_path):
    old, head = _repo(tmp_path)
    win = _opened(tmp_path, f"# source: repo @ {old[:7]}")
    assert win._view._toast_text == (
        f"Refs read at {old[:7]}, repo is at {head[:7]} — "
        "@path:line refs may open moved lines")
    assert win._view._toast_kind == "warn"


def test_opening_a_board_at_head_shows_no_notice(tmp_path):
    _, head = _repo(tmp_path)
    win = _opened(tmp_path, f"# source: repo @ {head[:7]}")
    assert win._view._toast_text == ""
