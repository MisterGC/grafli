"""One live board: its watchers, the versions they saw, and their edits.

A ``Room`` polls its board file (and the board's ``<stem>-res/`` vault) for
changes, has each new text drawn by the render worker and pushes the frame
to every tab on the board. The text of each pushed version is kept, so an
edit from a tab is applied to the version that tab saw and merged into the
file with ``grafli.sync.merge_boards`` — the same three-way merge the
desktop app runs when the file changes under it. An edit is drawn and pushed
before it is answered, so the answer names the version that shows it.

Undo is per author and version-based: each edit keeps the text before and
after it, and undoing it merges "after → before" into the file as it is now,
so what others changed since stays. No Qt.
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

from grafli.format import Board, is_newer, parse, serialize
from grafli.serve.ops import OpError, apply_op
from grafli.sync import atomic_write, merge_boards

# How often the file is looked at; a change shows after this plus a render.
POLL_S = 0.05
# Versions kept for edits made against them; an older base is refused.
KEEP_VERSIONS = 64
# Edits an author can undo, per board.
KEEP_UNDO = 100

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
    author: str = ""              # whose edits undo undoes
    fonts: set[str] = field(default_factory=set)


@dataclass
class Step:
    """One edit an author made: the file's text before and after it."""
    before: str
    after: str
    touched: str


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
                 poll_s: float = POLL_S,
                 history: dict[str, list[Step]] | None = None):
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
        # Author → their edits, oldest first; kept by the server, so a tab
        # that reconnects (or reloads) can still undo.
        self.history: dict[str, list[Step]] = {} if history is None else history
        self._sig: tuple = ()
        self._first = asyncio.Event()
        self._edit_lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()
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
            if _signature(self.path) != self._sig:
                await self._refresh()
                self._first.set()
            await asyncio.sleep(self._poll_s)

    async def _refresh(self, force: bool = False) -> int | None:
        """Draw and push the file if it changed since the last frame (or
        when *force*); the version pushed, or None."""
        async with self._publish_lock:
            sig = _signature(self.path)
            if sig == self._sig and not force:
                return None
            self._sig = sig
            return await self._publish()

    async def _publish(self) -> int | None:
        try:
            changed_at = os.stat(self.path).st_mtime
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            await self._broadcast({"t": "error",
                                   "message": f"cannot read {self.name}: {e}"})
            return None
        if not text.strip():
            # An editor that writes in place empties the file first; the
            # full text is the next change the poll sees.
            return None
        t0 = time.perf_counter()
        try:
            drawing = await self._renderer.render(self.path, text, self.root)
        except Exception as e:
            # A board mid-write or broken keeps its last good frame on screen.
            await self._broadcast({"t": "error",
                                   "message": f"{self.name} did not render: {e}"})
            return None
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
        return version

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

    async def edit(self, base: int, op: dict, author: str = "") -> dict:
        """Apply *op* to version *base* and merge it into the file.

        Returns ``{"touched": the element's id, "conflicts": [...],
        "version": the version that shows it}`` once that version is drawn
        and pushed (``version`` is None when it did not draw); raises
        ``OpError`` when the edit cannot be made.
        """
        async with self._edit_lock:
            base_text = self._texts.get(base) if isinstance(base, int) else None
            if base_text is None:
                raise OpError("this tab's board is too old to edit; "
                              "wait for the next frame")
            base_board = parse(base_text)
            local = parse(base_text)
            touched = apply_op(local, op)
            disk_text, remote = self._read_disk()
            if is_newer(base_board):
                raise OpError(f"{self.name} was written by a newer grafli; "
                              "it is read-only here")
            text, conflicts = self._merge(base_board, local, disk_text, remote)
            if text != disk_text and author:
                steps = self.history.setdefault(author, [])
                steps.append(Step(disk_text, text, touched["id"]))
                del steps[:-KEEP_UNDO]
            version = await self._land(text, disk_text)
        return {"touched": touched["id"], "conflicts": conflicts,
                "version": version}

    async def undo(self, author: str) -> dict:
        """Take back *author*'s last edit that still changes something.

        Merges the edit's "after → before" into the file as it is now, so
        what others changed since stays; a field someone changed after the
        edit keeps their value and is reported as a conflict. Raises
        ``OpError`` when the author has nothing left to undo.
        """
        async with self._edit_lock:
            steps = self.history.get(author) or []
            disk_text, remote = self._read_disk()
            while steps:
                step = steps.pop()
                text, conflicts = self._merge(parse(step.after),
                                              parse(step.before),
                                              disk_text, remote)
                if text != disk_text:
                    version = await self._land(text, disk_text)
                    return {"touched": step.touched, "conflicts": conflicts,
                            "version": version, "undone": True}
            raise OpError("nothing of yours to undo")

    def _read_disk(self) -> tuple[str, Board]:
        try:
            disk_text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            raise OpError(f"cannot read {self.name}: {e}") from e
        remote = parse(disk_text)
        if is_newer(remote):
            raise OpError(f"{self.name} was written by a newer grafli; "
                          "it is read-only here")
        return disk_text, remote

    @staticmethod
    def _merge(base: Board, local: Board, disk_text: str,
               remote: Board) -> tuple[str, list[dict]]:
        merged, conflicts = merge_boards(base, local, remote)
        _drop_loose_arrows(merged, remote)
        return serialize(merged), [{"kind": c.kind, "key": c.key,
                                    "detail": c.detail} for c in conflicts]

    async def _land(self, text: str, disk_text: str) -> int | None:
        """Write *text* when it differs from the file, then draw and push
        it; the version on screen afterwards."""
        if text == disk_text and self.frame is not None and self.frame.text == text:
            return self.frame.version
        if text != disk_text:
            atomic_write(self.path, text)
        return await self._refresh(force=True)


def _drop_loose_arrows(merged: Board, remote: Board) -> None:
    """Drop the arrows the merge left without an end: a box this side
    deleted (or an add it undid) that the other side had connected to.
    An arrow the file already held without an end stays as it was."""
    def ends(board: Board) -> set[str]:
        return {el.id for el in [*board.boxes, *board.notes, *board.images]}
    have, had = ends(merged), ends(remote)
    for arrow in list(merged.arrows):
        for end in (arrow.from_id, arrow.to_id):
            if end not in have and end in had:
                merged.remove_arrow(arrow)
                break


def _font_key(font: dict) -> str:
    return f"{font['family']}|{font['weight']}"
