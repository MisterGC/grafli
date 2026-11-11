"""The key table (`grafli/keymap.py`, #324): the F1 help shows every row of it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QTabWidget, QTextBrowser

from grafli import keymap


def _app():
    return QApplication.instance() or QApplication([])


def _rows(where: str):
    for g in keymap.groups(where):
        for k in g.keys:
            yield g, k


def test_every_group_is_in_the_app_or_the_tab_and_has_keys():
    ids = [g.id for g in keymap.GROUPS]
    assert len(ids) == len(set(ids))
    for g in keymap.GROUPS:
        assert g.where in (keymap.APP, keymap.TAB), g.id
        assert g.keys, g.id
        for k in g.keys:
            assert k.keys.strip() and k.does.strip(), (g.id, k)


@pytest.mark.parametrize("notation, text", [
    ("g z", "gz"),
    ("Shift+Z", "⇧Z"),
    ("Ctrl+R / Cmd+Shift+Z", "Ctrl+R / ⌘⇧Z"),
    ("+ / -", "+ / -"),
    ("g d / Return", "gd / Return"),
    ("Space / →", "Space / →"),
])
def test_compact_keys(notation, text):
    assert keymap.compact_keys(keymap.key(notation, "")) == text


def test_parse_keys_splits_alternatives_sequences_and_chords():
    assert keymap.parse_keys("g z / Ctrl+Shift+Z / +") == [
        [["g"], ["z"]], [["Ctrl", "Shift", "Z"]], [["+"]]]


@pytest.fixture
def help_tabs(tmp_path: Path, monkeypatch):
    """The plain text of each tab of the F1 dialog, by its title."""
    _app()
    from grafli.app import MainWindow
    board = tmp_path / "b.grafli"
    board.write_text('#!grafli v4\n@ box a "A" 0,0 100x60\n')
    win = MainWindow(str(board))
    shown: dict[str, str] = {}

    def _exec(dlg):
        tabs = dlg.findChild(QTabWidget)
        for i in range(tabs.count()):
            page = tabs.widget(i)
            browsers = ([page] if isinstance(page, QTextBrowser)
                        else page.findChildren(QTextBrowser))
            shown[tabs.tabText(i)] = "\n".join(b.toPlainText()
                                               for b in browsers)
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()
    win.close()
    return shown


@pytest.mark.parametrize("where, tab", [(keymap.APP, "Shortcuts"),
                                        (keymap.TAB, "Browser Tab")])
def test_the_help_shows_every_key_of_the_table(help_tabs, where, tab):
    text = help_tabs[tab]
    missing = [
        (g.id, k.keys) for g, k in _rows(where)
        if keymap.compact_keys(k) not in text or k.does not in text
    ]
    assert not missing, f"not in the F1 help's {tab} tab: {missing}"
    for g in keymap.groups(where):
        assert g.title.upper() in text, g.id


def test_the_help_filter_keeps_only_matching_rows():
    _app()
    from grafli.view.overlays import cheatsheet_html
    html = cheatsheet_html(keymap.APP, "heatmap")
    assert "Connectivity heatmap" in html
    assert "Zoom to fit" not in html
