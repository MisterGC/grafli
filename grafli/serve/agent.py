"""The board's agent: a Claude Code session the presenter already runs.

grafli never starts a session. The session runs ``grafli agent`` as one of
its MCP servers (``grafli.serve.mcp``, over stdio); when the presenter asks
it to connect, that bridge opens ``WS /agent`` on the running ``grafli
serve`` with the run's agent key, which it reads from the run's state file
(``serve-<port>.json`` in ``state_dir()``, readable by this user only). The
key is never part of a link, so no tab can take the agent's seat.

Over ``WS /agent`` the bridge sends ``{"t": "hello", "key", "name"}`` first
and gets ``{"t": "welcome", "name", "boards", "board"}``; then each of its
requests carries an ``id`` and is answered with ``ack`` or ``error``:

* ``{"t": "read", "board"}`` → ``{"board", "version", "text", "selection",
  "view"}``: the text on screen now, what the presenter selected and the
  presenter's camera (``None`` when the presenter is elsewhere);
* ``{"t": "write", "board", "base", "text", "about"}`` → ``{"version",
  "conflicts", "changes", "summary"}``: the whole board as the agent wrote
  it, merged into the file against version *base*, the way a tab's edit is;
  the tabs mark what it changed. A change of more than
  ``changes.PROPOSE_OVER`` elements is held as a proposal instead, which the
  presenter takes or drops: ``{"proposed": its id, "changes", "summary",
  "version"}``, and *about* (a few words) says on the board what it does;
* ``{"t": "undo", "board"}`` → ``{"version", "conflicts"}``: the agent's
  own last edit on the board taken back, what others changed since staying;
* ``{"t": "render", "board"}`` → ``{"board", "version", "png", "width",
  "height"}``: the board drawn as a PNG (base64), so the agent sees it.

``board`` may be left out: it is then the presenter's board, or the only
one. The server pushes ``{"t": "request", "board", "text", "from",
"about"}`` for a plain-language request from a tab (*about* the element
``{"id", "label"}`` it was asked on, or None), ``{"t": "notice", "board", "text",
"event"}`` when the presenter took or dropped its proposal or undid its
edit (*event* ``taken``, ``dropped`` or ``undone``), and ``{"t":
"replaced", "by"}`` when another session took the seat.

Every tab sees the seat in its ``peers`` message as ``agent``: ``None``
before any session connected, else ``{"name", "color", "present"}``;
``present`` turns false when the session drops (its process ends, or it
disconnects) and true again when the same or another session connects.

While a request from a tab waits for its answer — the agent's next write,
proposal or undo — every tab gets ``{"t": "work", "work": {"by", "color",
"board", "text", "from", "doing", "late", "late_after", "more"}}``: the
oldest open request (*text* None for a tab that may not see it), what the
agent does as far as the server sees it (*doing* ``"reading the board"``,
``"rendering the board"`` or ``""``), whether ``late_after`` seconds passed
without an answer, and how many more requests wait behind it. ``"work":
None`` once none is open, and when the session is gone. No Qt.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from grafli.serve.presence import clean_name

# Purple is the agent's alone; the presenter and the guests never get it.
AGENT_COLOR = "#7048e8"
# How long a request waits for its answer before the tabs say it is late.
LATE_S = 120
# What the agent is doing on a request, as far as the server sees it.
READING = "reading the board"
RENDERING = "rendering the board"


def state_dir() -> Path:
    """Where a ``grafli serve`` run leaves its state file for the bridge."""
    env = os.environ.get("GRAFLI_STATE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "grafli"


def state_path(port: int, where: Path | None = None) -> Path:
    return (where or state_dir()) / f"serve-{port}.json"


def write_state(host: str, port: int, key: str, root: Path,
                where: Path | None = None) -> Path:
    """Record a run for the bridge: where it listens and its agent key. The
    file is readable by this user only."""
    path = state_path(port, where)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    data = {"host": host, "port": port, "key": key, "root": str(root),
            "pid": os.getpid(), "started": time.time()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.chmod(path, 0o600)
    return path


def remove_state(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def find_state(port: int | None = None, where: Path | None = None) -> dict | None:
    """The run the bridge connects to: the one on *port*, else the latest
    one still running; None when there is none."""
    where = where or state_dir()
    paths = [state_path(port, where)] if port else sorted(
        where.glob("serve-*.json"))
    found = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and _alive(data.get("pid")):
            found.append(data)
    return max(found, key=lambda d: d.get("started", 0), default=None)


def local_host(host: str) -> str:
    """The address the bridge, on the same machine, dials for *host*."""
    if host in ("0.0.0.0", ""):
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


@dataclass(eq=False)
class AgentConn:
    """One bridge's connection: how to reach it and how to drop it."""
    send: Callable[[dict], Awaitable[None]]
    close: Callable[[], Awaitable[None]]
    name: str = ""


@dataclass
class Seat:
    """The agent as the tabs see it; it stays after a drop, as gone."""
    name: str
    conn: AgentConn | None = None
    color: str = AGENT_COLOR
    since: float = field(default_factory=time.time)

    @property
    def present(self) -> bool:
        return self.conn is not None

    def info(self) -> dict:
        return {"name": self.name, "color": self.color,
                "present": self.present}


@dataclass
class Request:
    """A request a tab sent the agent, open until its answer lands.
    *private*: the presenter asked it while the board hid something from
    the guests, so only the presenter's tabs see its text."""
    board: str
    text: str
    asked_by: str
    private: bool = False
    since: float = field(default_factory=time.monotonic)


def author(name: str) -> str:
    """Whose edits the agent *name*'s are in a board's undo history."""
    return f"agent:{name}"


def agent_name(asked, presenter_name: str = "") -> str:
    """The name the tabs show: what the session asked for, else the
    presenter's name with "'s agent", else "Agent"."""
    name = clean_name(asked)
    if name:
        return name
    if presenter_name:
        return clean_name(f"{presenter_name}'s agent")
    return "Agent"
