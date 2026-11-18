"""``grafli serve`` hosted inside the desktop app (``grafli.serve.host``): a
Claude Code session connects through ``grafli agent`` by the state file the
app writes, the app is the presenter of its board's room — it asks, takes or
drops a proposal and undoes the agent's last edit — and a guest's tab sees
the same board, the agent's edits and the working line. The bridge runs as
its own process, as Claude Code runs it; no Qt here."""

from __future__ import annotations

import json
import os
import queue
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from grafli.serve import server as srv  # noqa: E402
from grafli.serve.host import Host, HostError, missing_extra  # noqa: E402
from tests.test_serve import BOARD  # noqa: E402
from tests.test_serve_agent import Session  # noqa: E402
from tests.test_serve_presence import Peer  # noqa: E402


class Heard:
    """What the app's seat was told, in order."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.seen: list[dict] = []

    def __call__(self, msg):
        self.q.put(msg)

    def until(self, pred, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(
                    f"no such message; got {[m['t'] for m in self.seen]}")
            try:
                msg = self.q.get(timeout=left)
            except queue.Empty:
                continue
            self.seen.append(msg)
            if pred(msg):
                return msg


class Hosted:
    def __init__(self, root: Path, state: Path):
        self.root, self.state_dir = root, state
        self.heard = Heard()
        self.host = Host(root, self.heard, port=0, state_where=state)
        self.host.start()
        self.port = self.host.port
        self.keys = self.host.keys

    def url(self, name):
        return f"ws://127.0.0.1:{self.port}/ws/{name}"


@pytest.fixture
def hosted(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = tmp_path / "boards"
    root.mkdir()
    path = root / "b.grafli"
    path.write_text(BOARD, encoding="utf-8")
    h = Hosted(root, tmp_path / "state")
    h.path = path
    assert h.host.present(path).result(30) == "b"
    made: list[Session] = []

    def session():
        made.append(Session(h.state_dir))
        return made[-1]
    h.session = session
    yield h
    for s in made:
        if s.proc.poll() is None:
            s.kill()
    h.host.stop()


def _seat(hosted, pred):
    return hosted.heard.until(lambda m: m["t"] == "peers"
                              and m.get("agent") is not None
                              and pred(m["agent"]))


def _read(session):
    got = session.tool("read_board")
    return json.loads(got["content"][0]["text"]), got["content"][1]["text"]


def _write(session, base, text, **extra):
    got = session.tool("write_board", base_version=base, text=text, **extra)
    assert not got.get("isError"), got
    return json.loads(got["content"][0]["text"])


# ── Starting: the extra, the port, the state file ──

def test_without_the_serve_extra_hosting_says_what_to_install(monkeypatch,
                                                              tmp_path):
    assert missing_extra() is None
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    why = missing_extra()
    assert "pip install 'grafli[serve]'" in why and "uvicorn" in why
    with pytest.raises(HostError, match=r"grafli\[serve\]"):
        Host(tmp_path, lambda _m: None).start()


def test_a_host_writes_the_state_file_a_session_finds_and_removes_it(
        tmp_path):
    state = tmp_path / "state"
    host = Host(tmp_path, lambda _m: None, port=0, state_where=state)
    host.start()
    try:
        found = agents.find_state(where=state)
        assert found["port"] == host.port
        assert found["key"] == host.keys.agent
        assert found["root"] == str(tmp_path.resolve())
        links = host.links("b")
        assert links["edit"].endswith(f"/b/b#k={host.keys.editor}")
        assert links["watch"].endswith(f"/b/b#k={host.keys.viewer}")
    finally:
        host.stop()
    assert agents.find_state(where=state) is None
    assert not host.running


def test_a_board_outside_the_root_or_unsaved_is_not_presented(hosted,
                                                              tmp_path):
    outside = tmp_path / "elsewhere.grafli"
    outside.write_text(BOARD, encoding="utf-8")
    assert hosted.host.present(outside).result(10) is None
    assert hosted.host.present(None).result(10) is None
    got = hosted.host.ask("add a cache").result(10)
    assert got["t"] == "error" and "no board is hosted" in got["message"]


# ── The agent: connected by name, or not at all ──

def test_with_no_agent_asking_says_so_and_nothing_waits(hosted):
    hello = hosted.heard.until(lambda m: m["t"] == "peers")
    assert hello["agent"] is None
    got = hosted.host.ask("add a cache between api and db").result(10)
    assert got == {"t": "error", "id": None, "message": srv.NO_AGENT}
    # A session connecting afterwards hears nothing of it.
    session = hosted.session()
    assert not session.tool("connect", name="Claude").get("isError")
    _seat(hosted, lambda a: a["present"] and a["name"] == "Claude")
    time.sleep(0.5)
    assert not session.notes and session.lines.empty()
    assert hosted.path.read_text(encoding="utf-8") == BOARD


def test_a_session_connects_without_grafli_serve_and_hears_the_app(hosted):
    session = hosted.session()
    got = session.tool("connect", name="Claude")
    text = got["content"][0]["text"]
    assert "Connected to grafli serve" in text
    assert "The presenter is on board 'b'" in text
    agent = _seat(hosted, lambda a: a["present"])["agent"]
    assert agent["name"] == "Claude"

    # What the app selected and its view are what the agent reads.
    hosted.host.select("api")
    hosted.host.view(-10, -20, 800, 600)
    deadline = time.monotonic() + 5
    while True:
        meta, _text = _read(session)
        if meta["selection"] == ["api"] and meta["view"]:
            break
        assert time.monotonic() < deadline, meta
        time.sleep(0.05)
    assert meta["view"] == {"x": -10, "y": -20, "w": 800, "h": 600}

    # The session ends: the app sees the agent gone.
    session.end()
    _seat(hosted, lambda a: not a["present"])


# ── Asking: a sentence, or about the selected element ──

def test_a_plain_sentence_comes_back_as_an_edit_marked_by_the_agent(hosted):
    session = hosted.session()
    session.tool("connect", name="Claude")
    _seat(hosted, lambda a: a["present"])
    guest = Peer(hosted, "b", hosted.keys.editor, name="Anna")

    got = hosted.host.ask("add a cache between api and db").result(10)
    assert got["t"] == "ack" and got["agent"] == "Claude"
    note = session.note()
    assert note["params"]["content"] == "add a cache between api and db"
    assert note["params"]["meta"] == {"board": "b", "asked_by": "Presenter"}
    work = hosted.heard.until(lambda m: m["t"] == "work" and m["work"])
    assert work["work"]["by"] == "Claude"
    assert work["work"]["text"] == "add a cache between api and db"
    # The guest's tab sees the working line too.
    seen = guest.until(lambda m: m["t"] == "work" and m["work"])
    assert seen["work"]["text"] == "add a cache between api and db"

    meta, text = _read(session)
    wrote = _write(session, meta["version"],
                   text + '@ box cache "Cache" 120,160 120x60\n')
    assert wrote["changes"] == 1 and "proposed" not in wrote
    marked = hosted.heard.until(lambda m: m["t"] == "marked")
    assert marked["by"] == "Claude" and marked["ids"] == ["cache"]
    assert not marked["undone"]
    hosted.heard.until(lambda m: m["t"] == "work" and m["work"] is None)
    saved = parse(hosted.path.read_text(encoding="utf-8"))
    assert "cache" in {b.id for b in saved.boxes}
    # The guest sees the same board, and the agent's mark on it.
    frame = guest.until(lambda m: m["t"] == "frame"
                        and m["version"] >= wrote["version"])
    assert any(e.get("label") == "Cache" for e in frame["board"]["elements"])
    guest.until(lambda m: m["t"] == "marked" and m["ids"] == ["cache"])
    guest.close()


def test_asking_about_an_element_sends_it_with_the_request(hosted):
    session = hosted.session()
    session.tool("connect", name="Claude")
    _seat(hosted, lambda a: a["present"])
    # A box the app saved a moment ago is on the board the agent hears of.
    hosted.path.write_text(BOARD + '@ box q "Queue" 0,200 120x60\n',
                           encoding="utf-8")
    got = hosted.host.ask("split this in two", about="q").result(10)
    assert got["t"] == "ack", got
    meta = session.note()["params"]["meta"]
    assert meta["about"] == "q" and meta["about_label"] == "Queue"
    gone = hosted.host.ask("and this", about="nope").result(10)
    assert gone["t"] == "error" and "not on the board" in gone["message"]


# ── A big change is a proposal; undoing the agent leaves mine ──

def test_a_big_change_waits_as_a_proposal_the_app_takes_or_drops(hosted):
    session = hosted.session()
    session.tool("connect", name="Claude")
    _seat(hosted, lambda a: a["present"])
    meta, text = _read(session)
    more = "".join(f'@ box n{i} "N{i}" {i * 140},300 120x60\n'
                   for i in range(6))
    wrote = _write(session, meta["version"], text + more, about="six boxes")
    assert wrote["proposed"]
    shown = hosted.heard.until(lambda m: m["t"] == "proposal"
                               and m["proposal"])["proposal"]
    assert shown["count"] == 6 and shown["about"] == "six boxes"
    assert {s["id"] for s in shown["added"]} == {f"n{i}" for i in range(6)}
    assert all(s["rect"] for s in shown["added"])
    assert hosted.path.read_text(encoding="utf-8") == BOARD

    dropped = hosted.host.settle("drop").result(10)
    assert dropped["t"] == "ack" and dropped["dropped"] == 6
    hosted.heard.until(lambda m: m["t"] == "proposal" and not m["proposal"])
    assert "dropped" in session.note()["params"]["meta"]["event"]
    assert hosted.path.read_text(encoding="utf-8") == BOARD

    meta, text = _read(session)
    _write(session, meta["version"], text + more)
    hosted.heard.until(lambda m: m["t"] == "proposal" and m["proposal"])
    taken = hosted.host.settle("take").result(10)
    assert taken["t"] == "ack" and taken["taken"] == 6
    saved = parse(hosted.path.read_text(encoding="utf-8"))
    assert {f"n{i}" for i in range(6)} <= {b.id for b in saved.boxes}


def test_undoing_the_agents_edit_leaves_the_apps_own_edits(hosted):
    session = hosted.session()
    session.tool("connect", name="Claude")
    _seat(hosted, lambda a: a["present"])
    meta, text = _read(session)
    _write(session, meta["version"],
           text + '@ box cache "Cache" 120,160 120x60\n')
    hosted.heard.until(lambda m: m["t"] == "marked")
    # The app's own edit after it, saved to the file as the app autosaves.
    mine = hosted.path.read_text(encoding="utf-8").replace('"A"', '"Api"')
    hosted.path.write_text(mine, encoding="utf-8")

    got = hosted.host.undo_agent().result(10)
    assert got["t"] == "ack" and got["undone"]
    saved = parse(hosted.path.read_text(encoding="utf-8"))
    assert "cache" not in {b.id for b in saved.boxes}
    assert saved.box_by_id("a").label == "Api"
    assert "undid your last edit" in session.note()["params"]["content"]
    again = hosted.host.undo_agent().result(10)
    assert again["t"] == "error" and "no edit" in again["message"]
