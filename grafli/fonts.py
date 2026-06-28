"""Bundled-font registration, shared by the grafli app and the textli editor.

Lives apart from app.py so the standalone editor (textli) can register the
same fonts without importing the diagram app — keeping the editor extractable
into its own package later.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

_BUNDLED_FONTS = (
    "PatrickHand-Regular.ttf",
    "JetBrainsMonoNerdFont-Regular.ttf",
    "JetBrainsMonoNerdFont-Bold.ttf",
)


def register_bundled_fonts() -> None:
    """Load the fonts shipped in grafli/fonts/ into the running QApplication."""
    fonts_dir = Path(__file__).parent / "fonts"
    for name in _BUNDLED_FONTS:
        path = fonts_dir / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
