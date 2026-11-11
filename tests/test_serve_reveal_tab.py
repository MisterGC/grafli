"""Reveal mode between two browsers, in headless Chrome: a board served with
reveal mode starts with only its title in the guest's tab; the presenter
reveals a box, a box in a container and a box with its neighbours by jump
label, sees what is still hidden as faint outlines, and the board file stays
as it was. Keys are sent the way a keyboard sends them (Chrome's DevTools
protocol). Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from tests.test_serve_presence_tab import Browser, open_tab  # noqa: E402
from tests.test_serve_tab import CHROME, Served  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

BOARD = """#!grafli v1
# Payments: prepared before the call
@ note title 0,-150 "Payments: where a charge goes" ~xlarge !bold
@ box client "Client" 0,0 180x80
@ box core "Payment service" 300,-60 560x200 %blue
@ box api "API" 330,0 180x80 >core
@ box pay "Payments" 650,0 180x80 >core
@ box fraud "Fraud check" 650,300 180x80
@ box ledger "Ledger" 1000,0 180x80
@ arrow client -> api "charge"
@ arrow api -> pay "forward"
@ arrow pay -> fraud "score"
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
    s = Served(tmp_path_factory.mktemp("reveal-boards"), reveal=True)
    yield s
    s.stop()


def shown(chrome):
    """The ids of the elements with a rect this tab draws."""
    return set(chrome.js("grafliPage.current().elements.filter((e) => e.rect"
                         " && !e.hidden).map((e) => e.id)"))


def reveal_by_label(presenter, element_id):
    presenter.key("v")
    presenter.wait("grafliEdit.jump() !== null"
                   " && grafliEdit.jump().purpose === 'reveal'")
    label = presenter.js(f"grafliEdit.labelOf({json.dumps(element_id)})")
    assert label, f"no jump label on {element_id}"
    presenter.keys(label)


def test_the_presenter_reveals_by_jump_label_and_the_guest_sees_only_that(
        browsers, served):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = served.root / "payments.grafli"
    path.write_text(BOARD, encoding="utf-8")
    before, mtime = path.read_bytes(), os.stat(path).st_mtime_ns

    open_tab(presenter, served, "payments", "presenter")
    open_tab(guest, served, "payments", "viewer")
    presenter.wait("grafliReveal.on()")

    # The guest's tab has the title and nothing else, not even in its page.
    assert shown(guest) == {"title"}
    assert guest.js("grafliReveal.on()") is False
    for word in ("Ledger", "Fraud check", "Payment service"):
        assert not guest.js(f"document.documentElement.innerHTML"
                            f".includes({json.dumps(word)})"), word
    # The presenter's tab draws the same, and the rest as faint outlines.
    assert shown(presenter) == {"title"}
    assert set(presenter.js("grafliReveal.outlines()")) == {
        "client", "core", "api", "pay", "fraud", "ledger"}
    assert presenter.js("document.getElementById('reveal-chip').textContent"
                        ) == "revealing · 6 hidden"
    if shots:
        presenter.screenshot(Path(shots) / "reveal-1-presenter-start.png")
        guest.screenshot(Path(shots) / "reveal-1-guest-start.png")

    # v, then the client's jump label: the client shows on the guest's tab.
    reveal_by_label(presenter, "client")
    guest.wait("grafliPage.current().elements.some((e) => e.id === 'client')")
    assert shown(guest) == {"title", "client"}
    # A box in a container: the container's frame comes with it, and the
    # arrow from the client.
    reveal_by_label(presenter, "api")
    guest.wait("grafliPage.current().elements.some((e) => e.id === 'api')")
    assert shown(guest) == {"title", "client", "core", "api"}
    assert guest.js("grafliPage.current().lines.map((l) => l.ends.join('>'))"
                    ) == ["client>api"]
    presenter.wait("grafliReveal.outlines().length === 3")
    if shots:
        presenter.screenshot(Path(shots) / "reveal-2-presenter-api.png")
        guest.screenshot(Path(shots) / "reveal-2-guest-api.png")

    # Payments, then + right after: with its neighbours, in one more key.
    reveal_by_label(presenter, "pay")
    guest.wait("grafliPage.current().elements.some((e) => e.id === 'pay')")
    assert "ledger" not in shown(guest)
    presenter.wait("grafliLive.pending() === 0")
    presenter.key("+", shift=True)
    guest.wait("grafliPage.current().elements.some((e) => e.id === 'ledger')")
    assert shown(guest) == {"title", "client", "core", "api", "pay", "fraud",
                            "ledger"}
    presenter.wait("grafliReveal.outlines().length === 0")
    presenter.wait("document.getElementById('reveal-chip').textContent"
                   " === 'revealing · all shown'")
    if shots:
        presenter.screenshot(Path(shots) / "reveal-3-presenter-neighbours.png")
        guest.screenshot(Path(shots) / "reveal-3-guest-neighbours.png")

    # The guest cannot reveal; the presenter ends reveal mode with V.
    guest.key("v")
    guest.wait("document.getElementById('toast').textContent"
               ".includes('present link')")
    presenter.key("V", shift=True)
    presenter.wait("!grafliReveal.on()")
    presenter.wait("document.getElementById('reveal-chip').hidden")

    # The board file is unchanged after the reveal session.
    assert path.read_bytes() == before
    assert os.stat(path).st_mtime_ns == mtime
