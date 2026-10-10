"""Box docs (D2): a `&doc` box shows its doc's first sentence on one line
below its label at the detailed zoom level, `gv` peeks the whole doc in a
view-only panel that `Esc` closes, an external edit to the doc shows without
reopening the board, and a board without box docs is untouched."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser

from grafli.app import MainWindow
from grafli.format import Note
from grafli.items import NoteItem
from grafli.md_note import doc_first_sentence


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


COMBAT_DOC = ("# Combat\n\nA blow lands and **impact()** shakes the camera. "
              "Hit-stop follows.\n\n- lunge\n- impact\n")


def _system(tmp_path: Path) -> tuple[Path, Path]:
    """A board with a plain box, a `&doc` box and a doc-less box."""
    root = _write(tmp_path / "System.grafli",
                  '#!grafli v2\n'
                  '@ box plain "Plain" 0,0 240x80\n'
                  '@ box combat "Combat" 300,0 320x80 &doc:combat\n'
                  '@ box link "Site" 700,0 240x80 &link:https://example.org\n')
    doc = _write(tmp_path / "System-res" / "combat.md", COMBAT_DOC)
    return root, doc


def _window(path: Path) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    return win


def _zoom(win: MainWindow, scale: float):
    view = win._view
    view.setTransform(QTransform().scale(scale, scale))
    view._update_status_zoom()


def _select(win: MainWindow, box_id: str):
    view = win._view
    view._scene.clearSelection()
    view._box_items[box_id].setSelected(True)


def _press(win: MainWindow, *keys):
    for key in keys:
        QTest.keyClick(win._view, key)
    _app().processEvents()


def _press_gv(win: MainWindow):
    _press(win, Qt.Key.Key_G, Qt.Key.Key_V)


# ── The first sentence ──


def test_first_sentence_skips_headings_and_drops_markup():
    assert doc_first_sentence(COMBAT_DOC) == \
        "A blow lands and impact() shakes the camera."


def test_first_sentence_skips_front_matter_code_and_critic_marks():
    body = ("---\ntitle: x\n---\n```\ncode. here\n```\n"
            "> A [link](x.md) {>>why?<<}stays{-- gone--}! Then more.\n")
    assert doc_first_sentence(body) == "A link stays!"


def test_first_sentence_keeps_a_paragraph_without_a_full_stop():
    assert doc_first_sentence("- one list item, no stop\n- two") == \
        "one list item, no stop two"


def test_doc_without_prose_has_no_first_sentence():
    assert doc_first_sentence("# Only a heading\n") == ""
    assert doc_first_sentence("# Title\n\n---\n\n```\ncode.\n```\n") == ""
    assert doc_first_sentence("") == ""


def test_heading_only_doc_shows_no_line(tmp_path: Path):
    root, doc = _system(tmp_path)
    doc.write_text("# Combat\n")
    win = _window(root)
    _zoom(win, 1.0)
    assert win._view._box_items["combat"]._doc_line == ""
    win.close()


# ── The doc line ──


def test_doc_box_shows_its_first_sentence_below_the_label(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    item = view._box_items["combat"]
    assert item._doc_line == "A blow lands and impact() shakes the camera."
    # Label and doc line are centred as one block: the label moved up, the
    # line sits right below it, both inside the box.
    line = item.doc_line_rect()
    label_bottom = (item._label.pos().y() - item.pos().y()
                    + item._label.boundingRect().height())
    assert line.top() >= label_bottom
    assert line.bottom() <= item.box.h
    assert view._box_items["plain"]._doc_line == ""
    assert view._box_items["link"]._doc_line == ""
    win.close()


def test_doc_line_is_one_line_cut_to_the_box(tmp_path: Path):
    root, doc = _system(tmp_path)
    doc.write_text("A " + "very " * 60 + "long first sentence.\n")
    win = _window(root)
    _zoom(win, 1.0)
    item = win._view._box_items["combat"]
    assert item._doc_line.endswith("long first sentence.")
    rect = item.doc_line_rect()
    assert rect.height() == QFontMetricsF(item._doc_line_font()).height()
    assert rect.width() <= item.box.w
    win.close()


def test_doc_line_only_at_the_detailed_level(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    item = view._box_items["combat"]
    _zoom(win, 1.0)
    assert item._doc_line
    _zoom(win, 0.3)
    assert item._doc_line == ""
    _zoom(win, 1.0)
    assert item._doc_line
    win.close()


def test_box_without_room_shows_no_doc_line_and_does_not_grow(tmp_path: Path):
    root = _write(tmp_path / "Tight.grafli",
                  '#!grafli v2\n'
                  '@ box combat "Combat" 0,0 240x50 &doc:combat\n')
    _write(tmp_path / "Tight-res" / "combat.md", COMBAT_DOC)
    win = _window(root)
    _zoom(win, 1.0)
    item = win._view._box_items["combat"]
    assert item._doc_line == ""
    assert item.box.h == 50
    win.close()


def test_missing_doc_shows_no_doc_line(tmp_path: Path):
    root, doc = _system(tmp_path)
    doc.unlink()
    win = _window(root)
    _zoom(win, 1.0)
    assert win._view._box_items["combat"]._doc_line == ""
    win.close()


def test_exports_draw_the_box_without_its_doc_line(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    item = view._box_items["combat"]
    shown_pos = item._label.pos()
    with view.miniatures_held():
        assert item._doc_line == ""
        view._refresh_lod()
        assert item._doc_line == ""
    assert item._doc_line
    assert item._label.pos() == shown_pos
    win.close()


def test_undo_keeps_the_doc_line(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    view._push_undo()
    view._undo()
    assert view._box_items["combat"]._doc_line
    win.close()


def test_external_edit_to_a_box_doc_shows_without_reopening(tmp_path: Path):
    root, doc = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    assert str(doc) in win._docs_watcher._paths
    doc.write_text("Rewritten by an agent. Second sentence.\n")
    win._docs_watcher._check()
    _app().processEvents()
    assert win._file_path == root
    assert win._view._box_items["combat"]._doc_line == "Rewritten by an agent."
    win.close()


def test_board_without_box_docs_is_untouched(tmp_path: Path):
    root = _write(tmp_path / "Plain.grafli",
                  '#!grafli v2\n'
                  '@ box a "Alpha" 0,0 240x80\n'
                  '@ box b "Beta" 300,0 240x80 &link:https://example.org\n')
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    for item in view._box_items.values():
        assert item._doc_line == ""
        br = item._label.boundingRect()
        # The label sits centred in the box, as without box docs.
        assert item._label.pos().y() == item.pos().y() + (item.box.h - br.height()) / 2
    assert not (tmp_path / "Plain-res").exists()
    win.close()


# ── The peek ──


def test_gv_opens_the_whole_doc_beside_the_box(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    _select(win, "combat")
    before = root.read_text()
    box = view._box_items["combat"]
    geometry = (box.box.x, box.box.y, box.box.w, box.box.h)

    _press_gv(win)

    peek = view.doc_peek()
    assert peek is not None
    assert "Hit-stop follows." in peek.text()
    assert "impact" in peek.text()
    # The panel stays inside the viewport and moves nothing.
    assert view.viewport().rect().contains(view.doc_peek_rect())
    assert (box.box.x, box.box.y, box.box.w, box.box.h) == geometry
    assert not view._dirty
    assert root.read_text() == before
    win.close()


def test_peek_is_bounded_like_the_note_cap_and_scrolls(tmp_path: Path):
    root, doc = _system(tmp_path)
    doc.write_text("\n\n".join(f"Paragraph {i}." for i in range(60)))
    win = _window(root)
    _zoom(win, 1.0)
    _select(win, "combat")
    _press_gv(win)
    peek = win._view.doc_peek()
    font = NoteItem(Note(id="", x=0, y=0, text="", attach_kind="doc"))._note_font()
    cap_h = NoteItem._DISPLAY_CAP_LINES * QFontMetricsF(font).height()
    assert peek.height() <= cap_h + 2 * NoteItem._PAD + 4
    assert peek.scroll_bar().maximum() > 0
    win.close()


def test_esc_closes_the_peek_and_gv_toggles_it(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    _select(win, "combat")
    _press_gv(win)
    assert view.doc_peek() is not None
    _press(win, Qt.Key.Key_Escape)
    assert view.doc_peek() is None
    # Esc closed only the peek; the selection stays.
    assert view._box_items["combat"].isSelected()
    _press_gv(win)
    assert view.doc_peek() is not None
    _press_gv(win)
    assert view.doc_peek() is None
    win.close()


def test_peek_follows_the_box_when_the_view_pans(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    _select(win, "combat")
    _press_gv(win)
    before = view.doc_peek_rect()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() + 30)
    _app().processEvents()
    after = view.doc_peek_rect()
    assert after.translated(30, 0) == before
    win.close()


def test_peek_shows_an_external_edit(tmp_path: Path):
    root, doc = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    _select(win, "combat")
    _press_gv(win)
    doc.write_text("Rewritten by an agent.\n\nWith a second paragraph.\n")
    win._docs_watcher._check()
    _app().processEvents()
    peek = win._view.doc_peek()
    assert peek is not None
    assert "With a second paragraph." in peek.text()
    win.close()


def test_peek_closes_on_another_board(tmp_path: Path):
    root, _ = _system(tmp_path)
    other = _write(tmp_path / "Other.grafli",
                   '#!grafli v2\n'
                   '@ box combat "Combat" 0,0 320x80 &doc:combat\n')
    _write(tmp_path / "Other-res" / "combat.md", "Other doc.\n")
    win = _window(root)
    _zoom(win, 1.0)
    _select(win, "combat")
    _press_gv(win)
    assert win._view.doc_peek() is not None
    win._open_file(other)
    _app().processEvents()
    assert win._view.doc_peek() is None
    win.close()


def test_gv_toasts_on_a_box_without_a_doc(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    _select(win, "plain")
    _press_gv(win)
    assert view.doc_peek() is None
    assert view._toast_text == "'Plain' has no doc to peek at"
    _select(win, "link")
    _press_gv(win)
    assert view._toast_text == "'Site' has no doc to peek at"
    win.close()


def test_gv_toast_names_a_multi_line_label_on_one_line(tmp_path: Path):
    root = _write(tmp_path / "Two.grafli",
                  '#!grafli v2\n'
                  '@ box gw "API Gateway\\nrate limits" 0,0 240x80\n')
    win = _window(root)
    _select(win, "gw")
    _press_gv(win)
    assert win._view._toast_text == \
        "'API Gateway rate limits' has no doc to peek at"
    win.close()


def test_gv_toasts_without_a_selected_box(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    win._view._scene.clearSelection()
    _press_gv(win)
    assert win._view._toast_text == "Select a box with a doc to peek at it"
    win.close()


def test_gv_toasts_on_a_missing_doc(tmp_path: Path):
    root, doc = _system(tmp_path)
    doc.unlink()
    win = _window(root)
    _select(win, "combat")
    _press_gv(win)
    assert win._view.doc_peek() is None
    assert win._view._toast_text == \
        "The doc 'combat' of 'Combat' is missing"
    win.close()


def test_help_sheet_lists_gv(tmp_path: Path, monkeypatch):
    root, _ = _system(tmp_path)
    win = _window(root)
    shown: list[str] = []

    def _exec(dlg):
        shown.extend(b.toPlainText() for b in dlg.findChildren(QTextBrowser))
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()

    text = "\n".join(shown)
    assert "gv" in text
    assert "Peek at the box's doc (Esc closes)" in text
    win.close()
