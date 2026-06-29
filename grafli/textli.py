"""textli — standalone launcher for the Zen markdown editor.

Opens grafli's focused markdown editor on any file, without the diagram app.
Imports only the editor + the shared font helper — never app.py — so the
editor stays cleanly extractable into its own package later.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from grafli.fonts import register_bundled_fonts
from grafli.zen_md import ZenMarkdownEditor


def split_location(file_arg: str) -> tuple[str, str]:
    """Split an ``open`` argument into ``(path, anchor)``. A ``#heading-slug``
    fragment selects a heading to scroll to (markdown-link style); anchors are
    ``[a-z0-9-]`` slugs, so the first ``#`` starts the fragment."""
    path, _, anchor = file_arg.partition("#")
    return path, anchor


class TextliHost(QWidget):
    """Full-window host for the zen editor in standalone mode.

    The editor parents into this widget and paints its translucent dim wash
    over it, so the host just supplies a solid dark backdrop and owns the
    window lifecycle (closing the editor quits the app).
    """

    def __init__(self):
        super().__init__()
        # Solid dark backdrop — the editor's dim wash composites over it
        # cleanly (no graph behind it as there is inside grafli).
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#23272A"))
        self.setPalette(pal)
        self._editor: ZenMarkdownEditor | None = None

    def open(
        self,
        path: Path,
        text: str,
        anchor: str = "",
        read: bool = False,
    ) -> None:
        """Create the editor on the given file. Call after the host is shown
        so the editor sizes to a real window rect. ``anchor`` scrolls to a
        heading (its markdown slug); ``read`` opens the rendered read view."""
        self.setWindowTitle(f"textli — {path.name}")
        self._editor = ZenMarkdownEditor(
            parent=self, text=text, title=path.name, file_path=path,
            anchor=anchor, start_in_read=read,
        )
        # File-backed editing autosaves, so closing simply ends the session.
        self._editor.cancelled.connect(self.close)
        self._editor.finished.connect(lambda *_: self.close())

    def closeEvent(self, event):
        super().closeEvent(event)
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser(
        prog="textli",
        description="Standalone Zen markdown editor.",
    )
    parser.add_argument(
        "file",
        help="Markdown file to open, optionally with a #heading-slug location "
             "(e.g. notes.md#design-decisions). Created on first save if it "
             "doesn't exist.",
    )
    parser.add_argument(
        "-r", "--read",
        action="store_true",
        help="Open in the rendered read view (default: editable write view)",
    )
    args = parser.parse_args()

    file_arg, anchor = split_location(args.file)
    path = Path(file_arg).expanduser()
    if path.is_dir():
        parser.error(f"{path} is a directory")
    if not path.exists() and not path.parent.exists():
        parser.error(f"directory does not exist: {path.parent}")
    text = path.read_text(encoding="utf-8") if path.exists() else ""

    app = QApplication(sys.argv)
    app.setApplicationName("textli")
    register_bundled_fonts()

    # Let Ctrl+C quit cleanly (a periodic no-op tick lets the signal land).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    host = TextliHost()
    host.showMaximized()
    host.open(path, text, anchor=anchor, read=args.read)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
