"""``grafli serve`` inside the desktop app: what serve hosts, hosted by the app.

The app starts the same ASGI app ``grafli serve`` runs (``create_app``) on
a thread of its own, with its own asyncio loop, and writes the same state
file, so a Claude Code session connects through ``grafli agent`` and guest
tabs open their links exactly as they do with ``grafli serve``. The app
itself takes the presenter's seat in the room of the board it shows: an
in-process ``Client`` that hears what a present link's tab hears (who is
here and the agent's seat, what the agent works on, its marks and its
proposal) and asks what that tab asks (``ask``, take or drop a proposal,
undo the agent's last edit). Its selection and its view are the
presenter's, so the agent reads them.

The app and the server still meet only through the board file: the app
autosaves its edits and reloads, merging, what the agent writes; the room
polls the file and draws it for the tabs. Drawings are not passed to the
app, which draws the board itself.

Everything a ``Host`` hears arrives through *deliver* on the server's
thread; every request returns a ``concurrent.futures.Future`` of the answer
a tab would get (``{"t": "ack", ...}`` or ``{"t": "error", "message"}``).
The caller moves both onto its own thread. No Qt.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path
from typing import Callable

from grafli.serve import agent as agents
from grafli.serve import presence
from grafli.serve.render import board_name

# How long starting or stopping the server may take.
START_TIMEOUT_S = 10
STOP_TIMEOUT_S = 10

# What the app's tab-less seat is called in a room.
APP_AUTHOR = "app"


class HostError(Exception):
    """The app cannot host its boards: the extra is missing, or the port is
    taken."""


def missing_extra() -> str | None:
    """What hosting needs and is not installed, as a sentence; None when
    everything is there."""
    missing = []
    for module in ("starlette", "uvicorn", "websockets"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if not missing:
        return None
    return ("hosting the board for an agent and guests needs grafli's serve "
            "extra (missing: " + ", ".join(missing) + "); install it with "
            "pip install 'grafli[serve]'")


class Host:
    """The boards under *root*, served from inside the app.

    *deliver* gets every message a present link's tab would get, but the
    drawings; it runs on the server's thread.
    """

    def __init__(self, root: Path, deliver: Callable[[dict], None],
                 host: str | None = None, port: int | None = None,
                 theme: str = "light", renderer=None,
                 log: Callable[[str], None] | None = None,
                 state_where: Path | None = None):
        from grafli.serve.server import DEFAULT_HOST, Keys
        self.root = Path(root).resolve()
        self.host = host or DEFAULT_HOST
        self.port = port
        self.keys = Keys()
        self._deliver = deliver
        self._theme = theme
        self._renderer = renderer
        self._log = log or (lambda _m: None)
        self._where = state_where
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None
        self._sock = None
        self._state: Path | None = None
        self.hub = None
        # The app's seat: the room it presents in, and its client there.
        self._room = None
        self._client = None
        self.board: str | None = None

    # ── Starting and stopping ──

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Listen and serve; raises ``HostError`` when it cannot."""
        why = missing_extra()
        if why:
            raise HostError(why)
        import uvicorn
        from grafli.serve.render import RenderWorker
        from grafli.serve.server import DEFAULT_PORT, bind, create_app
        try:
            if self.port is None:
                # serve's port when it is free, else any: a `grafli serve`
                # running beside the app keeps its own.
                try:
                    self._sock = bind(self.host, DEFAULT_PORT)
                except OSError:
                    self._sock = bind(self.host, 0)
            else:
                self._sock = bind(self.host, self.port)
        except OSError as e:
            raise HostError(f"cannot listen on {self.host}:"
                            f"{self.port or DEFAULT_PORT}: {e}") from e
        self.port = self._sock.getsockname()[1]
        app = create_app(self.root, self.keys,
                         self._renderer or RenderWorker(self._theme),
                         self._log)
        self.hub = app.state.hub
        config = uvicorn.Config(app, log_level="warning", ws="auto",
                                lifespan="on", ws_max_size=1024 * 1024,
                                timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="grafli-host",
                                        daemon=True)
        self._thread.start()
        deadline = time.monotonic() + START_TIMEOUT_S
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self._close_socket()
                raise HostError("the board's server did not start")
            time.sleep(0.01)
        self._state = agents.write_state(self.host, self.port, self.keys.agent,
                                         self.root, self._where)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(
                self._server.serve(sockets=[self._sock]))
        finally:
            self._loop.close()

    def stop(self) -> None:
        """Leave the room, close every tab's and the agent's connection and
        remove the state file."""
        if self._state is not None:
            agents.remove_state(self._state)
            self._state = None
        if not self.running:
            self._close_socket()
            return
        try:
            self._submit(self._leave()).result(STOP_TIMEOUT_S)
        except Exception:
            pass
        self._server.should_exit = True
        self._thread.join(STOP_TIMEOUT_S)
        self._close_socket()

    def _close_socket(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def links(self, name: str) -> dict[str, str]:
        """The watch and edit links of board *name*, the way ``grafli
        serve`` prints them."""
        from grafli.serve.server import link
        return {"watch": link(self.host, self.port, name, self.keys.viewer),
                "edit": link(self.host, self.port, name, self.keys.editor)}

    # ── The app's seat ──

    def name_of(self, path: Path | None) -> str | None:
        """The name board *path* has here, or None when it is not served
        (outside the root, or not saved yet)."""
        if path is None:
            return None
        from grafli.serve.server import board_path
        name = board_name(self.root, Path(path))
        if name is None or board_path(self.root, name) is None:
            return None
        return name

    def present(self, path: Path | None) -> concurrent.futures.Future:
        """Present board *path*: the app leaves the room it was in and joins
        that board's, as its presenter; None, or a board not served here,
        leaves it on none. The future's result is the board's name, or
        None."""
        return self._submit(self._present(path))

    async def _present(self, path: Path | None) -> str | None:
        name = self.name_of(path)
        if name is not None and self._room is not None \
                and self._room.name == name:
            return name
        await self._leave()
        if name is None:
            return None
        from grafli.serve.room import Client
        client = Client(self._send, "presenter", APP_AUTHOR,
                        bucket=presence.Bucket(rate=1000, burst=1000))
        room = self.hub.room(Path(path).resolve(), name)
        self._room, self._client, self.board = room, client, name
        await room.join(client)
        await self.hub.arrived(room, client)
        if self.hub.open:
            await room.send_to(client, self.hub.work_message(client))
        return name

    async def _leave(self) -> None:
        room, client = self._room, self._client
        self._room = self._client = self.board = None
        if room is None or client is None:
            return
        await room.leave(client)
        await self.hub.departed(room)
        await self.hub.release(room)
        self._deliver({"t": "proposal", "proposal": None})

    async def _send(self, msg: dict) -> None:
        if msg.get("t") == "frame":
            return
        self._deliver(msg)

    # ── What the present link's tab asks ──

    def ask(self, text: str, about: str | None = None
            ) -> concurrent.futures.Future:
        """Send *text* to the agent, *about* the element with that id when
        given; answered like a tab's ``ask``."""
        from grafli.serve.server import _ask
        msg = {"t": "ask", "text": text}
        if about:
            msg["about"] = about
        return self._submit(self._handle(
            lambda room, client, send: _ask(self.hub, room, client, msg,
                                            send), catch_up=True))

    def settle(self, do: str) -> concurrent.futures.Future:
        """Take (*do* ``"take"``) or drop (``"drop"``) the agent's
        proposal."""
        from grafli.serve.server import _settle
        msg = {"t": "proposal", "do": do}
        return self._submit(self._handle(
            lambda room, client, send: _settle(room, client, msg, send)))

    def undo_agent(self) -> concurrent.futures.Future:
        """Take back the agent's last edit on the board; what changed since
        stays."""
        from grafli.serve.server import _undo_agent
        msg = {"t": "undo", "of": "agent"}
        return self._submit(self._handle(
            lambda room, client, send: _undo_agent(self.hub, room, client,
                                                   msg, send)))

    async def _handle(self, handler, catch_up: bool = False) -> dict:
        room, client = self._room, self._client
        if room is None or client is None:
            return {"t": "error", "message": "no board is hosted here; save "
                    "the board in the folder the app hosts"}
        if catch_up:
            # What the app saved a moment ago is the board the agent hears of.
            await room.catch_up()
        answers: list[dict] = []

        async def send(msg: dict) -> None:
            answers.append(msg)
        await handler(room, client, send)
        return answers[-1] if answers else {"t": "error",
                                            "message": "no answer"}

    def select(self, el_id: str | None) -> None:
        """What the app has selected: the agent reads it."""
        self._presence({"t": "select", "id": el_id})

    def view(self, x: float, y: float, w: float, h: float) -> None:
        """The app's camera, in board units: tabs following it go along."""
        self._presence({"t": "view", "x": x, "y": y, "w": w, "h": h})

    def _presence(self, msg: dict) -> None:
        async def run():
            if self._room is not None and self._client is not None:
                await self._room.presence(self._client, msg)
        if self.running:
            self._submit(run())

    def agent(self) -> dict | None:
        """The agent's seat as the tabs see it: ``{"name", "color",
        "present"}``, or None before any session connected."""
        return self.hub.agent_info() if self.hub is not None else None

    def _submit(self, coro) -> concurrent.futures.Future:
        if not self.running:
            coro.close()
            fut: concurrent.futures.Future = concurrent.futures.Future()
            fut.set_result({"t": "error",
                            "message": "the board is not hosted"})
            return fut
        return asyncio.run_coroutine_threadsafe(coro, self._loop)
