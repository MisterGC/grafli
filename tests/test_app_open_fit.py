"""Opening a file must focus the canvas and frame the board — even through a
window-sizing race. Regressions this guards:

* boards opened off-screen (the on-open fit fired before the viewport had its
  real size, leaving the view at 1:1 centred on the origin), and
* the canvas not grabbing keyboard focus, so M / Shift+Z silently did nothing
  until the user clicked the canvas (felt like a frozen app).
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# A large board so a correct fit is clearly < 1:1, and it overflows a 1400-wide
# viewport at 1:1 — i.e. it would be off-screen if the fit didn't run.
BOARD = (
    "#!grafli v1\n"
    "@ box a \"A\" 40,40 220x90\n"
    "@ box b \"B\" 1300,1300 220x90\n"
)


def test_open_focuses_canvas_and_fits_through_resize_race(tmp_path: Path):
    app = _app()
    f = tmp_path / "off.grafli"
    f.write_text(BOARD)
    win = MainWindow(str(f))

    # Cold-launch race: lay out tiny first, then the real window size.
    win.resize(20, 20)
    win.show()
    app.processEvents()
    win.resize(1400, 900)
    app.processEvents()
    app.processEvents()

    # The canvas owns keyboard focus, so M / Shift+Z work without a click.
    assert win._view.hasFocus()

    # The board is actually fit (zoomed out) and fully framed — not stranded
    # at 1:1 off-screen.
    assert win._view.transform().m11() < 1.0
    vp = win._view.mapToScene(win._view.viewport().rect()).boundingRect()
    content = win._view.scene().itemsBoundingRect()
    assert vp.contains(content)
