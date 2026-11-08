"""The HTTP and WebSocket side of ``grafli serve`` (an ASGI app, no Qt).

* ``GET /b/<board>`` — the live page. It holds no board: the drawing comes
  over the WebSocket only, after the key.
* ``WS /ws/<board>`` — the page sends ``{"t": "hello", "key"}`` first; the
  key read from the link after ``#k=`` decides whether the tab may watch
  (viewer), also edit (editor), or present: edit and be followed
  (presenter). Then the server sends ``welcome`` and a ``frame`` on every
  change; an editor or the presenter sends ``{"t": "edit", "id", "base",
  "op"}`` and gets ``ack`` or ``error`` with the same ``id``, the ack once
  the frame that shows the edit is pushed (its ``version``). ``{"t":
  "undo", "id"}`` takes back the last edit of the tab's author, the
  ``author`` its hello named (a tab keeps it across reloads).
* Presence — cursors, the laser, the presenter's view, who follows, names —
  is passed between the tabs of a board and never stored; see
  ``grafli.serve.presence``. The hello may carry the tab's ``name`` and
  whether it ``follow``s. When the presenter opens another board, the tabs
  on every other board get ``{"t": "away", "board", "href"}`` (``board``
  None once no board has the presenter).
* Reveal mode — the presenter's ``{"t": "reveal", "id", "do", ...}`` (see
  ``Room.reveal_step``) — hides part of the board from every other tab;
  it is answered with ``ack`` or ``error`` like an edit and, like presence,
  never stored. ``create_app(reveal=True)`` hides every board but its title
  from its first frame on.

A wrong key closes the socket with code 4401, an unknown board with 4404.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import re
import secrets
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from grafli.serve.ops import OpError
from grafli.serve.presence import KINDS as PRESENCE, clean_name
from grafli.serve.render import RenderWorker, board_name
from grafli.serve.reveal import RevealState
from grafli.serve.room import Client, Room

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7341
HELLO_TIMEOUT_S = 10

CLOSE_BAD_KEY = 4401
CLOSE_NO_BOARD = 4404

# What a tab may call its author: a short token it made up itself.
_AUTHOR_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _key() -> str:
    return secrets.token_urlsafe(16)


@dataclass
class Keys:
    """The run's three keys; a link carries one of them after ``#k=``."""
    viewer: str = field(default_factory=_key)
    editor: str = field(default_factory=_key)
    presenter: str = field(default_factory=_key)

    def __post_init__(self):
        if len({self.viewer, self.editor, self.presenter}) != 3:
            raise ValueError("the viewer, editor and presenter keys must differ")

    def role(self, key) -> str | None:
        if not isinstance(key, str):
            return None
        if hmac.compare_digest(key, self.presenter):
            return "presenter"
        if hmac.compare_digest(key, self.editor):
            return "editor"
        if hmac.compare_digest(key, self.viewer):
            return "viewer"
        return None


def board_path(root: Path, name: str) -> Path | None:
    """The board file *name* names under *root*, or None."""
    if not name or "\\" in name or name.startswith("/"):
        return None
    path = (root / f"{name}.grafli").resolve()
    if board_name(root, path) != name or not path.is_file():
        return None
    return path


def listed_boards(root: Path) -> list[str]:
    """The boards directly in *root*, by name; sub-boards in vaults are
    reached through their levels."""
    return sorted(board_name(root, p) for p in root.glob("*.grafli")
                  if p.is_file())


def link(host: str, port: int, name: str, key: str) -> str:
    """The link a tab opens: ``http://<host>:<port>/b/<board>#k=<key>``."""
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return f"http://{host}:{port}/b/{quote(name)}#k={key}"


class Hub:
    """The rooms of one server, opened on the first tab, closed after the
    last."""

    def __init__(self, root: Path, renderer, log: Callable[[str], None],
                 reveal: bool = False):
        self.root = root
        self.renderer = renderer
        self.log = log
        self.rooms: dict[Path, Room] = {}
        self.fonts: dict[str, dict] = {}
        # Board → author → their edits; outlives a room, so undo still works
        # after the last tab on a board reloaded.
        self.history: dict[Path, dict] = {}
        # Board → its reveal mode, kept like the history; *reveal* starts
        # every board hidden.
        self.reveal = reveal
        self.reveals: dict[Path, RevealState] = {}
        # The board the presenter's latest tab is on.
        self.lead_room: Room | None = None
        self._shell: str | None = None

    async def shell(self) -> str:
        if self._shell is None:
            self._shell = await self.renderer.shell()
        return self._shell

    def room(self, path: Path, name: str) -> Room:
        room = self.rooms.get(path)
        if room is None:
            room = Room(path, name, self.root, self.renderer, self.fonts,
                        log=self.log,
                        history=self.history.setdefault(path, {}),
                        reveal_state=self.reveals.setdefault(
                            path, RevealState(on_open=self.reveal)))
            self.rooms[path] = room
            room.start()
        return room

    async def release(self, room: Room) -> None:
        if not room.clients and self.rooms.get(room.path) is room:
            del self.rooms[room.path]
            await room.stop()

    # ── Where the presenter is: tabs on other boards follow them there ──

    def away(self, room: Room) -> dict:
        """What a tab on *room* hears of the presenter on another board."""
        lead = self.lead_room
        if lead is None or lead is room or lead.lead is None:
            return {"t": "away", "board": None, "href": None}
        return {"t": "away", "board": lead.name, "href": f"/b/{quote(lead.name)}"}

    async def arrived(self, room: Room, client: Client) -> None:
        if client.role == "presenter":
            self.lead_room = room
            await self._tell_away()
        else:
            msg = self.away(room)
            if msg["board"] is not None:
                await room.send_to(client, msg)

    async def departed(self, room: Room) -> None:
        if self.lead_room is room and room.lead is None:
            self.lead_room = None
            await self._tell_away()

    async def _tell_away(self) -> None:
        for room in list(self.rooms.values()):
            if room is not self.lead_room:
                await room.broadcast(self.away(room))

    async def close(self) -> None:
        for room in list(self.rooms.values()):
            await room.stop()
        self.rooms.clear()
        await self.renderer.close()


def create_app(root: Path, keys: Keys, renderer=None,
               log: Callable[[str], None] | None = None, reveal: bool = False):
    """The ASGI app serving the boards under *root*; with *reveal*, each
    board starts with only its title showing."""
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, PlainTextResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect

    root = Path(root).resolve()
    hub = Hub(root, renderer or RenderWorker(), log or (lambda _m: None),
              reveal=reveal)

    async def page(request):
        # The same page for every name: what exists is told only after the key.
        return HTMLResponse(await hub.shell(),
                            headers={"Cache-Control": "no-store",
                                     "Referrer-Policy": "no-referrer"})

    async def index(request):
        return PlainTextResponse("grafli serve: open a board's link, "
                                 "/b/<board>#k=<key>\n")

    async def live(ws: WebSocket):
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT_S)
        except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError,
                KeyError):
            await _close(ws, CLOSE_BAD_KEY, "no key")
            return
        role = keys.role(hello.get("key") if isinstance(hello, dict) else None)
        if role is None:
            await _close(ws, CLOSE_BAD_KEY, "wrong key")
            return
        name = ws.path_params["board"]
        path = board_path(root, name)
        if path is None:
            await _close(ws, CLOSE_NO_BOARD, "no such board")
            return

        send_lock = asyncio.Lock()

        async def send(msg: dict) -> None:
            async with send_lock:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))

        author = hello.get("author")
        if not (isinstance(author, str) and _AUTHOR_RE.fullmatch(author)):
            author = secrets.token_urlsafe(8)
        client = Client(send, role, author, name=clean_name(hello.get("name")),
                        following=hello.get("follow") is True
                        and role != "presenter")
        room = hub.room(path, name)
        await send({"t": "welcome", "role": role, "board": name,
                    "id": client.id})
        try:
            await room.join(client)
            await hub.arrived(room, client)
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                kind = msg.get("t")
                if kind in ("edit", "undo"):
                    await _edit(room, client, msg, send)
                elif kind == "reveal":
                    await _reveal(room, client, msg, send)
                elif kind in PRESENCE:
                    await room.presence(client, msg)
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            await room.leave(client)
            await hub.departed(room)
            await hub.release(room)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await hub.close()

    app = Starlette(routes=[
        Route("/", index),
        Route("/b/{board:path}", page),
        WebSocketRoute("/ws/{board:path}", live),
    ], lifespan=lifespan)
    app.state.hub = hub
    return app


async def _close(ws, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except RuntimeError:
        pass


async def _edit(room: Room, client: Client, msg: dict, send) -> None:
    req_id = msg.get("id")
    if not client.can_edit:
        await send({"t": "error", "id": req_id,
                    "message": "this link is for watching; "
                               "editing needs the editor link"})
        return
    try:
        if msg.get("t") == "undo":
            result = await room.undo(client.author)
        else:
            result = await room.edit(msg.get("base"), msg.get("op"),
                                     client.author)
    except OpError as e:
        await send({"t": "error", "id": req_id, "message": str(e)})
        return
    except Exception as e:
        # An edit that fails in a way the checks did not foresee is answered
        # like any other refused edit; the tab's connection stays open.
        await send({"t": "error", "id": req_id,
                    "message": f"the edit failed: {type(e).__name__}: {e}"})
        return
    await send({"t": "ack", "id": req_id, **result})


async def _reveal(room: Room, client: Client, msg: dict, send) -> None:
    req_id = msg.get("id")
    if client.role != "presenter":
        await send({"t": "error", "id": req_id,
                    "message": "only the present link reveals"})
        return
    try:
        result = await room.reveal_step(msg)
    except OpError as e:
        await send({"t": "error", "id": req_id, "message": str(e)})
        return
    await send({"t": "ack", "id": req_id, **result})


def bind(host: str, port: int) -> socket.socket:
    """A listening socket on *host* only — never every interface unless
    *host* says so."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                               flags=socket.AI_PASSIVE)
    family, kind, proto, _name, addr = infos[0]
    sock = socket.socket(family, kind, proto)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind(addr)
    sock.listen(128)
    sock.setblocking(False)
    return sock


def every_interface(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def run(root: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        theme: str = "light", verbose: bool = False,
        out=sys.stdout, open_board: str | None = None,
        reveal: bool = False) -> int:
    """Serve the boards under *root* until Ctrl+C; prints the links. With
    *reveal*, every board starts with only its title showing."""
    import uvicorn

    root = Path(root).resolve()
    keys = Keys()
    sock = bind(host, port)
    port = sock.getsockname()[1]

    def log(msg: str) -> None:
        if verbose:
            print(msg, file=out, flush=True)

    app = create_app(root, keys, RenderWorker(theme), log, reveal=reveal)
    names = [open_board] if open_board else listed_boards(root)
    print(f"grafli serve: {root} on {host}:{port} — your network or VPN only; "
          "Ctrl+C stops it", file=out)
    if every_interface(host):
        print(f"Warning: {host} listens on every interface", file=out)
    if reveal:
        print("Reveal mode: every board shows only its title until the "
              "present link's tab reveals it (v)", file=out)
    if not names:
        print("No boards here yet; a board's link is "
              + link(host, port, "<board>", keys.viewer), file=out)
    for name in names:
        print(f"  {name}", file=out)
        print(f"    watch:   {link(host, port, name, keys.viewer)}", file=out)
        print(f"    edit:    {link(host, port, name, keys.editor)}", file=out)
        print(f"    present: {link(host, port, name, keys.presenter)}", file=out)
    out.flush()
    config = uvicorn.Config(app, log_level="warning", ws="auto",
                            lifespan="on", ws_max_size=1024 * 1024)
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    return 0
