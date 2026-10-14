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


def test_thumbnails_draw_the_box_without_its_doc_line(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    item = view._box_items["combat"]
    shown_pos = item._label.pos()
    with view.miniatures_held():
        assert item._doc_line
    with view.doc_lines_held():
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



def _headless(path: Path):
    """A never-shown view set up as `grafli render` sets it up."""
    from grafli.format import parse
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.base_dir = str(path.parent)
    view.render_headless(path)
    view.load_board(parse(path.read_text()))
    return view


def test_headless_render_shows_the_doc_lines_the_app_shows(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = _headless(root)
    for scale in (0.3, 1.0, 2.0):
        _zoom(win, scale)
        view.setTransform(QTransform().scale(scale, scale))
        view._refresh_lod()
        lines = {bid: item._doc_line
                 for bid, item in win._view._box_items.items()}
        assert {bid: item._doc_line
                for bid, item in view._box_items.items()} == lines
    assert lines["combat"] == "A blow lands and impact() shakes the camera."
    win.close()


def test_render_draws_the_doc_line(tmp_path: Path):
    from PySide6.QtGui import QImage
    from grafli.app import _cmd_render
    root, doc = _system(tmp_path)
    with_line = tmp_path / "with.png"
    assert _cmd_render([str(root), str(with_line)]) == 0
    doc.unlink()
    without = tmp_path / "without.png"
    assert _cmd_render([str(root), str(without)]) == 0
    assert QImage(str(with_line)) != QImage(str(without))


def test_render_lod_keeps_the_zoomed_out_look(tmp_path: Path):
    # Fitted to the screen, the doc line is far too small to read, so
    # `--lod` renders the board as it did before render drew doc lines.
    from PySide6.QtGui import QImage
    from grafli.app import _cmd_render
    root, doc = _system(tmp_path)
    root.write_text(root.read_text()
                    + '@ box far "Far" 20000,20000 240x80\n')
    zoomed_out = tmp_path / "lod.png"
    assert _cmd_render([str(root), str(zoomed_out), "--lod"]) == 0
    doc.unlink()
    before = tmp_path / "before.png"
    assert _cmd_render([str(root), str(before), "--lod"]) == 0
    assert QImage(str(zoomed_out)) == QImage(str(before))


# ── Exports ──

def _tour_system(tmp_path: Path) -> Path:
    """The system board with two one-stop tours: one framing the `&doc` box
    close, one framing it with a box far away, so small on the slide."""
    root, _ = _system(tmp_path)
    root.write_text(root.read_text()
                    + '@ box far "Far" 20000,20000 240x80\n'
                    '@ bookmark near "Combat" @combat\n'
                    '@ bookmark wide "Everything" @combat,far\n'
                    '@ flow close "Close" near\n'
                    '@ flow distant "Distant" wide\n')
    return root


def _painted_doc_lines(monkeypatch) -> list:
    """Record each doc line a box paints, as (box id, text)."""
    from grafli.items import BoxItem
    painted = []
    paint = BoxItem._paint_doc_line

    def spy(self, painter):
        painted.append((self.box.id, self._doc_line))
        paint(self, painter)
    monkeypatch.setattr(BoxItem, "_paint_doc_line", spy)
    return painted


LINE = ("combat", "A blow lands and impact() shakes the camera.")


def test_pdf_and_pptx_slides_draw_the_doc_line(tmp_path: Path, monkeypatch):
    from grafli.app import _cmd_export
    root = _tour_system(tmp_path)
    _app()
    painted = _painted_doc_lines(monkeypatch)
    for out in ("close.pdf", "close.pptx"):
        painted.clear()
        assert _cmd_export([str(root), str(tmp_path / out),
                            "--flow", "close"]) == 0
        assert LINE in painted


def test_a_slide_too_wide_to_read_the_line_leaves_it_out(tmp_path: Path,
                                                         monkeypatch):
    from grafli.app import _cmd_export
    root = _tour_system(tmp_path)
    _app()
    painted = _painted_doc_lines(monkeypatch)
    for out in ("distant.pdf", "distant.pptx"):
        painted.clear()
        assert _cmd_export([str(root), str(tmp_path / out),
                            "--flow", "distant"]) == 0
        assert painted == []


def test_a_slide_judges_the_line_at_its_scale_not_the_canvas_zoom(
        tmp_path: Path, monkeypatch):
    # The canvas is zoomed out past the line but not the label, the slide
    # frames the box close: the slide keeps the line, and the canvas is as
    # it was afterwards.
    from grafli.pdfexport import export_flow_to_pdf
    root = _tour_system(tmp_path)
    win = _window(root)
    view = win._view
    _zoom(win, 1.0)
    _zoom(win, 0.7)
    item = view._box_items["combat"]
    assert "combat" not in view._lod_skip_set()
    assert item._doc_line == ""
    painted = _painted_doc_lines(monkeypatch)
    export_flow_to_pdf(view, view.board.flow_by_id("close"),
                       tmp_path / "close.pdf", root)
    assert LINE in painted
    assert item._doc_line == ""
    _zoom(win, 1.0)
    painted.clear()
    export_flow_to_pdf(view, view.board.flow_by_id("distant"),
                       tmp_path / "distant.pdf", root)
    assert painted == []
    assert item._doc_line == LINE[1]
    win.close()


def test_a_stop_in_another_board_draws_its_doc_lines(tmp_path: Path,
                                                     monkeypatch):
    from grafli.app import _cmd_export
    _system(tmp_path / "sub")
    root = _write(tmp_path / "Tour.grafli",
                  '#!grafli v3\n'
                  '@ box start "Start" 0,0 240x80\n'
                  '@ flow tour "Tour" sub/System.grafli#near\n')
    sub = tmp_path / "sub" / "System.grafli"
    sub.write_text(sub.read_text() + '@ bookmark near "Combat" @combat\n')
    _app()
    painted = _painted_doc_lines(monkeypatch)
    assert _cmd_export([str(root), str(tmp_path / "tour.pdf")]) == 0
    assert LINE in painted


def test_the_html_page_draws_the_doc_line(tmp_path: Path, monkeypatch):
    from grafli.htmlexport import export_html
    root, _ = _system(tmp_path)
    _app()
    painted = _painted_doc_lines(monkeypatch)
    export_html(root, tmp_path / "page.html")
    assert LINE in painted


def test_a_bookmark_thumbnail_leaves_the_doc_line_out(tmp_path: Path,
                                                      monkeypatch):
    from grafli.flows import render_bookmark_pixmap
    root = _tour_system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    view = win._view
    painted = _painted_doc_lines(monkeypatch)
    assert render_bookmark_pixmap(view, view.board.bookmark_by_id("near"),
                                  400, 300) is not None
    assert painted == []
    assert view._box_items["combat"]._doc_line == LINE[1]
    win.close()


def test_exports_of_a_board_without_box_docs_paint_no_doc_line(
        tmp_path: Path, monkeypatch):
    from grafli.app import _cmd_export
    from grafli.htmlexport import export_html
    root = _write(tmp_path / "Plain.grafli",
                  '#!grafli v2\n'
                  '@ box a "Alpha" 0,0 240x80\n'
                  '@ box b "Beta" 300,0 240x80 &link:https://example.org\n'
                  '@ bookmark ab "Both" @a,b\n'
                  '@ flow tour "Tour" ab\n')
    _app()
    painted = _painted_doc_lines(monkeypatch)
    assert _cmd_export([str(root), str(tmp_path / "plain.pdf")]) == 0
    assert _cmd_export([str(root), str(tmp_path / "plain.pptx")]) == 0
    export_html(root, tmp_path / "plain.html")
    assert painted == []


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
