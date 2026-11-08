"""Asking the board's agent in two browsers, in headless Chrome: with no
session connected the ':' line and the ask chip say there is no agent and
send nothing; with one connected, "add a cache between api and db" on the
presenter's ':' line reaches the session, whose answer comes back as an edit
glowing on both boards, and a guest's ask on a selected box tells the
session what it is about; once the session is gone, both say so. The
session is the ``grafli agent`` bridge driven over stdio, as Claude Code
drives it. Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from tests.test_serve_agent_tab import BOARD, browsers, sessions  # noqa: E402,F401
from tests.test_serve_presence_tab import open_tab  # noqa: E402
from tests.test_serve_tab import CHROME, Served  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

TOAST = "document.getElementById('toast').textContent"
ASK = "add a cache between api and db"


def _serve(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("ask-tab-boards"))
    s.state_dir = tmp_path_factory.mktemp("ask-tab-state")
    agents.write_state("127.0.0.1", s.port, s.keys.agent, s.root, s.state_dir)
    return s


@pytest.fixture
def served(tmp_path_factory):
    # Each test starts on a server no session has connected to.
    s = _serve(tmp_path_factory)
    yield s
    s.stop()


def _open(browsers, served, name):
    presenter, guest = browsers
    path = served.root / f"{name}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    open_tab(presenter, served, name, "presenter")
    open_tab(guest, served, name, "editor")
    presenter.js("grafliLive.post({t: 'name', name: 'Serein'})")
    guest.js("grafliLive.post({t: 'name', name: 'Anna'})")
    presenter.wait("grafliPresence.peers().filter("
                   "(p) => p.name === 'Serein' || p.name === 'Anna').length === 2")
    return path


def _command(tab, text):
    tab.key(":", shift=True)
    tab.wait("grafliEdit.command()")
    tab.type(text)
    tab.wait("grafliEdit.route().text !== ''")
    return tab.js("grafliEdit.route()")


def test_with_no_agent_connected_the_line_and_the_chip_say_so(
        browsers, served):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = _open(browsers, served, "noagent")
    before = path.read_bytes()

    route = _command(presenter, ASK)
    assert route == {"text": "plain language: no agent connected", "to": "none"}
    if shots:
        presenter.screenshot(Path(shots) / "ask-1-presenter-no-agent-line.png")
    presenter.key("Enter")
    presenter.wait(f"{TOAST}.startsWith('No agent is connected, so nothing was sent')")
    assert presenter.js("grafliLive.pending()") == 0

    # The guest selects the ledger: the chip is there, dashed, and says so.
    guest.js("grafliPage.selectId('ledger')")
    guest.wait("grafliAsk.chip() !== null")
    chip = guest.js("grafliAsk.chip()")
    assert chip["off"] is True and chip["title"].startswith("No agent is connected")
    guest.click_element("ask")
    guest.wait(f"{TOAST}.startsWith('No agent is connected, so nothing is asked')")
    assert guest.js("grafliEdit.field()") is None
    guest.key("a")
    assert guest.js("grafliEdit.field()") is None
    if shots:
        guest.screenshot(Path(shots) / "ask-2-guest-no-agent-chip.png")
    assert path.read_bytes() == before


def test_plain_language_and_ask_reach_the_agent_and_come_back_as_an_edit(
        browsers, served, sessions):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = _open(browsers, served, "payments")
    session = sessions()
    assert not session.tool("connect").get("isError")
    for tab in (presenter, guest):
        tab.wait("grafliPresence.agentShown() === \"Serein's agent\"")

    # A grafli line is still applied; plain language goes to the agent.
    route = _command(presenter, '@ box q "Queue"')
    assert route == {"text": "grafli line → applied", "to": "board"}
    presenter.key("Escape")
    route = _command(presenter, ASK)
    assert route == {"text": "plain language → Serein's agent", "to": "agent"}
    if shots:
        presenter.screenshot(Path(shots) / "ask-3-presenter-line-to-agent.png")
    presenter.key("Enter")
    presenter.wait(f"{TOAST}.startsWith(\"Asked Serein's agent: “{ASK}”\")")
    note = session.note()
    assert note["params"] == {"content": ASK,
                              "meta": {"board": "payments", "asked_by": "Serein"}}

    # The session answers on the board: a cache between the gateway and the
    # ledger. It lands and glows in both tabs.
    got = session.tool("read_board")
    meta = json.loads(got["content"][0]["text"])
    text = got["content"][1]["text"] + (
        '@ box cache "Cache" 0,320 200x90\n'
        '@ arrow api -> cache "read"\n@ arrow cache -> ledger "miss"\n')
    wrote = json.loads(session.tool("write_board", base_version=meta["version"],
                                    text=text)["content"][0]["text"])
    assert "proposed" not in wrote
    for tab in (presenter, guest):
        tab.wait("grafliAgent.marked().includes('cache')")
        assert tab.js("grafliPage.current().elements.find("
                      "(e) => e.id === 'cache').label") == "Cache"
    saved = parse(path.read_text(encoding="utf-8"))
    assert "cache" in {b.id for b in saved.boxes}
    assert {("api", "cache"), ("cache", "ledger")} <= {
        (a.from_id, a.to_id) for a in saved.arrows}
    if shots:
        presenter.screenshot(Path(shots) / "ask-4-presenter-answered.png")
        guest.screenshot(Path(shots) / "ask-4-guest-answered.png")

    # The guest asks about the ledger with the chip: the session hears what
    # the request is about.
    guest.js("grafliPage.selectId('ledger')")
    guest.wait("grafliAsk.chip() !== null && !grafliAsk.chip().off")
    guest.click_element("ask")
    guest.wait("grafliEdit.field() !== null")
    assert guest.js("document.getElementById('live-field').placeholder") == (
        "Ask Serein's agent about 'Ledger DB' · Enter sends, Esc closes")
    guest.type("split this by tenant")
    if shots:
        guest.screenshot(Path(shots) / "ask-5-guest-asks-about-ledger.png")
    guest.key("Enter")
    guest.wait(f"{TOAST}.startsWith(\"Asked Serein's agent\")")
    assert session.note()["params"] == {
        "content": "split this by tenant",
        "meta": {"board": "payments", "asked_by": "Anna", "about": "ledger",
                 "about_label": "Ledger DB"}}
    # The a key does the same.
    guest.key("a")
    guest.wait("grafliEdit.field() !== null")
    guest.key("Escape")
    assert guest.js("grafliEdit.field()") is None

    # The session goes: the line and the chip say so, and nothing is sent.
    session.kill()
    for tab in (presenter, guest):
        tab.wait("grafliPresence.agentShown() === \"Serein's agent · gone\"")
    guest.wait("grafliAsk.chip() !== null && grafliAsk.chip().off")
    route = _command(presenter, ASK)
    assert route == {"text": "plain language: Serein's agent is gone",
                     "to": "none"}
    presenter.key("Enter")
    presenter.wait(f"{TOAST}.startsWith(\"Serein's agent is gone, so nothing was sent\")")
    guest.click_element("ask")
    guest.wait(f"{TOAST}.startsWith(\"Serein's agent is gone, so nothing is asked\")")


def test_the_open_line_says_where_its_text_goes_as_the_agent_comes_and_goes(
        browsers, served, sessions):
    presenter, _guest = browsers
    _open(browsers, served, "follows")
    route = _command(presenter, ASK)
    assert route == {"text": "plain language: no agent connected", "to": "none"}

    # Nothing typed after this: the line follows the agent on its own.
    session = sessions()
    assert not session.tool("connect").get("isError")
    presenter.wait("grafliEdit.route().text === \"plain language → Serein's agent\""
                   " && grafliEdit.route().to === 'agent'")
    session.kill()
    presenter.wait("grafliEdit.route().text === "
                   "\"plain language: Serein's agent is gone\""
                   " && grafliEdit.route().to === 'none'")
    presenter.key("Escape")
