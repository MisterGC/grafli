"""Board links with a fragment: `&graph:<name>#<id>` and
`&link:<path>.grafli#<id>` open the board framed on the bookmark or element
`<id>` with it selected; a missing id opens fitted with a toast (#161)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def _boards(tmp_path: Path, attach: str) -> Path:
    """A root board whose `link` box carries *attach*, a vault sub-board
    `combat` and a sibling board `Other.grafli`, both far-flung so a fit and
    a framing differ. `combat` has a bookmark `strike` on blow + impact and an
    element `impact`; a box id `strike` would lose to the bookmark."""
    root = _write(tmp_path / "System.grafli",
                  "#!grafli v3",
                  '@ box player "Player" 0,0 120x60',
                  f'@ box link "Combat" 400,0 120x60 {attach}')
    combat = ("#!grafli v2",
              '@ box blow "blow()" 0,0 120x60',
              '@ box impact "impact()" 300,0 120x60',
              '@ box strike "strike box" 3000,2000 120x60',
              '@ box far "far" 6000,4000 120x60',
              '@ bookmark strike "Strike" @blow,impact')
    _write(tmp_path / "System-res" / "combat.grafli", *combat)
    _write(tmp_path / "Other.grafli", *combat)
    return root


def _window(path: Path) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    view = win._view
    view._animate_to_rect = lambda rect: view.goto_rect(rect, animate=False)
    return win


def _follow(win: MainWindow):
    """Select the root's `link` box and open its attachment, as Return does."""
    view = win._view
    view._scene.clearSelection()
    view._box_items["link"].setSelected(True)
    view._open_resource()
    _app().processEvents()   # let any queued on-open fit run, as it does live


def _visible(win: MainWindow) -> QRectF:
    view = win._view
    return view.mapToScene(view.viewport().rect()).boundingRect()


def _selected(win: MainWindow) -> list[str]:
    return sorted(bid for bid, it in win._view._box_items.items()
                  if it.isSelected())


def _transform(win: MainWindow) -> tuple[float, ...]:
    t = win._view.transform()
    return (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def _assert_framed_on(win: MainWindow, *ids: str):
    view = win._view
    target = QRectF()
    for bid in ids:
        r = view._box_items[bid].sceneBoundingRect()
        target = r if target.isNull() else target.united(r)
    visible = _visible(win)
    assert visible.contains(target)
    assert abs(visible.center().x() - target.center().x()) < 2
    assert abs(visible.center().y() - target.center().y()) < 2
    # Framed, not fitted: the far corner of the board is out of view.
    assert not visible.contains(view._box_items["far"].sceneBoundingRect())


def test_graph_fragment_opens_framed_on_the_element(tmp_path: Path):
    win = _window(_boards(tmp_path, "&graph:combat#impact"))
    _follow(win)
    assert win._file_path.name == "combat.grafli"
    assert _selected(win) == ["impact"]
    _assert_framed_on(win, "impact")


def test_link_fragment_opens_framed_on_the_element(tmp_path: Path):
    win = _window(_boards(tmp_path, "&link:Other.grafli#impact"))
    _follow(win)
    assert win._file_path.name == "Other.grafli"
    assert _selected(win) == ["impact"]
    _assert_framed_on(win, "impact")


def test_graph_fragment_opens_framed_on_the_bookmark(tmp_path: Path):
    # `strike` is both a bookmark and a box id: the bookmark wins.
    win = _window(_boards(tmp_path, "&graph:combat#strike"))
    _follow(win)
    assert _selected(win) == ["blow", "impact"]
    _assert_framed_on(win, "blow", "impact")


def test_link_fragment_opens_framed_on_the_bookmark(tmp_path: Path):
    win = _window(_boards(tmp_path, "&link:Other.grafli#strike"))
    _follow(win)
    assert _selected(win) == ["blow", "impact"]
    _assert_framed_on(win, "blow", "impact")


def test_fragment_frames_a_board_that_is_already_open(tmp_path: Path):
    win = _window(_boards(tmp_path, "&graph:combat#impact"))
    _follow(win)
    win._go_up()
    _app().processEvents()
    win._view._scene.clearSelection()
    _follow(win)
    assert _selected(win) == ["impact"]
    _assert_framed_on(win, "impact")


def test_missing_id_opens_fitted_with_a_toast(tmp_path: Path):
    win = _window(_boards(tmp_path, "&graph:combat#nope"))
    _follow(win)
    assert win._file_path.name == "combat.grafli"
    assert win._view._toast_text == "No element 'nope' in combat.grafli"
    assert _selected(win) == []
    fitted = _transform(win)
    win._zoom_fit(animate=False)
    assert _transform(win) == fitted
    assert _visible(win).contains(
        win._view._box_items["far"].sceneBoundingRect())


def test_missing_id_on_a_link_opens_fitted_with_a_toast(tmp_path: Path):
    win = _window(_boards(tmp_path, "&link:Other.grafli#nope"))
    _follow(win)
    assert win._file_path.name == "Other.grafli"
    assert win._view._toast_text == "No element 'nope' in Other.grafli"
    fitted = _transform(win)
    win._zoom_fit(animate=False)
    assert _transform(win) == fitted


def test_a_fragment_link_pushes_a_frame_for_gu(tmp_path: Path):
    root = _boards(tmp_path, "&graph:combat#impact")
    win = _window(root)
    _follow(win)
    assert win._buffers.board_path(win._file_path) == ["System", "Combat"]
    QTest.keyClick(win._view, Qt.Key.Key_G)
    QTest.keyClick(win._view, Qt.Key.Key_U)
    _app().processEvents()
    assert win._file_path == root
