"""``grafli agent``: the MCP server through which a Claude Code session the
presenter already runs becomes the board's agent.

Claude Code starts this process itself, as one of the session's MCP servers
over stdio (``claude mcp add -s user grafli -- grafli agent``); grafli
never starts a Claude Code session. The process does nothing until the
presenter asks the session to connect (``/mcp__grafli__connect``, or the
``connect`` tool): then it reads the running ``grafli serve``'s state file
and opens ``WS /agent`` with that run's agent key (``grafli.serve.agent``).

How a request pushed from a tab reaches the open session: this server
declares Claude Code's ``claude/channel`` capability and turns each
``request`` the server pushes into a ``notifications/claude/channel``
notification, which Claude Code puts into the running conversation as a
``<channel source="grafli" board="…" asked_by="…">`` turn. Claude Code
registers a channel only for a stdio server it was told to load as one: a
session started with ``claude --dangerously-load-development-channels
server:grafli``. In any other session the tools still work and pushed
requests are dropped by Claude Code, so ``connect`` says whether the
session can hear them only as far as this side can tell (it cannot).

The JSON-RPC here is the small part of MCP a stdio server needs:
``initialize``, ``ping``, ``tools/list``, ``tools/call``, ``prompts/list``
and ``prompts/get``; one JSON message per line. It answers with protocol
revision ``2025-06-18`` at the newest: Claude Code's docs say a channel
server on revision ``2026-07-28`` cannot deliver channel messages, and that
``MCP_PROTOCOL_NEGOTIATION=legacy`` in the session's environment avoids it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from grafli.serve import agent as agents

SERVER_NAME = "grafli"
# Newest first; a client asking for another revision gets the first.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
CONNECT_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 120

INSTRUCTIONS = """\
grafli: this session can be the agent of a live grafli board that the user \
presents with `grafli serve`. Nothing happens until the user asks you to \
connect: then call the `connect` tool. While connected, the board's tabs \
show you by name as present; read the board with `read_board` (its text, \
version, the presenter's selection and view), change it with `write_board` \
(the whole text, against the version you read; others' changes since are \
merged in), and look at it with `render_board`. Your edit lands at once and \
glows on the board with your name; one that changes more than 5 elements \
waits as a proposal the presenter takes or drops, so say in `about` what it \
does. `undo_board` takes back your last edit. Requests from people on the \
board arrive as <channel source="grafli" board="..." asked_by="...">the \
request</channel>: act on them on that board with read_board and \
write_board, and keep your answer on the board, not only in chat. A request \
asked on one element carries about="<its id>" and about_label="<its \
label>": that element is what it is about. Whether \
the presenter took or dropped your proposal, or undid your edit, arrives \
the same way, as <channel source="grafli" board="..." event="...">. \
`disconnect` leaves the seat; the tabs then show you as gone."""

_BOARD = {"type": "string",
          "description": "The board's name as in its link (/b/<name>); "
                         "leave out for the board the presenter is on"}

TOOLS = [
    {"name": "connect",
     "description": "Connect this session to the running `grafli serve` as "
                    "its boards' agent; the tabs show the agent present by "
                    "name. Connecting again (after a drop, or from another "
                    "session) takes the seat over.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string",
                  "description": "The name the tabs show; default "
                                 "\"<presenter>'s agent\""},
         "port": {"type": "integer",
                  "description": "The port of the grafli serve to join, "
                                 "when several run; default the latest"}}}},
    {"name": "disconnect",
     "description": "Leave the agent's seat; the tabs show the agent as gone.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_board",
     "description": "The board's text as on screen now, its version, what "
                    "the presenter selected and the presenter's view "
                    "(x, y, w, h in board units).",
     "inputSchema": {"type": "object", "properties": {"board": _BOARD}}},
    {"name": "write_board",
     "description": "Write the whole board text, changed from the version "
                    "you read; it is merged into the file the way every "
                    "tab's edit is, so others' changes since stay, and the "
                    "tabs show it at once, the elements it changed glowing "
                    "with your name. A change of more than 5 elements is "
                    "not written: it waits on the board as a proposal the "
                    "presenter takes (Enter) or drops (x), and you hear "
                    "which. Returns the new version (or the proposal), "
                    "what changed and any conflicts.",
     "inputSchema": {"type": "object", "required": ["base_version", "text"],
                     "properties": {
                         "base_version": {"type": "integer",
                                          "description": "The version "
                                          "read_board returned"},
                         "text": {"type": "string",
                                  "description": "The whole .grafli text"},
                         "about": {"type": "string",
                                   "description": "What the change does, in "
                                   "a few words (\"split Payments\"); the "
                                   "board shows it with a proposal"},
                         "board": _BOARD}}},
    {"name": "undo_board",
     "description": "Take back your last edit on the board; what others "
                    "changed since stays. Returns the new version and any "
                    "conflicts.",
     "inputSchema": {"type": "object", "properties": {"board": _BOARD}}},
    {"name": "render_board",
     "description": "The board drawn as a PNG, as the tabs show it, so you "
                    "can see what you wrote.",
     "inputSchema": {"type": "object", "properties": {"board": _BOARD}}},
]

PROMPTS = [
    {"name": "connect",
     "description": "Make this session the agent of the boards on the "
                    "running grafli serve",
     "arguments": [{"name": "name", "required": False,
                    "description": "The name the tabs show"}]},
]


class NotConnected(Exception):
    pass


class Bridge:
    """This session's link to a ``grafli serve`` run, and the JSON-RPC it
    speaks to Claude Code."""

    def __init__(self, write, port: int | None = None):
        self.write = write            # write(dict): one message to Claude Code
        self.port = port
        self.ws = None
        self.name = ""
        self.where = ""
        self.gone_why = ""
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next = 1

    # ── The link to grafli serve ──

    @property
    def connected(self) -> bool:
        return self.ws is not None

    async def connect(self, name: str = "", port: int | None = None) -> dict:
        import websockets
        state = agents.find_state(port or self.port)
        if state is None:
            raise NotConnected(
                "no grafli serve is running for this user"
                + (f" on port {port or self.port}" if port or self.port else "")
                + "; start one with `grafli serve <dir>`")
        await self.disconnect()
        host = agents.local_host(state["host"])
        shown = f"[{host}]" if ":" in host else host
        url = f"ws://{shown}:{state['port']}/agent"
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, max_size=None), CONNECT_TIMEOUT_S)
            await ws.send(json.dumps({"t": "hello", "key": state["key"],
                                      "name": name}))
            welcome = json.loads(await asyncio.wait_for(ws.recv(),
                                                        CONNECT_TIMEOUT_S))
        except Exception as e:
            raise NotConnected(f"cannot reach grafli serve at {url}: "
                               f"{type(e).__name__}: {e}") from e
        if welcome.get("t") != "welcome":
            await ws.close()
            raise NotConnected("grafli serve refused this session")
        self.ws, self.name, self.gone_why = ws, welcome["name"], ""
        self.where = f"{state['root']} on {host}:{state['port']}"
        self._reader = asyncio.create_task(self._read(ws))
        return welcome

    async def disconnect(self) -> None:
        ws, self.ws = self.ws, None
        if ws is not None:
            await ws.close()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        self._fail("disconnected")

    def _fail(self, why: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(NotConnected(why))
        self._pending.clear()

    async def _read(self, ws) -> None:
        why = "grafli serve went away"
        try:
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("t")
                if kind in ("ack", "error"):
                    fut = self._pending.pop(msg.get("id"), None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif kind == "request":
                    self.push(msg)
                elif kind == "notice":
                    self.push_notice(msg)
                elif kind == "replaced":
                    why = (f"another session took the agent's seat "
                           f"({msg.get('by')})")
        except Exception:
            pass
        if self.ws is ws:
            self.ws = None
            self.gone_why = why
            self._fail(why)

    async def ask(self, msg: dict) -> dict:
        """Send one request to grafli serve; its ack, or raises."""
        if self.ws is None:
            raise NotConnected(self._not_connected())
        req_id = self._next
        self._next += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self.ws.send(json.dumps({**msg, "id": req_id}))
            answer = await asyncio.wait_for(fut, REQUEST_TIMEOUT_S)
        except NotConnected:
            raise
        except Exception as e:
            self._pending.pop(req_id, None)
            raise NotConnected(f"{type(e).__name__}: {e}") from e
        if answer["t"] == "error":
            raise ValueError(answer.get("message", "refused"))
        return answer

    def _not_connected(self) -> str:
        why = f" ({self.gone_why})" if self.gone_why else ""
        return (f"not connected to grafli serve{why}; call connect "
                "(the user can also run /mcp__grafli__connect)")

    def push(self, msg: dict) -> None:
        """A request from a tab, into the conversation as a channel turn."""
        about = msg.get("about")
        about = about if isinstance(about, dict) else {}
        meta = {"board": str(msg.get("board") or ""),
                "asked_by": str(msg.get("from") or ""),
                "about": str(about.get("id") or ""),
                "about_label": str(about.get("label") or "")}
        self.write({"jsonrpc": "2.0", "method": "notifications/claude/channel",
                    "params": {"content": str(msg.get("text") or ""),
                               "meta": {k: v for k, v in meta.items() if v}}})

    def push_notice(self, msg: dict) -> None:
        """What the presenter did with this agent's edit, into the
        conversation as a channel turn."""
        meta = {"board": str(msg.get("board") or ""),
                "event": str(msg.get("event") or "")}
        self.write({"jsonrpc": "2.0", "method": "notifications/claude/channel",
                    "params": {"content": str(msg.get("text") or ""),
                               "meta": {k: v for k, v in meta.items() if v}}})

    # ── MCP ──

    async def handle(self, msg: dict) -> dict | None:
        """The answer to one JSON-RPC message from Claude Code, or None for
        a notification."""
        method, req_id = msg.get("method"), msg.get("id")
        if req_id is None:
            return None
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = await self._call(params.get("name"),
                                          params.get("arguments") or {})
            elif method == "prompts/list":
                result = {"prompts": PROMPTS}
            elif method == "prompts/get":
                result = self._prompt(params.get("name"),
                                      params.get("arguments") or {})
            else:
                return _error(req_id, -32601, f"no method {method}")
        except KeyError as e:
            return _error(req_id, -32602, str(e))
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _initialize(params: dict) -> dict:
        from grafli import __version__
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"protocolVersion": version,
                "capabilities": {"tools": {}, "prompts": {},
                                 "experimental": {"claude/channel": {}}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": INSTRUCTIONS}

    @staticmethod
    def _prompt(name, args: dict) -> dict:
        if name != "connect":
            raise KeyError(f"no prompt {name}")
        asked = args.get("name")
        how = (f'with name "{asked}"' if isinstance(asked, str) and asked
               else "with no name")
        return {"description": PROMPTS[0]["description"],
                "messages": [{"role": "user", "content": {
                    "type": "text",
                    "text": f"Call the grafli connect tool now, {how}. Then "
                            "say in one line which board the presenter is "
                            "on and that you are listening for requests "
                            "from the board."}}]}

    async def _call(self, name, args: dict) -> dict:
        try:
            if name == "connect":
                port = args.get("port")
                welcome = await self.connect(
                    args.get("name") if isinstance(args.get("name"), str) else "",
                    port if isinstance(port, int) else None)
                board = welcome.get("board")
                return _text(
                    f"Connected to grafli serve ({self.where}) as "
                    f"\"{self.name}\"; the tabs show you as present. "
                    + (f"The presenter is on board '{board}'. " if board
                       else "No presenter's tab is open yet. ")
                    + "Boards: " + (", ".join(welcome.get("boards") or [])
                                    or "(none listed)") + ". Requests from "
                    "the board arrive as <channel source=\"grafli\"> turns "
                    "when this session was started with "
                    "--dangerously-load-development-channels server:grafli.")
            if name == "disconnect":
                was = self.connected
                await self.disconnect()
                self.gone_why = "you disconnected"
                return _text("Disconnected; the tabs show the agent as gone."
                             if was else "Not connected.")
            if name == "read_board":
                got = await self.ask({"t": "read", "board": args.get("board")})
                meta = {k: got[k] for k in ("board", "version", "selection",
                                            "view", "proposal")}
                return {"content": [{"type": "text", "text": json.dumps(meta)},
                                    {"type": "text", "text": got["text"]}]}
            if name == "write_board":
                about = args.get("about")
                got = await self.ask({"t": "write", "board": args.get("board"),
                                      "base": args.get("base_version"),
                                      "text": args.get("text"),
                                      "about": about if isinstance(about, str)
                                      else ""})
                out = {k: got[k] for k in ("board", "version", "conflicts",
                                           "changes", "summary") if k in got}
                if got.get("proposed") is not None:
                    out["proposed"] = got["proposed"]
                    out["note"] = (
                        f"{got['changes']} changes are more than 5, so the "
                        "board shows them as a proposal and the file is "
                        "unchanged; the presenter takes it with Enter or "
                        "drops it with x, and you hear which"
                        + (" (it replaced your earlier proposal)"
                           if got.get("replaced") else ""))
                return _text(json.dumps(out))
            if name == "undo_board":
                got = await self.ask({"t": "undo", "board": args.get("board")})
                return _text(json.dumps({k: got[k] for k in
                                         ("board", "version", "conflicts")}))
            if name == "render_board":
                got = await self.ask({"t": "render",
                                      "board": args.get("board")})
                return {"content": [
                    {"type": "text", "text": json.dumps(
                        {k: got[k] for k in ("board", "version", "width",
                                             "height")})},
                    {"type": "image", "data": got["png"],
                     "mimeType": "image/png"}]}
        except NotConnected as e:
            return _text(str(e), error=True)
        except ValueError as e:
            return _text(str(e), error=True)
        return _text(f"no tool {name}", error=True)


def _text(text: str, error: bool = False) -> dict:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if error:
        out["isError"] = True
    return out


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


async def serve_stdio(port: int | None = None, stdin=None, stdout=None) -> int:
    """Speak MCP on *stdin*/*stdout* (binary streams) until stdin closes."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=64 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader),
                                 stdin)

    def write(msg: dict) -> None:
        stdout.write(json.dumps(msg, ensure_ascii=False).encode("utf-8")
                     + b"\n")
        stdout.flush()

    bridge = Bridge(write, port)
    tasks: set[asyncio.Task] = set()

    async def answer(msg: dict) -> None:
        reply = await bridge.handle(msg)
        if reply is not None:
            write(reply)

    try:
        while line := await reader.readline():
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                write(_error(None, -32700, "not JSON"))
                continue
            if not isinstance(msg, dict):
                continue
            # A slow tool call never holds up a ping.
            task = asyncio.create_task(answer(msg))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        # The session ended: the seat goes with it.
        await bridge.disconnect()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="grafli agent",
        description="The MCP server that makes a Claude Code session you "
                    "run the agent of your grafli serve boards. Claude Code "
                    "starts it; register it once with\n"
                    "  claude mcp add -s user grafli -- grafli agent\n"
                    "start the session with\n"
                    "  claude --dangerously-load-development-channels "
                    "server:grafli\n"
                    "so requests from the board reach it, and connect it "
                    "with /mcp__grafli__connect while grafli serve runs. "
                    "grafli never starts a session itself.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=None,
                        help="The port of the grafli serve to join (default: "
                             "the latest one running)")
    args = parser.parse_args(argv)
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("grafli agent needs the serve extra: pip install 'grafli[serve]'",
              file=sys.stderr)
        return 2
    # Answers go to a private copy of stdout; anything else printed lands on
    # stderr and cannot break a message line.
    out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        return asyncio.run(serve_stdio(args.port, sys.stdin.buffer, out))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
