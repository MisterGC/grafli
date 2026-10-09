"""Buffer management for multi-document support."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from grafli.format import Board


@dataclass
class ViewState:
    """Opaque snapshot of the view's internal state."""

    undo_stack: list[str] = field(default_factory=list)
    redo_stack: list[str] = field(default_factory=list)
    dirty: bool = False
    transform: tuple[float, ...] = ()  # m11, m12, m21, m22, dx, dy
    h_scroll: int = 0
    v_scroll: int = 0
    selected_box_ids: list[str] = field(default_factory=list)
    selected_note_ids: list[str] = field(default_factory=list)
    # Ctrl+O / Ctrl+I jumplist (scene rects), kept per board
    nav_stack: list = field(default_factory=list)
    nav_index: int = -1


@dataclass
class BufferState:
    """Frozen state for one open buffer."""

    file_path: Path | None
    last_written: str
    board: Board
    view_state: ViewState
    file_mtime: float = 0.0


@dataclass
class BoardFrame:
    """One step into a board: the board you came from, as you left it, and
    the element you entered through. Session state only, never written."""

    parent_path: Path
    parent_view: ViewState
    child_path: Path
    label: str
    # Id of the element entered through, so `gu` can zoom back out of it.
    via_id: str = ""


class BufferManager:
    """Manages a list of open buffers with an active index."""

    def __init__(self):
        self._buffers: list[BufferState] = []
        self._active_index: int = -1
        self._prev_index: int = -1
        # Boards entered through a link, root first; `gu` pops the last one.
        self._frames: list[BoardFrame] = []

    @property
    def active_index(self) -> int:
        return self._active_index

    @property
    def prev_index(self) -> int:
        return self._prev_index

    @property
    def active(self) -> BufferState | None:
        if 0 <= self._active_index < len(self._buffers):
            return self._buffers[self._active_index]
        return None

    @property
    def count(self) -> int:
        return len(self._buffers)

    @property
    def buffers(self) -> list[BufferState]:
        return self._buffers

    def add(self, buf: BufferState) -> int:
        """Add a buffer and return its index."""
        self._buffers.append(buf)
        return len(self._buffers) - 1

    def remove(self, index: int) -> BufferState | None:
        """Remove buffer at index. Returns the removed buffer or None."""
        if not (0 <= index < len(self._buffers)):
            return None
        removed = self._buffers.pop(index)
        # Adjust active index
        if self._active_index >= len(self._buffers):
            self._active_index = max(0, len(self._buffers) - 1)
        elif self._active_index > index:
            self._active_index -= 1
        # Adjust prev index
        if self._prev_index == index:
            self._prev_index = -1
        elif self._prev_index > index:
            self._prev_index -= 1
        if self._prev_index >= len(self._buffers):
            self._prev_index = -1
        return removed

    def switch_to(self, index: int) -> bool:
        """Switch active buffer. Returns True if index is valid."""
        if not (0 <= index < len(self._buffers)):
            return False
        if index == self._active_index:
            return True
        self._prev_index = self._active_index
        self._active_index = index
        return True

    def find_by_path(self, path: Path) -> int:
        """Return index of buffer with given path, or -1."""
        resolved = path.resolve()
        for i, buf in enumerate(self._buffers):
            if buf.file_path and buf.file_path.resolve() == resolved:
                return i
        return -1

    # ── Board stack ──

    def push_frame(self, frame: BoardFrame) -> None:
        """Record entering ``frame.child_path`` from ``frame.parent_path``.
        Entering from a board off the current chain starts a new chain."""
        if self._frames and not _same(self._frames[-1].child_path,
                                      frame.parent_path):
            self._frames.clear()
        self._frames.append(frame)

    def frame_for(self, path: Path | None) -> BoardFrame | None:
        """The frame that leads back up from *path*, or None at the top."""
        if path is None or not self._frames:
            return None
        top = self._frames[-1]
        return top if _same(top.child_path, path) else None

    def pop_frame(self) -> BoardFrame | None:
        return self._frames.pop() if self._frames else None

    def board_path(self, path: Path | None) -> list[str]:
        """Labels from the root board down to *path*, or [] when *path* was
        not entered through a link."""
        if self.frame_for(path) is None:
            return []
        return ([self._frames[0].parent_path.stem]
                + [f.label for f in self._frames])


def _same(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()
