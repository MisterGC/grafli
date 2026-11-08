"""The board's agent in two browsers, in headless Chrome: the presenter's
tab and a guest's tab show a connected Claude Code session's agent by name,
show it gone when the session's process ends, and present again when a
session connects again; what the presenter selects with the keys is what the
agent reads. The session is the ``grafli agent`` bridge driven over stdio,
as Claude Code drives it. Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.serve import agent as agents  # noqa: E402
from tests.test_serve_agent import Session  # noqa: E402
from tests.test_serve_presence_tab import Browser, open_tab  # noqa: E402
from tests.test_serve_tab import CHROME, Served  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

BOARD = """#!grafli v1
@ box api "API gateway" 0,0 200x90
@ box pay "Payments" 420,0 200x90
@ box ledger "Ledger DB" 420,320 200x90
@ arrow api -> pay "charge"
@ arrow pay -> ledger "write"
"""


@pytest.fixture(scope="module")
def browsers():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    presenter = Browser(1400, 900)
    guest = Browser(1100, 860)
    yield presenter, guest
    presenter.close()
    guest.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("agent-boards"))
    s.state_dir = tmp_path_factory.mktemp("agent-state")
    agents.write_state("127.0.0.1", s.port, s.keys.agent, s.root, s.state_dir)
    yield s
    s.stop()


@pytest.fixture
def sessions(served):
    made = []

    def start():
        made.append(Session(served.state_dir))
        return made[-1]
    yield start
    for s in made:
        if s.proc.poll() is None:
            s.kill()


AGENT = "grafliPresence.agentShown()"


def test_the_tabs_show_the_agent_by_name_gone_and_back(browsers, served,
                                                       sessions):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    (served.root / "payments.grafli").write_text(BOARD, encoding="utf-8")
    open_tab(presenter, served, "payments", "presenter")
    open_tab(guest, served, "payments", "viewer")
    presenter.js("grafliLive.post({t: 'name', name: 'Serein'})")
    presenter.wait("grafliPresence.peers().some((p) => p.name === 'Serein')")
    # No session connected yet: no agent in the bar.
    assert presenter.js(AGENT) is None and guest.js(AGENT) is None

    # The presenter selects Payments by its jump label.
    presenter.key("f")
    presenter.wait("grafliEdit.jump() !== null")
    presenter.keys(presenter.js("grafliEdit.labelOf('pay')"))
    presenter.wait("grafliPage.selected() === 'pay'")

    first = sessions()
    got = first.tool("connect")
    assert not got.get("isError"), got
    for tab in (presenter, guest):
        tab.wait(f"{AGENT} === \"Serein's agent\"")
    guest.wait("document.getElementById('toast').textContent"
               "=== \"Serein's agent connected\"")
    if shots:
        presenter.screenshot(Path(shots) / "agent-1-presenter-present.png")
        guest.screenshot(Path(shots) / "agent-1-guest-present.png")
    meta = json.loads(first.tool("read_board")["content"][0]["text"])
    assert meta["board"] == "payments" and meta["selection"] == ["pay"]

    # The session's process ends: both tabs show the agent gone.
    first.kill()
    for tab in (presenter, guest):
        tab.wait(f"{AGENT} === \"Serein's agent · gone\"")
    presenter.wait("document.getElementById('toast').textContent"
                   " === \"Serein's agent is gone\"")
    assert presenter.js("grafliPresence.agent().present") is False
    if shots:
        presenter.screenshot(Path(shots) / "agent-2-presenter-gone.png")
        guest.screenshot(Path(shots) / "agent-2-guest-gone.png")

    # A session connects again: present again, and it reads the board.
    second = sessions()
    second.tool("connect")
    for tab in (presenter, guest):
        tab.wait(f"{AGENT} === \"Serein's agent\"")
    assert presenter.js("grafliPresence.agent().present") is True
    if shots:
        presenter.screenshot(Path(shots) / "agent-3-presenter-back.png")
    meta = json.loads(second.tool("read_board")["content"][0]["text"])
    assert meta["selection"] == ["pay"]
    second.end()
    presenter.wait(f"{AGENT} === \"Serein's agent · gone\"")
