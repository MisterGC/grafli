"""Code refs resolve against the board's ``# source:`` repo (#217)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from grafli.diagnostics import check_missing_resource
from grafli.format import board_source, parse, ref_root
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BODY = """\
@ box a "A" 0,0 120x60
@ note n 0,200 \"\"\"
code:
the evidence
  @src/x.py:3
\"\"\"
@ bookmark all "All of it" @a,n "Where the code is."
@ flow tour "Tour" all
"""

_SOURCED = "#!grafli v2\n# source: repo @ a1b2c3d\n" + _BODY
_PLAIN = "#!grafli v2\n" + _BODY


def _tree(tmp_path: Path, src: str = _SOURCED) -> Path:
    """A board beside a repo that holds ``src/x.py``."""
    (tmp_path / "repo" / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "repo" / "src" / "x.py").write_text("a\nb\nc\n")
    board = tmp_path / "map.grafli"
    board.write_text(src)
    return board


# ── the comment ────────────────────────────────────────────────────

def test_board_source_reads_the_repo_and_revision():
    assert board_source(parse(_SOURCED)) == ("repo", "a1b2c3d")
    assert board_source(parse("# source: ~/dev/my repo\n")) == (
        "~/dev/my repo", "")
    assert board_source(parse(_PLAIN)) is None


def test_ref_root_takes_the_repo_from_the_board_directory(tmp_path):
    assert ref_root(parse(_SOURCED), tmp_path) == tmp_path / "repo"
    assert ref_root(parse("# source: /abs/repo @ 1\n"), tmp_path) == Path(
        "/abs/repo")
    assert ref_root(parse("# source: ~/r\n"), tmp_path) == Path(
        "~/r").expanduser()
    assert ref_root(parse(_PLAIN), tmp_path) == tmp_path


# ── diagnose ───────────────────────────────────────────────────────

def test_diagnose_finds_a_ref_in_the_source_repo(tmp_path):
    board = _tree(tmp_path)
    diags = check_missing_resource(parse(board.read_text()), tmp_path)
    assert [d for d in diags if d.code == "missing-resource"] == []


def test_diagnose_reports_a_ref_missing_from_the_source_repo(tmp_path):
    board = _tree(tmp_path, _SOURCED.replace("src/x.py", "src/y.py"))
    diags = check_missing_resource(parse(board.read_text()), tmp_path)
    assert [d.message for d in diags] == [
        "'n' references 'src/y.py' which does not exist"]


def test_diagnose_without_the_comment_resolves_against_the_board(tmp_path):
    board = _tree(tmp_path, _PLAIN)
    diags = check_missing_resource(parse(board.read_text()), tmp_path)
    assert [d.message for d in diags] == [
        "'n' references 'src/x.py' which does not exist"]
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("")
    assert check_missing_resource(parse(board.read_text()), tmp_path) == []


def test_diagnose_cli_passes_a_sourced_board(tmp_path, capsys):
    from grafli.app import _cmd_diagnose
    board = _tree(tmp_path)
    assert _cmd_diagnose([str(board), "--json"]) == 0
    codes = [d["code"] for d in json.loads(capsys.readouterr().out)]
    assert "missing-resource" not in codes


# ── the app ────────────────────────────────────────────────────────

def _view_of(board: Path) -> GrafliView:
    view = GrafliView()
    view._file_path = board      # the view is its own window here
    view.load_board(parse(board.read_text()))
    return view


class _Settings:
    def __init__(self, *_args):
        pass

    def value(self, *_args, **_kw):
        return "ed {path}:{line}"


def _opened(monkeypatch, tmp_path: Path, src: str) -> list[list[str]]:
    import grafli.view.resources as res
    QApplication.instance() or QApplication([])
    board = _tree(tmp_path, src)
    view = _view_of(board)
    launched: list[list[str]] = []
    monkeypatch.setattr(res, "QSettings", _Settings)
    monkeypatch.setattr(res.subprocess, "Popen",
                        lambda argv, **_kw: launched.append(argv))
    view._open_code_ref("@src/x.py:3")
    return launched


def test_the_app_opens_a_ref_in_the_source_repo(tmp_path, monkeypatch):
    assert _opened(monkeypatch, tmp_path, _SOURCED) == [
        ["ed", f"{(tmp_path / 'repo/src/x.py').resolve()}:3"]]


def test_the_app_without_the_comment_opens_beside_the_board(
        tmp_path, monkeypatch):
    assert _opened(monkeypatch, tmp_path, _PLAIN) == [
        ["ed", f"{(tmp_path / 'src/x.py').resolve()}:3"]]


def test_an_overlay_without_a_repo_takes_the_boards_source(
        tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    board = _tree(tmp_path)
    vault = tmp_path / "map-res"
    vault.mkdir()
    (vault / "tests.overlay.json").write_text(json.dumps({
        "title": "Tests", "kind": "category",
        "categories": [{"id": "fail", "label": "Failing", "color": "#f00"}],
        "entries": {"a": {"category": "fail", "refs": ["@src/x.py:3"]}},
    }))
    view = _view_of(board)
    view.show_overlay("tests")
    view._box_items["a"].setSelected(True)
    view.viewport().grab()
    opened = []
    monkeypatch.setattr(view, "_open_code_ref", opened.append)
    rect, _ref = view._overlay_ref_rects[0]
    assert view._overlay_legend_press(rect.center())
    assert opened == [f"@{tmp_path / 'repo/src/x.py'}:3"]


# ── render and the exports ─────────────────────────────────────────

def test_render_draws_a_sourced_board_as_one_without_it(tmp_path):
    """The comment only moves where a ref opens; the ref is drawn as
    written, so the render is pixel-identical."""
    from grafli.app import _cmd_render
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sourced = _tree(tmp_path / "a")
    plain = _tree(tmp_path / "b", _PLAIN)
    assert _cmd_render([str(sourced), str(tmp_path / "a.png")]) == 0
    assert _cmd_render([str(plain), str(tmp_path / "b.png")]) == 0
    assert QImage(str(tmp_path / "a.png")) == QImage(str(tmp_path / "b.png"))


def test_the_pdf_export_shows_the_ref_as_written(tmp_path):
    from PySide6.QtPdf import QPdfDocument

    from grafli.app import _cmd_export
    board = _tree(tmp_path)
    out = tmp_path / "tour.pdf"
    assert _cmd_export([str(board), str(out)]) == 0
    doc = QPdfDocument()
    doc.load(str(out))
    text = "\n".join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    doc.close()
    assert "@src/x.py:3" in text


def test_the_html_export_keeps_the_ref_as_written(tmp_path):
    from grafli.app import _cmd_export_html
    board = _tree(tmp_path)
    out = tmp_path / "map.html"
    assert _cmd_export_html([str(board), str(out)]) == 0
    page = out.read_text()
    assert "src/x.py:3" in page
    assert str(tmp_path) not in page
