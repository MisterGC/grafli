"""The board's agent in grafli serve: a Claude Code session connects through
the ``grafli agent`` MCP bridge, the tabs show it by name, it reads, writes
and renders the board, a request pushed from the server reaches it as a
channel notification, and a dropped session shows as gone until one
connects again. The bridge runs as its own process speaking MCP on stdin
and stdout, as Claude Code runs it; the tabs are WebSocket clients."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli import skills  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from grafli.serve import mcp  # noqa: E402
from grafli.serve import server as srv  # noqa: E402
from tests.test_serve import BOARD, Served  # noqa: E402
from tests.test_serve_presence import Peer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── Unit: keys, names, the state file ──

def test_the_agent_key_differs_from_every_link_key_and_opens_no_tab():
    keys = srv.Keys()
    assert len({keys.viewer, keys.editor, keys.presenter, keys.agent}) == 4
    assert keys.role(keys.agent) is None
    assert keys.is_agent(keys.agent) and not keys.is_agent(keys.presenter)
    with pytest.raises(ValueError):
        srv.Keys("a", "b", "c", "a")


def test_the_agent_is_named_by_the_session_else_after_the_presenter():
    assert agents.agent_name("  Claude\n") == "Claude"
    assert agents.agent_name("", "Serein") == "Serein's agent"
    assert agents.agent_name(None) == "Agent"


def test_the_state_file_is_private_and_a_dead_run_is_skipped(tmp_path):
    path = agents.write_state("0.0.0.0", 7341, "secret", tmp_path, tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    found = agents.find_state(where=tmp_path)
    assert found["key"] == "secret" and found["port"] == 7341
    assert agents.local_host(found["host"]) == "127.0.0.1"
    dead = json.loads(path.read_text())
    dead.update(port=7342, pid=2 ** 22 + 12345)
    agents.state_path(7342, tmp_path).write_text(json.dumps(dead))
    assert agents.find_state(7342, tmp_path) is None
    assert agents.find_state(where=tmp_path)["port"] == 7341
    agents.remove_state(path)
    assert agents.find_state(where=tmp_path) is None


# ── Unit: what the bridge tells Claude Code ──

def _handle(msg):
    return asyncio.run(mcp.Bridge(lambda _m: None).handle(msg))


def test_the_bridge_declares_a_claude_code_channel_and_its_tools():
    got = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2026-07-28"}})["result"]
    assert got["capabilities"]["experimental"] == {"claude/channel": {}}
    # A revision it does not know is answered with the newest it speaks.
    assert got["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]
    assert 'source="grafli"' in got["instructions"]
    names = [t["name"] for t in _handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["connect", "disconnect", "read_board", "write_board",
                     "undo_board", "render_board", "authoring_guide"]
    prompt = _handle({"jsonrpc": "2.0", "id": 3, "method": "prompts/get",
                      "params": {"name": "connect",
                                 "arguments": {"name": "Claude"}}})["result"]
    assert "connect tool" in prompt["messages"][0]["content"]["text"]
    assert _handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert _handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]


def test_a_tool_called_before_connect_says_how_to_connect():
    got = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "read_board", "arguments": {}}})["result"]
    assert got["isError"] and "call connect" in got["content"][0]["text"]


# ── Unit: the skill's authoring guidance, from the bridge itself ──

def _guide(**args):
    return _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "authoring_guide",
                               "arguments": args}})["result"]


def test_the_instructions_point_the_session_at_the_authoring_guide():
    got = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {}})["result"]
    assert "`authoring_guide`" in got["instructions"]
    assert "nothing installed" in got["instructions"]
    tool = next(t for t in mcp.TOOLS if t["name"] == "authoring_guide")
    refs = tool["inputSchema"]["properties"]["reference"]["enum"]
    assert refs == list(skills.skill_references()) and "format.md" in refs


def test_the_guide_is_the_packaged_skill_core_and_names_its_references():
    got = _guide()
    assert not got.get("isError"), got
    text = got["content"][0]["text"]
    core = skills.skill_path().read_text(encoding="utf-8")
    body = core.split("\n---\n", 2)[2].lstrip("\n")
    assert text.endswith(body)
    # The loader's trigger header is left out; the preface maps the file
    # steps to the board's tools and names every reference file.
    assert "description: >" not in text and "name: grafli" not in text
    preface = text[:text.index(body)]
    for tool in ("read_board", "write_board", "render_board"):
        assert tool in preface
    for name in skills.skill_references():
        assert name in preface


def test_the_guide_returns_one_reference_file_and_refuses_an_unknown_one():
    for name, content in skills.skill_references().items():
        assert _guide(reference=name)["content"][0]["text"] == content
    got = _guide(reference="nope.md")
    assert got["isError"] and "format.md" in got["content"][0]["text"]


@pytest.mark.parametrize("reference", [["format.md"], {"name": "format.md"},
                                       5, True])
def test_a_reference_that_is_not_a_name_is_answered_with_an_error(reference):
    got = _guide(reference=reference)
    assert got["isError"]
    for name in skills.skill_references():
        assert name in got["content"][0]["text"]


# ── End to end: a server, the bridge as Claude Code runs it, tabs ──

class Session:
    """The ``grafli agent`` process a Claude Code session runs, driven over
    stdin and stdout the way Claude Code drives it."""

    def __init__(self, state_dir: Path, home: Path | None = None):
        env = dict(os.environ, GRAFLI_STATE_DIR=str(state_dir),
                   PYTHONPATH=str(REPO))
        if home is not None:
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "grafli.serve.mcp"], cwd=REPO, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.lines: queue.Queue = queue.Queue()
        self.notes: list[dict] = []
        threading.Thread(target=self._pump, daemon=True).start()
        self.next_id = 1
        init = self.call("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}})
        assert init["capabilities"]["experimental"] == {"claude/channel": {}}
        self.init = init
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(json.loads(line))

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()

    def call(self, method, params=None, timeout=30):
        req = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": req, "method": method,
                   "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            msg = self.lines.get(timeout=max(deadline - time.monotonic(), 0.01))
            if msg.get("id") == req:
                assert "error" not in msg, msg
                return msg["result"]
            self.notes.append(msg)

    def tool(self, tool, /, **args):
        return self.call("tools/call", {"name": tool, "arguments": args})

    def note(self, timeout=10):
        """The next notification the bridge sent to Claude Code."""
        if self.notes:
            return self.notes.pop(0)
        msg = self.lines.get(timeout=timeout)
        assert "id" not in msg, msg
        return msg

    def end(self):
        """The session ends: Claude Code closes the bridge's stdin."""
        self.proc.stdin.close()
        assert self.proc.wait(10) == 0

    def kill(self):
        self.proc.kill()
        self.proc.wait(10)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path_factory.mktemp("agent"))
    s.state_dir = tmp_path_factory.mktemp("state")
    s.state = agents.write_state("127.0.0.1", s.port, s.keys.agent, s.root,
                                 s.state_dir)
    yield s
    s.stop()


@pytest.fixture
def board(served, request):
    path = served.root / f"{request.node.name}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    return path


@pytest.fixture
def sessions(served):
    made = []

    def start(home=None):
        made.append(Session(served.state_dir, home))
        return made[-1]
    yield start
    for s in made:
        if s.proc.poll() is None:
            s.kill()


def _text(result):
    return result["content"][0]["text"]


def _agent_is(tab, pred):
    return tab.peers(lambda m: m.get("agent") is not None and pred(m["agent"]))


def _hub(served):
    return served.app.state.hub


def test_a_connected_session_shows_by_name_reads_writes_and_renders(
        served, board, sessions):
    name = board.stem
    presenter = Peer(served, name, served.keys.presenter, name="Serein")
    guest = Peer(served, name, served.keys.viewer)
    session = sessions()
    got = session.tool("connect")
    assert not got.get("isError"), got
    assert "Serein's agent" in _text(got) and f"'{name}'" in _text(got)
    for tab in (presenter, guest):
        seen = _agent_is(tab, lambda a: a["present"])["agent"]
        assert seen == {"name": "Serein's agent", "color": agents.AGENT_COLOR,
                        "present": True}

    presenter.post(t="select", id="b")
    presenter.post(t="view", x=-10, y=-20, w=800, h=600)
    time.sleep(0.2)
    read = session.tool("read_board")
    meta = json.loads(_text(read))
    assert meta["board"] == name and meta["selection"] == ["b"]
    assert meta["view"] == {"x": -10.0, "y": -20.0, "w": 800.0, "h": 600.0}
    assert read["content"][1]["text"] == board.read_text(encoding="utf-8")

    text = read["content"][1]["text"].replace('"B"', '"Billing"')
    wrote = json.loads(_text(session.tool("write_board",
                                          base_version=meta["version"],
                                          text=text)))
    assert wrote["conflicts"] == [] and wrote["version"] > meta["version"]
    assert '"Billing"' in board.read_text(encoding="utf-8")
    frame = guest.until(lambda m: m["t"] == "frame"
                        and m["version"] == wrote["version"])
    assert any(e.get("label") == "Billing" for e in frame["board"]["elements"])

    shot = session.tool("render_board")
    image = shot["content"][1]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    assert base64.b64decode(image["data"])[:8] == b"\x89PNG\r\n\x1a\n"
    presenter.close()
    guest.close()


def test_a_session_with_no_skill_installed_is_offered_the_guide_on_connect(
        served, board, sessions, tmp_path):
    # A home with no skill in it: what the session gets comes from the
    # bridge alone.
    assert not (tmp_path / ".claude").exists()
    session = sessions(home=tmp_path)
    assert "`authoring_guide`" in session.init["instructions"]
    listed = [t["name"] for t in session.call("tools/list")["tools"]]
    assert "authoring_guide" in listed
    got = session.tool("connect")
    assert not got.get("isError"), got
    assert "read authoring_guide" in _text(got)
    guide = _text(session.tool("authoring_guide"))
    core = skills.skill_path().read_text(encoding="utf-8")
    assert guide.endswith(core.split("\n---\n", 2)[2].lstrip("\n"))
    design = session.tool("authoring_guide", reference="design.md")
    assert _text(design) == skills.skill_references()["design.md"]
    session.end()


def test_a_write_against_an_old_version_keeps_what_others_changed(
        served, board, sessions):
    name = board.stem
    presenter = Peer(served, name, served.keys.presenter)
    session = sessions()
    session.tool("connect", name="Claude")
    meta = json.loads(_text(read := session.tool("read_board", board=name)))
    # The presenter renames A after the agent read the board.
    presenter.send({"t": "edit", "base": presenter.frames[-1]["version"],
                    "op": {"op": "rename", "id": "a", "label": "Gateway"}})
    text = read["content"][1]["text"].replace('"B"', '"Billing"')
    session.tool("write_board", base_version=meta["version"], text=text)
    saved = board.read_text(encoding="utf-8")
    assert '"Gateway"' in saved and '"Billing"' in saved
    stale = session.tool("write_board", base_version=-1, text=text)
    assert stale["isError"] and "read the board again" in _text(stale)
    presenter.close()


def test_a_text_that_holds_no_board_is_refused_and_the_file_stays(
        served, board, sessions):
    name = board.stem
    session = sessions()
    session.tool("connect")
    meta = json.loads(_text(session.tool("read_board", board=name)))
    before = board.read_bytes()
    got = session.tool("write_board", board=name,
                       base_version=meta["version"],
                       text="I added a cache between A and B.")
    assert got["isError"] and "no board elements" in _text(got)
    assert board.read_bytes() == before


def test_the_agent_writes_a_board_no_tab_is_on(served, board, sessions):
    name = board.stem
    session = sessions()
    session.tool("connect")
    # No tab on the board: each request opens a room and closes it again.
    assert board.resolve() not in _hub(served).rooms
    read = session.tool("read_board", board=name)
    meta = json.loads(_text(read))
    assert board.resolve() not in _hub(served).rooms
    text = read["content"][1]["text"].replace('"A"', '"Gateway"')
    got = session.tool("write_board", board=name,
                       base_version=meta["version"], text=text)
    assert not got.get("isError"), got
    wrote = json.loads(_text(got))
    assert wrote["conflicts"] == [] and wrote["version"] > meta["version"]
    assert '"Gateway"' in board.read_text(encoding="utf-8")


def test_a_request_pushed_from_the_board_reaches_the_session_as_a_channel(
        served, board, sessions):
    name = board.stem
    presenter = Peer(served, name, served.keys.presenter)
    session = sessions()
    session.tool("connect")
    _agent_is(presenter, lambda a: a["present"])
    hub = _hub(served)
    loop = hub.rooms[board.resolve()]._task.get_loop()
    sent = asyncio.run_coroutine_threadsafe(
        hub.ask_agent(name, "add a cache between A and B", "Anna"), loop)
    assert sent.result(10) is True
    note = session.note()
    assert note == {"jsonrpc": "2.0", "method": "notifications/claude/channel",
                    "params": {"content": "add a cache between A and B",
                               "meta": {"board": name, "asked_by": "Anna"}}}
    presenter.close()


def test_a_dropped_session_shows_as_gone_and_connecting_again_resumes(
        served, board, sessions):
    name = board.stem
    presenter = Peer(served, name, served.keys.presenter)
    first = sessions()
    first.tool("connect", name="Claude")
    _agent_is(presenter, lambda a: a["present"] and a["name"] == "Claude")

    # The session's process ends without a word: the tab shows it gone.
    first.kill()
    gone = _agent_is(presenter, lambda a: not a["present"])["agent"]
    assert gone["name"] == "Claude"
    hub = _hub(served)
    loop = hub.rooms[board.resolve()]._task.get_loop()
    # Nothing waits unseen for a session that is gone.
    assert asyncio.run_coroutine_threadsafe(
        hub.ask_agent(name, "anyone?", "Anna"), loop).result(10) is False
    # A tab that comes now sees the agent gone, too.
    late = Peer(served, name, served.keys.viewer)
    joined = [m for m in late.seen if m["t"] == "peers"][-1]
    assert joined["agent"] == {"name": "Claude", "color": agents.AGENT_COLOR,
                               "present": False}

    # Another session connects: present again, and requests reach it.
    second = sessions()
    second.tool("connect", name="Claude")
    _agent_is(presenter, lambda a: a["present"])
    _agent_is(late, lambda a: a["present"])
    assert asyncio.run_coroutine_threadsafe(
        hub.ask_agent(name, "add a cache", "Anna"), loop).result(10) is True
    assert second.note()["params"]["content"] == "add a cache"
    assert json.loads(_text(second.tool("read_board")))["board"] == name

    # The session ends the way Claude Code ends it: stdin closes.
    second.end()
    _agent_is(presenter, lambda a: not a["present"])
    presenter.close()
    late.close()


def test_a_second_session_takes_the_seat_and_the_first_is_told(
        served, board, sessions):
    name = board.stem
    presenter = Peer(served, name, served.keys.presenter)
    first, second = sessions(), sessions()
    first.tool("connect", name="One")
    _agent_is(presenter, lambda a: a["present"] and a["name"] == "One")
    second.tool("connect", name="Two")
    _agent_is(presenter, lambda a: a["present"] and a["name"] == "Two")
    deadline = time.monotonic() + 10
    while True:
        got = first.tool("read_board")
        if got.get("isError") or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert got["isError"] and "another session took" in _text(got)
    # The first one leaving does not take the second one's seat away.
    first.tool("disconnect")
    assert not second.tool("read_board").get("isError")
    seat = _hub(served).seat
    assert seat.present and seat.name == "Two"
    presenter.close()


def test_a_session_without_the_agent_key_gets_no_seat(served, board):
    import websockets.sync.client as ws_sync
    with ws_sync.connect(f"ws://127.0.0.1:{served.port}/agent") as ws:
        ws.send(json.dumps({"t": "hello", "key": served.keys.presenter}))
        with pytest.raises(Exception):
            ws.recv(timeout=5)
        assert ws.close_code == srv.CLOSE_BAD_KEY
