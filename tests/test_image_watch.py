"""Live reload of externally edited image files (issue #146).

A board's referenced image files are polled by their own MultiFileWatcher;
when one changes on disk the matching ImageItem re-reads it in place — no
board reload, no scene rebuild, no dirty flag.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG_SQUARE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" fill="#3366aa"/></svg>\n'
)
SVG_WIDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100">'
    '<rect width="300" height="100" fill="#aa3366"/></svg>\n'
)


def _window(tmp: str, board_text: str):
    QApplication.instance() or QApplication([])
    f = os.path.join(tmp, "t.grafli")
    with open(f, "w") as fh:
        fh.write(board_text)
    from grafli.app import MainWindow
    w = MainWindow(f)
    w.resize(900, 600)
    return w


def test_watch_images_lists_board_image_paths():
    with tempfile.TemporaryDirectory() as tmp:
        res = os.path.join(tmp, "t-res")
        os.makedirs(res)
        with open(os.path.join(res, "logo.svg"), "w") as fh:
            fh.write(SVG_SQUARE)
        w = _window(tmp, '#!grafli v2\n'
                         '@ image i1 "t-res/logo.svg" 0,0 320x240\n')
        w._watch_images()
        assert w._images_watcher is not None
        assert w._images_watcher._paths == [
            os.path.join(tmp, "t-res", "logo.svg"),
        ]


def test_no_images_leaves_no_watcher():
    with tempfile.TemporaryDirectory() as tmp:
        w = _window(tmp, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
        w._watch_images()
        assert w._images_watcher is None


def test_external_svg_edit_reloads_the_item():
    with tempfile.TemporaryDirectory() as tmp:
        svg = os.path.join(tmp, "logo.svg")
        with open(svg, "w") as fh:
            fh.write(SVG_SQUARE)
        w = _window(tmp, '#!grafli v2\n'
                         '@ image i1 "logo.svg" 0,0 320x240\n')
        w._watch_images()
        item = w._view._image_items["i1"]
        before = item._aspect_ratio
        assert abs(before - 1.0) < 0.01

        with open(svg, "w") as fh:
            fh.write(SVG_WIDE)
        w._images_watcher._check()

        assert abs(item._aspect_ratio - 3.0) < 0.01
        # A file change is not a board change.
        assert not w._view._dirty


def test_reload_images_ignores_unrelated_paths():
    with tempfile.TemporaryDirectory() as tmp:
        svg = os.path.join(tmp, "logo.svg")
        with open(svg, "w") as fh:
            fh.write(SVG_SQUARE)
        w = _window(tmp, '#!grafli v2\n'
                         '@ image i1 "logo.svg" 0,0 320x240\n')
        item = w._view._image_items["i1"]
        with open(svg, "w") as fh:
            fh.write(SVG_WIDE)
        w._view.reload_images([os.path.join(tmp, "other.svg")])
        assert abs(item._aspect_ratio - 1.0) < 0.01
