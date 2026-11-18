"""The standard control scheme (#352): menus, toolbar, mouse and the usual
shortcuts beside the vim keys.

The heart of it is :func:`test_every_documented_control_runs_its_command`:
every row of ``keymap.STANDARD_GROUPS`` — the table the F1 help, the "at a
glance" page and the docs show — is pressed or clicked in a real window, and
the test fails when the app does not run the command the row names. Rows
that name a behaviour (``mouse:``, ``text:``, ``play:``) each have a test of
their own here, listed in :data:`BEHAVIOUR_TESTS`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import (QFocusEvent, QImage, QKeySequence, QMouseEvent,
                           QWheelEvent, QDropEvent)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QGraphicsSimpleTextItem,
                               QMenu)

from grafli import controls, keymap
from grafli.constants import Mode
from grafli.format import serialize

REPO = Path(__file__).resolve().parent.parent

BOARD = """#!grafli v4
@ box a "A" 0,0 100x60
@ box b "B" 300,0 100x60
@ box big "Big" 0,200 400x300
@ box c "C" 700,700 80x40
@ note n 600,0 "A note"
@ arrow a -> b "go"
"""

L = Qt.MouseButton.LeftButton
NOB = Qt.MouseButton.NoButton
NOMOD = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path, text: str = BOARD, scheme=controls.STANDARD):
    _app()
    from grafli.app import MainWindow
    board = tmp_path / "b.grafli"
    board.write_text(text)
    win = MainWindow(str(board))
    win.resize(1100, 800)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)
    if scheme == controls.STANDARD:
        win.set_control_scheme(controls.STANDARD)
    view = win._view
    view.resetTransform()
    view.centerOn(QPointF(350, 300))
    view.setFocus()
    return win, view


@pytest.fixture
def std(tmp_path):
    win, view = _window(tmp_path)
    yield win, view
    win._view._dirty = False
    win.close()


@pytest.fixture
def fired(std, monkeypatch):
    """Every command the window runs, recorded instead of run.

    The real ``std_run`` still dispatches: only the handlers it finds are
    replaced by recorders, so a command with no handler is not recorded
    (``std_run`` says "No command") and the test pressing it fails."""
    _, view = std
    real = view._std_handlers()
    calls: list[tuple[str, dict]] = []

    def recorder(name):
        return lambda **kw: calls.append((name, kw))

    monkeypatch.setattr(view, "_std_handlers",
                        lambda: {name: recorder(name) for name in real})
    return calls


# ── Mouse and keys, as a user gives them ────────────────────────────

def _vpos(view, scene_pt) -> QPointF:
    return QPointF(view.mapFromScene(scene_pt))


def _mouse(view, etype, scene_pt, button=L, buttons=None, mods=NOMOD):
    vp = view.viewport()
    pos = _vpos(view, scene_pt)
    glob = QPointF(vp.mapToGlobal(pos.toPoint()))
    if buttons is None:
        buttons = (NOB if etype == QEvent.Type.MouseButtonRelease
                   else button)
    QApplication.sendEvent(vp, QMouseEvent(etype, pos, glob, button,
                                           buttons, mods))


def _click(view, pt, button=L, mods=NOMOD):
    _mouse(view, QEvent.Type.MouseButtonPress, pt, button, mods=mods)
    _mouse(view, QEvent.Type.MouseButtonRelease, pt, button, mods=mods)


def _double_click(view, pt):
    _click(view, pt)
    _mouse(view, QEvent.Type.MouseButtonDblClick, pt)
    _mouse(view, QEvent.Type.MouseButtonRelease, pt)


def _drag(view, a: QPointF, b: QPointF, button=L, mods=NOMOD, steps=8):
    _mouse(view, QEvent.Type.MouseButtonPress, a, button, mods=mods)
    for i in range(1, steps + 1):
        p = a + (b - a) * (i / steps)
        _mouse(view, QEvent.Type.MouseMove, p, NOB, buttons=button,
               mods=mods)
    _mouse(view, QEvent.Type.MouseButtonRelease, b, button, mods=mods)


def _center(item) -> QPointF:
    return item.sceneBoundingRect().center()


def _label_of(view, arrow):
    return next(it for it in view._scene.items()
                if isinstance(it, QGraphicsSimpleTextItem)
                and it.data(0) is arrow)


def _no_popups(monkeypatch):
    monkeypatch.setattr(QMenu, "popup", lambda self, *a, **k: None)
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)


# ── The scheme: asked once, switched in place, remembered ───────────

def test_the_first_start_asks_once_and_the_choice_is_kept(monkeypatch):
    asked = []
    monkeypatch.setattr(controls, "ask_scheme",
                        lambda parent=None, default=None:
                        asked.append(default) or controls.VIM)
    assert controls.saved_scheme() is None
    assert controls.restore_or_ask() == controls.VIM
    controls.set_scheme(controls.STANDARD)
    # The next start: the saved choice, no question.
    assert controls.restore_or_ask() == controls.VIM
    assert asked == [controls.STANDARD]      # a new user's fallback


def test_closing_the_question_takes_the_standard_scheme(monkeypatch):
    monkeypatch.setattr(controls, "ask_scheme",
                        lambda parent=None, default=None: "")
    assert controls.restore_or_ask() == controls.STANDARD
    assert controls.saved_scheme() == controls.STANDARD


def test_an_earlier_user_who_closes_the_question_keeps_the_vim_keys(
        monkeypatch):
    controls._settings().setValue("theme/name", "dark")
    offered = []
    monkeypatch.setattr(controls, "ask_scheme",
                        lambda parent=None, default=None:
                        offered.append(default) or "")
    assert controls.restore_or_ask() == controls.VIM
    assert offered == [controls.VIM]
    assert controls.saved_scheme() == controls.VIM


def test_the_question_falls_back_on_the_default_it_shows():
    _app()
    from grafli.standard_ui import SchemeDialog
    dlg = SchemeDialog(current=controls.VIM)
    assert dlg.choice == controls.VIM
    dlg.reject()
    assert dlg.choice == controls.VIM


def test_the_question_offers_both_schemes():
    _app()
    from PySide6.QtWidgets import QPushButton
    from grafli.standard_ui import SchemeDialog
    dlg = SchemeDialog()
    assert dlg.choice == controls.STANDARD
    dlg.findChild(QPushButton, "scheme_vim").click()
    assert dlg.choice == controls.VIM
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_main_settles_the_scheme_before_the_window(monkeypatch):
    import inspect
    from grafli import app
    src = inspect.getsource(app.main)
    assert src.index("controls.restore_or_ask()") < src.index(
        "window = MainWindow(")


def test_switching_keeps_the_open_board_and_survives_a_restart(tmp_path):
    win, view = _window(tmp_path, scheme=controls.VIM)
    try:
        assert not win.menuBar().isVisibleTo(win)
        view._box_items["a"].setSelected(True)
        view._push_undo()
        board, undo = view.board, list(view._undo_stack)
        path = win._file_path
        win.set_control_scheme(controls.STANDARD)
        assert controls.is_standard()
        assert win.menuBar().isVisibleTo(win)
        assert win._std_toolbar is not None and \
            win._std_toolbar.isVisibleTo(win)
        # The same board, selection, undo history and file — no reload.
        assert view.board is board and win._file_path == path
        assert view._undo_stack == undo
        assert view._box_items["a"].isSelected()
        assert all(not a.isEnabled() for a in win._vim_actions)
        assert controls.saved_scheme() == controls.STANDARD

        win.set_control_scheme(controls.VIM)
        assert not win.menuBar().isVisibleTo(win)
        assert not win._std_toolbar.isVisibleTo(win)
        assert win._std_toolbar not in win.findChildren(type(win._std_toolbar)) \
            or win.toolBarArea(win._std_toolbar) != Qt.ToolBarArea.TopToolBarArea \
            or not win._std_toolbar.isVisibleTo(win)
        assert win.menuBar().actions() == []
        assert all(not a.isEnabled() for a in win._std.actions.values())
        assert all(a.isEnabled() for a in win._vim_actions)
        assert view.board is board
        assert controls.saved_scheme() == controls.VIM
    finally:
        win.close()


def test_the_scheme_switch_is_in_the_tools_panel_and_the_help(
        tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    win, view = _window(tmp_path, scheme=controls.VIM)
    try:
        win._side_panel._buttons["scheme"].clicked.emit("scheme")
        assert controls.is_standard() and win.menuBar().isVisibleTo(win)

        def _exec(dlg):
            dlg.findChild(QPushButton, "switch_scheme").click()
            return 0

        monkeypatch.setattr(QDialog, "exec", _exec)
        view._show_cheatsheet()
        assert controls.scheme() == controls.VIM
        assert not win.menuBar().isVisibleTo(win)
    finally:
        win.close()


def test_the_help_menu_switches_the_scheme(std):
    win, view = std
    act = _walk(win.menuBar().actions(),
                ["Help", "Control scheme", controls.TITLES[controls.VIM]])
    act.trigger()
    assert controls.scheme() == controls.VIM
    assert not win.menuBar().isVisibleTo(win)


# ── Every documented control is bound ───────────────────────────────

_KEY_NAMES = {
    "Esc": Qt.Key.Key_Escape, "Delete": Qt.Key.Key_Delete,
    "Backspace": Qt.Key.Key_Backspace, "Enter": Qt.Key.Key_Return,
    "Tab": Qt.Key.Key_Tab, "Space": Qt.Key.Key_Space,
    "←": Qt.Key.Key_Left, "→": Qt.Key.Key_Right, "↑": Qt.Key.Key_Up,
    "↓": Qt.Key.Key_Down, "+": Qt.Key.Key_Plus, "-": Qt.Key.Key_Minus,
    "=": Qt.Key.Key_Equal, "[": Qt.Key.Key_BracketLeft,
    "]": Qt.Key.Key_BracketRight,
}
_MOD_NAMES = {"Ctrl": CTRL, "Cmd": CTRL, "Shift": SHIFT, "Alt": ALT}


def chords(notation: str) -> list[list[str]]:
    """The chords a row's keys stand for; ``←↑↓→`` is all four arrows."""
    out = []
    for alt in keymap.parse_keys(notation):
        assert len(alt) == 1, f"no key sequences in the standard scheme: " \
                              f"{notation!r}"
        chord = alt[0]
        if chord[-1] == "←↑↓→":
            out += [chord[:-1] + [a] for a in "←↑↓→"]
        else:
            out.append(chord)
    return out


def press(view, chord: list[str]):
    mods = NOMOD
    for part in chord[:-1]:
        mods |= _MOD_NAMES[part]
    name = chord[-1]
    if name in _KEY_NAMES:
        key = _KEY_NAMES[name]
    elif re.fullmatch(r"F\d+", name):
        key = Qt.Key(Qt.Key.Key_F1.value + int(name[1:]) - 1)
    else:
        key = QKeySequence(name)[0].key()
    QTest.keyClick(view, key, mods)


def _menu_of(act):
    # QMenu.menuInAction first: QAction.menu() hands back a deleted object
    # on some PySide6 releases.
    menu = QMenu.menuInAction(act)
    return menu if isinstance(menu, QMenu) else None


def _walk(actions, segments):
    from grafli.standard_ui import clean_text
    act = None
    for i, seg in enumerate(segments):
        act = next((a for a in actions
                    if clean_text(a.text()) == clean_text(seg)), None)
        assert act is not None, (
            f"{' ▸ '.join(segments)}: no {seg!r} among "
            f"{[clean_text(a.text()) for a in actions if a.text()]}")
        if i < len(segments) - 1:
            sub = _menu_of(act)
            assert sub is not None, f"{seg!r} is not a menu"
            sub.aboutToShow.emit()
            actions = sub.actions()
    return act


def _first_leaf(menu: QMenu):
    menu.aboutToShow.emit()
    for a in menu.actions():
        if a.isSeparator() or not a.isEnabled():
            continue
        sub = _menu_of(a)
        if sub is not None:
            leaf = _first_leaf(sub)
            if leaf is not None:
                return leaf
            continue
        return a
    return None


def _documented_rows():
    for g in keymap.STANDARD_GROUPS:
        for k in g.keys:
            yield pytest.param(g, k, id=f"{g.id}:{k.keys}:{k.action}")


BEHAVIOUR_PREFIXES = ("mouse:", "text:", "play:")


@pytest.mark.parametrize("group, row", list(_documented_rows()))
def test_every_documented_control_runs_its_command(group, row, std, fired,
                                                   monkeypatch):
    """Press the row's keys, or click its menu, toolbar or right-click
    item: the command the row names must run."""
    assert row.action, f"{group.id} {row.keys!r} names no command"
    win, view = std
    if row.action.startswith(BEHAVIOUR_PREFIXES):
        assert row.action in BEHAVIOUR_TESTS, (
            f"{row.action}: a documented behaviour without a test")
        return
    def check_handler():
        handler = _real_handlers(view).get(row.action)
        assert handler is not None, f"{row.action}: no command runs it"
        assert not hasattr(handler, "std_missing"), (
            f"{row.action}: the window has no {handler.std_missing}")
    view._box_items["a"].setSelected(True)
    if not row.is_gesture:
        check_handler()
        for chord in chords(row.keys):
            fired.clear()
            press(view, chord)
            assert [a for a, _ in fired] == [row.action], (
                f"{'+'.join(chord)} ran {fired}, the docs say {row.action}")
        return
    segments = row.keys.split(" ▸ ")
    assert len(segments) >= 2, f"{row.keys!r}: a gesture is a behaviour " \
                               f"(mouse:) or a menu path"
    where, path = segments[0], segments[1:]
    if where == "Toolbar":
        act = _walk(win._std_toolbar.actions(), path)
    elif where == "Right-click":
        _no_popups(monkeypatch)
        menu = view._std_context_menu(_vpos(view, _center(
            view._box_items["a"])))
        act = _walk(menu.actions(), path)
    else:
        act = _walk(win.menuBar().actions(), segments)
    sub = _menu_of(act)
    if sub is not None:
        assert sub.objectName() == row.action, (
            f"{row.keys}: the menu is {sub.objectName()!r}, the docs say "
            f"{row.action!r}")
        leaf = _first_leaf(sub)
        assert leaf is not None, f"{row.keys}: an empty menu"
        fired.clear()
        leaf.trigger()
        assert fired, f"{row.keys} ▸ {leaf.text()} runs nothing"
        return
    check_handler()
    fired.clear()
    act.trigger()
    assert [a for a, _ in fired] == [row.action]


def _real_handlers(view):
    from grafli.view.standard import StandardMixin
    return StandardMixin._std_handlers(view)


def test_every_command_the_menus_and_toolbar_run_is_bound(std):
    """No menu item, toolbar button or key leads to a missing command."""
    from grafli.standard_ui import ACTIONS
    from grafli.view.standard import PLAYBACK_KEYS, STANDARD_KEYS
    win, view = std
    handlers = _real_handlers(view)
    used = (set(ACTIONS) - {"at_a_glance"}) | {
        a for a, _ in STANDARD_KEYS.values()} | set(PLAYBACK_KEYS.values()) | {
        "color", "textsize", "face", "axis", "connected_box", "attach",
        "follow_arrow", "scheme", "on_target", "insert_box", "insert_note",
        "connect_from", "play_mode", "play_transition"}
    assert not used - set(handlers), used - set(handlers)
    missing = {name: h.std_missing for name, h in handlers.items()
               if hasattr(h, "std_missing")}
    assert not missing, f"window methods that do not exist: {missing}"


def test_switching_back_and_forth_piles_nothing_up(tmp_path):
    from PySide6.QtGui import QAction
    win, view = _window(tmp_path, scheme=controls.VIM)
    try:
        counts = []
        for _ in range(3):
            win.set_control_scheme(controls.STANDARD)
            win.set_control_scheme(controls.VIM)
            QApplication.sendPostedEvents(None,
                                          QEvent.Type.DeferredDelete.value)
            counts.append((len(win.findChildren(QAction)),
                           len(win.findChildren(QMenu))))
        assert counts[0] == counts[1] == counts[2]
        win.set_control_scheme(controls.STANDARD)
        assert [a.text() for a in win.menuBar().actions()][:2] == [
            "File", "Edit"]
    finally:
        win.close()


def test_no_two_standard_rows_share_keys_and_words():
    rows = [(keymap.compact_keys(k), k.does)
            for g in keymap.STANDARD_GROUPS for k in g.keys]
    assert len(rows) == len(set(rows))


def test_a_plain_letter_never_runs_a_command(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    before = (serialize(view.board), view.mode, view.transform(),
              view._minimap_visible, view._grid_mode, view._notes_hidden,
              view._arrows_dimmed, view._debug_overlay,
              win._side_panel.isVisible(), view._legend_visible,
              view._lod_enabled)
    ran = []
    real = view.std_run
    view.std_run = lambda a, **kw: ran.append(a) or real(a, **kw)
    keys = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + list(
        "0123456789/=#\\,`+-.;'")
    for ch in keys:
        for mods in (NOMOD, SHIFT):
            key = QKeySequence(ch)[0].key()
            QTest.keyClick(view, key, mods)
    after = (serialize(view.board), view.mode, view.transform(),
             view._minimap_visible, view._grid_mode, view._notes_hidden,
             view._arrows_dimmed, view._debug_overlay,
             win._side_panel.isVisible(), view._legend_visible,
             view._lod_enabled)
    assert ran == []
    assert after == before
    assert not (view._search_active or view._jump_active or view._box_mode
                or view._focus_active or view._complexity_active
                or view._graph_nav_active or view._g_pending)
    assert [i.box.id for i in view._scene.selectedItems()] == ["a"]


def test_the_vim_keys_are_off_and_back_on(tmp_path):
    win, view = _window(tmp_path, scheme=controls.VIM)
    try:
        view._box_items["a"].setSelected(True)
        QTest.keyClick(view, Qt.Key.Key_X)     # vim: x deletes
        assert view.board.box_by_id("a") is None
        win.set_control_scheme(controls.STANDARD)
        view._box_items["b"].setSelected(True)
        QTest.keyClick(view, Qt.Key.Key_X)     # standard: nothing
        assert view.board.box_by_id("b") is not None
    finally:
        win.close()


# ── The usual shortcuts do what they do elsewhere ───────────────────

def test_copy_cut_paste(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_C, CTRL)
    assert [b.label for b in view._clipboard_boxes] == ["A"]
    n = len(view.board.boxes)
    QTest.keyClick(view, Qt.Key.Key_V, CTRL)
    assert len(view.board.boxes) == n + 1
    view._scene.clearSelection()
    view._box_items["b"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_X, CTRL)
    assert view.board.box_by_id("b") is None
    assert [b.label for b in view._clipboard_boxes] == ["B"]
    QTest.keyClick(view, Qt.Key.Key_V, CTRL)
    assert "B" in [b.label for b in view.board.boxes]


def test_undo_and_redo(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.board.box_by_id("a") is None
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)
    assert view.board.box_by_id("a") is not None
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL | SHIFT)
    assert view.board.box_by_id("a") is None
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)
    QTest.keyClick(view, Qt.Key.Key_Y, CTRL)
    assert view.board.box_by_id("a") is None


def test_select_all_and_find(std):
    win, view = std
    QTest.keyClick(view, Qt.Key.Key_A, CTRL)
    selected = view._scene.selectedItems()
    assert len(selected) == len(view.board.boxes) + len(view.board.notes)
    QTest.keyClick(view, Qt.Key.Key_F, CTRL)
    assert view._search_active
    QTest.keyClicks(view, "Big")      # typed into the find field
    assert view._search_text == "Big"
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view._search_active


def test_delete_removes_the_selection_and_an_arrow(std):
    win, view = std
    arrow = view.board.arrows[0]
    view._select_arrow(arrow)
    QTest.keyClick(view, Qt.Key.Key_Backspace)
    assert view.board.arrows == []
    view._box_items["c"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.board.box_by_id("c") is None


def test_the_arrow_keys_move_the_selection_or_pan(std):
    win, view = std
    box = view.board.box_by_id("c")
    view._box_items["c"].setSelected(True)
    x, y = box.x, box.y
    QTest.keyClick(view, Qt.Key.Key_Right)
    QTest.keyClick(view, Qt.Key.Key_Down, SHIFT)
    assert box.x > x and box.y > y
    assert (box.x - x) < (box.y - y)          # Shift moves further
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)
    assert view.board.box_by_id("c").y == y
    view._scene.clearSelection()
    h = view.horizontalScrollBar().value()
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert view.horizontalScrollBar().value() > h


def test_moving_a_box_by_keys_takes_what_it_holds(std):
    win, view = std
    # Drop c into big so it is nested, then move big with an arrow key.
    _drag(view, _center(view._box_items["c"]), QPointF(200, 350))
    assert view.board.box_by_id("c").parent == "big"
    view._scene.clearSelection()
    view._box_items["big"].setSelected(True)
    view._box_items["c"].setSelected(True)   # held and selected: moves once
    cx, bx = view.board.box_by_id("c").x, view.board.box_by_id("big").x
    QTest.keyClick(view, Qt.Key.Key_Right)
    dx_big = view.board.box_by_id("big").x - bx
    assert dx_big > 0
    assert view.board.box_by_id("c").x - cx == dx_big


# ── Mouse and menus alone ───────────────────────────────────────────

def _toolbar(win, text):
    return _walk(win._std_toolbar.actions(), [text])


def test_toolbar_creates_a_box_a_note_and_an_image(std, tmp_path,
                                                   monkeypatch):
    win, view = std
    n_boxes = len(view.board.boxes)
    _toolbar(win, "Box").trigger()
    assert view.mode == Mode.RECT
    _click(view, QPointF(900, 100))
    assert len(view.board.boxes) == n_boxes + 1
    assert view.mode == Mode.SELECT and view._editor is not None
    view._commit_editor()

    _toolbar(win, "Note").trigger()
    n_notes = len(view.board.notes)
    _click(view, QPointF(900, 300))
    assert len(view.board.notes) == n_notes + 1
    assert view._note_widget is not None
    view._commit_editor()

    png = tmp_path / "pic.png"
    img = QImage(40, 20, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.red)
    img.save(str(png))
    monkeypatch.setattr(view, "_image_file_dialog", lambda: [str(png)])
    _toolbar(win, "Image").trigger()
    assert len(view.board.images) == 1


def test_toolbar_mockup_places_an_svg(std, monkeypatch):
    win, view = std
    opened = []
    monkeypatch.setattr(view, "_open_image_source", opened.append)
    _toolbar(win, "Mockup").trigger()
    assert view.mode == Mode.IMAGE
    _click(view, QPointF(900, 500))
    assert len(view.board.images) == 1 and opened


def test_toolbar_arrow_connects_two_boxes(std):
    win, view = std
    _toolbar(win, "Arrow").trigger()
    assert view.mode == Mode.CONNECT
    _click(view, _center(view._box_items["b"]))
    _click(view, _center(view._box_items["c"]))
    assert any(a.from_id == "b" and a.to_id == "c"
               for a in view.board.arrows)


def test_the_right_click_menu_connects_and_deletes(std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    menu = view._std_context_menu(_vpos(view, _center(view._box_items["c"])))
    _walk(menu.actions(), ["Connect from here"]).trigger()
    _click(view, _center(view._box_items["big"]))
    assert any(a.from_id == "c" and a.to_id == "big"
               for a in view.board.arrows)
    view.set_mode(Mode.SELECT)
    menu = view._std_context_menu(_vpos(view, _center(view._box_items["c"])))
    _walk(menu.actions(), ["Delete"]).trigger()
    assert view.board.box_by_id("c") is None


def test_the_right_click_menu_on_the_canvas_creates_there(std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    spot = QPointF(1000, 1000)
    menu = view._std_context_menu(_vpos(view, spot))
    _walk(menu.actions(), ["New box here"]).trigger()
    box = view.board.boxes[-1]
    assert abs(box.x + box.w / 2 - spot.x()) < 2
    view._commit_editor()
    menu = view._std_context_menu(_vpos(view, spot + QPointF(0, 200)))
    _walk(menu.actions(), ["New note here"]).trigger()
    assert view._note_widget is not None


def test_double_click_renames_a_box_and_an_arrows_label(std):
    win, view = std
    _double_click(view, _center(view._box_items["a"]))
    assert view._editor is not None
    view._editor.setPlainText("Renamed")
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert view.board.box_by_id("a").label == "Renamed"

    arrow = view.board.arrows[0]
    _double_click(view, _center(_label_of(view, arrow)))
    assert view._editor is not None and view._edit_target is arrow
    view._editor.setPlainText("leads to")
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert view.board.arrows[0].label == "leads to"


def test_f2_renames_and_the_edit_menu_edits_in_a_window(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    assert view._editor is not None
    view._commit_editor()
    view._scene.clearSelection()
    view._note_items["n"].setSelected(True)
    _walk(win.menuBar().actions(), ["Edit", "Edit in a window"]).trigger()
    from grafli.standard_ui import PlainTextWindow
    assert isinstance(view._zen_editor, PlainTextWindow)
    view._zen_editor.field.setPlainText("Longer text\nover lines")
    view._zen_editor.done()
    assert view.board.notes[0].text == "Longer text\nover lines"
    assert view._zen_editor is None


def test_format_menu_sets_colour_icon_and_text(std, monkeypatch):
    win, view = std
    view._box_items["a"].setSelected(True)
    _walk(win.menuBar().actions(), ["Format", "Colour", "Primary"]).trigger()
    assert view.board.box_by_id("a").color == "%primary"
    monkeypatch.setattr(view, "_icon_dialog", lambda cur, place: ("star",
                                                                  "lead"))
    _walk(win.menuBar().actions(), ["Format", "Icon"]).trigger()
    box = view.board.box_by_id("a")
    assert (box.icon, box.icon_placement) == ("star", "lead")
    _walk(win.menuBar().actions(), ["Format", "Text", "Large"]).trigger()
    _walk(win.menuBar().actions(), ["Format", "Text", "Bold"]).trigger()
    _walk(win.menuBar().actions(), ["Format", "Text", "Font", "Sans"]
          ).trigger()
    box = view.board.box_by_id("a")
    assert box.textsize == "large" and "bold" in box.emphasis and box.sans
    _walk(win.menuBar().actions(), ["Format", "Appearance", "Background",
                                    "Flat"]).trigger()
    assert view.board.box_by_id("a").style == "flat"
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)
    assert view.board.box_by_id("a").style == ""


def test_format_menu_styles_an_arrow(std):
    win, view = std
    view._select_arrow(view.board.arrows[0])
    _walk(win.menuBar().actions(), ["Format", "Colour", "Accent"]).trigger()
    assert view.board.arrows[0].color == "%accent"
    _walk(win.menuBar().actions(), ["Format", "Appearance", "Routing"])
    target, axes = view.std_axes()
    assert target == "arrow"
    row = next(i for i, a in enumerate(axes) if a["label"] == "Line")
    value = axes[row]["options"][1][1]
    view.std_run("axis", row=row, value=value)
    assert view.board.arrows[0].style == value
    _walk(win.menuBar().actions(), ["Format", "Arrow kind"]).trigger()
    assert view.board.arrows[0].kind in ("graph", "annotation")


def test_the_icon_dialog_picks_with_the_mouse():
    _app()
    from grafli.standard_ui import IconDialog
    dlg = IconDialog(None, "", "")
    for i in range(dlg.grid.count()):
        if dlg.grid.item(i).text() == "star":
            dlg.grid.setCurrentRow(i)
    dlg.placement.setCurrentIndex(2)
    assert dlg.value() == ("star", "badge")
    dlg.number.setValue(3)
    dlg.filled.setChecked(True)
    name, _ = dlg.value()
    assert name.endswith("3") and name != "3"
    dlg.filter.setText("star")
    hidden = [dlg.grid.item(i).isHidden() for i in range(dlg.grid.count())]
    assert any(hidden) and not all(hidden)


def test_toolbar_undo_redo_and_file_menu(std, monkeypatch, tmp_path):
    win, view = std
    view._box_items["a"].setSelected(True)
    _toolbar(win, "Delete").trigger()
    assert view.board.box_by_id("a") is None
    _toolbar(win, "Undo").trigger()
    assert view.board.box_by_id("a") is not None
    _toolbar(win, "Redo").trigger()
    assert view.board.box_by_id("a") is None

    from PySide6.QtWidgets import QFileDialog
    other = tmp_path / "other.grafli"
    other.write_text('#!grafli v4\n@ box z "Z" 0,0 100x60\n')
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(other), ""))
    _walk(win.menuBar().actions(), ["File", "Open"]).trigger()
    assert win._file_path == other
    view.board.box_by_id("z").label = "Saved"
    _walk(win.menuBar().actions(), ["File", "Save"]).trigger()
    assert '"Saved"' in other.read_text()
    svg = tmp_path / "out.svg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(svg), ""))
    _walk(win.menuBar().actions(), ["File", "Export", "SVG"]).trigger()
    assert svg.exists() and "<svg" in svg.read_text()


# ── The behaviours the table names ──────────────────────────────────

def test_click_selects(std):
    win, view = std
    _click(view, _center(view._box_items["b"]))
    assert view._box_items["b"].isSelected()


def test_shift_click_adds_to_the_selection(std):
    win, view = std
    _click(view, _center(view._box_items["a"]))
    _click(view, _center(view._box_items["b"]), mods=SHIFT)
    assert view._box_items["a"].isSelected()
    assert view._box_items["b"].isSelected()


def test_drag_on_empty_canvas_selects_in_a_rectangle(std):
    win, view = std
    _drag(view, QPointF(-50, -50), QPointF(450, 100))
    ids = {i.box.id for i in view._scene.selectedItems()}
    assert {"a", "b"} <= ids and "big" not in ids


def test_dragging_moves(std):
    win, view = std
    box = view.board.box_by_id("b")
    x = box.x
    _drag(view, _center(view._box_items["b"]),
          _center(view._box_items["b"]) + QPointF(120, 0))
    assert box.x > x + 60


def test_dropping_on_a_box_nests_and_outside_takes_out(std):
    win, view = std
    _drag(view, _center(view._box_items["c"]), QPointF(200, 350))
    assert view.board.box_by_id("c").parent == "big"
    _drag(view, _center(view._box_items["c"]), QPointF(900, 900))
    assert not view.board.box_by_id("c").parent


def test_dragging_a_corner_resizes(std):
    win, view = std
    item = view._box_items["c"]
    _click(view, _center(item))
    box = view.board.box_by_id("c")
    w = box.w
    corner = QPointF(box.x + box.w, box.y + box.h)
    _drag(view, corner - QPointF(1, 1), corner + QPointF(80, 40))
    assert box.w > w + 30


def test_double_click_edits(std):
    win, view = std
    _double_click(view, _center(view._note_items["n"]))
    assert view._note_widget is not None


def test_right_click_opens_the_menu_for_what_is_under_it(std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    names = lambda m: {a.objectName() for a in m.actions()}  # noqa: E731
    h = view.horizontalScrollBar().value()
    _click(view, _center(view._box_items["b"]), Qt.MouseButton.RightButton)
    menu = view._last_context_menu
    assert {"rename", "delete", "color", "connect_from"} <= names(menu)
    assert view._box_items["b"].isSelected()
    assert not view._panning and view.horizontalScrollBar().value() == h
    _click(view, _center(_label_of(view, view.board.arrows[0])),
           Qt.MouseButton.RightButton)
    assert "arrow_kind" in names(view._last_context_menu)
    _click(view, QPointF(1500, 1500), Qt.MouseButton.RightButton)
    assert {"insert_box", "insert_note", "paste_here"} <= names(
        view._last_context_menu)


def test_alt_drag_draws_an_arrow(std):
    win, view = std
    _drag(view, _center(view._box_items["b"]), _center(view._box_items["c"]),
          mods=ALT)
    assert any(a.from_id == "b" and a.to_id == "c" for a in view.board.arrows)


def test_middle_drag_and_space_drag_pan(std):
    win, view = std
    h = view.horizontalScrollBar().value()
    _drag(view, QPointF(1200, 1200), QPointF(1100, 1200),
          Qt.MouseButton.MiddleButton)
    assert view.horizontalScrollBar().value() > h
    h = view.horizontalScrollBar().value()
    QTest.keyPress(view, Qt.Key.Key_Space)
    _drag(view, _center(view._box_items["c"]),
          _center(view._box_items["c"]) - QPointF(100, 0))
    QTest.keyRelease(view, Qt.Key.Key_Space)
    assert view.horizontalScrollBar().value() > h
    assert not view._box_items["c"].isSelected()   # panned, did not grab


def test_the_wheel_zooms(std):
    win, view = std
    z = view.transform().m11()
    vp = view.viewport()
    pos = QPointF(vp.width() / 2, vp.height() / 2)
    ev = QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(),
                     QPoint(0, 120), NOB, NOMOD, Qt.ScrollPhase.NoScrollPhase,
                     False)
    QApplication.sendEvent(vp, ev)
    assert view.transform().m11() > z


def test_dropping_image_files_adds_them(std, tmp_path):
    win, view = std
    png = tmp_path / "drop.png"
    img = QImage(30, 30, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.blue)
    img.save(str(png))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(png))])
    vp = view.viewport()
    ev = QDropEvent(QPointF(vp.width() / 2, vp.height() / 2),
                    Qt.DropAction.CopyAction, mime, L, NOMOD)
    view.dropEvent(ev)
    assert len(view.board.images) == 1


def test_enter_keeps_a_label(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._editor.setPlainText("Kept")
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert view._editor is None
    assert view.board.box_by_id("a").label == "Kept"


def test_a_note_edits_without_vim_and_ctrl_enter_keeps_it(std):
    win, view = std
    from grafli.standard_ui import PlainInlineEditor
    view._note_items["n"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    widget = view._note_widget
    assert isinstance(widget, PlainInlineEditor)
    widget.selectAll()
    # No modes: Esc is not a NORMAL mode, i / x / d are just letters.
    QTest.keyClicks(widget, "ix dd")
    QTest.keyClick(widget, Qt.Key.Key_Return)
    QTest.keyClicks(widget, "two")
    QTest.keyClick(widget, Qt.Key.Key_Return, CTRL)
    assert view._note_widget is None
    assert view.board.notes[0].text == "ix dd\ntwo"


def test_esc_keeps_the_text_and_closes(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._editor.setPlainText("Esc keeps")
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view._editor is None
    assert view.board.box_by_id("a").label == "Esc keeps"
    view._scene.clearSelection()
    view._note_items["n"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._note_widget.setPlainText("note kept")
    QTest.keyClick(view._note_widget, Qt.Key.Key_Escape)
    assert view._note_widget is None
    assert view.board.notes[0].text == "note kept"


def test_clicking_elsewhere_keeps_the_text(std):
    win, view = std
    view._note_items["n"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._note_widget.setPlainText("clicked away")
    QApplication.sendEvent(view._note_widget,
                           QFocusEvent(QEvent.Type.FocusOut))
    assert view._note_widget is None
    assert view.board.notes[0].text == "clicked away"


def test_the_text_window_saves_with_ctrl_s(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    view.std_run("edit_text")          # the box's document, a file
    window = view._zen_editor
    assert window is not None and window._file_path is not None
    window.field.setPlainText("# A\n\nWritten without vim.\n")
    QTest.keyClick(window.field, Qt.Key.Key_S, CTRL)
    assert "Written without vim." in window._file_path.read_text()
    assert view._zen_editor is window          # still open
    QTest.keyClick(window.field, Qt.Key.Key_Escape)
    assert view._zen_editor is None


TOUR = """#!grafli v4
@ box a "A" 0,0 100x60
@ box b "B" 400,0 100x60
@ bookmark s1 "One" @a
@ bookmark s2 "Two" @b
@ flow f "Tour" s1 s2
"""


@pytest.fixture
def tour(tmp_path):
    win, view = _window(tmp_path, TOUR)
    view.play_flow("f")
    assert view._flow_player.active
    yield win, view
    win.close()


def test_playback_space_and_right_go_on(tour):
    win, view = tour
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert view._flow_player.index == 1
    view._flow_player.goto(0)
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert view._flow_player.index == 1


def test_playback_left_goes_back(tour):
    win, view = tour
    view._flow_player.goto(1)
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert view._flow_player.index == 0


def test_playback_esc_stops_and_letters_do_nothing(tour):
    win, view = tour
    mode, smooth = view._flow_player.mode, view._flow_player.smooth
    for k in (Qt.Key.Key_P, Qt.Key.Key_T, Qt.Key.Key_L, Qt.Key.Key_Q):
        QTest.keyClick(view, k)
    assert view._flow_player.active and view._flow_player.index == 0
    assert (view._flow_player.mode, view._flow_player.smooth) == (
        mode, smooth)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view._flow_player is None or not view._flow_player.active


BEHAVIOUR_TESTS = {
    "mouse:play_menu": None,      # filled in below
    "mouse:select": test_click_selects,
    "mouse:add_select": test_shift_click_adds_to_the_selection,
    "mouse:rubber_band": test_drag_on_empty_canvas_selects_in_a_rectangle,
    "mouse:move": test_dragging_moves,
    "mouse:nest": test_dropping_on_a_box_nests_and_outside_takes_out,
    "mouse:resize": test_dragging_a_corner_resizes,
    "mouse:edit": test_double_click_renames_a_box_and_an_arrows_label,
    "mouse:context_menu": test_right_click_opens_the_menu_for_what_is_under_it,
    "mouse:alt_connect": test_alt_drag_draws_an_arrow,
    "mouse:pan": test_middle_drag_and_space_drag_pan,
    "mouse:zoom": test_the_wheel_zooms,
    "mouse:drop_images": test_dropping_image_files_adds_them,
    "text:enter": test_enter_keeps_a_label,
    "text:ctrl_enter": test_a_note_edits_without_vim_and_ctrl_enter_keeps_it,
    "text:esc": test_esc_keeps_the_text_and_closes,
    "text:click_away": test_clicking_elsewhere_keeps_the_text,
    "text:save": test_the_text_window_saves_with_ctrl_s,
    "play:next": test_playback_space_and_right_go_on,
    "play:prev": test_playback_left_goes_back,
    "play:stop": test_playback_esc_stops_and_letters_do_nothing,
}


def test_every_behaviour_test_is_for_a_documented_row():
    documented = {k.action for g in keymap.STANDARD_GROUPS for k in g.keys}
    assert set(BEHAVIOUR_TESTS) <= documented


# ── The help and the docs follow the scheme ─────────────────────────

def test_the_f1_help_shows_the_active_scheme(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel, QTabWidget, QTextBrowser
    win, view = _window(tmp_path)
    shown = {}

    def _exec(dlg):
        tabs = dlg.findChild(QTabWidget)
        page = tabs.widget(0)
        shown["text"] = "\n" + "\n".join(
            b.toPlainText() for b in page.findChildren(QTextBrowser)) + "\n"
        shown["note"] = dlg.findChild(QLabel, "scheme_note").text()
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    QTest.keyClick(view, Qt.Key.Key_F1)
    win.close()
    assert "Standard" in shown["note"]
    missing = [(g.id, k.keys) for g in keymap.STANDARD_GROUPS for k in g.keys
               if f"\n{keymap.compact_keys(k)}\n{k.does}\n" not in
               shown["text"]]
    assert not missing
    vim_only = keymap.find("modes", "n")
    assert vim_only.does not in shown["text"]


def test_the_page_for_the_standard_scheme(tmp_path, monkeypatch):
    from grafli import helppage
    page = helppage.render_page(controls.STANDARD)
    for g in keymap.STANDARD_GROUPS:
        card = helppage.card_html(page, g.id)
        for k in g.keys:
            assert helppage.row_html(k) in card, (g.id, k.keys)
    assert 'id="k-modes"' not in page
    copy = REPO / helppage.DOCS_COPIES[controls.STANDARD]
    assert copy.read_text(encoding="utf-8") == page, (
        "docs/at-a-glance-standard.html is out of date: run "
        "python -m grafli.helppage")
    controls.set_scheme(controls.STANDARD)
    local = helppage.local_copy()
    assert local.read_text(encoding="utf-8") == page
    local.unlink()


STANDARD_DOCS = ("standard-controls.md", "navigating-standard.md")


def _doc(name: str) -> str:
    return (REPO / "docs" / name).read_text(encoding="utf-8")


def _documented_chords() -> set[str]:
    out = set()
    for g in keymap.STANDARD_GROUPS:
        for k in g.keys:
            if not k.is_gesture:
                out |= {"+".join(c) for c in chords(k.keys)}
    return out


_KBD_CHORD = re.compile(r"<kbd>([^<]+)</kbd>((?:\s*\+\s*<kbd>[^<]+</kbd>)*)")


@pytest.mark.parametrize("name", STANDARD_DOCS)
def test_every_key_the_standard_docs_name_is_a_bound_control(name):
    """A key the standard pages name must be a row of the table, which
    the test above presses; a lone modifier is a mouse gesture's
    (Shift+click)."""
    known = _documented_chords()
    wrong = []
    for m in _KBD_CHORD.finditer(_doc(name)):
        parts = [m.group(1)] + re.findall(r"<kbd>([^<]+)</kbd>", m.group(2))
        if all(p in _MOD_NAMES for p in parts):
            continue
        chord = "+".join(parts)
        if chord not in known:
            wrong.append(chord)
    assert not wrong, f"{name} names keys no standard control has: {wrong}"


_MENU_PATH = re.compile(r"\*\*((?:File|Edit|Insert|Format|Arrange|View|Go|"
                        r"Tours|Help|Toolbar|Right-click) ▸ [^*]+)\*\*")


@pytest.mark.parametrize("name", STANDARD_DOCS)
def test_every_menu_item_the_standard_docs_name_exists(name, std,
                                                       monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    view._box_items["a"].setSelected(True)
    paths = _MENU_PATH.findall(_doc(name))
    assert paths, f"{name} names no menu item"
    for path in paths:
        segments = [" ".join(s.split()) for s in path.split(" ▸ ")]
        where = segments[0]
        if where == "Toolbar":
            _walk(win._std_toolbar.actions(), segments[1:])
        elif where == "Right-click":
            menu = view._std_context_menu(_vpos(view, _center(
                view._box_items["a"])))
            _walk(menu.actions(), segments[1:])
        else:
            _walk(win.menuBar().actions(), segments)


def test_the_standard_controls_page_lists_every_row():
    from grafli import helppage
    text = _doc("standard-controls.md")
    assert helppage.standard_controls_md() in text, (
        "docs/standard-controls.md is out of date: run "
        "python -m grafli.helppage")


def test_the_docs_navigation_has_each_scheme():
    nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
    for page in ("keybindings.md", "standard-controls.md", "navigating.md",
                 "navigating-standard.md"):
        assert page in nav, page
    # Each page says which scheme it is for and points at the other.
    assert "navigating-standard.md" in _doc("navigating.md")
    assert "navigating.md" in _doc("navigating-standard.md")
    assert "standard-controls.md" in _doc("keybindings.md")
    assert "keybindings.md" in _doc("standard-controls.md")


def test_on_screen_hints_name_standard_controls(tmp_path):
    win, view = _window(tmp_path, "#!grafli v4\n")
    try:
        lines = " ".join(t for t, _ in view._empty_hint_lines())
        assert "toolbar" in lines and "n box" not in lines
        win.set_control_scheme(controls.VIM)
        assert view._empty_hint_lines()[0][0].startswith("n box")
    finally:
        win.close()


def test_text_commands_that_reach_the_canvas_go_to_the_open_field(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._editor.setPlainText("label text")
    view.std_run("select_all")
    view.std_run("copy")
    assert QApplication.clipboard().text() == "label text"
    assert view._editor is not None and view.board.box_by_id("a")
    view._commit_editor()
    view._scene.clearSelection()
    view._note_items["n"].setSelected(True)
    view.std_run("edit_text")
    window = view._zen_editor
    window.field.setPlainText("saved by the menu")
    view.std_run("save")          # File ▸ Save while the window is open
    assert view.board.notes[0].text == "saved by the menu"
    assert view._zen_editor is window
    window.done()


# ── Review fixes (#352) ─────────────────────────────────────────────

def test_right_click_while_presenting_has_the_tour_controls(tour,
                                                            monkeypatch):
    win, view = tour
    _no_popups(monkeypatch)
    view._flow_player.end()          # present it from the start, as F5 does
    win._present_current()
    try:
        assert not win.menuBar().isVisibleTo(win)
        player = view._flow_player
        _click(view, QPointF(0, 0), Qt.MouseButton.RightButton)
        menu = view._last_context_menu
        assert menu.objectName() == "playback_menu"
        named = {a.objectName(): a for a in menu.actions()}
        mode, smooth = player.mode, player.smooth
        named["play_mode"].trigger()
        named["play_transition"].trigger()
        assert player.mode != mode and player.smooth != smooth
        named["play_next"].trigger()
        assert player.index == 1
    finally:
        win._exit_present()


BEHAVIOUR_TESTS["mouse:play_menu"] = \
    test_right_click_while_presenting_has_the_tour_controls


def test_enter_offers_to_attach_with_the_mouse_not_letters(std,
                                                           monkeypatch):
    win, view = std
    from grafli.view import resources
    monkeypatch.setattr(resources, "_ResourcePicker",
                        lambda *a, **k: pytest.fail("the letter picker"))
    _no_popups(monkeypatch)
    box = view.board.box_by_id("c")
    view._box_items["c"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_Return)
    menu = view._last_context_menu
    assert menu.objectName() == "attach"
    assert all(not a.text().startswith("[") for a in menu.actions())
    next(a for a in menu.actions()
         if a.objectName() == "attach:grafli").trigger()
    assert box.attach_kind == "graph"
    assert win._file_path.name == "c.grafli"     # went into the sub-board


def test_edit_attach_gives_a_box_a_sub_board(std):
    win, view = std
    box = view.board.box_by_id("b")
    view._box_items["b"].setSelected(True)
    _walk(win.menuBar().actions(), ["Edit", "Attach", "Sub-board"]).trigger()
    assert box.attach_kind == "graph" and win._file_path.name == "b.grafli"


def test_edit_in_a_window_reopens_the_document(std):
    win, view = std
    view._box_items["b"].setSelected(True)
    view.std_run("edit_text")
    view._zen_editor.field.setPlainText("# B\n\nfirst words\n")
    view._zen_editor.done()
    assert view.board.box_by_id("b").attach_kind == "doc"
    view._box_items["b"].setSelected(True)
    view.std_run("edit_text")
    assert view._zen_editor is not None
    assert "first words" in view._zen_editor.text()
    view._zen_editor.done()


def test_find_keeps_the_keys_from_the_board(std):
    win, view = std
    QTest.keyClick(view, Qt.Key.Key_F, CTRL)
    QTest.keyClicks(view, "B")
    QTest.keyClick(view, Qt.Key.Key_X, CTRL)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.board.box_by_id("b") is not None
    assert view.board.box_by_id("big") is not None
    QApplication.clipboard().setText("ig")
    QTest.keyClick(view, Qt.Key.Key_V, CTRL)
    assert view._search_text == "Big"


def test_the_right_click_menu_acts_on_the_box_it_was_opened_on(
        std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    view._box_items["a"].setSelected(True)
    view._box_items["b"].setSelected(True)
    menu = view._std_context_menu(_vpos(view, _center(view._box_items["b"])))
    _walk(menu.actions(), ["Rename"]).trigger()
    assert view._edit_target is view._box_items["b"]
    view._commit_editor()
    # With a tool active, the right-clicked box is still what is acted on.
    _toolbar(win, "Arrow").trigger()
    menu = view._std_context_menu(_vpos(view, _center(view._box_items["c"])))
    assert view.mode == Mode.SELECT and view._box_items["c"].isSelected()
    _walk(menu.actions(), ["Delete"]).trigger()
    assert view.board.box_by_id("c") is None


def test_a_label_being_typed_is_kept_before_the_right_click_acts(
        std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    view._select_arrow(view.board.arrows[0])
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._editor.setPlainText("typed")
    menu = view._std_context_menu(_vpos(view, _center(view._box_items["c"])))
    _walk(menu.actions(), ["Delete"]).trigger()
    assert view.board.box_by_id("c") is None
    assert [a.label for a in view.board.arrows] == ["typed"]


def test_clicking_elsewhere_keeps_a_label_and_goes_on(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    view._editor.setPlainText("Clicked away")
    _click(view, _center(view._box_items["b"]))
    assert view._editor is None
    assert view.board.box_by_id("a").label == "Clicked away"
    assert view._box_items["b"].isSelected()


def test_select_all_takes_the_arrows_too(std):
    win, view = std
    before = serialize(view.board)
    QTest.keyClick(view, Qt.Key.Key_A, CTRL)
    assert view._selected_arrows == view.board.arrows
    view.std_run("textsize", value="large")
    assert view.board.arrows[0].textsize == "large"
    assert view.board.box_by_id("a").textsize == "large"
    assert view._selected_arrows and view._scene.selectedItems()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert not view.board.boxes and not view.board.arrows
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)      # one step back
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)      # and the text size
    assert serialize(view.board) == before


def test_copying_an_arrow_copies_its_label_not_an_old_copy(std):
    win, view = std
    view._box_items["c"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_C, CTRL)
    view._select_arrow(view.board.arrows[0])
    QTest.keyClick(view, Qt.Key.Key_C, CTRL)
    assert QApplication.clipboard().text() == "go"
    assert not view._clipboard_boxes
    boxes = len(view.board.boxes)
    QTest.keyClick(view, Qt.Key.Key_V, CTRL)
    assert len(view.board.boxes) == boxes
    assert any(n.text == "go" for n in view.board.notes)


def test_paste_here_takes_the_latest_copy_like_ctrl_v(std, monkeypatch):
    win, view = std
    _no_popups(monkeypatch)
    view._box_items["c"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_C, CTRL)
    QApplication.clipboard().setText("from another app")
    boxes = len(view.board.boxes)
    menu = view._std_context_menu(_vpos(view, QPointF(1300, 1300)))
    _walk(menu.actions(), ["Paste here"]).trigger()
    assert len(view.board.boxes) == boxes
    assert any(n.text == "from another app" for n in view.board.notes)


def test_switching_to_standard_ends_vim_jump_labels(tmp_path):
    win, view = _window(tmp_path, scheme=controls.VIM)
    try:
        QTest.keyClick(view, Qt.Key.Key_F)
        assert view._jump_active
        win.set_control_scheme(controls.STANDARD)
        assert not view._jump_active
        before = serialize(view.board)
        for k in (Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D):
            QTest.keyClick(view, k)
        assert serialize(view.board) == before
        assert not view._scene.selectedItems()
    finally:
        win.close()


def test_a_collapsed_group_refuses_edits(std, monkeypatch):
    win, view = std
    monkeypatch.setattr(view, "_selection_has_locked", lambda: True)
    view._box_items["a"].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_F2)
    assert view._editor is None
    view.std_run("color", value="%primary")
    view.std_run("bold")
    box = view.board.box_by_id("a")
    assert box.color == "" and "bold" not in box.emphasis


def test_the_icon_dialog_keeps_a_zero_badge_and_a_picked_symbol_wins():
    _app()
    from grafli.standard_ui import IconDialog
    dlg = IconDialog(None, "0", "")
    assert dlg.value() == ("0", "")
    star = next(dlg.grid.item(i) for i in range(dlg.grid.count())
                if dlg.grid.item(i).text() == "star")
    dlg.grid.setCurrentItem(star)
    dlg.grid.itemClicked.emit(star)
    assert dlg.value() == ("star", "")


def test_the_text_window_survives_a_reload(std):
    win, view = std
    view._note_items["n"].setSelected(True)
    view.std_run("edit_text")
    window = view._zen_editor
    view._rebuild_scene()                 # what a live reload does
    window.field.setPlainText("after the reload")
    QTest.keyClick(window.field, Qt.Key.Key_S, CTRL)
    assert view.board.notes[0].text == "after the reload"
    window.field.setPlainText("and done")
    window.done()
    assert view.board.notes[0].text == "and done"


def test_done_does_not_overwrite_a_file_changed_meanwhile(std):
    win, view = std
    view._box_items["a"].setSelected(True)
    view.std_run("edit_text")
    path = view._zen_editor._file_path
    view._zen_editor.done()
    view._box_items["a"].setSelected(True)
    view.std_run("edit_text")
    path.write_text("the agent wrote this\n")
    QTest.keyClick(view._zen_editor.field, Qt.Key.Key_Escape)
    assert view._zen_editor is None
    assert path.read_text() == "the agent wrote this\n"


def test_a_failed_save_keeps_the_text_window_open(std, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win, view = std
    view._box_items["a"].setSelected(True)
    view.std_run("edit_text")
    window = view._zen_editor
    path = window._file_path
    window.field.setPlainText("cannot be written")
    path.chmod(0o444)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a))
    try:
        window.done()
        assert warned and view._zen_editor is window and window.isVisible()
        window.cancel()
        assert view._zen_editor is None
    finally:
        path.chmod(0o644)


def test_the_panels_delete_and_rename_do_what_their_keys_do(std):
    win, view = std
    view._select_arrow(view.board.arrows[0])
    win._side_panel._buttons["edit_label"].clicked.emit("edit_label")
    assert view._edit_target is view.board.arrows[0]
    view._commit_editor()
    view._select_arrow(view.board.arrows[0])
    win._side_panel._buttons["delete"].clicked.emit("delete")
    assert view.board.arrows == []


def test_space_let_go_elsewhere_does_not_stick(std):
    win, view = std
    QTest.keyPress(view, Qt.Key.Key_Space)
    assert view._std_space_held
    QApplication.sendEvent(view, QFocusEvent(
        QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
    assert not view._std_space_held
    _drag(view, QPointF(-50, -50), QPointF(450, 100))
    assert view._box_items["a"].isSelected()


def test_arrow_key_presses_in_a_row_are_one_undo_step_on_the_grid(std):
    win, view = std
    view._grid_mode = "off"
    item = view._box_items["c"]
    item.setPos(703, 700)                     # off the grid
    view._grid_mode = "snap"
    box = view.board.box_by_id("c")
    assert box.x == 703
    item.setSelected(True)
    depth = len(view._undo_stack)
    for _ in range(3):
        QTest.keyClick(view, Qt.Key.Key_Right)
    assert len(view._undo_stack) == depth + 1
    assert box.x == 760                       # on the grid: 720, 740, 760
    QTest.keyClick(view, Qt.Key.Key_Z, CTRL)
    assert view.board.box_by_id("c").x == 703


def test_the_annotation_help_names_the_standard_controls(std):
    win, view = std
    html = view._notes_help_html()
    assert "F2" in html and "editable with <span" not in html


def test_the_flows_panel_hints_follow_the_scheme(std):
    from PySide6.QtWidgets import QLabel
    win, view = std
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    panel = win._side_panel._flows_panel
    panel._bookmarks_expanded = True
    panel.refresh()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    texts = " ".join(lab.text() for lab in panel.findChildren(QLabel))
    assert "Tours ▸ Bookmark the view" in texts
    assert "gb" not in texts


def test_right_click_menus_do_not_pile_up(std, monkeypatch):
    from shiboken6 import isValid
    win, view = std
    _no_popups(monkeypatch)
    first = view._std_context_menu(_vpos(view, QPointF(1300, 1300)))
    view._std_context_menu(_vpos(view, QPointF(1300, 1300)))
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert not isValid(first)
