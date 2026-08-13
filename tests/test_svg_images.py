"""Dropping image files on the canvas: path policy, sizing, SVG rendering.

An image dropped from inside the board's own directory is referenced where
it lies (so an externally edited SVG stays the source of truth); one from
outside is copied into the vault. SVGs render through a QSvgRenderer, so
they stay crisp and can be reloaded after an external edit.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli.format import Image
from grafli.items import ImageItem, default_image_size
from grafli.resources import image_ref, res_dir, resolve_image_path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


SVG_2_1 = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">' \
          b'<rect width="100" height="50" fill="#3366aa"/></svg>'
SVG_1_2 = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200">' \
          b'<rect width="100" height="200" fill="#aa6633"/></svg>'


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp: Path, name: str = "t.grafli"):
    _app()
    f = tmp / name
    f.write_text('#!grafli v2\n@ box a "A" 0,0 120x60\n')
    from grafli.app import MainWindow
    w = MainWindow(str(f))
    w.resize(900, 600)
    return w


def _png(path: Path, w: int, h: int):
    _app()
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0x3366AA)
    assert img.save(str(path), "PNG")


# ── resolve_image_path ────────────────────────────────────────────────────

def test_resolve_image_path_joins_relative(tmp_path: Path):
    got = resolve_image_path(str(tmp_path), "res/a.svg")
    assert got == os.path.join(str(tmp_path), "res", "a.svg")


def test_resolve_image_path_passes_absolute_through(tmp_path: Path):
    abs_p = str(tmp_path / "a.svg")
    assert resolve_image_path(str(tmp_path / "other"), abs_p) == abs_p


def test_resolve_image_path_without_base_dir():
    assert resolve_image_path("", "res/./a.svg") == os.path.join("res", "a.svg")


# ── image_ref: in place vs. copied into the vault ─────────────────────────

def test_image_ref_in_tree_file_stays_put(tmp_path: Path):
    grafli = tmp_path / "board.grafli"
    grafli.touch()
    art = tmp_path / "art"
    art.mkdir()
    src = art / "logo.svg"
    src.write_bytes(SVG_2_1)

    assert image_ref(grafli, src) == "art/logo.svg"
    assert not res_dir(grafli).exists()      # nothing was copied
    assert src.exists()


def test_image_ref_outside_file_is_copied_into_vault(tmp_path: Path):
    grafli = tmp_path / "board" / "board.grafli"
    grafli.parent.mkdir()
    grafli.touch()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    src = outside / "logo.svg"
    src.write_bytes(SVG_2_1)

    assert image_ref(grafli, src) == "board-res/logo.svg"
    assert (res_dir(grafli) / "logo.svg").read_bytes() == SVG_2_1
    assert src.exists()                      # the original is left alone


def test_image_ref_reuses_identical_vault_file(tmp_path: Path):
    grafli = tmp_path / "board" / "board.grafli"
    grafli.parent.mkdir()
    grafli.touch()
    src = tmp_path / "logo.svg"
    src.write_bytes(SVG_2_1)

    assert image_ref(grafli, src) == "board-res/logo.svg"
    assert image_ref(grafli, src) == "board-res/logo.svg"
    assert sorted(p.name for p in res_dir(grafli).iterdir()) == ["logo.svg"]


def test_image_ref_suffixes_on_name_collision(tmp_path: Path):
    grafli = tmp_path / "board" / "board.grafli"
    grafli.parent.mkdir()
    grafli.touch()
    a = tmp_path / "a" / "logo.svg"
    b = tmp_path / "b" / "logo.svg"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(SVG_2_1)
    b.write_bytes(SVG_1_2)

    assert image_ref(grafli, a) == "board-res/logo.svg"
    assert image_ref(grafli, b) == "board-res/logo-1.svg"
    assert (res_dir(grafli) / "logo-1.svg").read_bytes() == SVG_1_2


# ── default_image_size ────────────────────────────────────────────────────

def test_default_size_svg_scales_up_to_the_fit_box():
    assert default_image_size(100, 50, vector=True) == (320.0, 160.0)


def test_default_size_svg_scales_down_to_the_fit_box():
    assert default_image_size(1000, 1000, vector=True) == (240.0, 240.0)


def test_default_size_raster_never_upscales():
    assert default_image_size(100, 50, vector=False) == (100.0, 50.0)


def test_default_size_raster_scales_down():
    assert default_image_size(640, 400, vector=False) == (320.0, 200.0)


def test_default_size_degenerate_falls_back_to_the_box():
    assert default_image_size(0, 100, vector=True) == (320.0, 240.0)
    assert default_image_size(100, -1, vector=False) == (320.0, 240.0)


# ── ImageItem: SVG loading, painting, reload ──────────────────────────────

def _svg_item(tmp_path: Path, data: bytes = SVG_2_1) -> ImageItem:
    _app()
    (tmp_path / "logo.svg").write_bytes(data)
    image = Image(id="i1", image_path="logo.svg", x=0, y=0, w=320, h=160)
    return ImageItem(image, base_dir=str(tmp_path))


def test_image_item_loads_svg(tmp_path: Path):
    item = _svg_item(tmp_path)
    assert item._renderer is not None
    assert item._placeholder is False
    assert item._aspect_ratio == 2.0
    assert item.resolved_path == str(tmp_path / "logo.svg")


def test_image_item_paints_svg(tmp_path: Path):
    item = _svg_item(tmp_path)
    canvas = QImage(320, 160, QImage.Format.Format_ARGB32)
    canvas.fill(0)
    painter = QPainter(canvas)
    item.paint(painter, None, None)
    painter.end()
    # The SVG is a solid rect, so the middle pixel must carry its colour.
    assert QImage.pixelColor(canvas, 160, 80).blue() > 100


def test_broken_svg_falls_back_to_placeholder(tmp_path: Path):
    item = _svg_item(tmp_path, b"<svg not really")
    assert item._renderer is None
    assert item._placeholder is True


def test_reload_from_disk_picks_up_a_changed_svg(tmp_path: Path):
    item = _svg_item(tmp_path)
    assert item._aspect_ratio == 2.0
    (tmp_path / "logo.svg").write_bytes(SVG_1_2)
    item.reload_from_disk()
    assert item._aspect_ratio == 0.5
    assert item.image.w == 320 and item.image.h == 160   # layout untouched


def test_reload_from_disk_recovers_from_missing_file(tmp_path: Path):
    _app()
    image = Image(id="i1", image_path="logo.svg", x=0, y=0, w=320, h=160)
    item = ImageItem(image, base_dir=str(tmp_path))
    assert item._placeholder is True
    (tmp_path / "logo.svg").write_bytes(SVG_1_2)
    item.reload_from_disk()
    assert item._placeholder is False
    assert item._aspect_ratio == 0.5


def test_reload_from_disk_keeps_rendering_of_half_written_file(tmp_path: Path):
    item = _svg_item(tmp_path)
    (tmp_path / "logo.svg").write_bytes(b'<svg xmlns="http://www.w3')
    item.reload_from_disk()
    assert item._renderer is not None      # previous rendering survives
    assert item._placeholder is False
    assert item._aspect_ratio == 2.0


def test_reload_from_disk_picks_up_a_changed_raster(tmp_path: Path):
    _app()
    _png(tmp_path / "shot.png", 100, 50)
    image = Image(id="i1", image_path="shot.png", x=0, y=0, w=100, h=50)
    item = ImageItem(image, base_dir=str(tmp_path))
    assert item._aspect_ratio == 2.0
    _png(tmp_path / "shot.png", 100, 200)
    item.reload_from_disk()
    assert item._aspect_ratio == 0.5


# ── _add_image_files end to end ───────────────────────────────────────────

def test_drop_in_tree_svg_references_it_in_place(tmp_path: Path):
    w = _window(tmp_path)
    art = tmp_path / "art"
    art.mkdir()
    (art / "logo.svg").write_bytes(SVG_2_1)

    w._view._add_image_files([art / "logo.svg"], QPointF(100, 100))

    images = w._view._board.images
    assert len(images) == 1
    img = images[0]
    assert img.image_path == "art/logo.svg"
    assert (img.w, img.h) == (320.0, 160.0)              # svg scaled up to fit
    assert (img.x, img.y) == (100 - 160.0, 100 - 80.0)   # centred on the drop
    assert not res_dir(tmp_path / "t.grafli").exists()   # not copied
    from grafli.format import serialize
    assert f'@ image {img.id} "art/logo.svg"' in serialize(w._view._board)


def test_drop_outside_raster_is_copied_into_the_vault(tmp_path: Path):
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    w = _window(board_dir)
    outside = tmp_path / "shots"
    outside.mkdir()
    _png(outside / "shot.png", 640, 400)

    w._view._add_image_files([outside / "shot.png"], QPointF(0, 0))

    images = w._view._board.images
    assert len(images) == 1
    assert images[0].image_path == "t-res/shot.png"
    assert (images[0].w, images[0].h) == (320.0, 200.0)
    assert (board_dir / "t-res" / "shot.png").exists()


def test_drop_of_several_files_cascades(tmp_path: Path):
    w = _window(tmp_path)
    (tmp_path / "a.svg").write_bytes(SVG_2_1)
    (tmp_path / "b.svg").write_bytes(SVG_2_1)

    w._view._add_image_files([tmp_path / "a.svg", tmp_path / "b.svg"],
                             QPointF(0, 0))

    images = w._view._board.images
    assert len(images) == 2
    assert images[1].x - images[0].x == 24.0
    assert images[1].y - images[0].y == 24.0
    assert all(w._view._image_items[i.id].isSelected() for i in images)


def test_drop_of_an_unreadable_file_is_skipped(tmp_path: Path):
    w = _window(tmp_path)
    (tmp_path / "broken.svg").write_bytes(b"not an svg at all")

    w._view._add_image_files([tmp_path / "broken.svg"], QPointF(0, 0))

    assert w._view._board.images == []
    assert "broken.svg" in w._view._toast_text


def test_drop_without_a_saved_board_toasts(tmp_path: Path):
    _app()
    from grafli.app import MainWindow
    w = MainWindow()
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)

    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))

    assert w._view._board.images == []
    assert "Save the board first" in w._view._toast_text


# ── the view's drag & drop plumbing ───────────────────────────────────────

def _mime(paths):
    from PySide6.QtCore import QMimeData
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def test_drag_enter_accepts_image_urls(tmp_path: Path):
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    # The event only borrows the mime data — keep a reference of our own.
    mime = _mime([tmp_path / "logo.svg"])
    ev = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
    w._view.dragEnterEvent(ev)
    assert ev.isAccepted()


def test_non_image_files_are_left_to_the_default_handling(tmp_path: Path):
    # QGraphicsView accepts every drag enter itself, so what matters is that
    # a non-image drop is passed on and adds nothing to the board.
    w = _window(tmp_path)
    (tmp_path / "notes.txt").write_text("hi")
    mime = _mime([tmp_path / "notes.txt"])
    assert w._view._dropped_image_paths(mime) == []
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    w._view.dropEvent(ev)
    assert w._view._board.images == []


def test_drop_event_adds_the_image(tmp_path: Path):
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    mime = _mime([tmp_path / "logo.svg"])
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    w._view.dropEvent(ev)
    assert [i.image_path for i in w._view._board.images] == ["logo.svg"]


# ── windowless views (headless render/export) ─────────────────────────────

def test_windowless_view_resolves_relative_paths_via_base_dir(tmp_path: Path):
    # `grafli render`/`export` build a GrafliView with no MainWindow above
    # it, so relative image paths must resolve through the view's base_dir.
    _app()
    from grafli.format import parse
    from grafli.view import GrafliView
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    board = parse('#!grafli v1\n@ image i1 "logo.svg" 0,0 320x160\n')
    view = GrafliView()
    view.base_dir = str(tmp_path)
    view.load_board(board)
    item = view._image_items["i1"]
    assert not item._placeholder
    assert item._renderer is not None


# ── the frame flag and its type defaults (#147) ───────────────────────────

def test_frame_flag_round_trips():
    from grafli.format import parse, serialize
    src = ('#!grafli v1\n'
           '@ image a "a.svg" 0,0 100x100 !frame\n'
           '@ image b "b.png" 0,0 100x100 !noframe\n'
           '@ image c "c.png" 0,0 100x100\n')
    board = parse(src)
    assert board.image_by_id("a").frame == "on"
    assert board.image_by_id("b").frame == "off"
    assert board.image_by_id("c").frame == ""
    out = serialize(board)
    assert '@ image a "a.svg" 0,0 100x100 !frame' in out
    assert '@ image b "b.png" 0,0 100x100 !noframe' in out
    assert '@ image c "c.png" 0,0 100x100' in out
    assert '!frame' not in out.splitlines()[-1]   # default stays unserialized


def test_frame_default_follows_the_file_type():
    from grafli.format import image_frame_enabled
    assert image_frame_enabled(Image(id="i", image_path="shot.png",
                                     x=0, y=0, w=10, h=10))
    assert not image_frame_enabled(Image(id="i", image_path="art.SVG",
                                         x=0, y=0, w=10, h=10))
    assert image_frame_enabled(Image(id="i", image_path="art.svg",
                                     x=0, y=0, w=10, h=10, frame="on"))
    assert not image_frame_enabled(Image(id="i", image_path="shot.png",
                                         x=0, y=0, w=10, h=10, frame="off"))


def test_frame_flag_survives_with_parent_and_attach():
    from grafli.format import parse, serialize
    src = ('#!grafli v1\n'
           '@ box p "P" 0,0 400x300\n'
           '@ image i "r.svg" 10,10 100x100 !noframe >p &link:https://x.y\n')
    board = parse(src)
    img = board.image_by_id("i")
    assert (img.frame, img.parent, img.attach_kind) == ("off", "p", "link")
    assert parse(serialize(board)).image_by_id("i").frame == "off"


# ── opening the source file in the system app (#147) ──────────────────────

def test_open_image_source_desktop_opens_the_file(tmp_path: Path, monkeypatch):
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))
    item = next(iter(w._view._image_items.values()))

    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    w._view._open_image_source(item)
    assert len(opened) == 1
    assert opened[0].toLocalFile() == str(tmp_path / "logo.svg")


def test_open_image_source_missing_file_toasts(tmp_path: Path, monkeypatch):
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))
    item = next(iter(w._view._image_items.values()))
    (tmp_path / "logo.svg").unlink()

    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    w._view._open_image_source(item)
    assert opened == []
    assert "not found" in w._view._toast_text


def test_edit_selected_opens_the_image_file(tmp_path: Path, monkeypatch):
    # `e` means "edit what the element is" — for an image that is its file,
    # opened in the system app (#148).
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))

    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    w._view._edit_selected()
    assert [u.toLocalFile() for u in opened] == [str(tmp_path / "logo.svg")]


def test_open_image_source_gives_feedback(tmp_path: Path, monkeypatch):
    # Success shows "Opening ..." (the app may launch behind the window);
    # when openUrl AND the platform-opener fallback fail, it warns instead
    # of going silent.
    import subprocess

    def _fail_popen(cmd, **kw):
        raise OSError("no opener")

    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))
    item = next(iter(w._view._image_items.values()))

    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: True))
    w._view._open_image_source(item)
    assert "Opening logo.svg" in w._view._toast_text

    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: False))
    monkeypatch.setattr(subprocess, "Popen", _fail_popen)
    w._view._open_image_source(item)
    assert "could not open logo.svg" in w._view._toast_text


def test_open_image_source_falls_back_to_the_platform_opener(
        tmp_path: Path, monkeypatch):
    # Qt can hold a stale LaunchServices view (app registered while grafli
    # runs); the `open`/`xdg-open` fallback sees the current state.
    import subprocess
    w = _window(tmp_path)
    (tmp_path / "logo.svg").write_bytes(SVG_2_1)
    w._view._add_image_files([tmp_path / "logo.svg"], QPointF(0, 0))
    item = next(iter(w._view._image_items.values()))

    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: False))
    launched = []
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **kw: launched.append(cmd))
    w._view._open_image_source(item)
    assert launched and launched[0][-1] == str(tmp_path / "logo.svg")
    assert "Opening logo.svg" in w._view._toast_text
