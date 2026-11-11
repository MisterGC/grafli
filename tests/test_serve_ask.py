"""Asking the board's agent from a tab: an editor's or the presenter's
plain-language request goes to the connected Claude Code session as a
channel turn, about the element it was asked on when there is one, and the
session's answer comes back as an edit on the board. Without a session, or
with one that is gone, the tab is told so and nothing waits to be sent
later. The session is the ``grafli agent`` bridge driven over stdio, as
Claude Code drives it; the tabs are WebSocket clients."""

from __future__ import annotations

import json
import os
import queue
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from grafli.serve import server as srv  # noqa: E402
from tests.test_serve import Served  # noqa: E402
from tests.test_serve_agent import Session  # noqa: E402
from tests.test_serve_presence import Peer  # noqa: E402

BOARD = """#!grafli v1
@ box api "API" 0,0 160x80
@ box db "Ledger DB" 400,0 160x80
@ arrow api -> db "write"
"""


def _serve(tmp_path_factory, reveal=False):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path_factory.mktemp("ask-boards"), reveal=reveal)
    s.state_dir = tmp_path_factory.mktemp("ask-state")
    agents.write_state("127.0.0.1", s.port, s.keys.agent, s.root, s.state_dir)
    return s


@pytest.fixture
def fresh(tmp_path_factory):
    """A server no session has connected to yet."""
    s = _serve(tmp_path_factory)
    yield s
    s.stop()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = _serve(tmp_path_factory)
    yield s
    s.stop()


@pytest.fixture
def sessions():
    made = []

    def start(served):
        made.append(Session(served.state_dir))
        return made[-1]
    yield start
    for s in made:
        if s.proc.poll() is None:
            s.kill()


def _board(served, name):
    path = served.root / f"{name}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    return path


def _ask(tab, text, **extra):
    return tab.send({"t": "ask", "text": text, **extra})


def _agent_is(tab, pred):
    return tab.peers(lambda m: m.get("agent") is not None and pred(m["agent"]))


def _no_note(session, s=0.5):
    """Nothing reached the session in the next *s* seconds."""
    time.sleep(s)
    assert not session.notes
    with pytest.raises(queue.Empty):
        session.lines.get_nowait()


def test_with_no_agent_connected_the_tab_is_told_and_nothing_waits(
        fresh, sessions):
    path = _board(fresh, "none")
    before = path.read_bytes()
    guest = Peer(fresh, "none", fresh.keys.editor, name="Anna")
    got = _ask(guest, "add a cache between api and db")
    assert got["t"] == "error" and got["message"] == srv.NO_AGENT
    assert "no agent is connected" in got["message"]
    # A session that connects afterwards hears nothing of it.
    session = sessions(fresh)
    assert not session.tool("connect").get("isError")
    _agent_is(guest, lambda a: a["present"])
    _no_note(session)
    assert path.read_bytes() == before
    guest.close()


def test_a_plain_language_request_comes_back_as_an_edit_on_the_board(
        served, sessions):
    path = _board(served, "cache")
    guest = Peer(served, "cache", served.keys.editor, name="Anna")
    session = sessions(served)
    session.tool("connect", name="Claude")
    _agent_is(guest, lambda a: a["present"] and a["name"] == "Claude")

    got = _ask(guest, "add a cache between api and db")
    assert got == {"t": "ack", "id": got["id"], "agent": "Claude"}
    note = session.note()
    assert note == {"jsonrpc": "2.0", "method": "notifications/claude/channel",
                    "params": {"content": "add a cache between api and db",
                               "meta": {"board": "cache", "asked_by": "Anna"}}}

    # The session acts on it as the bridge's instructions ask: it reads the
    # board, writes it back with the cache, and the edit lands.
    read = session.tool("read_board", board="cache")
    meta = json.loads(read["content"][0]["text"])
    text = read["content"][1]["text"].replace(
        '@ arrow api -> db "write"\n',
        '@ box cache "Cache" 200,160 160x80\n'
        '@ arrow api -> cache "read"\n@ arrow cache -> db "miss"\n')
    wrote = json.loads(session.tool("write_board", board="cache",
                                    base_version=meta["version"],
                                    text=text)["content"][0]["text"])
    assert "proposed" not in wrote
    # The frame that shows it, and the mark that makes it glow by name.
    frame = guest.until(lambda m: m["t"] == "frame"
                        and m["version"] >= wrote["version"])
    assert any(e.get("label") == "Cache" for e in frame["board"]["elements"])
    marked = next((m for m in guest.seen if m["t"] == "marked"), None) \
        or guest.until(lambda m: m["t"] == "marked")
    assert marked["by"] == "Claude" and "cache" in marked["ids"]
    saved = parse(path.read_text(encoding="utf-8"))
    assert {b.id for b in saved.boxes} == {"api", "db", "cache"}
    assert {(a.from_id, a.to_id) for a in saved.arrows} == {
        ("api", "cache"), ("cache", "db")}
    guest.close()


def test_an_ask_on_a_selection_tells_the_agent_what_it_is_about(
        served, sessions):
    _board(served, "about")
    presenter = Peer(served, "about", served.keys.presenter, name="Serein")
    session = sessions(served)
    session.tool("connect", name="Claude")
    _agent_is(presenter, lambda a: a["present"])

    got = _ask(presenter, "split this by tenant", about="db")
    assert got["t"] == "ack"
    assert session.note()["params"] == {
        "content": "split this by tenant",
        "meta": {"board": "about", "asked_by": "Serein", "about": "db",
                 "about_label": "Ledger DB"}}
    # An arrow is named the way the tab names it.
    assert _ask(presenter, "label it", about="api->db")["t"] == "ack"
    meta = session.note()["params"]["meta"]
    assert meta["about"] == "api->db" and meta["about_label"] == "write"

    # What is not on the board is refused, and nothing reaches the session.
    got = _ask(presenter, "split this", about="nope")
    assert got["t"] == "error" and "not on the board" in got["message"]
    _no_note(session)
    presenter.close()


def test_a_watch_link_an_empty_and_an_overlong_request_are_refused(
        served, sessions):
    _board(served, "refused")
    viewer = Peer(served, "refused", served.keys.viewer)
    editor = Peer(served, "refused", served.keys.editor)
    session = sessions(served)
    session.tool("connect")
    _agent_is(viewer, lambda a: a["present"])
    got = _ask(viewer, "add a cache")
    assert got["t"] == "error" and "for watching" in got["message"]
    got = _ask(editor, "   ")
    assert got["t"] == "error" and "empty" in got["message"]
    got = _ask(editor, "x" * (srv.ASK_MAX_CHARS + 1))
    assert got["t"] == "error" and str(srv.ASK_MAX_CHARS) in got["message"]
    _no_note(session)
    viewer.close()
    editor.close()


def test_an_ask_while_the_agent_is_gone_says_so_and_is_not_kept(
        served, sessions):
    _board(served, "gone")
    guest = Peer(served, "gone", served.keys.editor, name="Anna")
    first = sessions(served)
    first.tool("connect", name="Claude")
    _agent_is(guest, lambda a: a["present"] and a["name"] == "Claude")
    first.kill()
    _agent_is(guest, lambda a: not a["present"])

    got = _ask(guest, "add a cache")
    assert got["t"] == "error"
    assert got["message"].startswith("Claude is gone, so nothing was sent")

    # Connected again: the request asked meanwhile is not delivered late,
    # and a new one gets through.
    second = sessions(served)
    second.tool("connect", name="Claude")
    _agent_is(guest, lambda a: a["present"])
    _no_note(second)
    assert _ask(guest, "add a cache, please")["t"] == "ack"
    assert second.note()["params"]["content"] == "add a cache, please"
    guest.close()


def test_in_reveal_mode_a_guest_cannot_ask_about_a_hidden_element(
        tmp_path_factory, sessions):
    served = _serve(tmp_path_factory, reveal=True)
    try:
        _board(served, "hidden")
        presenter = Peer(served, "hidden", served.keys.presenter)
        guest = Peer(served, "hidden", served.keys.editor)
        session = sessions(served)
        session.tool("connect")
        _agent_is(guest, lambda a: a["present"])
        # The board starts hidden: the guest is not told the box exists.
        got = _ask(guest, "what is this?", about="db")
        assert got["t"] == "error" and "not on the board" in got["message"]
        got = _ask(guest, "what is this?", about="api->db")
        assert got["t"] == "error" and "not on the board" in got["message"]
        _no_note(session)
        # The presenter sees it all, and may.
        assert _ask(presenter, "what is this?", about="db")["t"] == "ack"
        assert session.note()["params"]["meta"]["about"] == "db"
        # Revealed, the guest may too.
        assert presenter.send({"t": "reveal", "do": "show",
                               "el": "db"})["t"] == "ack"
        assert _ask(guest, "what is this?", about="db")["t"] == "ack"
        assert session.note()["params"]["meta"]["about_label"] == "Ledger DB"
        presenter.close()
        guest.close()
    finally:
        served.stop()
