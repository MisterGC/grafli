"""The board's agent in the desktop app, driven through the real window: the
``:`` line hosts the board, a Claude Code session connects through ``grafli
agent`` without ``grafli serve`` started by hand, the status bar names it, a
sentence comes back as an edit that glows, an element is asked about with
Shift+A, a big change is taken with Enter or dropped with x, Shift+U undoes
the agent's edit and leaves the app's own, and a guest's tab follows along.
The bridge runs as its own process, as Claude Code runs it."""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from grafli.app import MainWindow  # noqa: E402
from grafli.format import parse  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from tests.test_serve import BOARD  # noqa: E402
from tests.test_serve_agent import Session  # noqa: E402
from tests.test_serve_presence import Peer  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _wait(pred, timeout=20.0, what="it"):
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise TimeoutError(f"{what} did not happen in {timeout} s")
        QApplication.processEvents()
        time.sleep(0.01)


class App:
    def __init__(self, tmp_path: Path):
        _app()
        self.root = tmp_path / "boards"
        self.root.mkdir()
        self.path = self.root / "b.grafli"
        self.path.write_text(BOARD, encoding="utf-8")
        self.win = MainWindow(str(self.path), serve_port=0)
        self.win.show()
        self.view = self.win._view
        self.agent = self.win._agent
        self.sessions: list[Session] = []

    def toast(self) -> str:
        return self.view._toast_text

    def colon(self, text: str | None = None):
        """``:``, then *text* and Enter when given."""
        QTest.keyClicks(self.view, ":")
        assert self.agent.line.isVisible()
        if text is not None:
            self.type(text)

    def type(self, text: str):
        edit = self.agent.line.edit
        QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key.Key_Return)

    def session(self, name="Claude") -> Session:
        s = Session(Path(os.environ["GRAFLI_STATE_DIR"]))
        self.sessions.append(s)
        got = s.tool("connect", name=name)
        assert not got.get("isError"), got
        _wait(lambda: self.agent.seat and self.agent.seat["present"],
              what="the agent connecting")
        return s

    def select(self, el_id: str):
        self.view._scene.clearSelection()
        self.view._box_items[el_id].setSelected(True)

    def close(self):
        for s in self.sessions:
            if s.proc.poll() is None:
                s.kill()
        self.win._view._dirty = False
        self.win.close()


@pytest.fixture
def app(tmp_path):
    a = App(tmp_path)
    yield a
    a.close()


def _read(session):
    got = session.tool("read_board")
    return json.loads(got["content"][0]["text"]), got["content"][1]["text"]


def _write(session, base, text, **extra):
    got = session.tool("write_board", base_version=base, text=text, **extra)
    assert not got.get("isError"), got
    return json.loads(got["content"][0]["text"])


# ── Connecting, and none connected ──

def test_the_colon_line_hosts_the_board_and_says_no_agent_is_connected(app):
    assert app.agent.chip.text() == "✦ no agent connected"
    assert app.agent.host is None
    app.colon()
    # Hosted now: the state file a session's `grafli agent` looks for.
    found = agents.find_state()
    assert found and found["port"] == app.agent.host.port
    assert found["root"] == str(app.root.resolve())
    _wait(lambda: app.agent.board == "b")
    assert "no agent connected" in app.agent.line.where.text()
    app.type("add a cache between api and db")
    _wait(lambda: "No agent is connected" in app.toast(), what="the answer")
    assert "nothing was sent" in app.toast()
    # Nothing waits: a session connecting afterwards hears nothing of it.
    session = app.session()
    time.sleep(0.5)
    assert not session.notes and session.lines.empty()
    assert app.agent.chip.text() == "✦ Claude"
    assert app.path.read_text(encoding="utf-8") == BOARD
    session.end()
    _wait(lambda: app.agent.chip.text() == "✦ Claude · gone")


def test_stopping_turns_collection_back_on_and_the_board_hosts_again(app):
    assert gc.isenabled()
    app.colon()
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Escape)
    # While the app hosts, only its GUI thread collects garbage.
    assert not gc.isenabled()
    port = app.agent.host.port
    assert agents.find_state(port)["port"] == port
    session = app.session()
    assert app.agent.chip.text() == "✦ Claude"

    app.agent.stop()
    assert agents.find_state(port) is None
    assert gc.isenabled()
    assert app.agent.host is None
    assert app.agent.chip.text() == "✦ no agent connected"
    assert "Stopped hosting" in app.toast()

    # "Host this board" in the status bar's menu hosts it again, and a
    # session connects to the new run.
    app.agent.host_from_menu()
    assert app.agent.host is not None and not gc.isenabled()
    again = agents.find_state(app.agent.host.port)
    assert again and again["key"] == app.agent.host.keys.agent
    assert "Hosting boards/" in app.toast()
    _wait(lambda: app.agent.board == "b")
    session.end()
    app.session("Claude again")
    assert app.agent.chip.text() == "✦ Claude again"
    app.agent.stop(quiet=True)
    assert gc.isenabled()


def test_without_the_serve_extra_the_app_says_what_is_missing(app,
                                                              monkeypatch):
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    app.colon()
    assert "pip install 'grafli[serve]'" in app.toast()
    assert app.agent.host is None
    assert "not hosted" in app.agent.line.where.text()
    # A grafli line still works without it.
    app.type('box cache "Cache"')
    assert app.win.board.box_by_id("cache") is not None


# ── The ':' line: a grafli line is applied, plain language is asked ──

def test_a_grafli_line_is_applied_directly_and_undone_with_u(app):
    app.select("a")
    app.colon()
    QTest.keyClicks(app.agent.line.edit, 'box cache "Cache"')
    assert app.agent.line.where.text() == "grafli line → applied"
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Return)
    cache = app.win.board.box_by_id("cache")
    a = app.win.board.box_by_id("a")
    assert cache is not None and cache.y > a.y
    assert app.view._box_items["cache"].isSelected()
    app.colon('arrow cache -> b "fills"')
    assert {(x.from_id, x.to_id) for x in app.win.board.arrows} >= {
        ("cache", "b")}
    QTest.keyClick(app.view, Qt.Key.Key_U)
    QTest.keyClick(app.view, Qt.Key.Key_U)
    assert app.win.board.box_by_id("cache") is None
    # A line that does not fit the board leaves it as it was.
    app.colon('arrow x -> nowhere "no"')
    assert "no box, note or image" in app.toast()
    assert app.win.board.box_by_id("x") is None


def test_a_sentence_comes_back_as_an_edit_the_app_marks(app):
    app.colon()
    session = app.session()
    app.type("add a cache between api and db")
    note = session.note()
    assert note["params"]["content"] == "add a cache between api and db"
    assert note["params"]["meta"]["board"] == "b"
    _wait(lambda: app.agent.working(), what="the working line")
    assert app.agent.working() == ("✦ Claude is working on: add a cache "
                                   "between api and db")
    assert "Asked Claude" in app.toast()

    meta, text = _read(session)
    _write(session, meta["version"],
           text + '@ box cache "Cache" 120,160 120x60\n')
    _wait(lambda: app.agent.marked_ids() == ["cache"], what="the mark")
    assert app.win.board.box_by_id("cache").label == "Cache"
    assert "Claude: +1 box" in app.toast()
    _wait(lambda: app.agent.working() is None)


def test_shift_a_asks_about_the_selected_element(app):
    app.colon()
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Escape)
    session = app.session()
    app.select("a")
    QTest.keyClick(app.view, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier)
    assert app.agent.line.isVisible()
    assert app.agent.line.about == "a"
    assert app.agent.line.where.text() == "plain language → Claude"
    app.type("split this in two")
    meta = session.note()["params"]["meta"]
    assert meta["about"] == "a" and meta["about_label"] == "A"
    # Selected and in view: what the agent reads of the app.
    _wait(lambda: _read(session)[0]["selection"] == ["a"])
    assert _read(session)[0]["view"]


# ── The agent's big change and its undo ──

def test_a_proposal_is_taken_with_enter_or_dropped_with_x(app):
    app.colon()
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Escape)
    session = app.session()
    more = "".join(f'@ box n{i} "N{i}" {i * 140},300 120x60\n'
                   for i in range(6))
    meta, text = _read(session)
    _write(session, meta["version"], text + more, about="six boxes")
    _wait(lambda: app.agent.proposal is not None, what="the proposal")
    assert app.agent.banner().startswith("✦ Claude proposes 6 changes · "
                                         "six boxes")
    QTest.keyClick(app.view, Qt.Key.Key_X)
    _wait(lambda: app.agent.proposal is None)
    assert app.win.board.box_by_id("n0") is None
    assert app.path.read_text(encoding="utf-8") == BOARD

    meta, text = _read(session)
    _write(session, meta["version"], text + more)
    _wait(lambda: app.agent.proposal is not None)
    QTest.keyClick(app.view, Qt.Key.Key_Return)
    _wait(lambda: app.win.board.box_by_id("n5") is not None,
          what="the proposal taken")
    assert app.agent.proposal is None
    _wait(lambda: "n0" in app.agent.marked_ids())


def test_shift_u_undoes_the_agents_edit_and_leaves_the_apps_own(app):
    app.colon()
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Escape)
    session = app.session()
    meta, text = _read(session)
    _write(session, meta["version"],
           text + '@ box cache "Cache" 120,160 120x60\n')
    _wait(lambda: app.win.board.box_by_id("cache") is not None)
    # The app's own edit after it, not saved yet.
    app.view._push_undo()
    app.win.board.box_by_id("a").label = "Api"
    app.view._rebuild_scene()
    app.view.mark_dirty()
    QTest.keyClick(app.view, Qt.Key.Key_U, Qt.KeyboardModifier.ShiftModifier)
    _wait(lambda: app.win.board.box_by_id("cache") is None,
          what="the agent's edit undone")
    assert app.win.board.box_by_id("a").label == "Api"
    saved = parse(app.path.read_text(encoding="utf-8"))
    assert saved.box_by_id("cache") is None
    assert saved.box_by_id("a").label == "Api"
    assert "Undid Claude's edit" in app.toast()


# ── Guests in a browser tab ──

def test_a_guest_tab_sees_the_board_the_agents_edit_and_the_working_line(
        app):
    app.colon()
    QTest.keyClick(app.agent.line.edit, Qt.Key.Key_Escape)
    _wait(lambda: app.agent.board == "b")
    session = app.session()
    link = app.agent.host.links("b")["edit"]
    assert link.startswith(f"http://127.0.0.1:{app.agent.host.port}/b/b#k=")

    class Where:
        def url(self, name):
            return f"ws://127.0.0.1:{app.agent.host.port}/ws/{name}"
    guest = Peer(Where(), "b", link.split("#k=", 1)[1], name="Anna")
    # The app's own edit reaches the tab once the app saves it.
    app.view._push_undo()
    app.win.board.box_by_id("a").label = "Api"
    app.view._rebuild_scene()
    app.view.mark_dirty()
    app.win._flush_autosave()
    guest.until(lambda m: m["t"] == "frame" and any(
        e.get("label") == "Api" for e in m["board"]["elements"]))
    # The app leads: the guest's tab names the presenter, and the agent.
    peers = [m for m in guest.seen if m["t"] == "peers"][-1]
    assert peers["agent"]["name"] == "Claude" and peers["agent"]["present"]
    assert "Presenter" in [p["name"] for p in peers["peers"]]
    assert peers["lead"] is not None

    app.colon("add a cache between api and db")
    seen = guest.until(lambda m: m["t"] == "work" and m["work"])
    assert seen["work"]["text"] == "add a cache between api and db"
    session.note()
    meta, text = _read(session)
    _write(session, meta["version"],
           text + '@ box cache "Cache" 120,160 120x60\n')
    guest.until(lambda m: m["t"] == "marked" and m["ids"] == ["cache"])
    guest.until(lambda m: m["t"] == "work" and m["work"] is None)
    guest.close()
