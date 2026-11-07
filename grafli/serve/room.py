"""One live board: its watchers, the versions they saw, and their edits.

A ``Room`` polls its board file (and the board's ``<stem>-res/`` vault) for
changes, has each new text drawn by the render worker and pushes the frame
to every tab on the board. The text of each pushed version is kept, so an
edit from a tab is applied to the version that tab saw and merged into the
file with ``grafli.sync.merge_boards`` — the same three-way merge the
desktop app runs when the file changes under it. No Qt.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from grafli.format import is_newer, parse, serialize
from grafli.serve.ops import OpError, apply_op
from grafli.sync import atomic_write, merge_boards

# How often the file is looked at; a change shows after this plus a render.
POLL_S = 0.05
# Versions kept for edits made against them; an older base is refused.
KEEP_VERSIONS = 64

# One counter for every room of a server, so a version names one text even
# across a room that closed and opened again.
_versions = itertools.count(1)


class Renderer(Protocol):
    async def render(self, path: Path, text: str, root: Path) -> dict: ...


@dataclass(eq=False)
class Client:
    """A tab on the board: how to reach it, what it may do, what it has."""
    send: Callable[[dict], Awaitable[None]]
    role: str                     # "viewer" or "editor"
    fonts: set[str] = field(default_factory=set)


@dataclass
class Frame:
    version: int
    text: str
    drawing: dict                 # board, svgs, docs (as the worker drew it)
    changed_at: float             # the file's mtime that this frame shows
    render_ms: float
    pushed_at: float = 0.0


def _signature(path: Path) -> tuple:
    """What a change to the board or its vault changes."""
    try:
        st = os.stat(path)
        sig: list = [st.st_mtime_ns, st.st_size]
    except OSError:
        return ()
    vault = path.with_name(f"{path.stem}-res")
    try:
        with os.scandir(vault) as it:
            for e in it:
                if e.is_file():
                    s = e.stat()
                    sig.append((e.name, s.st_mtime_ns, s.st_size))
    except OSError:
        pass
    return tuple(sorted(map(str, sig)))


class Room:
    def __init__(self, path: Path, name: str, root: Path, renderer: Renderer,
                 fonts: dict[str, dict], log: Callable[[str], None] | None = None,
                 poll_s: float = POLL_S):
        self.path = path
        self.name = name
        self.root = root
        self._renderer = renderer
        self._fonts = fonts           # shared by every room of the server
        self._log = log or (lambda _msg: None)
        self._poll_s = poll_s
        self.clients: set[Client] = set()
        self.frame: Frame | None = None
        self._texts: OrderedDict[int, str] = OrderedDict()
        self._sig: tuple = ()
        self._wake = asyncio.Event()
        self._first = asyncio.Event()
        self._edit_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # ── Watching and pushing ──

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def ready(self) -> Frame | None:
        await self._first.wait()
        return self.frame

    async def _run(self) -> None:
        while True:
            sig = _signature(self.path)
            if sig != self._sig or self._wake.is_set():
                self._wake.clear()
                self._sig = sig
                await self._publish()
                self._first.set()
            try:
                await asyncio.wait_for(self._wake.wait(), self._poll_s)
            except TimeoutError:
                pass

    async def _publish(self) -> None:
        try:
            changed_at = os.stat(self.path).st_mtime
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            await self._broadcast({"t": "error",
                                   "message": f"cannot read {self.name}: {e}"})
            return
        if not text.strip():
            # An editor that writes in place empties the file first; the
            # full text is the next change the poll sees.
            return
        t0 = time.perf_counter()
        try:
            drawing = await self._renderer.render(self.path, text, self.root)
        except Exception as e:
            # A board mid-write or broken keeps its last good frame on screen.
            await self._broadcast({"t": "error",
                                   "message": f"{self.name} did not render: {e}"})
            return
        render_ms = (time.perf_counter() - t0) * 1000
        for font in drawing.pop("fonts", []):
            self._fonts[_font_key(font)] = font
        version = next(_versions)
        self._texts[version] = text
        while len(self._texts) > KEEP_VERSIONS:
            self._texts.popitem(last=False)
        self.frame = Frame(version, text, drawing, changed_at, render_ms)
        await asyncio.gather(*(self._send_frame(c) for c in list(self.clients)))
        self.frame.pushed_at = time.time()
        self._log(f"{self.name} v{version}: drawn in {render_ms:.0f} ms, "
                  f"pushed to {len(self.clients)} tab(s) "
                  f"{(self.frame.pushed_at - changed_at) * 1000:.0f} ms "
                  f"after the file changed")

    def _frame_message(self, client: Client) -> dict:
        assert self.frame is not None
        fonts = [f for k, f in self._fonts.items() if k not in client.fonts]
        client.fonts.update(_font_key(f) for f in fonts)
        return {"t": "frame", "version": self.frame.version,
                "changed_at": self.frame.changed_at,
                "render_ms": round(self.frame.render_ms, 1),
                "sent_at": time.time(), **self.frame.drawing, "fonts": fonts}

    async def _send_frame(self, client: Client) -> None:
        try:
            await client.send(self._frame_message(client))
        except Exception:
            self.clients.discard(client)

    async def _broadcast(self, msg: dict) -> None:
        for client in list(self.clients):
            try:
                await client.send(msg)
            except Exception:
                self.clients.discard(client)

    async def join(self, client: Client) -> None:
        """Add *client*; it gets the frame on screen now, or the first one
        when it is drawn."""
        has_frame = self.frame is not None
        self.clients.add(client)
        if has_frame:
            await self._send_frame(client)
        else:
            await self.ready()

    def leave(self, client: Client) -> None:
        self.clients.discard(client)

    # ── Edits ──

    def text_of(self, version: int) -> str | None:
        return self._texts.get(version)

    async def edit(self, base: int, op: dict) -> dict:
        """Apply *op* to version *base* and merge it into the file.

        Returns ``{"touched": the element's id, "conflicts": [...]}``; raises
        ``OpError`` when the edit cannot be made. The new frame follows as
        soon as the merged text is drawn.
        """
        async with self._edit_lock:
            base_text = self._texts.get(base) if isinstance(base, int) else None
            if base_text is None:
                raise OpError("this tab's board is too old to edit; "
                              "wait for the next frame")
            base_board = parse(base_text)
            local = parse(base_text)
            touched = apply_op(local, op)
            try:
                disk_text = self.path.read_text(encoding="utf-8")
            except OSError as e:
                raise OpError(f"cannot read {self.name}: {e}") from e
            remote = parse(disk_text)
            if is_newer(remote) or is_newer(base_board):
                raise OpError(f"{self.name} was written by a newer grafli; "
                              "it is read-only here")
            merged, conflicts = merge_boards(base_board, local, remote)
            text = serialize(merged)
            if text != disk_text:
                atomic_write(self.path, text)
            self._wake.set()
        return {"touched": touched["id"],
                "conflicts": [{"kind": c.kind, "key": c.key,
                               "detail": c.detail} for c in conflicts]}


def _font_key(font: dict) -> str:
    return f"{font['family']}|{font['weight']}"
