"""Reliable file watcher using polling + mtime/size checks.

QFileSystemWatcher can be flaky on macOS when files are written by
external editors (like Claude's Write/Edit tools). This uses a QTimer
to poll for changes based on mtime and size — simple and reliable.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal


class JsonSafeWatcher(QObject):
    """Polls a file for changes and emits file_changed when modified externally."""

    file_changed = Signal()

    def __init__(self, path: str, interval_ms: int = 500, parent=None):
        super().__init__(parent)
        self._path = path
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)
        self._last_mtime: float = 0
        self._last_size: int = 0
        self._snapshot()

    def _snapshot(self):
        try:
            st = os.stat(self._path)
            self._last_mtime = st.st_mtime
            self._last_size = st.st_size
        except OSError:
            self._last_mtime = 0
            self._last_size = 0

    def _check(self):
        try:
            st = os.stat(self._path)
        except OSError:
            return
        if st.st_mtime != self._last_mtime or st.st_size != self._last_size:
            self._last_mtime = st.st_mtime
            self._last_size = st.st_size
            self.file_changed.emit()

    def start(self):
        self._snapshot()
        self._timer.start()

    def stop(self):
        self._timer.stop()
