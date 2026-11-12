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
  ``author`` its hello named (a tab keeps it across reloads); the
  presenter's ``{"t": "undo", "id", "of": "agent"}`` takes back the agent's
  last edit instead.
* The agent's edits — ``{"t": "marked"}`` names the elements one touched;
  ``{"t": "proposal", "proposal"}`` carries the agent's large change that
  waits (``None`` once there is none), and the presenter's ``{"t":
  "proposal", "id", "do": "take" | "drop", "proposal": its id}`` settles it
  (see ``Room.write`` and ``Room.settle``).
* Asking the agent — an editor's or the presenter's ``{"t": "ask", "id",
  "text", "about"}`` (*about* an element's id, or left out) goes to the
  agent's session as a ``request`` and is answered with ``ack`` naming the
  ``agent``; with no session connected, or one that is gone, it is answered
  with ``error`` saying so, and nothing waits to be sent later. Until the
  agent's next write, proposal or undo, every tab gets ``{"t": "work"}``
  saying what it works on (see ``grafli.serve.agent``).
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
* ``WS /agent`` — the board's agent: a Claude Code session the presenter
  runs, through its ``grafli agent`` bridge, with the run's agent key from
  the state file (never in a link); see ``grafli.serve.agent``. One session
  holds the seat at a time; every tab sees it in ``peers`` as present or
  gone.

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
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from grafli.serve import agent as agents
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

# The longest plain-language request a tab may send the agent.
ASK_MAX_CHARS = 2000
# What a tab hears when it asks and no session was ever connected.
NO_AGENT = ("no agent is connected, so nothing was sent; the presenter "
            "connects a Claude Code session with /mcp__grafli__connect")

# What a tab may call its author: a short token it made up itself.
_AUTHOR_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _key() -> str:
    return secrets.token_urlsafe(16)


@dataclass
class Keys:
    """The run's keys: a link carries one of the first three after
    ``#k=``; the agent's is only in the run's state file."""
    viewer: str = field(default_factory=_key)
    editor: str = field(default_factory=_key)
    presenter: str = field(default_factory=_key)
    agent: str = field(default_factory=_key)

    def __post_init__(self):
        if len({self.viewer, self.editor, self.presenter, self.agent}) != 4:
            raise ValueError("the viewer, editor, presenter and agent keys "
                             "must differ")

    def is_agent(self, key) -> bool:
        return isinstance(key, str) and hmac.compare_digest(key, self.agent)

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
        # Board → the texts of its recent versions, kept the same way.
        self.texts: dict[Path, OrderedDict] = {}
        # Board → its reveal mode, kept like the history; *reveal* starts
        # every board hidden.
        self.reveal = reveal
        self.reveals: dict[Path, RevealState] = {}
        # The board the presenter's latest tab is on.
        self.lead_room: Room | None = None
        # The agent's seat: None until a session first connects.
        self.seat: agents.Seat | None = None
        # Board → the agent's proposal waiting for the presenter.
        self.proposals: dict = {}
        # The requests sent to the agent and not answered yet, oldest
        # first; what it is doing on the oldest; when that one is late.
        self.open: list[agents.Request] = []
        self.doing = ""
        self.late_s: float = agents.LATE_S
        self._late: asyncio.TimerHandle | None = None
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
                            path, RevealState(on_open=self.reveal)),
                        agent=self.agent_info,
                        texts=self.texts.setdefault(path, OrderedDict()),
                        proposals=self.proposals,
                        tell_agent=self.tell_agent)
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

    # ── The agent's seat ──

    def agent_info(self) -> dict | None:
        return self.seat.info() if self.seat else None

    def presenter_name(self) -> str:
        lead = self.lead_room.lead if self.lead_room else None
        return lead.name if lead else ""

    async def seat_agent(self, conn: agents.AgentConn) -> None:
        """Give *conn* the seat; a session that held it is told and let go."""
        old = self.seat.conn if self.seat else None
        self.seat = agents.Seat(conn.name, conn)
        if old is not None and old is not conn:
            try:
                await old.send({"t": "replaced", "by": conn.name})
                await old.close()
            except Exception:
                pass
        self.log(f"agent: {conn.name} connected")
        await self._tell_peers()
        if old is not conn:
            # The new session never heard the requests sent to the old one.
            await self.drop_work()

    async def unseat_agent(self, conn: agents.AgentConn) -> None:
        """*conn* went: the tabs show its agent as gone, working on
        nothing."""
        if self.seat is not None and self.seat.conn is conn:
            self.seat.conn = None
            self.log(f"agent: {conn.name} is gone")
            await self._tell_peers()
            await self.drop_work()

    # ── What the agent is working on, until its answer lands ──

    async def agent_doing(self, doing: str) -> None:
        """The agent reads or renders a board while a request is open."""
        if self.open and doing != self.doing:
            self.doing = doing
            await self.send_work()

    async def answered(self) -> None:
        """The agent wrote, proposed or undid: the oldest request is
        answered."""
        if not self.open:
            return
        self.open.pop(0)
        self.doing = ""
        self._time_late()
        await self.send_work()

    async def drop_work(self) -> None:
        """No open request is worked on any more: the session is gone."""
        if not self.open:
            return
        self.open.clear()
        self.doing = ""
        self._time_late()
        await self.send_work()

    def _time_late(self) -> None:
        """Tell the tabs again once the oldest request is late."""
        if self._late is not None:
            self._late.cancel()
            self._late = None
        if not self.open:
            return
        loop = asyncio.get_running_loop()
        left = self.open[0].since + self.late_s - time.monotonic()
        self._late = loop.call_later(max(left, 0),
                                     lambda: loop.create_task(self.send_work()))

    def work_message(self, client: Client) -> dict:
        """What *client*'s tab shows of the agent's work now."""
        seat = self.seat
        if not self.open or seat is None or not seat.present:
            return {"t": "work", "work": None}
        r = self.open[0]
        hidden = r.private and client.role != "presenter"
        return {"t": "work", "work": {
            "by": seat.name, "color": seat.color, "board": r.board,
            "text": None if hidden else r.text, "from": r.asked_by,
            "doing": self.doing,
            "late": time.monotonic() - r.since >= self.late_s,
            "late_after": self.late_s, "more": len(self.open) - 1}}

    async def send_work(self) -> None:
        for room in list(self.rooms.values()):
            await asyncio.gather(*(room.send_to(c, self.work_message(c))
                                   for c in list(room.clients)))

    async def ask_agent(self, board: str, text: str, asked_by: str,
                        about: dict | None = None,
                        private: bool = False) -> bool:
        """Push a plain-language request to the agent's session, *about* an
        element (``{"id", "label"}``) when one is named, and show it on
        every tab as worked on (its text on the presenter's tabs only when
        *private*); False when no session holds the seat, so nothing waits
        unseen."""
        conn = self.seat.conn if self.seat else None
        if conn is None:
            return False
        request = agents.Request(board, text, asked_by, private)
        # Open before it is sent: an answer can come back before the send
        # returns.
        self.open.append(request)
        try:
            await conn.send({"t": "request", "board": request.board,
                             "text": request.text, "from": request.asked_by,
                             "about": about})
        except Exception:
            if request in self.open:
                self.open.remove(request)
            return False
        if request in self.open:
            await self._opened(request)
        return True

    async def _opened(self, request: agents.Request) -> None:
        if self.open[0] is request:
            self.doing = ""
            self._time_late()
        await self.send_work()

    async def tell_agent(self, msg: dict) -> None:
        """Push *msg* to the agent's session, if one holds the seat."""
        conn = self.seat.conn if self.seat else None
        if conn is None:
            return
        try:
            await conn.send(msg)
        except Exception:
            pass

    async def _tell_peers(self) -> None:
        for room in list(self.rooms.values()):
            await room.send_peers()

    def agent_board(self, name) -> tuple[Path, str]:
        """The board an agent request names, else the presenter's, else the
        only one; raises ``OpError`` naming the boards when none fits."""
        if isinstance(name, str) and name:
            path = board_path(self.root, name)
            if path is None:
                raise OpError(f"no board '{name}'; boards: "
                              + ", ".join(listed_boards(self.root)))
            return path, name
        if self.lead_room is not None:
            return self.lead_room.path, self.lead_room.name
        names = listed_boards(self.root)
        if len(names) == 1:
            return board_path(self.root, names[0]), names[0]
        raise OpError("the presenter has no board open; name one of: "
                      + (", ".join(names) or "(none here)"))

    async def close(self) -> None:
        if self._late is not None:
            self._late.cancel()
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
            if hub.open:
                await room.send_to(client, hub.work_message(client))
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                kind = msg.get("t")
                if kind == "undo" and msg.get("of") == "agent":
                    await _undo_agent(hub, room, client, msg, send)
                elif kind in ("edit", "undo"):
                    await _edit(room, client, msg, send)
                elif kind == "proposal":
                    await _settle(room, client, msg, send)
                elif kind == "ask":
                    await _ask(hub, room, client, msg, send)
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

    async def agent_ws(ws: WebSocket):
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT_S)
        except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError,
                KeyError):
            await _close(ws, CLOSE_BAD_KEY, "no key")
            return
        if not (isinstance(hello, dict) and keys.is_agent(hello.get("key"))):
            await _close(ws, CLOSE_BAD_KEY, "wrong key")
            return
        send_lock = asyncio.Lock()

        async def send(msg: dict) -> None:
            async with send_lock:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))

        conn = agents.AgentConn(
            send, lambda: _close(ws, 1000, "another session is the agent"),
            agents.agent_name(hello.get("name"), hub.presenter_name()))
        lead = hub.lead_room.name if hub.lead_room else None
        await send({"t": "welcome", "name": conn.name, "board": lead,
                    "boards": listed_boards(root)})
        await hub.seat_agent(conn)
        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and hub.seat and hub.seat.conn is conn:
                    await _agent_request(hub, conn, msg, send)
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            await hub.unseat_agent(conn)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await hub.close()

    app = Starlette(routes=[
        Route("/", index),
        Route("/b/{board:path}", page),
        WebSocketRoute("/ws/{board:path}", live),
        WebSocketRoute("/agent", agent_ws),
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


async def _answer(send, req_id, work) -> None:
    """Answer request *req_id* with *work*'s result, or with its error."""
    try:
        result = await work
    except OpError as e:
        await send({"t": "error", "id": req_id, "message": str(e)})
        return
    except Exception as e:
        await send({"t": "error", "id": req_id,
                    "message": f"it failed: {type(e).__name__}: {e}"})
        return
    await send({"t": "ack", "id": req_id, **result})


async def _settle(room: Room, client: Client, msg: dict, send) -> None:
    if client.role != "presenter":
        await send({"t": "error", "id": msg.get("id"),
                    "message": "only the present link takes or drops a "
                               "proposal"})
        return
    await _answer(send, msg.get("id"),
                  room.settle(msg.get("do"), msg.get("proposal")))


async def _undo_agent(hub: Hub, room: Room, client: Client, msg: dict,
                      send) -> None:
    req_id = msg.get("id")
    if client.role != "presenter":
        await send({"t": "error", "id": req_id,
                    "message": "only the present link undoes the agent's "
                               "edit"})
        return
    if hub.seat is None:
        await send({"t": "error", "id": req_id,
                    "message": "no agent has edited here"})
        return
    name = hub.seat.name
    await _answer(send, req_id, room.undo_agent(
        agents.author(name), name, who=client.shown_name()))


async def _ask(hub: Hub, room: Room, client: Client, msg: dict,
               send) -> None:
    """Pass a tab's plain-language request on to the agent's session, or
    say why it is not: no session, or it is gone. Nothing is queued."""
    req_id = msg.get("id")
    if not client.can_edit:
        await send({"t": "error", "id": req_id,
                    "message": "this link is for watching; asking the agent "
                               "needs the editor link"})
        return
    text = msg.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        await send({"t": "error", "id": req_id,
                    "message": "nothing to ask: the request is empty"})
        return
    if len(text) > ASK_MAX_CHARS:
        await send({"t": "error", "id": req_id,
                    "message": f"a request to the agent is at most "
                               f"{ASK_MAX_CHARS} characters"})
        return
    about = None
    if msg.get("about") is not None:
        about = room.subject(client, msg.get("about"))
        if about is None:
            await send({"t": "error", "id": req_id,
                        "message": "what the request is about is not on "
                                   "the board"})
            return
    seat = hub.seat
    if seat is None:
        await send({"t": "error", "id": req_id, "message": NO_AGENT})
        return
    # Only the presenter's tabs see what the presenter asks while the
    # board hides something from the others.
    private = client.role == "presenter" and bool(room.reveal.hidden)
    if not await hub.ask_agent(room.name, text, client.shown_name(), about,
                               private):
        await send({"t": "error", "id": req_id,
                    "message": f"{seat.name} is gone, so nothing was sent; "
                               "the presenter connects a session again"})
        return
    hub.log(f"agent: {client.shown_name()} asked {seat.name} on {room.name}")
    await send({"t": "ack", "id": req_id, "agent": seat.name})


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


async def _agent_request(hub: Hub, conn: agents.AgentConn, msg: dict,
                         send) -> None:
    """Answer one of the agent's ``read``, ``write``, ``render`` or
    ``undo``."""
    req_id, kind = msg.get("id"), msg.get("t")
    if kind not in ("read", "write", "render", "undo"):
        await send({"t": "error", "id": req_id,
                    "message": f"no agent request '{kind}'"})
        return
    try:
        path, name = hub.agent_board(msg.get("board"))
        if kind == "read":
            await hub.agent_doing(agents.READING)
        elif kind == "render":
            await hub.agent_doing(agents.RENDERING)
        room = hub.room(path, name)
        try:
            frame = await room.ready()
            if frame is None:
                raise OpError(f"{name} did not render")
            if kind == "read":
                lead = room.lead is not None
                waiting = room.proposal
                result = {"board": name, "version": frame.version,
                          "text": frame.text,
                          "selection": [room.selection] if room.selection
                          else [],
                          "view": room.view if lead else None,
                          "proposal": None if waiting is None else {
                              "id": waiting.id, "by": waiting.by,
                              "changes": waiting.changes.count,
                              "summary": waiting.changes.summary()}}
            elif kind == "write":
                about = msg.get("about")
                result = {"board": name, **await room.write(
                    msg.get("base"), msg.get("text"),
                    agents.author(conn.name), by=conn.name,
                    about=about if isinstance(about, str) else "")}
            elif kind == "undo":
                result = {"board": name, **await room.undo_agent(
                    agents.author(conn.name), conn.name)}
            else:
                drawing = await hub.renderer.png(path, frame.text, hub.root)
                result = {"board": name, "version": frame.version,
                          "png": drawing["png"], "width": drawing["width"],
                          "height": drawing["height"]}
        finally:
            await hub.release(room)
    except OpError as e:
        await send({"t": "error", "id": req_id, "message": str(e)})
        return
    except Exception as e:
        await send({"t": "error", "id": req_id,
                    "message": f"{kind} failed: {type(e).__name__}: {e}"})
        return
    if kind in ("write", "undo"):
        # Its edit or proposal is on the tabs: the request is answered.
        await hub.answered()
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
    state = agents.write_state(host, port, keys.agent, root)
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
    print("Agent: a Claude Code session you run connects with "
          "/mcp__grafli__connect (setup: grafli agent --help)", file=out)
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
        agents.remove_state(state)
    return 0
