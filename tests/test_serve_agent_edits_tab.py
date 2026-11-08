"""The agent's edits in two browsers, in headless Chrome: a small edit of the
agent's glows in both tabs with its name, the presenter's U undoes it and
leaves the presenter's own later rename, and a 7-element change shows in
both tabs as a proposal that the presenter drops with x and takes with
Enter. The agent is the ``grafli agent`` bridge driven over stdio, as
Claude Code drives it. Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from tests.test_serve_agent_tab import BOARD, browsers, sessions  # noqa: E402,F401
from tests.test_serve_presence_tab import open_tab  # noqa: E402
from tests.test_serve_tab import CHROME, Served  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

# Payments split into three: Payments and its two arrows go, three boxes
# and one arrow come — 7 changes.
SPLIT = """#!grafli v1
@ box api "API gateway" 0,0 200x90
@ box charge "Charge" 800,-120 200x90
@ box refund "Refund" 800,0 200x90
@ box payout "Payout" 800,120 200x90
@ box ledger "Ledger DB" 420,320 200x90
@ arrow api -> charge "charge"
"""


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("agent-edit-boards"))
    s.state_dir = tmp_path_factory.mktemp("agent-edit-state")
    agents.write_state("127.0.0.1", s.port, s.keys.agent, s.root, s.state_dir)
    yield s
    s.stop()


def _read(session):
    got = session.tool("read_board")
    return json.loads(got["content"][0]["text"]), got["content"][1]["text"]


def _write(session, version, text, **extra):
    got = session.tool("write_board", base_version=version, text=text, **extra)
    assert not got.get("isError"), got
    return json.loads(got["content"][0]["text"])


def _labels(path):
    return {b.id: b.label for b in parse(path.read_text(encoding="utf-8")).boxes}


def test_the_agents_edit_glows_undoes_per_author_and_a_big_one_is_a_proposal(
        browsers, served, sessions):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = served.root / "payments.grafli"
    path.write_text(BOARD, encoding="utf-8")
    open_tab(presenter, served, "payments", "presenter")
    open_tab(guest, served, "payments", "viewer")
    presenter.js("grafliLive.post({t: 'name', name: 'Serein'})")
    presenter.wait("grafliPresence.peers().some((p) => p.name === 'Serein')")
    session = sessions()
    assert not session.tool("connect").get("isError")
    presenter.wait("grafliPresence.agentShown() === \"Serein's agent\"")

    # A small edit: it lands at once and glows in both tabs, with the name.
    meta, text = _read(session)
    text += '@ box cache "Cache" 0,320 200x90\n@ arrow api -> cache "read"\n'
    wrote = _write(session, meta["version"], text)
    assert wrote["changes"] == 2 and "proposed" not in wrote
    for tab in (presenter, guest):
        tab.wait("grafliAgent.marked().includes('cache')")
        assert sorted(tab.js("grafliAgent.marked()")) == ["api->cache", "cache"]
    assert presenter.js("grafliAgent.tag()") == (
        f"✦ v{wrote['version']} · Serein's agent · U undo")
    assert guest.js("grafliAgent.tag()") == (
        f"✦ v{wrote['version']} · Serein's agent")
    if shots:
        presenter.screenshot(Path(shots) / "edits-1-presenter-glow.png")
        guest.screenshot(Path(shots) / "edits-1-guest-glow.png")

    # The presenter renames the gateway with the keys, after the agent.
    presenter.key("f")
    presenter.wait("grafliEdit.jump() !== null")
    presenter.keys(presenter.js("grafliEdit.labelOf('api')"))
    presenter.wait("grafliPage.selected() === 'api'")
    presenter.key("e")
    presenter.wait("grafliEdit.field() !== null")
    presenter.js("document.getElementById('live-field').value = ''")
    presenter.type("Gateway")
    presenter.key("Enter")
    presenter.wait("grafliPage.current().elements.some("
                   "(e) => e.label === 'Gateway')")

    # U undoes the agent's edit; the presenter's rename stays.
    presenter.key("U", shift=True)
    presenter.wait("!grafliPage.current().elements.some((e) => e.id === 'cache')")
    guest.wait("!grafliPage.current().elements.some((e) => e.id === 'cache')")
    labels = _labels(path)
    assert "cache" not in labels and labels["api"] == "Gateway"
    presenter.wait("document.getElementById('toast').textContent"
                   " === \"Undid Serein's agent's edit\"")
    undone = session.note()
    assert undone["params"]["meta"]["event"] == "undone"

    # A change of 7 elements: a proposal in both tabs, the file untouched.
    before = path.read_bytes()
    meta, _text = _read(session)
    wrote = _write(session, meta["version"], SPLIT.replace(
        '"API gateway"', '"Gateway"'), about="split Payments")
    assert wrote["changes"] == 7 and wrote["proposed"]
    banner = "✦ Serein's agent proposes 7 changes · split Payments"
    presenter.wait(f"grafliAgent.banner() === {json.dumps(banner + 'Enter take · x drop')}")
    guest.wait(f"grafliAgent.banner() === "
               f"{json.dumps(banner + 'the presenter takes it or drops it')}")
    for tab in (presenter, guest):
        assert sorted(tab.js("grafliAgent.outlined()")) == [
            "api->charge", "api->pay", "charge", "pay", "pay->ledger",
            "payout", "refund"]
    assert path.read_bytes() == before
    if shots:
        presenter.screenshot(Path(shots) / "edits-2-presenter-proposal.png")
        guest.screenshot(Path(shots) / "edits-2-guest-proposal.png")

    # x drops it: the banner goes, the file stays, the agent hears it.
    presenter.key("x")
    for tab in (presenter, guest):
        tab.wait("grafliAgent.banner() === null")
    assert path.read_bytes() == before
    assert _labels(path)["pay"] == "Payments"
    assert session.note()["params"]["meta"]["event"] == "dropped"

    # Proposed again, Enter takes it: it lands and glows as the agent's.
    meta, _text = _read(session)
    _write(session, meta["version"], SPLIT.replace(
        '"API gateway"', '"Gateway"'), about="split Payments")
    presenter.wait("grafliAgent.banner() !== null")
    presenter.key("Enter")
    for tab in (presenter, guest):
        tab.wait("grafliAgent.banner() === null"
                 " && grafliAgent.marked().includes('charge')")
    assert sorted(_labels(path)) == ["api", "charge", "ledger", "payout",
                                     "refund"]
    assert session.note()["params"]["meta"]["event"] == "taken"
    if shots:
        presenter.screenshot(Path(shots) / "edits-3-presenter-taken.png")
    session.end()
