"""Sub-board miniatures and entering a level (D3): a `&graph` box large enough
on screen shows a raster of its sub-board, kept until that file changes;
exports leave it out; `gd` and Return zoom into the box and hand over to the
sub-board, `gu` zooms back out; a board without `&graph` boxes is untouched."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser

from grafli.app import MainWindow
from grafli.lod import (
    MINIATURE_HIDE_PX,
    MINIATURE_SHOW_PX,
    should_show_miniature,
)
from grafli.miniature import MiniatureCache
from grafli.view import levels


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _system(tmp_path: Path) -> tuple[Path, Path]:
    """A root board with one large `&graph` box and one plain box."""
    root = _write(tmp_path / "System.grafli",
                  '#!grafli v2\n'
                  '@ box plain "Plain" 0,0 400x300\n'
                  '@ box combat "Combat" 600,0 400x300 &graph:combat\n')
    sub = _write(tmp_path / "System-res" / "combat.grafli",
                 '#!grafli v2\n'
                 '@ box blow "blow()" 0,0 160x60\n'
                 '@ box impact "impact()" 300,0 160x60\n'
                 '@ arrow blow -> impact\n')
    return root, sub


def _window(path: Path, *, transitions: bool = False) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    if not transitions:
        win._view.transitions_enabled = lambda: False
    return win


def _zoom(win: MainWindow, scale: float):
    view = win._view
    view.setTransform(QTransform().scale(scale, scale))
    view._update_status_zoom()


def _select(win: MainWindow, box_id: str):
    view = win._view
    view._scene.clearSelection()
    view._box_items[box_id].setSelected(True)


def _wait_for_transition():
    QTest.qWait(levels.ZOOM_MS + levels.FADE_MS + 250)


# ── Threshold ──


def test_miniature_threshold_has_a_dead_band():
    assert should_show_miniature(MINIATURE_SHOW_PX, False)
    assert not should_show_miniature(MINIATURE_SHOW_PX - 1, False)
    # Once shown it stays until the lower bound.
    assert should_show_miniature(MINIATURE_HIDE_PX, True)
    assert not should_show_miniature(MINIATURE_HIDE_PX - 1, True)


def test_graph_box_shows_its_miniature_once_large_enough(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    view._lod_enabled = False   # isolate the miniature threshold
    item = view._box_items["combat"]
    area = item.miniature_rect()
    short = min(area.width(), area.height())

    _zoom(win, 1.0)
    assert item._miniature is not None
    # Inside the dead band it stays …
    _zoom(win, (MINIATURE_HIDE_PX + 4) / short)
    assert item._miniature is not None
    # … below it goes, and the band now keeps it away.
    _zoom(win, (MINIATURE_HIDE_PX - 4) / short)
    assert item._miniature is None
    _zoom(win, (MINIATURE_HIDE_PX + 4) / short)
    assert item._miniature is None
    _zoom(win, (MINIATURE_SHOW_PX + 4) / short)
    assert item._miniature is not None
    win.close()


def test_miniature_is_the_sub_board_fitted(tmp_path: Path):
    from grafli.format import parse
    from grafli.view import GrafliView
    root, sub = _system(tmp_path)
    win = _window(root)
    _zoom(win, 1.0)
    pix = win._view._box_items["combat"]._miniature
    # Framed like opening the sub-board: its content plus the fit margin.
    fresh = GrafliView()
    fresh.load_board(parse(sub.read_text()))
    rect = fresh.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
    assert abs(pix.width() / pix.height()
               - rect.width() / rect.height()) < 0.02
    win.close()


def test_label_moves_to_the_top_while_the_miniature_shows(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    view._lod_enabled = False
    item = view._box_items["combat"]
    _zoom(win, 1.0)
    assert item._label.pos().y() == item.pos().y() + 8
    _zoom(win, 0.1)
    assert item._miniature is None
    centred = item.pos().y() + (item.box.h
                                - item._label.boundingRect().height()) / 2
    assert item._label.pos().y() == centred
    win.close()


def test_plain_box_and_hidden_view_show_no_miniature(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _zoom(win, 2.0)
    assert win._view._box_items["plain"]._miniature is None
    win.hide()
    _zoom(win, 2.0)
    assert win._view._box_items["combat"]._miniature is None
    win.close()


def test_missing_sub_board_shows_no_miniature(tmp_path: Path):
    root, sub = _system(tmp_path)
    sub.unlink()
    win = _window(root)
    _zoom(win, 1.0)
    assert win._view._box_items["combat"]._miniature is None
    win.close()


def test_container_box_shows_no_miniature(tmp_path: Path):
    root = _write(tmp_path / "Nest.grafli",
                  '#!grafli v2\n'
                  '@ box outer "Outer" 0,0 600x400 &graph:inner\n'
                  '@ box child "Child" 40,80 160x60 >outer\n')
    _write(tmp_path / "Nest-res" / "inner.grafli",
           '#!grafli v2\n@ box x "X" 0,0 160x60\n')
    win = _window(root)
    _zoom(win, 1.0)
    assert win._view._box_items["outer"]._miniature is None
    win.close()


def test_icon_boxes_show_a_miniature_only_with_a_corner_badge(tmp_path: Path):
    root = _write(tmp_path / "Icons.grafli",
                  '#!grafli v2\n'
                  '@ box lead "Lead" 0,0 400x300 *lead:gear &graph:combat\n'
                  '@ box fill "Fill" 500,0 400x300 *gear &graph:combat\n'
                  '@ box badge "Badge" 1000,0 400x300 *badge:gear '
                  '&graph:combat\n')
    _write(tmp_path / "Icons-res" / "combat.grafli",
           '#!grafli v2\n@ box x "X" 0,0 160x60\n')
    win = _window(root)
    _zoom(win, 1.0)
    items = win._view._box_items
    # A lead icon keeps its label centred beside the icon: no room below.
    assert items["lead"]._miniature is None
    assert items["fill"]._miniature is None
    badge = items["badge"]
    assert badge._miniature is not None
    # The badge sits in the corner, above the miniature.
    side = badge._badge_icon_side()
    assert 8.0 + side <= badge.miniature_rect().top()
    win.close()


# ── Cache ──


def test_cache_renders_once_until_the_file_changes(tmp_path: Path):
    _app()
    _, sub = _system(tmp_path)
    cache = MiniatureCache()
    first = cache.get(sub)
    assert first is not None
    assert cache.get(sub) is first
    assert cache.renders == 1

    sub.write_text(sub.read_text() + '@ box stagger "stagger" 0,200 160x60\n')
    second = cache.get(sub)
    assert cache.renders == 2
    assert second is not first
    # The new box below makes the board taller: the raster follows.
    assert second.height() / second.width() > first.height() / first.width()


def test_miniature_updates_after_the_sub_board_file_changes(tmp_path: Path):
    root, sub = _system(tmp_path)
    win = _window(root)
    view = win._view
    _zoom(win, 1.0)
    item = view._box_items["combat"]
    before = item._miniature
    assert view._miniature_watcher._paths == [str(sub.resolve())]

    sub.write_text(sub.read_text() + '@ box stagger "stagger" 0,200 160x60\n')
    view._miniature_watcher._check()   # one poll tick, no zoom needed

    assert item._miniature is not None
    assert item._miniature is not before
    assert (item._miniature.height() / item._miniature.width()
            > before.height() / before.width())
    win.close()


# ── Exports ──


def test_exports_render_without_the_miniature(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    _zoom(win, 1.0)
    item = view._box_items["combat"]
    shown = item._miniature
    assert shown is not None

    with_mini = view._render_png_image(scale=1)
    svg_with = bytes(view._render_svg_bytes().data())
    # The miniature comes back once the export is done.
    assert item._miniature is shown

    item.set_miniature(None)
    plain = view._render_png_image(scale=1)
    svg_plain = bytes(view._render_svg_bytes().data())
    assert with_mini == plain
    assert svg_with == svg_plain
    win.close()


def test_bookmark_thumbnail_leaves_the_miniature_out(tmp_path: Path):
    from grafli.flows import render_bookmark_pixmap
    from grafli.format import Bookmark
    root, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    _zoom(win, 1.0)
    bm = Bookmark(id="b", label="", focus=["combat"])
    with_mini = render_bookmark_pixmap(view, bm, 400, 300).toImage()
    item = view._box_items["combat"]
    pix = item._miniature
    item.set_miniature(None)
    plain = render_bookmark_pixmap(view, bm, 400, 300).toImage()
    assert with_mini == plain
    item.set_miniature(pix)
    win.close()


# ── Entering ──


def test_gd_enters_the_selected_boxs_sub_board(tmp_path: Path):
    root, sub = _system(tmp_path)
    win = _window(root)
    _select(win, "combat")
    QTest.keyClick(win._view, Qt.Key.Key_G)
    QTest.keyClick(win._view, Qt.Key.Key_D)
    _app().processEvents()
    assert win._file_path.resolve() == sub.resolve()
    assert win._board_path() == ["System", "Combat"]
    win.close()


def test_gd_without_a_sub_board_toasts_and_stays(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root)
    _select(win, "plain")
    QTest.keyClick(win._view, Qt.Key.Key_G)
    QTest.keyClick(win._view, Qt.Key.Key_D)
    assert win._file_path.resolve() == root.resolve()
    assert win._view._toast_text == "Select a box with a sub-board to go down"
    win.close()


def test_return_zooms_into_the_box_then_hands_over(tmp_path: Path):
    root, sub = _system(tmp_path)
    win = _window(root, transitions=True)
    view = win._view
    _zoom(win, 0.5)
    left = view.snapshot_state()
    _select(win, "combat")
    QTest.keyClick(view, Qt.Key.Key_Return)
    # Mid-zoom: still on the parent, closer in, nothing pushed yet.
    QTest.qWait(levels.ZOOM_MS // 2)
    assert win._file_path.resolve() == root.resolve()
    assert view._current_zoom() > 0.5
    assert view._box_items["combat"]._miniature is not None
    _wait_for_transition()
    assert win._file_path.resolve() == sub.resolve()
    frame = win._buffers.frame_for(sub)
    assert frame.via_id == "combat"
    assert frame.parent_view.transform == left.transform
    win.close()


def test_gu_zooms_back_out_to_where_you_left(tmp_path: Path):
    root, sub = _system(tmp_path)
    win = _window(root, transitions=True)
    view = win._view
    _zoom(win, 0.5)
    left = view.snapshot_state()
    _select(win, "combat")
    QTest.keyClick(view, Qt.Key.Key_Return)
    _wait_for_transition()
    assert win._file_path.resolve() == sub.resolve()

    QTest.keyClick(view, Qt.Key.Key_G)
    QTest.keyClick(view, Qt.Key.Key_U)
    # The reverse starts framed on the box, zoomed in past where you left.
    assert win._file_path.resolve() == root.resolve()
    assert view._current_zoom() > 0.5
    _wait_for_transition()
    assert view.snapshot_state().transform == left.transform
    assert (view.horizontalScrollBar().value(),
            view.verticalScrollBar().value()) == (left.h_scroll, left.v_scroll)
    win.close()


def test_switching_boards_mid_zoom_calls_the_entry_off(tmp_path: Path):
    root, _ = _system(tmp_path)
    other = _write(tmp_path / "Other.grafli",
                   '#!grafli v2\n@ box o "Other" 0,0 160x60\n')
    win = _window(root, transitions=True)
    view = win._view
    _zoom(win, 0.5)
    _select(win, "combat")
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.qWait(levels.ZOOM_MS // 3)
    win._open_file(other)
    QTest.qWait(300)   # Other's own animated fit
    settled = view.snapshot_state().transform
    _wait_for_transition()
    # Still on Other, its camera left alone, nothing pushed for `gu`.
    assert win._file_path.resolve() == other.resolve()
    assert view.snapshot_state().transform == settled
    assert win._buffers.frame_for(other) is None
    assert win._board_path() == []
    win.close()


def test_switching_boards_mid_gu_leaves_the_new_board_alone(tmp_path: Path):
    root, sub = _system(tmp_path)
    other = _write(tmp_path / "Other.grafli",
                   '#!grafli v2\n@ box o "Other" 0,0 160x60\n')
    win = _window(root, transitions=True)
    view = win._view
    _zoom(win, 0.5)
    _select(win, "combat")
    QTest.keyClick(view, Qt.Key.Key_Return)
    _wait_for_transition()
    assert win._file_path.resolve() == sub.resolve()
    QTest.keyClick(view, Qt.Key.Key_G)
    QTest.keyClick(view, Qt.Key.Key_U)
    QTest.qWait(levels.ZOOM_MS // 3)
    # No fit of its own, so nothing else would stop the reverse zoom.
    win._open_file(other, zoom_fit=False)
    settled = view.snapshot_state().transform
    _wait_for_transition()
    assert win._file_path.resolve() == other.resolve()
    assert view.snapshot_state().transform == settled
    win.close()


def test_zooming_alone_never_switches_boards(tmp_path: Path):
    root, _ = _system(tmp_path)
    win = _window(root, transitions=True)
    for scale in (0.5, 1.0, 2.0, 5.0):
        _zoom(win, scale)
        view = win._view
        view.centerOn(view._box_items["combat"].sceneBoundingRect().center())
    QTest.qWait(50)
    assert win._file_path.resolve() == root.resolve()
    win.close()


def test_help_sheet_lists_gd(tmp_path: Path, monkeypatch):
    root, _ = _system(tmp_path)
    win = _window(root)
    shown: list[str] = []

    def _exec(dlg):
        shown.extend(b.toPlainText() for b in dlg.findChildren(QTextBrowser))
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()
    assert "Zoom into the box's sub-board" in "\n".join(shown)
    win.close()


# ── Plain boards ──


def test_board_without_graph_boxes_is_untouched(tmp_path: Path):
    root = _write(tmp_path / "Plain.grafli",
                  '#!grafli v2\n'
                  '@ box a "A" 0,0 400x300\n'
                  '@ box b "B" 600,0 400x300 &link:https://example.com\n'
                  '@ arrow a -> b\n')
    win = _window(root)
    view = win._view
    for scale in (0.5, 1.0, 3.0):
        _zoom(win, scale)
        for item in view._box_items.values():
            assert item._miniature is None
            centred = item.pos().y() + (
                item.box.h - item._label.boundingRect().height()) / 2
            assert item._label.pos().y() == centred
    assert getattr(view, "_miniature_watcher", None) is None
    assert getattr(view, "_miniatures", None) is None   # nothing rendered
    win.close()
