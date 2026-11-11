"""One palette per map: ``<stem>-res/palette.json`` and ``%name``.

A map is a board plus the sub-boards in its vault. The palette file in the
map's vault names colours::

    {"entries": {
        "storage": {"color": "%teal", "label": "Persistence"},
        "hot":     {"color": "#C0392B", "label": "Hot path"}
    }}

A box, note or connector uses ``%storage`` like a theme token, and every board
of the map resolves it against the same file, so changing an entry recolours
them all. An entry's colour is a theme token (it follows light/dark) or a hex.
A name is lowercase letters, as theme tokens are, and may not shadow one: the
theme token wins and ``diagnose`` reports the entry.

An entry can also carry a whole kind of box — a plugin, a third-party
tool, a pseudo-state — so a board does not repeat the same tokens on every
box of the kind::

    "plugin": {"color": "%teal", "label": "Plugin",
               "icon": "lead:puzzle", "outline": "dashed",
               "bold": true, "size": "small"}

A box coloured ``%plugin`` then draws with that icon, outline, weight and
label size (``look``); a token written on the box wins over its kind's. The
kind is resolved where the box is drawn, so the file keeps only what was
written.

A data file beside the board, like the overlay files: nothing in the
``.grafli`` changes but the ``%name`` it uses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from grafli.format import (BOX_SIZES, ICON_PLACEMENTS, THEME_COLOR_TOKENS,
                           Board, Box, emphasis_from_flags, split_icon)
from grafli.resources import res_dir

FILE_NAME = "palette.json"
_RE_NAME = re.compile(r'^[a-z]+$')
_RE_COLOR = re.compile(r'^(#[0-9A-Fa-f]{6}|%[a-z]+)$')
_RE_SIZE = re.compile(r'^(' + BOX_SIZES + r')$')
OUTLINES = ("dashed", "dotted")


@dataclass
class Entry:
    name: str
    color: str      # "%token" (a theme token) or "#rrggbb"
    label: str
    # The kind a box coloured with the entry takes, each "" / False = none:
    icon: str = ""      # a ``*`` token's value: "puzzle", "lead:puzzle"
    outline: str = ""   # "dashed" or "dotted"
    bold: bool = False
    size: str = ""      # a ``~size`` value: "small", "large", "18"

    @property
    def is_kind(self) -> bool:
        """True when the entry gives a box more than its colour."""
        return bool(self.icon or self.outline or self.bold or self.size)


@dataclass
class Problem:
    name: str       # the entry, or "" for the file as a whole
    message: str
    shadows: bool = False


def _vault_owner(directory: Path) -> Path | None:
    """The board whose vault *directory* is, or None."""
    if not directory.name.endswith("-res"):
        return None
    owner = directory.parent / f"{directory.name[:-len('-res')]}.grafli"
    return owner if owner.is_file() else None


def candidate_paths(grafli_path: Path) -> list[Path]:
    """Where the map's palette may live, outermost board first: the vault of
    every board this one sits inside, then its own vault."""
    grafli_path = Path(grafli_path).resolve()
    paths = [res_dir(grafli_path) / FILE_NAME]
    directory = grafli_path.parent
    while _vault_owner(directory) is not None:
        paths.append(directory / FILE_NAME)
        directory = directory.parent
    return paths[::-1]


def palette_path(grafli_path: Path) -> Path | None:
    """The map's palette file: the outermost one that exists, so every board
    of a map reads the same file."""
    for path in candidate_paths(grafli_path):
        if path.is_file():
            return path
    return None


def parse_palette(text: str) -> tuple[list[Entry], list[Problem]]:
    """The usable entries of a palette file and what is wrong with it.

    An entry that is malformed or shadows a theme token is left out and
    reported; the rest still apply.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [Problem("", f"not JSON: {e.msg} (line {e.lineno})")]
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return [], [Problem("", "needs an 'entries' object")]
    entries: list[Entry] = []
    problems: list[Problem] = []
    for name, value in data["entries"].items():
        if not _RE_NAME.match(name):
            problems.append(Problem(
                name, f"name {name!r} must be lowercase letters a-z"))
            continue
        if name in THEME_COLOR_TOKENS:
            problems.append(Problem(
                name, f"%{name} shadows the theme token %{name}", True))
            continue
        if not isinstance(value, dict):
            problems.append(Problem(name, f"%{name} must be an object"))
            continue
        color, label = value.get("color", ""), value.get("label", "")
        if not isinstance(color, str) or not _RE_COLOR.match(color):
            problems.append(Problem(
                name, f"%{name}: 'color' must be a #rrggbb or a %token"))
            continue
        if color.startswith("%") and color[1:] not in THEME_COLOR_TOKENS:
            problems.append(Problem(
                name, f"%{name}: {color} is not a theme token"))
            continue
        if not isinstance(label, str):
            problems.append(Problem(name, f"%{name}: 'label' must be a string"))
            continue
        kind_problem = _kind_problem(name, value)
        if kind_problem:
            problems.append(Problem(name, kind_problem))
            continue
        entries.append(Entry(name, color, label or name.capitalize(),
                             icon=value.get("icon", ""),
                             outline=value.get("outline", ""),
                             bold=value.get("bold", False),
                             size=str(value.get("size", ""))))
    return entries, problems


def _kind_problem(name: str, value: dict) -> str:
    """What is wrong with the kind fields of entry *name*, or ""."""
    icon = value.get("icon", "")
    if not isinstance(icon, str):
        return f"%{name}: 'icon' must be a string such as \"lead:puzzle\""
    if icon:
        from grafli.iconset import has_icon
        place, glyph = split_icon(icon)
        if ":" in icon and place not in ICON_PLACEMENTS:
            return (f"%{name}: icon {icon!r} — a placement is "
                    + " or ".join(ICON_PLACEMENTS))
        if not has_icon(glyph):
            return f"%{name}: {icon!r} is not an icon"
    outline = value.get("outline", "")
    if outline not in ("", *OUTLINES):
        return f"%{name}: 'outline' must be \"dashed\" or \"dotted\""
    if not isinstance(value.get("bold", False), bool):
        return f"%{name}: 'bold' must be true or false"
    size = value.get("size", "")
    if isinstance(size, int) and not isinstance(size, bool):
        size = str(size)
    if not isinstance(size, str) or (size and not _RE_SIZE.match(size)):
        return f"%{name}: 'size' must be a box size such as \"small\" or 18"
    return ""


def read_palette(path: Path | None) -> tuple[list[Entry], list[Problem]]:
    if path is None:
        return [], []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return [], [Problem("", f"cannot read: {e.strerror}")]
    return parse_palette(text)


def attach_names(board: Board, grafli_path: Path | None) -> list[Entry]:
    """Tell *board* its map palette's names, so a ``%name`` among them writes
    the board as v4; returns the entries."""
    entries = load_palette(grafli_path)
    board.palette_names = frozenset(e.name for e in entries)
    return entries


def load_palette(grafli_path: Path | None) -> list[Entry]:
    """The entries every board of *grafli_path*'s map resolves ``%name``
    against; empty without a board file or a palette."""
    if grafli_path is None:
        return []
    return read_palette(palette_path(Path(grafli_path)))[0]


# The shown map's kinds, ``{name: entry}`` for the entries that carry one.
# Set by the view for the board it loads, as ``theme.set_map_palette`` is
# for the colours.
_kinds: dict[str, Entry] = {}


def set_kinds(entries: list[Entry]) -> bool:
    """Make *entries*' kinds the ones ``look`` applies; returns whether
    they changed."""
    global _kinds
    kinds = {e.name: e for e in entries if e.is_kind}
    if kinds == _kinds:
        return False
    _kinds = kinds
    return True


def kind_of(color: str) -> Entry | None:
    """The entry whose kind a box coloured *color* takes, or None."""
    if not color.startswith("%"):
        return None
    return _kinds.get(color[1:])


def look(box: Box) -> Box:
    """*box* as it draws: its own tokens, and for each one it leaves out,
    its kind's. *box* itself when its colour carries no kind."""
    entry = kind_of(box.color)
    if entry is None:
        return box
    changes: dict = {}
    if entry.icon and not box.icon:
        changes["icon_placement"], changes["icon"] = split_icon(entry.icon)
    if entry.outline and not box.border:
        changes["border"] = entry.outline
    if entry.size and not box.textsize:
        changes["textsize"] = entry.size
    if entry.bold and "bold" not in box.emphasis.split():
        changes["emphasis"] = emphasis_from_flags(
            {*box.emphasis.split(), "bold"})
    return replace(box, **changes) if changes else box
