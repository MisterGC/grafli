"""What an edit changed on a board, element by element, and the agent's
proposals.

The agent's edit lands at once when it changes at most ``PROPOSE_OVER``
elements (boxes, notes, images and arrows, each added, removed or changed
counted once); the tabs then mark the elements it touched in the agent's
colour, with its name. A larger change does not touch the file: it waits as
a ``Proposal`` on the board until the presenter takes it or drops it.

An element is named the way a tab knows it: a box, note or image by its id,
an arrow by its id or else by ``"<from>-><to>"``. No Qt.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from grafli.format import Board

# The agent's change that is larger than this arrives as a proposal.
PROPOSE_OVER = 5

_KINDS = (("boxes", "box"), ("notes", "note"), ("images", "image"),
          ("arrows", "arrow"))
_PLURAL = {"box": "boxes", "note": "notes", "image": "images",
           "arrow": "arrows"}

_proposals = itertools.count(1)


def element_key(el) -> str:
    if hasattr(el, "from_id"):
        return el.id or f"{el.from_id}->{el.to_id}"
    return el.id


@dataclass
class Changes:
    """The elements of a board one edit added, removed and changed, by key,
    each with its kind."""
    added: dict[str, str] = field(default_factory=dict)
    removed: dict[str, str] = field(default_factory=dict)
    changed: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def summary(self) -> str:
        """``"+3 boxes, −1 box, ~1 arrow"``: what the edit does, in counts."""
        parts = []
        for sign, part in (("+", self.added), ("−", self.removed),
                           ("~", self.changed)):
            for _attr, kind in _KINDS:
                n = sum(1 for k in part.values() if k == kind)
                if n:
                    parts.append(f"{sign}{n} {kind if n == 1 else _PLURAL[kind]}")
        return ", ".join(parts)


def changes(before: Board, after: Board) -> Changes:
    """What turned *before* into *after*."""
    out = Changes()
    for attr, kind in _KINDS:
        old = {element_key(e): e for e in getattr(before, attr)}
        new = {element_key(e): e for e in getattr(after, attr)}
        for key, el in new.items():
            if key not in old:
                out.added[key] = kind
            elif old[key] != el:
                out.changed[key] = kind
        for key in old.keys() - new.keys():
            out.removed[key] = kind
    return out


@dataclass
class Proposal:
    """The agent's change that waits for the presenter: the file's text it
    was made against and the text it would make."""
    by: str                       # the agent's name, as the tabs show it
    author: str                   # whose undo history it joins once taken
    before: str
    text: str
    changes: Changes
    about: str = ""               # what it does, in the agent's words
    # Where the proposed elements are drawn: what the tabs outline.
    added: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_proposals))

    def message(self, color: str, shapes: bool = True) -> dict:
        """What a tab is told of it; without *shapes* only who proposes how
        much (a guest's tab while reveal mode hides part of the board): no
        outlines, and not what the agent says it does, which may name a
        hidden element."""
        msg = {"id": self.id, "by": self.by, "color": color,
               "count": self.changes.count,
               "summary": self.changes.summary()}
        if shapes:
            msg.update(about=self.about, added=self.added,
                       changed=self.changed,
                       removed=sorted(self.changes.removed))
        return msg


def shapes(drawing: dict, keys) -> list[dict]:
    """The elements *keys* names as *drawing* draws them: a box, note or
    image with its rect and label, an arrow with its lines."""
    keys = set(keys)
    board = drawing.get("board") or {}
    out, seen = [], set()
    for e in board.get("elements", []):
        if e["id"] in keys and e["id"] not in seen and (e.get("rect")
                                                        or e.get("paths")):
            seen.add(e["id"])
            shape = {"id": e["id"], "kind": e["kind"],
                     "label": e.get("label", "")}
            if e.get("rect"):
                shape["rect"] = e["rect"]
            else:
                shape["paths"] = e["paths"]
            out.append(shape)
    for line in board.get("lines", []):
        key = line.get("id") or "->".join(line["ends"])
        if key in keys and key not in seen:
            seen.add(key)
            out.append({"id": key, "kind": "arrow", "label": "",
                        "paths": line["paths"]})
    return out
