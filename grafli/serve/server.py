"""The HTTP and WebSocket side of ``grafli serve`` (an ASGI app, no Qt).

* ``GET /b/<board>`` — the live page. It holds no board: the drawing comes
  over the WebSocket only, after the key.
* ``WS /ws/<board>`` — the page sends ``{"t": "hello", "key"}`` first; the
  key read from the link after ``#k=`` decides whether the tab may watch
  (viewer) or also edit (editor). Then the server sends ``welcome`` and a
  ``frame`` on every change; an editor sends ``{"t": "edit", "id", "base",
  "op"}`` and gets ``ack`` or ``error`` with the same ``id``.

A wrong key closes the socket with code 4401, an unknown board with 4404.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import secrets
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from grafli.serve.ops import OpError
from grafli.serve.render import RenderWorker, board_name
from grafli.serve.room import Client, Room

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7341
HELLO_TIMEOUT_S = 10

CLOSE_BAD_KEY = 4401
CLOSE_NO_BOARD = 4404


@dataclass
class Keys:
    """The run's two keys; a link carries one of them after ``#k=``."""
    viewer: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    editor: str = field(default_factory=lambda: secrets.token_urlsafe(16))

    def __post_init__(self):
        if self.viewer == self.editor:
            raise ValueError("the viewer and editor keys must differ")

    def role(self, key) -> str | None:
        if not isinstance(key, str):
            return None
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
    from urllib.parse import quote
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return f"http://{host}:{port}/b/{quote(name)}#k={key}"


class Hub:
    """The rooms of one server, opened on the first tab, closed after the
    last."""

    def __init__(self, root: Path, renderer, log: Callable[[str], None]):
        self.root = root
        self.renderer = renderer
        self.log = log
        self.rooms: dict[Path, Room] = {}
        self.fonts: dict[str, dict] = {}
        self._shell: str | None = None

    async def shell(self) -> str:
        if self._shell is None:
            self._shell = await self.renderer.shell()
        return self._shell

    def room(self, path: Path, name: str) -> Room:
        room = self.rooms.get(path)
        if room is None:
            room = Room(path, name, self.root, self.renderer, self.fonts,
                        log=self.log)
            self.rooms[path] = room
            room.start()
        return room

    async def release(self, room: Room) -> None:
        if not room.clients and self.rooms.get(room.path) is room:
            del self.rooms[room.path]
            await room.stop()

    async def close(self) -> None:
        for room in list(self.rooms.values()):
            await room.stop()
        self.rooms.clear()
        await self.renderer.close()


def create_app(root: Path, keys: Keys, renderer=None,
               log: Callable[[str], None] | None = None):
    """The ASGI app serving the boards under *root*."""
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, PlainTextResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect

    root = Path(root).resolve()
    hub = Hub(root, renderer or RenderWorker(), log or (lambda _m: None))

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

        client = Client(send, role)
        room = hub.room(path, name)
        await send({"t": "welcome", "role": role, "board": name})
        await room.join(client)
        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict) or msg.get("t") != "edit":
                    continue
                await _edit(room, client, msg, send)
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            room.leave(client)
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
    if client.role != "editor":
        await send({"t": "error", "id": req_id,
                    "message": "this link is for watching; "
                               "editing needs the editor link"})
        return
    try:
        result = await room.edit(msg.get("base"), msg.get("op"))
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
        out=sys.stdout, open_board: str | None = None) -> int:
    """Serve the boards under *root* until Ctrl+C; prints the links."""
    import uvicorn

    root = Path(root).resolve()
    keys = Keys()
    sock = bind(host, port)
    port = sock.getsockname()[1]

    def log(msg: str) -> None:
        if verbose:
            print(msg, file=out, flush=True)

    app = create_app(root, keys, RenderWorker(theme), log)
    names = [open_board] if open_board else listed_boards(root)
    print(f"grafli serve: {root} on {host}:{port} — your network or VPN only; "
          "Ctrl+C stops it", file=out)
    if every_interface(host):
        print(f"Warning: {host} listens on every interface", file=out)
    if not names:
        print("No boards here yet; a board's link is "
              + link(host, port, "<board>", keys.viewer), file=out)
    for name in names:
        print(f"  {name}", file=out)
        print(f"    watch: {link(host, port, name, keys.viewer)}", file=out)
        print(f"    edit:  {link(host, port, name, keys.editor)}", file=out)
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
