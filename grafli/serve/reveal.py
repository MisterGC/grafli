"""Reveal mode in a live tab: a prepared board starts with only its title
showing, and the presenter uncovers it element by element, in any order.

What is hidden is a set of element ids — every box, note and image but the
title when reveal mode began, less what the presenter revealed since. It is
presence: it lives in the server's memory only and is never written to the
board file. An element added after reveal mode began is not in the set, so
what is drawn during the talk shows at once.

The tabs other than the presenter's get a drawing of the board without the
hidden elements: the server draws ``guest_text`` instead of the file, so
nothing hidden — label, doc, bookmark — reaches them. The presenter's tab
gets that same drawing plus the hidden elements' rects and lines, which it
draws as faint outlines (``lead_drawing``). No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grafli.format import Board, parse, serialize

# The element that stays when the rest is hidden: the board's title, by the
# id the grafli skill gives it (``@ note title ...``).
TITLE_IDS = frozenset({"title"})


@dataclass
class RevealState:
    """One board's reveal mode; it outlives the board's room, so a reload of
    the presenter's tab finds the board as it left it."""
    on_open: bool = False             # hide the board on its first frame
    hidden: set[str] | None = None    # None: reveal mode is off
    started: bool = field(default=False, repr=False)

    @property
    def on(self) -> bool:
        return self.hidden is not None


def _placed(board: Board) -> dict[str, object]:
    """Every box, note and image of *board*, by id."""
    return {el.id: el for el in [*board.boxes, *board.notes, *board.images]
            if el.id}


def _ancestors(placed: dict[str, object], el_id: str) -> list[str]:
    out, seen = [], {el_id}
    parent = getattr(placed.get(el_id), "parent", "")
    while parent and parent in placed and parent not in seen:
        out.append(parent)
        seen.add(parent)
        parent = getattr(placed[parent], "parent", "")
    return out


def _holds(placed: dict[str, object], el_id: str) -> set[str]:
    """*el_id* and everything it holds, at any depth."""
    out = {el_id}
    while True:
        more = {i for i, el in placed.items()
                if getattr(el, "parent", "") in out and i not in out}
        if not more:
            return out
        out |= more


def start(board: Board) -> set[str]:
    """The ids hidden when reveal mode begins: all but the title and the
    containers it sits in."""
    placed = _placed(board)
    keep = set()
    for el_id in TITLE_IDS & placed.keys():
        keep |= {el_id, *_ancestors(placed, el_id)}
    return set(placed) - keep


def hidden_now(board: Board, hidden: set[str]) -> set[str]:
    """The ids of *board* not drawn for the guests: those in *hidden* and
    everything a hidden container holds."""
    placed = _placed(board)
    out = set()
    for el_id in hidden & placed.keys():
        out |= _holds(placed, el_id)
    return out


def neighbours(board: Board, el_id: str) -> set[str]:
    """What an arrow connects *el_id* to."""
    out = set()
    for arrow in board.arrows:
        if arrow.from_id == el_id:
            out.add(arrow.to_id)
        elif arrow.to_id == el_id:
            out.add(arrow.from_id)
    return out & _placed(board).keys()


def uncover(board: Board, el_id: str, near: bool = False) -> set[str]:
    """The ids revealing *el_id* shows: the element with what it holds and
    the containers it sits in; with *near*, the same for each element an
    arrow connects it to. Raises ``KeyError`` when *board* has no such
    element."""
    placed = _placed(board)
    if el_id not in placed:
        raise KeyError(el_id)
    out = set()
    for one in {el_id, *(neighbours(board, el_id) if near else ())}:
        out |= _holds(placed, one) | set(_ancestors(placed, one))
    return out


def guest_board(board: Board, hidden: set[str]) -> Board:
    """*board* as the guests see it: without the hidden elements, the
    arrows to them, and the bookmarks and flows that would show them."""
    gone = hidden_now(board, hidden)
    for el in list(board.boxes):
        if el.id in gone:
            board.remove_box(el)
    for el in list(board.notes):
        if el.id in gone:
            board.remove_note(el)
    for el in list(board.images):
        if el.id in gone:
            board.remove_image(el)
    for arrow in list(board.arrows):
        if arrow.from_id in gone or arrow.to_id in gone:
            board.remove_arrow(arrow)
    dropped = set()
    for bm in list(board.bookmarks):
        if gone & set(bm.focus):
            dropped.add(bm.id)
            board.remove_bookmark(bm)
    for flow in list(board.flows):
        if flow.auto_start in gone or any(s.ref in dropped
                                          for s in flow.steps):
            board.remove_flow(flow)
    return board


def guest_text(text: str, hidden: set[str]) -> str | None:
    """The board text the guests' drawing is made from, or None when
    nothing of *text* is hidden."""
    board = parse(text)
    if not hidden_now(board, hidden):
        return None
    return serialize(guest_board(board, hidden))


def _line_key(line: dict) -> str:
    return line.get("id") or "->".join(line["ends"])


def lead_drawing(full: dict, guest: dict | None, hidden: int) -> dict:
    """What the presenter's tab draws in reveal mode: the guests' drawing,
    with the board's whole bounds and its hidden elements and lines marked
    ``hidden`` for the faint outlines; ``board.reveal`` says how many
    elements are hidden."""
    if guest is None:
        board = {**full["board"], "reveal": {"hidden": 0}}
        return {**full, "board": board}
    shown = guest["board"]
    seen = {e["id"] for e in shown["elements"]}
    lines = {_line_key(line) for line in shown["lines"]}
    board = {**shown, "bounds": full["board"]["bounds"],
             "elements": [*shown["elements"],
                          *({**e, "hidden": True}
                            for e in full["board"]["elements"]
                            if e["id"] not in seen)],
             "hidden_lines": [line for line in full["board"]["lines"]
                              if _line_key(line) not in lines],
             "reveal": {"hidden": hidden}}
    return {**guest, "board": board,
            "docs": {**full.get("docs", {}), **guest.get("docs", {})}}
