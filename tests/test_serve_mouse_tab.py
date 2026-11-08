"""The mouse in a grafli serve tab, in headless Chrome: a guest with an edit
link selects, renames, moves, connects and drops a ``Q:`` question with the
mouse alone, and a second browser on a watch link sees each change; a watch
link's tab gets none of them. A real server, the real render worker, and
mouse events sent the way a mouse sends them (Chrome's DevTools protocol).
Skipped when no Chrome or Chromium is found."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from tests.test_serve_presence_tab import Browser, open_tab  # noqa: E402
from tests.test_serve_tab import CHROME, Served, settled  # noqa: E402

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")

BOARD = """#!grafli v1
@ box lane "Checkout" 0,0 700x260
@ box api "API gateway" 40,80 200x90 >lane
@ box pay "Payments" 440,80 200x90 >lane
@ box ledger "Ledger DB" 440,420 200x90
@ box audit "Audit" 0,420 200x90
@ arrow api -> pay "charge"
"""


class Mouse(Browser):
    """A Browser that presses, drags and double-clicks on board elements."""

    def at(self, elem_id, fx=0.5, fy=0.5):
        """The screen point at fractions *fx*, *fy* of *elem_id*'s rect."""
        return self.js(
            "(() => { const e = grafliPage.current().elements.find("
            f"(x) => x.id === {json.dumps(elem_id)}); const m = document"
            ".getElementById('stage').getScreenCTM(); const p = new DOMPoint("
            f"e.rect[0] + e.rect[2] * {fx}, e.rect[1] + e.rect[3] * {fy})"
            ".matrixTransform(m); return [p.x, p.y]; })()")

    def click(self, x, y, button="left", count=1):
        self.move(x, y)
        for n in range(1, count + 1):
            self.mouse("mousePressed", x, y, button=button, clickCount=n)
            self.mouse("mouseReleased", x, y, button=button, clickCount=n)

    def drag(self, a, b, steps=8):
        self.move(*a)
        self.mouse("mousePressed", *a, button="left", clickCount=1)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", a[0] + (b[0] - a[0]) * i / steps,
                       a[1] + (b[1] - a[1]) * i / steps, button="left", buttons=1)
        self.mouse("mouseReleased", *b, button="left", clickCount=1)

    def toast(self):
        return self.js("document.getElementById('toast').textContent")


@pytest.fixture(scope="module")
def browsers():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    guest, watcher = Mouse(1400, 900), Mouse(1100, 860)
    yield guest, watcher
    guest.close()
    watcher.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("mouse-boards"))
    yield s
    s.stop()


def board_at(path: Path):
    return parse(path.read_text(encoding="utf-8"))


def shows(tab, expr, timeout=15):
    """Wait until *expr*, about the element map ``E`` (id → element of the
    drawing on screen), is true in *tab*."""
    tab.wait("(() => { const E = Object.fromEntries(grafliPage.current()"
             f".elements.map((e) => [e.id, e])); return {expr}; }})()", timeout)


def test_each_gesture_changes_the_board_and_shows_in_every_tab(browsers, served):
    guest, watcher = browsers
    shots = os.environ.get("GRAFLI_TAB_SHOTS")
    path = served.root / "checkout.grafli"
    path.write_text(BOARD, encoding="utf-8")
    open_tab(guest, served, "checkout", "editor")
    open_tab(watcher, served, "checkout", "viewer")
    guest.key("Z", shift=True)
    guest.wait("grafliPage.busy() === false")

    # Click selects.
    guest.click(*guest.at("pay"))
    guest.wait("grafliPage.selected() === 'pay'")
    assert guest.js("grafliLive.pending()") == 0

    # Double-click renames: the field holds the label, typing replaces it.
    guest.click(*guest.at("pay"), count=2)
    guest.wait("grafliEdit.field() === 'Payments'")
    guest.type("Billing")
    guest.key("Enter")
    settled(guest)
    assert board_at(path).box_by_id("pay").label == "Billing"
    shows(watcher, "E.pay.label === 'Billing'")

    # Drag moves: Audit, out on the canvas, goes right and down.
    before = board_at(path).box_by_id("audit")
    a = guest.at("audit")
    guest.drag(a, (a[0] + 120, a[1] + 40))
    settled(guest)
    after = board_at(path).box_by_id("audit")
    assert after.x > before.x + 40 and after.y > before.y + 10
    assert after.parent == "" and after.w == before.w
    shows(watcher, f"E.audit.rect[0] > {before.x + 40}")

    # Drag into a container: Ledger DB, let go over the lane, goes in it.
    guest.drag(guest.at("ledger"), guest.at("lane", 0.5, 0.85))
    settled(guest)
    ledger = board_at(path).box_by_id("ledger")
    assert ledger.parent == "lane" and ledger.y < 260
    shows(watcher, "E.ledger.parent === 'lane'")

    # Drag the container: what it holds goes along.
    lane0, api0 = board_at(path).box_by_id("lane"), board_at(path).box_by_id("api")
    top = guest.at("lane", 0.5, 0.06)
    guest.drag(top, (top[0], top[1] + 60))
    settled(guest)
    lane1, api1 = board_at(path).box_by_id("lane"), board_at(path).box_by_id("api")
    assert lane1.y - lane0.y == pytest.approx(api1.y - api0.y) and lane1.y > lane0.y

    # A drag from a box's edge connects: API gateway → Audit.
    guest.drag(guest.at("api", 0.5, 0.97), guest.at("audit"))
    settled(guest)
    assert ("api", "audit") in {(x.from_id, x.to_id) for x in board_at(path).arrows}
    shows(watcher, "'api->audit' in E")
    # Letting go over nothing connects nothing.
    arrows = len(board_at(path).arrows)
    guest.drag(guest.at("audit", 0.98, 0.5), guest.stage_point(0.97, 0.97))
    guest.wait("document.getElementById('toast').textContent"
               ".includes('Let go over a box')")
    assert len(board_at(path).arrows) == arrows

    # Right-click drops a Q: question, typed in place.
    guest.click(*guest.at("pay"), button="right")
    guest.wait("grafliEdit.field() === ''")
    guest.type("who signs off a refund?")
    if shots:
        guest.screenshot(Path(shots) / "mouse-question-field.png")
    guest.key("Enter")
    settled(guest)
    notes = board_at(path).notes
    assert [n.text for n in notes] == ["Q: who signs off a refund?"]
    pay = board_at(path).box_by_id("pay")
    # Beside the box it was asked on, so the box keeps its look.
    assert notes[0].x >= pay.x + pay.w and notes[0].parent == "lane"
    shows(watcher, f"E[{json.dumps(notes[0].id)}].text"
                   " === 'Q: who signs off a refund?'")
    # On the empty canvas, at the point.
    guest.click(*guest.stage_point(0.9, 0.12), button="right")
    guest.wait("grafliEdit.field() === ''")
    guest.type("Q: is there a sandbox?")
    guest.key("Enter")
    settled(guest)
    texts = sorted(n.text for n in board_at(path).notes)
    assert texts == ["Q: is there a sandbox?", "Q: who signs off a refund?"]
    shows(watcher, "Object.values(E).filter((e) => e.kind === 'note').length === 2")
    if shots:
        guest.key("Escape")
        guest.screenshot(Path(shots) / "mouse-guest.png")
        watcher.screenshot(Path(shots) / "mouse-watcher.png")
        (Path(shots) / "checkout.grafli").write_text(path.read_text())

    # Undo takes the guest's mouse edits back like any other.
    guest.key("u")
    settled(guest)
    assert len(board_at(path).notes) == 1


def test_a_watch_link_allows_none_of_the_gestures(browsers, served):
    _guest, watcher = browsers
    path = served.root / "watched.grafli"
    path.write_text(BOARD, encoding="utf-8")
    before = path.read_bytes()
    open_tab(watcher, served, "watched", "viewer")
    watcher.key("Z", shift=True)
    watcher.wait("grafliPage.busy() === false")

    # A click still selects: that changes nothing on the board.
    watcher.click(*watcher.at("pay"))
    watcher.wait("grafliPage.selected() === 'pay'")
    watcher.js("document.getElementById('toast').textContent = ''")
    watcher.click(*watcher.at("pay"), count=2)
    watcher.wait("document.getElementById('toast').textContent"
                 ".includes('for watching')")
    assert watcher.js("grafliEdit.field()") is None
    watcher.js("document.getElementById('toast').textContent = ''")
    watcher.click(*watcher.at("audit"), button="right")
    watcher.wait("document.getElementById('toast').textContent"
                 ".includes('for watching')")
    assert watcher.js("grafliEdit.field()") is None
    # A drag on a box pans, as on the export page; from an edge too.
    view = watcher.js("grafliPage.view()")
    a = watcher.at("audit")
    watcher.drag(a, (a[0] + 120, a[1] + 40))
    watcher.drag(watcher.at("api", 0.5, 0.97), watcher.at("audit"))
    assert watcher.js("grafliPage.view()") != view
    assert watcher.js("grafliMouse.pressing()") is None
    assert watcher.js("grafliLive.pending()") == 0
    assert path.read_bytes() == before


def test_a_double_click_renames_a_level_box_a_lone_click_opens_it(
        browsers, served):
    guest, _watcher = browsers
    (served.root / "top-res").mkdir()
    (served.root / "top-res" / "inner.grafli").write_text(
        '#!grafli v1\n@ box db "Inside" 0,0 200x90\n', encoding="utf-8")
    path = served.root / "top.grafli"
    path.write_text('#!grafli v1\n@ box svc "Service" 0,0 200x90 &graph:inner\n',
                    encoding="utf-8")
    open_tab(guest, served, "top", "editor")
    guest.click(*guest.at("svc"), count=2)
    guest.wait("grafliEdit.field() === 'Service'")
    guest.type("Checkout service")
    guest.key("Enter")
    settled(guest)
    assert board_at(path).box_by_id("svc").label == "Checkout service"
    assert guest.js("location.pathname") == "/b/top"
    guest.click(*guest.at("svc"))
    guest.wait("location.pathname === '/b/top-res/inner'"
               " && window.grafliPage && grafliPage.board() !== null")
