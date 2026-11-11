"""The key table (`grafli/keymap.py`, #324): the F1 help and the "grafli at a
glance" page show every row of it, and the website's copy of the page is
current."""

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


@pytest.mark.parametrize("where", [keymap.APP, keymap.TAB])
def test_no_two_rows_in_one_place_share_keys_and_words(where):
    # The F1 test finds a row by its keys and words side by side; two rows
    # alike would let one stand in for the other.
    rows = [(keymap.compact_keys(k), k.does) for _, k in _rows(where)]
    assert len(rows) == len(set(rows))


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
    text = "\n" + help_tabs[tab] + "\n"
    # Qt puts each table cell on its own line: a row is its keys, then
    # what they do, on the next line.
    missing = [
        (g.id, k.keys, k.does) for g, k in _rows(where)
        if f"\n{keymap.compact_keys(k)}\n{k.does}\n" not in text
    ]
    assert not missing, f"not in the F1 help's {tab} tab: {missing}"
    for g in keymap.groups(where):
        assert g.title.upper() in text, g.id


def test_the_style_grids_name_their_own_keys():
    symbols = keymap.find("style", "i").does
    assert "0\u20139 a number badge" in symbols and "f filled" in symbols
    text = keymap.find("style", "t").does
    assert "o outline" in text and "s shadow" in text


def test_the_help_filter_keeps_only_matching_rows():
    _app()
    from grafli.view.overlays import cheatsheet_html
    html = cheatsheet_html(keymap.APP, "heatmap")
    assert "Connectivity heatmap" in html
    assert "Zoom to fit" not in html


# ── The "grafli at a glance" page ──────────────────────────────────

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("where", [keymap.APP, keymap.TAB])
def test_the_page_shows_every_key_of_the_table(where):
    from grafli import helppage
    page = helppage.render_page()
    for g in keymap.groups(where):
        assert f'id="k-{g.id}"' in page, g.id
    missing = [
        (g.id, k.keys, k.does) for g, k in _rows(where)
        if helppage.row_html(k) not in helppage.card_html(page, g.id)
    ]
    assert not missing, f"not on the page: {missing}"


def test_the_page_shows_both_ways_of_working_with_the_agent():
    from grafli import helppage
    page = helppage.render_page()
    desk, meeting = page.split('class="way meet"')
    assert "<b>T:</b>" in desk and "<b>Q:</b>" in desk
    assert "grafli skill install claude" in desk
    for part in ("/mcp__grafli__connect", "<kbd>:</kbd>",
                 helppage.keys_html(keymap.key("Shift+U", "")),
                 "disconnect from grafli"):
        assert part in meeting, part


def test_the_website_copy_is_the_page_the_table_renders():
    from grafli import helppage
    copy = REPO / helppage.DOCS_COPY
    assert copy.read_text(encoding="utf-8") == helppage.render_page(), (
        "docs/at-a-glance.html is out of date: run "
        "python -m grafli.helppage docs/at-a-glance.html")


def test_the_page_has_no_trailing_whitespace():
    from grafli import helppage
    lines = helppage.render_page().splitlines()
    assert [i for i, ln in enumerate(lines, 1) if ln != ln.rstrip()] == []


def _click_page_button(tmp_path: Path, monkeypatch):
    """Click **grafli at a glance** in the F1 help, the temp directory in
    ``tmp_path``; the URLs it opened and the view."""
    _app()
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QPushButton
    from grafli import helppage
    from grafli.app import MainWindow
    temp = tmp_path / "tmp"
    temp.mkdir(exist_ok=True)
    board = tmp_path / "b.grafli"
    board.write_text('#!grafli v4\n@ box a "A" 0,0 100x60\n')
    win = MainWindow(str(board))
    monkeypatch.setattr(helppage.tempfile, "gettempdir", lambda: str(temp))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: opened.append(url) or True)

    def _exec(dlg):
        dlg.findChild(QPushButton, "at_a_glance").click()
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()
    win.close()
    return opened, win._view, temp


def test_the_help_opens_the_page_in_the_browser(tmp_path: Path, monkeypatch):
    from grafli import helppage
    opened, _, temp = _click_page_button(tmp_path, monkeypatch)
    assert len(opened) == 1 and opened[0].isLocalFile()
    page = Path(opened[0].toLocalFile())
    assert page.parent == temp
    assert page.read_text(encoding="utf-8") == helppage.render_page()


def test_a_file_squatting_the_old_fixed_name_does_not_stop_the_page(
        tmp_path: Path, monkeypatch):
    from grafli import helppage
    temp = tmp_path / "tmp"
    temp.mkdir()
    squat = temp / "grafli-at-a-glance.html"
    squat.write_text("someone else's")
    squat.chmod(0o444)
    opened, _, _ = _click_page_button(tmp_path, monkeypatch)
    assert len(opened) == 1
    page = Path(opened[0].toLocalFile())
    assert page != squat
    assert page.read_text(encoding="utf-8") == helppage.render_page()
    assert squat.read_text() == "someone else's"


def test_the_help_says_so_when_the_page_cannot_be_written(
        tmp_path: Path, monkeypatch):
    from grafli import helppage

    def _fail():
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(helppage, "local_copy", _fail)
    opened, view, _ = _click_page_button(tmp_path, monkeypatch)
    assert opened == []
    assert view._toast_text == ("Could not write the help page: "
                                "No space left on device")
