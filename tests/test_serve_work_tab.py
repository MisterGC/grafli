"""What the agent works on, in two browsers, in headless Chrome: a request
from the presenter's ':' line shows on both tabs as "✦ <agent> is working
on: <request>" until the agent's write lands; the line follows the agent as
it reads and renders the board; a request left unanswered past ``late_s``
says so; and the line goes once the session is gone. The session is the
``grafli agent`` bridge driven over stdio, as Claude Code drives it.
Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from tests.test_serve_agent_tab import browsers, sessions  # noqa: E402,F401
from tests.test_serve_ask_tab import ASK, _command, _open  # noqa: E402
from tests.test_serve_ask_tab import served  # noqa: E402,F401
from tests.test_serve_tab import CHROME  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

WORKING = "grafliAgent.working()"
HEAD = "✦ Serein's agent is working on: "


def _shows(tab, text):
    tab.wait(f"{WORKING} === {json.dumps(text)}")


def test_both_tabs_show_the_request_until_the_agents_write_lands(
        browsers, served, sessions):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    _open(browsers, served, "payments")
    session = sessions()
    assert not session.tool("connect").get("isError")
    for tab in (presenter, guest):
        tab.wait("grafliPresence.agentShown() === \"Serein's agent\"")
        assert tab.js(WORKING) is None

    _command(presenter, ASK)
    presenter.key("Enter")
    for tab in (presenter, guest):
        _shows(tab, HEAD + ASK)
    assert session.note()["params"]["content"] == ASK
    if shots:
        guest.screenshot(Path(shots) / "work-1-guest-working.png")

    got = session.tool("read_board")
    for tab in (presenter, guest):
        _shows(tab, HEAD + ASK + " · reading the board")
    if shots:
        presenter.screenshot(Path(shots) / "work-2-presenter-reading.png")
    assert not session.tool("render_board").get("isError")
    for tab in (presenter, guest):
        _shows(tab, HEAD + ASK + " · rendering the board")

    meta = json.loads(got["content"][0]["text"])
    text = got["content"][1]["text"] + '@ box cache "Cache" 0,320 200x90\n'
    session.tool("write_board", base_version=meta["version"], text=text)
    for tab in (presenter, guest):
        tab.wait(f"{WORKING} === null")
        assert tab.js("grafliAgent.marked().includes('cache')")


def test_an_unanswered_request_says_so_and_goes_with_the_session(
        browsers, served, sessions):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    served.app.state.hub.late_s = 1
    _open(browsers, served, "late")
    session = sessions()
    assert not session.tool("connect").get("isError")
    guest.wait("grafliPresence.agentShown() === \"Serein's agent\"")

    # The guest asks on the ledger with the chip.
    guest.js("grafliPage.selectId('ledger')")
    guest.wait("grafliAsk.chip() !== null && !grafliAsk.chip().off")
    guest.click_element("ask")
    guest.wait("grafliEdit.field() !== null")
    guest.type("split this by tenant")
    guest.key("Enter")
    late = "✦ Serein's agent has not answered in 1 second: split this by tenant"
    for tab in (presenter, guest):
        _shows(tab, late)
        assert tab.js("grafliAgent.late()") is True
    if shots:
        presenter.screenshot(Path(shots) / "work-3-presenter-late.png")

    session.kill()
    for tab in (presenter, guest):
        tab.wait("grafliPresence.agentShown() === \"Serein's agent · gone\"")
        tab.wait(f"{WORKING} === null")
