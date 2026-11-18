"""The board's agent in the desktop app, as a present link's tab has it.

The app hosts what ``grafli serve`` hosts (``grafli.serve.host``) once the
agent is first needed — the ``:`` line opens, an element is asked about, or
"Host this board" in the agent's menu in the status bar — so a Claude Code
session connects with ``/mcp__grafli__connect`` and guest tabs open the
board's links without ``grafli serve`` started by hand. The app is the
presenter of its board:

* ``:`` opens the command line: a grafli line (``@ box cache "Cache"``) is
  applied to the board, with the app's own undo; plain language goes to the
  agent. The line says on its right where its text goes;
* ``Shift+A`` asks the agent about the selected element;
* while a request is open, a line at the top says what the agent works on;
* the elements the agent's edit touched glow in its purple, with its name,
  for a few seconds; ``Shift+U`` takes that edit back, and only that;
* a change of more than five elements waits as its proposal: a banner and
  dashed outlines, ``Enter`` takes it, ``x`` drops it.

``AgentLink`` holds what the app knows of the agent and draws it on the
view; ``CommandLine`` is the ``:`` line. The status bar's ``AgentChip``
names the agent, or says none is connected.
"""

from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication,
                           QPainter, QPen)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QToolButton)

from grafli import theme
from grafli.constants import FONT_FAMILY
from grafli.serve.agent import AGENT_COLOR

# How long an edit of the agent's glows, as in the tab.
MARK_MS = 4000
# How often the app's selection and view are passed on to the agent.
PRESENCE_MS = 150
# How much of an element's label the ask prompt shows.
ASK_LABEL_CHARS = 40

CONNECT_HINT = "in your Claude Code session: /mcp__grafli__connect"


def agent_color() -> QColor:
    return QColor(AGENT_COLOR)


def selected_element(view) -> tuple[str, str] | None:
    """The one selected element's id and label, or None: a box, note or
    image, or else a connector."""
    from grafli.serve.changes import element_key
    items = view._scene.selectedItems()
    if len(items) == 1:
        item = items[0]
        for attr in ("box", "note", "image"):
            el = getattr(item, attr, None)
            if el is not None and getattr(el, "id", ""):
                label = (getattr(el, "label", "") or getattr(el, "text", "")
                         or el.id)
                return el.id, label
    if not items and len(view._selected_arrows) == 1:
        arrow = view._selected_arrows[0]
        return element_key(arrow), (arrow.label
                                    or f"{arrow.from_id} -> {arrow.to_id}")
    return None


def _first_line(text: str, limit: int) -> str:
    line = text.splitlines()[0] if text else ""
    return line if len(line) <= limit else line[:limit - 1] + "…"


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


class MainThreadCollector(QObject):
    """Python's cyclic garbage collection on the GUI thread only, while the
    host's thread runs.

    A collection runs on whichever thread happens to allocate; one on the
    host's thread that frees a dropped Qt widget's cycle destroys the widget
    off the GUI thread, which crashes Qt later (see the suite's
    ``tests/conftest.py``). So while the app hosts, automatic collection is
    off and this timer collects whatever generation is due, here.
    """

    def __init__(self, parent=None, interval_ms: int = 500):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.collect)
        self._was_enabled = False

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self):
        if self.active:
            return
        self._was_enabled = gc.isenabled()
        gc.disable()
        self._timer.start()

    def stop(self):
        if not self.active:
            return
        self._timer.stop()
        if self._was_enabled:
            gc.enable()

    def collect(self):
        counts, limits = gc.get_count(), gc.get_threshold()
        due = [g for g in range(3) if counts[g] > limits[g]]
        if due:
            gc.collect(max(due))


class CommandLine(QFrame):
    """The ``:`` line along the bottom of the canvas.

    *submitted(text, about)* fires on Enter with the stripped text and the id
    of the element asked about (None on the plain ``:`` line); Esc closes
    it. Up and Down walk the lines sent before.
    """

    submitted = Signal(str, object)
    closed = Signal()

    def __init__(self, viewport, route):
        super().__init__(viewport)
        self.setObjectName("agentline")
        self._route = route           # route(text, about) -> (where, words)
        self._about: str | None = None
        self._history: list[str] = []
        self._at = 0
        self._prompt = QLabel(":", self)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(
            '@ box cache "Cache", or plain language   ·   Enter sends, '
            'Esc closes')
        self.edit.setFrame(False)
        self.where = QLabel("", self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)
        layout.addWidget(self._prompt)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.where)
        self.edit.textChanged.connect(self.update_route)
        self.edit.returnPressed.connect(self._send)
        self.edit.installEventFilter(self)
        viewport.installEventFilter(self)
        self.apply_theme()
        self.hide()

    @property
    def about(self) -> str | None:
        return self._about

    def apply_theme(self):
        bg = QColor(theme.OVERLAY_BG)
        ink = theme.overlay_ink(0.92).name()
        self.setStyleSheet(
            f"#agentline {{ background: {bg.name()}; border: 1px solid "
            f"{AGENT_COLOR}; border-radius: 8px; }}"
            f" QLabel, QLineEdit {{ color: {ink}; background: transparent;"
            f" font-family: '{FONT_FAMILY}'; font-size: 13px; }}")

    def open(self, about: str | None = None, prompt: str = ":"):
        self._about = about
        self._prompt.setText(prompt)
        self.edit.clear()
        self._at = len(self._history)
        self._place()
        self.show()
        self.raise_()
        self.update_route()
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def close_line(self):
        if self.isHidden():
            return
        self.hide()
        self._about = None
        self.closed.emit()

    def update_route(self, *_):
        where, words = self._route(self.edit.text(), self._about)
        self.where.setText(words)
        self.where.setProperty("to", where)
        color = (AGENT_COLOR if where == "agent"
                 else theme.INK_FAINT.name())
        self.where.setStyleSheet(f"color: {color}; font-size: 11px;")

    def route(self) -> str:
        """Where the text on the line goes now: "board", "agent" or
        "none"."""
        return self.where.property("to") or ""

    def _send(self):
        text = self.edit.text().strip()
        about = self._about
        self.close_line()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self.submitted.emit(text, about)

    def _place(self):
        vp = self.parentWidget()
        w = max(min(vp.width() - 48, 900), 200)
        h = self.sizeHint().height()
        self.setGeometry((vp.width() - w) // 2, vp.height() - h - 64, w, h)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            if self.isVisible():
                self._place()
            return False
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close_line()
                return True
            if key == Qt.Key.Key_Up and self._at > 0:
                self._at -= 1
                self.edit.setText(self._history[self._at])
                return True
            if key == Qt.Key.Key_Down and self._at < len(self._history):
                self._at += 1
                self.edit.setText(self._history[self._at]
                                  if self._at < len(self._history) else "")
                return True
        return super().eventFilter(obj, event)


class AgentChip(QToolButton):
    """The agent in the status bar: its name in purple, "gone" when its
    session dropped, else that none is connected. Its menu hosts the board
    and copies the links guests open."""

    def __init__(self, link: "AgentLink"):
        super().__init__()
        self._link = link
        self.setAutoRaise(True)
        # Clicked, never tabbed to: Tab belongs to the canvas, which cycles
        # the selection through siblings with it.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setMenu(QMenu(self))
        self.menu().aboutToShow.connect(self._fill_menu)
        self.refresh()

    def refresh(self):
        seat, host = self._link.seat, self._link.host
        if seat is not None and seat.get("present"):
            text, color = f"✦ {seat['name']}", AGENT_COLOR
            tip = f"{seat['name']} is connected: : asks it, Shift+A on the " \
                  "selection"
        elif seat is not None:
            text, color = f"✦ {seat['name']} · gone", theme.STATUS_DIM.name()
            tip = f"{seat['name']}'s session dropped; {CONNECT_HINT} again"
        else:
            text, color = "✦ no agent connected", theme.STATUS_DIM.name()
            tip = (CONNECT_HINT[0].upper() + CONNECT_HINT[1:] if host
                   else "Press : to host this board, then "
                        + CONNECT_HINT)
        if host is not None and self._link.board is None:
            tip += f" · this board is not in {host.root}, the folder hosted"
        self.setText(text)
        self.setToolTip(tip)
        self.setStyleSheet(f"QToolButton {{ color: {color}; border: none; }}"
                           " QToolButton::menu-indicator { image: none; }")

    def _fill_menu(self):
        menu = self.menu()
        menu.clear()
        link = self._link
        if link.host is None:
            menu.addAction("Host this board for an agent and guests",
                           link.host_from_menu)
            return
        name = link.board
        if name is not None:
            links = link.host.links(name)
            menu.addAction("Copy the edit link for guests",
                           lambda: link.copy_link(links["edit"]))
            menu.addAction("Copy the watch link for guests",
                           lambda: link.copy_link(links["watch"]))
            menu.addSeparator()
        menu.addAction("Stop hosting (the agent and guests leave)",
                       link.stop)


class AgentLink(QObject):
    """What the app knows of the board's agent, and how it asks it.

    Lives on the GUI thread; what the host's thread hears comes in through
    the ``heard`` signal, the answers to requests through ``_answered``.
    """

    heard = Signal(object)
    _answered = Signal(object, object)
    changed = Signal()

    def __init__(self, window, host_addr: str | None = None,
                 port: int | None = None, state_where: Path | None = None):
        super().__init__(window)
        self.window = window
        self.host = None
        self._addr, self._port, self._where = host_addr, port, state_where
        self.board: str | None = None
        self.seat: dict | None = None
        self.work: dict | None = None
        self.proposal: dict | None = None
        self.mark: dict | None = None
        self._mark_timer = QTimer(self)
        self._mark_timer.setSingleShot(True)
        self._mark_timer.setInterval(MARK_MS)
        self._mark_timer.timeout.connect(self._unmark)
        self._presence = QTimer(self)
        self._presence.setInterval(PRESENCE_MS)
        self._presence.timeout.connect(self._send_presence)
        self._sent_sel: object = ()
        self._sent_view: tuple | None = None
        self._collector = MainThreadCollector(self)
        self.heard.connect(self._on_message)
        self._answered.connect(lambda done, answer: done(answer))
        self.changed.connect(self._repaint)
        view = window._view
        self.line = CommandLine(view.viewport(), self.route)
        self.line.submitted.connect(self._on_submitted)
        self.line.closed.connect(lambda: view.setFocus())
        self.chip = AgentChip(self)
        self.changed.connect(self.chip.refresh)

    @property
    def view(self):
        return self.window._view

    def toast(self, text: str, kind: str = "info"):
        self.view.toast(text, kind)

    # ── Hosting ──

    def ensure_hosted(self) -> str | None:
        """Host the board shown, if it is not yet; why it cannot be, or
        None once it is."""
        path = self.window._file_path
        if path is None:
            return ("save the board first: the agent and guests work on "
                    "its file")
        if self.host is not None:
            if self.host.name_of(path) is None:
                return (f"this board is not in {self.host.root}, the folder "
                        "the app hosts; stop hosting in the agent's menu in "
                        "the status bar to host this one")
            return None
        from grafli.serve.host import Host, HostError, missing_extra
        why = missing_extra()
        if why:
            return why
        host = Host(Path(path).parent, self.heard.emit, host=self._addr,
                    port=self._port, theme=theme.name(),
                    state_where=self._where)
        self._collector.start()
        try:
            host.start()
        except HostError as e:
            self._collector.stop()
            return str(e)
        self.host = host
        self.follow(path)
        self._presence.start()
        print(f"grafli: hosting {host.root} on {host.host}:{host.port} for "
              f"an agent and guests ({CONNECT_HINT})", flush=True)
        self.changed.emit()
        return None

    def host_from_menu(self):
        why = self.ensure_hosted()
        if why:
            self.toast(_capital(why), "warn")
        else:
            self.toast(f"Hosting {self.host.root.name}/ · {CONNECT_HINT}")

    def follow(self, path: Path | None):
        """The app shows board *path* now: present that one."""
        if self.host is None:
            return
        name = self.host.name_of(path)
        if name is not None and name == self.board:
            return
        self.board = name
        self.seat_proposal(None)
        self.mark = None
        self._sent_sel, self._sent_view = (), None
        self._when(self.host.present(path), lambda _name: self.changed.emit())
        self.changed.emit()

    def stop(self, quiet: bool = False):
        host, self.host = self.host, None
        self._presence.stop()
        if host is not None:
            host.stop()
        self._collector.stop()
        self.board = self.seat = self.work = self.proposal = self.mark = None
        self.changed.emit()
        if not quiet:
            self.toast("Stopped hosting: the agent and guests left")

    def copy_link(self, url: str):
        QGuiApplication.clipboard().setText(url)
        self.toast("Copied the link: the key is after #, so hand it out "
                   "only to whom it is for")

    # ── Where a line's text goes ──

    def route(self, text: str, about: str | None) -> tuple[str, str]:
        from grafli.serve.ops import is_line
        if self.host is None:
            plain = ("none", "plain language: not hosted")
        elif self.board is None:
            plain = ("none", "plain language: this board is not hosted")
        elif self.seat is None:
            plain = ("none", "plain language: no agent connected")
        elif not self.seat.get("present"):
            plain = ("none", f"plain language: {self.seat['name']} is gone")
        else:
            plain = ("agent", f"plain language → {self.seat['name']}")
        if about is not None:
            return plain
        text = text.strip()
        line = ("board", "grafli line → applied")
        if not text:
            return line[0], f"{line[1]} · {plain[1]}"
        return line if is_line(text) else plain

    # ── Asking ──

    def open_line(self):
        why = self.ensure_hosted()
        self.line.open()
        if why:
            self.toast(_capital(why), "warn")

    def ask_about_selection(self):
        picked = selected_element(self.view)
        if picked is None:
            self.toast("Select one element to ask the agent about", "info")
            return
        why = self.ensure_hosted()
        if why:
            self.toast(_capital(why), "warn")
            return
        away = self._not_here()
        if away:
            self.toast(away, "warn")
            return
        el_id, label = picked
        self.line.open(about=el_id, prompt=(
            f"✦ ask {self.seat['name']} about "
            f"'{_first_line(label, ASK_LABEL_CHARS)}':"))

    def _not_here(self) -> str | None:
        """Why nothing can be asked now, or None when the agent is here."""
        if self.seat is None:
            return ("No agent is connected, so nothing is asked; "
                    + CONNECT_HINT)
        if not self.seat.get("present"):
            return (f"{self.seat['name']} is gone, so nothing is asked; "
                    f"{CONNECT_HINT} again")
        return None

    def _on_submitted(self, text: str, about):
        from grafli.serve.ops import is_line
        if about is None and is_line(text):
            self.window.apply_grafli_line(text)
            return
        self.ask(text, about)

    def ask(self, text: str, about: str | None = None):
        why = self.ensure_hosted()
        if why:
            self.toast(_capital(why), "warn")
            return
        # What the app has not saved yet is not on the board the agent reads.
        self.window._flush_autosave()
        short = text if len(text) <= 48 else text[:47] + "…"

        def done(answer):
            if answer.get("t") == "ack":
                self.toast(f"Asked {answer['agent']}: “{short}” · the answer "
                           "comes to the board")
            else:
                self.toast(_capital(answer.get("message", "not asked")),
                           "warn")
        self._when(self.host.ask(text, about), done)

    # ── The agent's edits and proposal ──

    def take(self):
        self._settle("take")

    def drop(self):
        self._settle("drop")

    def _settle(self, do: str):
        p = self.proposal
        if p is None or self.host is None:
            self.toast("No proposal of the agent's waits", "info")
            return
        self.window._flush_autosave()

        def done(answer):
            if answer.get("t") != "ack":
                self.toast(_capital(answer.get("message", "")), "warn")
                return
            if do == "drop":
                self.toast(f"Dropped {p['by']}'s proposal")
            else:
                self.toast(f"Took {p['by']}'s proposal"
                           + ("; a later change by someone else stays"
                              if answer.get("conflicts") else ""))
                self.window._on_file_changed()
        self._when(self.host.settle(do), done)

    def undo(self):
        if self.host is None:
            self.toast("The agent has made no edit here", "info")
            return
        self.window._flush_autosave()
        name = self.seat["name"] if self.seat else "the agent"

        def done(answer):
            if answer.get("t") != "ack":
                self.toast(_capital(answer.get("message", "")), "warn")
                return
            self.window._on_file_changed()
            self._unmark()
            self.toast(f"Undid {name}'s edit"
                       + (", but a later change by someone else stays"
                          if answer.get("conflicts") else ""))
        self._when(self.host.undo_agent(), done)

    def seat_proposal(self, proposal: dict | None):
        had, self.proposal = self.proposal, proposal
        if proposal is not None and (had is None or had["id"] != proposal["id"]):
            self.toast(f"{proposal['by']} proposes {proposal['count']} "
                       "changes: Enter takes it, x drops it")
            self._show_proposal()
        self.changed.emit()

    def _show_proposal(self):
        rects = [QRectF(*s["rect"]) for s in (*self.proposal.get("added", ()),
                                               *self.proposal.get("changed", ()))
                 if s.get("rect")]
        rects += [r for r in (self._rect_of(i) for i in
                              self.proposal.get("removed", ())) if r]
        if not rects:
            return
        union = rects[0]
        for r in rects[1:]:
            union = union.united(r)
        view = self.view
        shown = view.mapToScene(view.viewport().rect()).boundingRect()
        if not shown.contains(union):
            view._animate_to_rect(union.adjusted(-60, -60, 60, 60))

    def _unmark(self):
        if self.mark is not None:
            self.mark = None
            self._mark_timer.stop()
            self.changed.emit()

    # ── What the host's thread heard ──

    def _on_message(self, msg: dict):
        if self.host is None:
            # Queued before hosting stopped.
            return
        kind = msg.get("t")
        if kind == "peers":
            self.seat = msg.get("agent")
            self.changed.emit()
            if self.line.isVisible():
                self.line.update_route()
        elif kind == "work":
            self.work = msg.get("work")
            self.changed.emit()
        elif kind == "proposal":
            self.seat_proposal(msg.get("proposal"))
        elif kind == "marked":
            # The edit is in the file already: show it now, not at the
            # watcher's next look.
            self.window._on_file_changed()
            if msg.get("undone"):
                self.toast(f"{msg['by']} undid its last edit")
            else:
                self.toast(f"{msg['by']}: {msg.get('summary') or 'changed the board'}"
                           " · Shift+U undoes it")
            self.mark = {"by": msg["by"], "ids": list(msg.get("ids") or []),
                         "version": msg.get("version")}
            self._mark_timer.start()
            self.changed.emit()
        elif kind == "error" and msg.get("message"):
            self.toast(_capital(msg["message"]), "warn")

    def _when(self, future, done):
        """Run *done(answer)* on the GUI thread once *future* is answered."""
        def landed(fut):
            try:
                answer = fut.result()
            except Exception as e:
                answer = {"t": "error", "message": f"{type(e).__name__}: {e}"}
            self._answered.emit(done, answer)
        future.add_done_callback(landed)

    def _send_presence(self):
        if self.host is None or self.board is None:
            return
        picked = selected_element(self.view)
        sel = picked[0] if picked else None
        if sel != self._sent_sel:
            self._sent_sel = sel
            self.host.select(sel)
        view = self.view
        r = view.mapToScene(view.viewport().rect()).boundingRect()
        at = (round(r.x(), 1), round(r.y(), 1), round(r.width(), 1),
              round(r.height(), 1))
        if at != self._sent_view and r.width() > 0 and r.height() > 0:
            self._sent_view = at
            self.host.view(*at)

    def _repaint(self):
        self.view.viewport().update()

    # ── Drawing on the view ──

    def _items_of(self, el_id: str):
        view = self.view
        for items in (view._box_items, view._note_items, view._image_items):
            item = items.get(el_id)
            if item is not None:
                return item, None
        from grafli.items import ArrowLineItem
        from grafli.serve.changes import element_key
        lines = [g for g in view._arrow_items if isinstance(g, ArrowLineItem)
                 and g.data(0) is not None and element_key(g.data(0)) == el_id]
        return None, lines

    def _rect_of(self, el_id: str) -> QRectF | None:
        item, lines = self._items_of(el_id)
        if item is not None:
            return item.sceneBoundingRect()
        if lines:
            r = lines[0].sceneBoundingRect()
            for g in lines[1:]:
                r = r.united(g.sceneBoundingRect())
            return r
        return None

    def marked_ids(self) -> list[str]:
        """The ids glowing now: the agent's last edit, as far as the board
        on screen holds them."""
        if self.mark is None:
            return []
        return [i for i in self.mark["ids"] if self._has(i)]

    def _has(self, el_id: str) -> bool:
        item, lines = self._items_of(el_id)
        return item is not None or bool(lines)

    def banner(self) -> str | None:
        """The proposal's banner as drawn, or None."""
        p = self.proposal
        if p is None:
            return None
        return (f"✦ {p['by']} proposes {p['count']} changes · "
                f"{p.get('about') or p.get('summary', '')}   Enter take · x drop")

    def working(self) -> str | None:
        """The working line as drawn, or None."""
        w = self.work
        if w is None:
            return None
        if w.get("late"):
            mins = max(round(w.get("late_after", 120) / 60), 1)
            head = (f"✦ {w['by']} has not answered in {mins} minute"
                    + ("s" if mins != 1 else "") + ":")
        else:
            head = f"✦ {w['by']} is working on:"
        what = (w["text"] if w.get("text") is not None
                else f"a request from {w.get('from', '')}")
        parts = []
        if w.get("doing") and not w.get("late"):
            parts.append(w["doing"])
        if w.get("board") != self.board:
            parts.append(f"on {w.get('board')}")
        if w.get("more"):
            parts.append(f"{w['more']} more waiting")
        return f"{head} {what}" + (f" · {' · '.join(parts)}" if parts else "")

    def paint(self, painter: QPainter):
        """Draw the agent's marks and proposal (the painter in scene
        coordinates), then its banner and working line on top."""
        if self.mark is None and self.proposal is None and self.work is None:
            return
        color = agent_color()
        painter.save()
        # The HUD drawn before this may have left the painter in viewport
        # space: draw on the board in its own coordinates.
        painter.setTransform(self.view.viewportTransform())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.proposal is not None:
            self._paint_proposal(painter, color)
        if self.mark is not None:
            self._paint_mark(painter, color)
        painter.restore()
        lines = [t for t in (self.banner(), self.working()) if t]
        if lines:
            self._paint_banners(painter, lines, color)

    def _paint_mark(self, painter: QPainter, color: QColor):
        halo = QColor(color)
        halo.setAlpha(60)
        edge = QPen(color, 2)
        edge.setCosmetic(True)
        lowest: QRectF | None = None
        for el_id in self.mark["ids"]:
            item, lines = self._items_of(el_id)
            if item is not None:
                r = item.sceneBoundingRect().adjusted(-4, -4, 4, 4)
                painter.setPen(QPen(halo, 10))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(r, 8, 8)
                painter.setPen(edge)
                painter.drawRoundedRect(r, 8, 8)
                if lowest is None or r.bottom() > lowest.bottom():
                    lowest = r
            for g in lines or ():
                path = g.mapToScene(g.path())
                pen = QPen(halo, 10)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.strokePath(path, pen)
                painter.strokePath(path, edge)
                if lowest is None:
                    lowest = g.sceneBoundingRect()
        if lowest is None:
            return
        text = f"✦ {self.mark['by']} · Shift+U undo"
        font = QFont(FONT_FAMILY, 9)
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        tag = QRectF(lowest.left(), lowest.bottom() + 4,
                     fm.horizontalAdvance(text) + 12, fm.height() + 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(tag, 4, 4)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_proposal(self, painter: QPainter, color: QColor):
        p = self.proposal
        dashed = QPen(color, 2, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        fill = QColor(color)
        fill.setAlpha(24)
        font = QFont(FONT_FAMILY, 10)
        painter.setFont(font)
        for shape in (*p.get("changed", ()), *p.get("added", ())):
            if shape.get("rect"):
                r = QRectF(*shape["rect"])
                painter.setPen(dashed)
                painter.setBrush(QBrush(fill))
                painter.drawRoundedRect(r, 6, 6)
                if shape.get("label"):
                    painter.setPen(QPen(color))
                    painter.drawText(r, Qt.AlignmentFlag.AlignCenter
                                     | Qt.TextFlag.TextWordWrap,
                                     _first_line(shape["label"], 60))
        gone = QPen(color, 2, Qt.PenStyle.DashLine)
        gone.setCosmetic(True)
        for el_id in p.get("removed", ()):
            r = self._rect_of(el_id)
            if r is None:
                continue
            painter.setPen(gone)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(r, 6, 6)
            painter.drawLine(QPointF(r.left() + 8, r.center().y()),
                             QPointF(r.right() - 8, r.center().y()))

    def _paint_banners(self, painter: QPainter, lines: list[str],
                       color: QColor):
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(FONT_FAMILY, 11)
        painter.setFont(font)
        fm = painter.fontMetrics()
        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.94)
        y = 10.0
        width = self.view.viewport().width()
        for text in lines:
            # Shortened in the middle: the keys at its end stay readable.
            text = fm.elidedText(text, Qt.TextElideMode.ElideMiddle,
                                 max(width - 180, 120))
            w = fm.horizontalAdvance(text) + 24
            # Centred, clear of the panel and theme buttons at the top left.
            r = QRectF((width - w) / 2, y, w, fm.height() + 12)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(r, 8, 8)
            painter.setPen(QPen(theme.overlay_ink(0.92)))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            y = r.bottom() + 6
        painter.restore()

    def apply_theme(self):
        self.line.apply_theme()
        self.chip.refresh()
