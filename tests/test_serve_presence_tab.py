"""Presence between two browsers, in headless Chrome: the presenter's tab and
a guest's tab in a second Chrome, a real server and the real render worker.
The guest follows the presenter's view, sees the presenter's named cursor
and laser, stops following with one click and follows again. Keys, mouse
moves and clicks are sent the way a keyboard and a mouse send them (Chrome's
DevTools protocol). Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from tests.test_serve_tab import CHROME, Chrome, Served  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

BOARD = """#!grafli v1
@ box api "API gateway" 0,0 200x90
@ box pay "Payments" 420,0 200x90
@ box ledger "Ledger DB" 420,320 200x90
@ box cache "Cache" 1400,900 200x90
@ arrow api -> pay "charge"
@ arrow pay -> ledger "write"
@ arrow pay -> cache "read"
"""


class Browser(Chrome):
    """A Chrome that also moves and clicks the mouse."""

    def mouse(self, kind, x, y, **extra):
        self.call("Input.dispatchMouseEvent", session=True, type=kind,
                  x=x, y=y, **extra)

    def move(self, x, y):
        self.mouse("mouseMoved", x, y)

    def click_element(self, element_id):
        """Click the middle of the element *element_id*, as a mouse does."""
        r = self.js(f"(() => {{ const r = document.getElementById("
                    f"{json.dumps(element_id)}).getBoundingClientRect();"
                    " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        self.move(*r)
        self.mouse("mousePressed", *r, button="left", clickCount=1)
        self.mouse("mouseReleased", *r, button="left", clickCount=1)

    def stage_point(self, fx, fy):
        """The point at fractions *fx*, *fy* of the board's stage."""
        return self.js("(() => { const r = document.getElementById('stage')"
                       ".getBoundingClientRect(); return ["
                       f"r.left + r.width * {fx}, r.top + r.height * {fy}]; }})()")


@pytest.fixture(scope="module")
def browsers():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    presenter = Browser(1400, 900)
    # The guest's window has another shape: following frames the
    # presenter's view whole, it does not copy the numbers.
    guest = Browser(1100, 860)
    yield presenter, guest
    presenter.close()
    guest.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("presence-boards"))
    yield s
    s.stop()


def open_tab(chrome, served, name, role):
    key = {"presenter": served.keys.presenter, "editor": served.keys.editor,
           "viewer": served.keys.viewer}[role]
    from grafli.serve import server as srv
    chrome.open(srv.link("127.0.0.1", served.port, name, key))
    chrome.wait("window.grafliPresence && grafliPage.board() !== null"
                " && grafliLive.role() !== null && grafliPresence.me() !== null")


def views(presenter, guest):
    return presenter.js("grafliPage.view()"), guest.js("grafliPage.view()")


def shows_whole(outer, inner, tol=1.0):
    """*outer* holds *inner* whole, centred, and touches it on one side."""
    if "x" not in outer or "x" not in inner:
        return False  # a tab with no frame yet has no view
    cx = lambda v: v["x"] + v["w"] / 2  # noqa: E731
    cy = lambda v: v["y"] + v["h"] / 2  # noqa: E731
    return (abs(cx(outer) - cx(inner)) < tol and abs(cy(outer) - cy(inner)) < tol
            and outer["w"] >= inner["w"] - tol and outer["h"] >= inner["h"] - tol
            and (abs(outer["w"] - inner["w"]) < tol
                 or abs(outer["h"] - inner["h"]) < tol))


def wait_following(presenter, guest, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        p, g = views(presenter, guest)
        if shows_whole(g, p):
            return p, g
        time.sleep(0.05)
    raise AssertionError(f"the guest's view {g} does not show the presenter's {p}")


def test_a_second_browser_follows_stops_following_and_sees_the_laser(
        browsers, served):
    presenter, guest = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = served.root / "payments.grafli"
    path.write_text(BOARD, encoding="utf-8")
    before, mtime = path.read_bytes(), os.stat(path).st_mtime_ns

    open_tab(presenter, served, "payments", "presenter")
    open_tab(guest, served, "payments", "viewer")

    # The presenter names themself with the name button in the bar.
    presenter.click_element("me")
    presenter.wait("!document.getElementById('me-field').hidden")
    presenter.type("Serein")
    presenter.key("Enter")
    guest.wait("grafliPresence.peers().some((p) => p.name === 'Serein')")
    lead = presenter.js("grafliPresence.me()")
    assert guest.js("grafliPresence.lead()") == lead
    assert guest.js("grafliPresence.following()") is True
    guest.wait("document.getElementById('follow').textContent"
               " === 'Stop following Serein'")
    presenter.wait("document.getElementById('followers').textContent"
                   " === '1 following you'")

    # Following: the presenter zooms in and pans with the keys; the guest's
    # tab shows what the presenter's shows.
    fit = presenter.js("grafliPage.view()")
    for k in ("+", "ArrowRight", "ArrowDown"):
        presenter.key(k, shift=k == "+")
    presenter.wait(f"grafliPage.view().w < {fit['w'] * 0.9}")
    p_view, g_view = wait_following(presenter, guest)

    # The presenter's cursor, by name, and the laser.
    presenter.key("k")
    presenter.wait("grafliPresence.laser()")
    for i in range(12):
        presenter.move(*presenter.stage_point(0.25 + i * 0.03, 0.55 - i * 0.012))
        time.sleep(0.03)
    guest.wait(f"grafliPresence.trail({json.dumps(lead)}) > 0")
    guest.wait("grafliPresence.shown().includes('Serein')")
    cursor = guest.js(f"grafliPresence.cursor({json.dumps(lead)})")
    assert (p_view["x"] <= cursor["x"] <= p_view["x"] + p_view["w"]
            and p_view["y"] <= cursor["y"] <= p_view["y"] + p_view["h"])
    if shots:
        guest.screenshot(Path(shots) / "guest-follows-with-laser.png")
        presenter.screenshot(Path(shots) / "presenter-laser.png")
    presenter.key("k")
    presenter.wait("!grafliPresence.laser()")
    # The laser fades on the guest's screen; the cursor stays.
    guest.wait(f"grafliPresence.trail({json.dumps(lead)}) === 0")
    assert "Serein" in guest.js("grafliPresence.shown()")

    # Stop following: one click on the button in the bar.
    guest.click_element("follow")
    guest.wait("!grafliPresence.following()")
    guest.wait("document.getElementById('follow').textContent === 'Follow Serein'")
    presenter.wait("document.getElementById('followers').textContent"
                   " === '0 following you'")
    held = guest.js("grafliPage.view()")
    for k in ("-", "-", "ArrowLeft", "ArrowLeft", "ArrowUp"):
        presenter.key(k)
    presenter.wait(f"grafliPage.view().w > {p_view['w'] * 1.3}")
    time.sleep(0.5)
    assert guest.js("grafliPage.view()") == held
    if shots:
        guest.screenshot(Path(shots) / "guest-stopped-following.png")

    # Follow again: one click, and the guest is back on the presenter's view.
    guest.click_element("follow")
    guest.wait("grafliPresence.following()")
    wait_following(presenter, guest)

    # The guest's own zoom takes over from following.
    guest.key("-")
    guest.wait("!grafliPresence.following()")
    guest.wait("document.getElementById('toast').textContent"
               ".includes('Stopped following Serein')")

    # Nothing of it reached the board file.
    assert path.read_bytes() == before
    assert os.stat(path).st_mtime_ns == mtime


def test_a_follower_goes_along_when_the_presenter_opens_a_level(browsers, served):
    """A level into another board is that board's own page; a guest who
    follows lands on it too."""
    presenter, guest = browsers
    (served.root / "top-res").mkdir()
    (served.root / "top-res" / "inner.grafli").write_text(
        '#!grafli v1\n@ box db "Inside" 0,0 200x90\n', encoding="utf-8")
    (served.root / "top.grafli").write_text(
        '#!grafli v1\n@ box svc "Service" 0,0 200x90 &graph:inner\n',
        encoding="utf-8")
    open_tab(presenter, served, "top", "presenter")
    open_tab(guest, served, "top", "viewer")
    guest.wait("grafliPresence.lead() !== null")
    if not guest.js("grafliPresence.following()"):
        guest.click_element("follow")
        guest.wait("grafliPresence.following()")
    # The presenter opens the level with the keys: select Service, g d.
    presenter.key("f")
    presenter.wait("grafliEdit.jump() !== null")
    presenter.keys(presenter.js("grafliEdit.labelOf('svc')"))
    presenter.wait("grafliPage.selected() === 'svc'")
    presenter.key("g")
    presenter.key("d")
    presenter.wait("location.pathname === '/b/top-res/inner'"
                   " && window.grafliPresence && grafliPresence.me() !== null")
    guest.wait("location.pathname === '/b/top-res/inner'"
               " && window.grafliPresence && grafliPresence.lead() !== null", 20)
    assert guest.js("grafliLive.role()") == "viewer"
    assert guest.js("grafliPresence.following()") is True
    wait_following(presenter, guest)
