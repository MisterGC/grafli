"""Every keypress either acts or explains itself (#154).

The silent no-op sweep: keys that used to do nothing now either do the
obvious thing (hjkl moves an image) or say why they can't (a toast). These
tests pin both halves — the new feedback, and the normal flows that must
keep working without a toast in the way.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsRectItem

from grafli.constants import _CTRL_MOD
from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    return QApplication.instance() or QApplication([])


def _view(src: str = "#!grafli v2\n") -> GrafliView:
    _app()
    view = GrafliView()
    # Grid mode comes from QSettings — pin it so steps are 1 scene unit and
    # nothing re-snaps behind the assertion.
    view._grid_mode = "off"
    view.load_board(parse(src))
    view.resize(900, 600)
    return view


def _window(tmp: Path | None = None, text: str = "#!grafli v2\n"):
    _app()
    from grafli.app import MainWindow
    if tmp is None:
        w = MainWindow()
    else:
        f = tmp / "t.grafli"
        f.write_text(text)
        w = MainWindow(str(f))
    w.resize(900, 600)
    w._view._grid_mode = "off"
    return w


def _key(view, key, mods=Qt.KeyboardModifier.NoModifier):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))


_BOARD = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ note n1 400,0 "a note"
@ image i1 "shots/pic.png" 200,200 100x80
"""


# ── H1: hjkl moves an image like everything else ──────────────────


def test_hjkl_moves_a_selected_image():
    view = _view(_BOARD)
    item = view._image_items["i1"]
    item.setSelected(True)
    _key(view, Qt.Key.Key_L)
    _key(view, Qt.Key.Key_J)

    img = view.board.image_by_id("i1")
    assert (img.x, img.y) == (201.0, 201.0)
    assert (item.pos().x(), item.pos().y()) == (201.0, 201.0)


def test_hjkl_still_moves_boxes_and_notes():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    view._note_items["n1"].setSelected(True)
    _key(view, Qt.Key.Key_H)

    assert view.board.box_by_id("a").x == -1.0
    assert view.board.note_by_id("n1").x == 399.0


def test_move_with_nothing_movable_toasts_and_pushes_no_undo():
    view = _view(_BOARD)
    stray = QGraphicsRectItem(0, 0, 10, 10)
    stray.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
    view._scene.addItem(stray)
    stray.setSelected(True)
    _key(view, Qt.Key.Key_L)

    assert "Select a box, note, or image" in view._toast_text
    assert view._undo_stack == []


# ── H2 / H12: dimension mode is for boxes ─────────────────────────


def test_d_on_a_note_only_selection_toasts_and_does_not_enter():
    view = _view(_BOARD)
    view._note_items["n1"].setSelected(True)
    _key(view, Qt.Key.Key_D)

    assert view._toast_text == "Only boxes resize with hjkl"
    assert view._box_mode == ""
    assert view._undo_stack == []


def test_resize_keys_in_dimension_mode_refuse_a_note_selection():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    _key(view, Qt.Key.Key_D)
    assert view._box_mode == "dimension"

    # Selection narrowed to a note while the mode is live.
    view._box_items["a"].setSelected(False)
    view._note_items["n1"].setSelected(True)
    view._box_mode = "dimension"
    view._undo_stack.clear()
    _key(view, Qt.Key.Key_L)

    assert view._toast_text == "Only boxes resize with hjkl"
    assert view._undo_stack == []


def test_dimension_mode_still_resizes_a_box():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    _key(view, Qt.Key.Key_D)
    _key(view, Qt.Key.Key_L, Qt.KeyboardModifier.ShiftModifier)

    assert view.board.box_by_id("a").w == 121.0
    assert view._undo_stack


def test_style_mode_badges_an_image_selection():
    view = _view(_BOARD)
    view._image_items["i1"].setSelected(True)
    _key(view, Qt.Key.Key_S)

    assert view._box_mode == "style"
    assert view._mode_badge is not None


# ── A converted _record_shortcut hint (gz) ────────────────────────


def test_gz_without_a_selection_toasts():
    view = _view(_BOARD)
    _key(view, Qt.Key.Key_G)
    _key(view, Qt.Key.Key_Z)

    assert view._toast_text == "Select an element to zoom into"


def test_slide_ratio_without_a_box_toasts():
    view = _view(_BOARD)
    view._note_items["n1"].setSelected(True)
    view._snap_selection_to_slide_ratio()

    assert "slide ratio" in view._toast_text


# ── H3: markdown attach needs a saved board ───────────────────────


def test_shift_e_on_an_unsaved_board_toasts():
    w = _window()
    w._view.load_board(parse(_BOARD))
    w._view._box_items["a"].setSelected(True)
    _key(w._view, Qt.Key.Key_E, Qt.KeyboardModifier.ShiftModifier)

    assert w._view._toast_text == "Save the board first to attach a markdown doc"


def test_return_resource_picker_on_an_unsaved_board_toasts():
    w = _window()
    w._view.load_board(parse(_BOARD))
    w._view._box_items["a"].setSelected(True)
    _key(w._view, Qt.Key.Key_Return)

    assert w._view._toast_text == "Save the board first to attach resources"


# ── H5 / H6: pasting a clipboard image ────────────────────────────


def test_paste_image_on_an_untitled_board_asks_where_to_save(tmp_path: Path,
                                                             monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QFileDialog
    target = tmp_path / "fresh.grafli"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )
    w = _window()
    img = QImage(64, 40, QImage.Format.Format_ARGB32)
    img.fill(0x3366AA)
    w._view._paste_clipboard_image(QPointF(0, 0), img)

    assert w._file_path == target
    assert len(w._view._board.images) == 1
    assert (tmp_path / w._view._board.images[0].image_path).exists()


def test_paste_image_reports_a_failed_write(tmp_path: Path, monkeypatch):
    from PySide6.QtGui import QImage
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    monkeypatch.setattr(QImage, "save", lambda *a, **k: False)
    img = QImage(64, 40, QImage.Format.Format_ARGB32)
    img.fill(0x3366AA)
    w._view._paste_clipboard_image(QPointF(0, 0), img)

    assert w._view._toast_text.startswith("Couldn't write ")
    assert w._view._toast_kind == "error"
    assert w._view._board.images == []


# ── S1: a deferred save is reported on ⌘S, never by autosave ──────


def _defer_reconcile(w, monkeypatch):
    """Make the conflict-check refuse to parse, as a mid-write file would."""
    def _boom(_self, _disk_text):
        raise ValueError("mid-write")
    from grafli.app import MainWindow
    monkeypatch.setattr(MainWindow, "_reconcile_external", _boom)
    # Disk differs from what we last wrote, so the check actually runs.
    w._file_path.write_text("#!grafli v2\n@ box zz \"Z\" 0,0 10x10\n")


def test_manual_save_reports_a_deferred_save(tmp_path: Path, monkeypatch):
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    _defer_reconcile(w, monkeypatch)
    w._save_file()

    assert w._view._toast_text == "Save deferred — the file on disk is mid-write"


def test_autosave_defers_quietly(tmp_path: Path, monkeypatch):
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    _defer_reconcile(w, monkeypatch)
    w._view._toast_text = ""
    w._autosave()

    assert w._view._toast_text == ""


def test_a_normal_manual_save_still_confirms(tmp_path: Path):
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    w._view.mark_dirty()
    w._save_file()

    assert w._view._toast_text == "Saved t.grafli"


# ── M17: an empty yank keeps the clipboard ────────────────────────


def test_empty_yank_toasts_and_keeps_the_clipboard():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    _key(view, Qt.Key.Key_Y)
    assert len(view._clipboard_boxes) == 1

    view._scene.clearSelection()
    _key(view, Qt.Key.Key_Y)

    assert view._toast_text == "Nothing selected to copy"
    assert len(view._clipboard_boxes) == 1


def test_yank_then_paste_still_duplicates_a_box():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    _key(view, Qt.Key.Key_Y)
    view._paste_at(QPointF(600, 600))

    assert len(view.board.boxes) == 2


# ── L1: empty undo / redo stacks ──────────────────────────────────


def test_undo_on_an_empty_stack_toasts():
    view = _view(_BOARD)
    _key(view, Qt.Key.Key_U)

    assert view._toast_text == "Nothing to undo"


def test_redo_on_an_empty_stack_toasts():
    view = _view(_BOARD)
    _key(view, Qt.Key.Key_R, _CTRL_MOD)

    assert view._toast_text == "Nothing to redo"


def test_undo_after_a_real_edit_still_undoes():
    view = _view(_BOARD)
    view._box_items["a"].setSelected(True)
    _key(view, Qt.Key.Key_L)
    assert view.board.box_by_id("a").x == 1.0

    _key(view, Qt.Key.Key_U)
    assert view.board.box_by_id("a").x == 0.0


# ── H11: the heatmap needs connectors ─────────────────────────────


def test_complexity_without_connectors_toasts_and_stays_out():
    view = _view(_BOARD)
    _key(view, Qt.Key.Key_A)

    assert view._toast_text == "No connectors to analyse"
    assert not view._complexity_active


def test_complexity_still_enters_with_connectors():
    view = _view(_BOARD + '@ box b "B" 400,400 120x60\n@ arrow a -> b ""\n')
    _key(view, Qt.Key.Key_A)

    assert view._complexity_active


# ── M14/M15: a bookmark whose anchor is gone says so ──────────────


def test_bookmark_with_deleted_elements_toasts():
    view = _view(_BOARD + '@ bookmark bm "Gone" @nope\n')
    view.goto_bookmark("bm")

    assert "elements are gone" in view._toast_text


def test_unknown_bookmark_toasts():
    view = _view(_BOARD)
    view.goto_bookmark("missing")

    assert view._toast_text == "Bookmark not found on this board"


def test_a_live_bookmark_still_flies_quietly():
    view = _view(_BOARD + '@ bookmark bm "Here" @a\n')
    view.goto_bookmark("bm", animate=False)

    assert view._toast_text == ""
