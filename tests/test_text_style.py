"""Text emphasis (bold/italic) and the style-mode type grid (size x style).

Covers the format layer (`!bold`/`!italic` flags + the ``emphasis`` field on
boxes and notes) and the type picker (open/navigate/commit/cancel)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.constants import FONT_FAMILY, NOTE_FONT_FAMILY
from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


# ── format ──────────────────────────────────────────────────────

def test_emphasis_roundtrip():
    src = (
        "#!grafli v1\n"
        '@ box a "Title" 0,0 160x60 ~large !bold\n'
        '@ box b "B" 200,0 120x60 !flat !bold !italic\n'
        '@ note n 0,120 "aside" ~small !italic\n'
        '@ note m 0,200 """\nl1\nl2\n""" !mono !bold >a\n'
    )
    b = parse(src)
    assert b.boxes[0].emphasis == "bold"
    assert b.boxes[1].emphasis == "bold italic" and b.boxes[1].style == "flat"
    assert b.notes[0].emphasis == "italic"
    assert b.notes[1].emphasis == "bold" and b.notes[1].style == "mono"
    assert serialize(b) == src   # canonical !bold before !italic, byte-stable


def test_emphasis_flag_order_normalizes():
    # Author order is tolerated; serialization is canonical (bold, italic).
    b = parse('#!grafli v1\n@ box a "T" 0,0 100x50 !italic !bold\n')
    assert b.boxes[0].emphasis == "bold italic"
    assert "!bold !italic" in serialize(b)


# ── type picker ─────────────────────────────────────────────────

def test_type_picker_open_starts_on_current():
    view = _view('@ box a "A" 0,0 160x60 ~large !bold\n')
    view._box_items["a"].setSelected(True)
    view._open_type_picker()
    assert view._type_picker_active
    assert view._TYPE_SIZES[view._type_picker_size_idx] == "large"
    assert view._TYPE_EMPH[view._type_picker_emph_idx] == "bold"


def test_type_picker_navigate_live_preview():
    view = _view('@ box a "A" 0,0 160x60\n')
    a = view._box_items["a"]
    a.setSelected(True)
    view._open_type_picker()
    view._type_picker_move(0, 1)        # size down a row from "" -> large
    view._type_picker_move(1, 0)        # emphasis -> bold
    assert a.box.textsize == "large"
    assert a.box.emphasis == "bold"
    # clamps at edges
    for _ in range(10):
        view._type_picker_move(-1, -1)
    assert view._type_picker_size_idx == 0 and view._type_picker_emph_idx == 0


def test_type_picker_commit_is_undoable():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    undo_before = len(view._undo_stack)
    view._open_type_picker()
    view._type_picker_move(0, 2)        # -> xlarge
    view._type_picker_move(1, 0)        # -> bold
    view._commit_type_picker()
    assert view.board.box_by_id("a").textsize == "xlarge"
    assert view.board.box_by_id("a").emphasis == "bold"
    assert len(view._undo_stack) == undo_before + 1
    view._undo()
    assert view.board.box_by_id("a").textsize == ""
    assert view.board.box_by_id("a").emphasis == ""


def test_type_picker_cancel_reverts():
    view = _view('@ box a "A" 0,0 160x60 ~small !italic\n')
    a = view._box_items["a"]
    a.setSelected(True)
    view._open_type_picker()
    view._type_picker_move(1, 1)
    view._cancel_type_picker()
    assert view._box_items["a"].box.textsize == "small"
    assert view._box_items["a"].box.emphasis == "italic"


# ── note font (handwritten by default, !mono = monospace) ───────

def test_note_handwritten_by_default():
    view = _view('@ note n 0,0 "freeform"\n')
    assert view._note_items["n"]._note_font().family() == NOTE_FONT_FAMILY


def test_mono_note_uses_monospace():
    view = _view('@ note n 0,0 "x" !mono\n')
    assert view._note_items["n"]._note_font().family() == FONT_FAMILY


def test_code_note_uses_monospace():
    view = _view('@ note c 0,0 "code: y = 2"\n')
    assert view._note_items["c"]._note_font().family() == FONT_FAMILY


def test_mono_toggle_invalidates_markdown_doc_cache():
    # Regression: the layout cache key must include style/emphasis, else a
    # mono (or bold/italic) toggle shows no change on an already-painted note.
    view = _view('@ note n 0,0 """\nmd:\n- [ ] t\n"""\n')
    it = view._note_items["n"]
    assert it._md_document().defaultFont().family() == NOTE_FONT_FAMILY
    it.set_text_mono(True)
    assert it._md_document().defaultFont().family() == FONT_FAMILY
    it.set_emphasis("bold")
    assert it._md_document().defaultFont().bold()


def test_type_picker_tab_toggles_note_font():
    view = _view('@ note n 0,0 "hi"\n')
    view._note_items["n"].setSelected(True)
    view._open_type_picker()
    assert view._type_picker_font == ""                 # handwritten
    view._toggle_type_font()
    assert view._type_picker_font == "mono"
    assert view._note_items["n"].note.style == "mono"   # live
    view._commit_type_picker()
    assert view.board.notes[0].style == "mono"


def test_type_picker_cancel_restores_note_font():
    view = _view('@ note n 0,0 "hi" !mono\n')
    view._note_items["n"].setSelected(True)
    view._open_type_picker()
    assert view._type_picker_font == "mono"
    view._toggle_type_font()                            # preview hand
    view._cancel_type_picker()
    assert view._note_items["n"].note.style == "mono"   # reverted


def test_type_picker_applies_to_note():
    view = _view('@ note n 0,0 "hi"\n')
    view._note_items["n"].setSelected(True)
    view._open_type_picker()
    view._type_picker_move(1, 1)
    view._commit_type_picker()
    note = view.board.notes[0]
    assert note.textsize == "large" and note.emphasis == "bold"


# ── bold actually renders (regression) ──────────────────────────
#
# The handwritten face (Patrick Hand) ships no bold weight and the platform's
# synthetic emboldening of it is near-invisible, so bold notes used to read as
# regular. Mono now bundles a real Bold face; handwritten gets a painter-level
# faux-bold stroke. Both must make bold visibly differ from regular.

def _render_note(text: str, emphasis: str, style: str = "") -> "object":
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QGraphicsScene
    from grafli.format import Note
    from grafli.items import NoteItem
    item = NoteItem(Note(id="n", text=text, x=0, y=0,
                         emphasis=emphasis, style=style))
    scene = QGraphicsScene()
    scene.addItem(item)
    r = scene.itemsBoundingRect()
    img = QImage(int(r.width()) + 16, int(r.height()) + 16,
                 QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene.render(p, QRectF(0, 0, img.width(), img.height()),
                 r.adjusted(-8, -8, 8, 8))
    p.end()
    return img


def _pixel_diff_pct(a, b) -> float:
    w, h = min(a.width(), b.width()), min(a.height(), b.height())
    diff = sum(1 for y in range(h) for x in range(w)
               if a.pixel(x, y) != b.pixel(x, y))
    return 100.0 * diff / (w * h)


def test_real_mono_bold_face_is_bundled():
    # The crisp mono bold depends on a real Bold face for the family, not the
    # platform's weak synthesis.
    from PySide6.QtGui import QFontDatabase
    from grafli.app import _register_bundled_fonts
    QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    assert "Bold" in QFontDatabase.styles(FONT_FAMILY)


def test_bold_visibly_changes_handwritten_note():
    QApplication.instance() or QApplication([])
    from grafli.app import _register_bundled_fonts
    _register_bundled_fonts()
    reg = _render_note("Sample text here", "")
    bold = _render_note("Sample text here", "bold")
    assert _pixel_diff_pct(reg, bold) > 1.5


def test_bold_visibly_changes_mono_note():
    QApplication.instance() or QApplication([])
    from grafli.app import _register_bundled_fonts
    _register_bundled_fonts()
    reg = _render_note("Sample text here", "", "mono")
    bold = _render_note("Sample text here", "bold", "mono")
    assert _pixel_diff_pct(reg, bold) > 1.5
