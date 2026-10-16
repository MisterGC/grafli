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

A data file beside the board, like the overlay files: nothing in the
``.grafli`` changes but the ``%name`` it uses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from grafli.format import THEME_COLOR_TOKENS, Board
from grafli.resources import res_dir

FILE_NAME = "palette.json"
_RE_NAME = re.compile(r'^[a-z]+$')
_RE_COLOR = re.compile(r'^(#[0-9A-Fa-f]{6}|%[a-z]+)$')


@dataclass
class Entry:
    name: str
    color: str      # "%token" (a theme token) or "#rrggbb"
    label: str


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
        entries.append(Entry(name, color, label or name.capitalize()))
    return entries, problems


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
