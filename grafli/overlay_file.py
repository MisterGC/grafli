"""Overlay files: analysis data an agent or script writes beside a board.

One JSON file per overlay, ``<stem>-res/<name>.overlay.json``, colours the
board's elements by id — a category or a value each — and carries the legend,
a note and code refs per element, and where the data came from. Nothing in the
``.grafli`` changes; the files are derived data the producer regenerates.
``OverlayProvider`` reads one into a ``HeatReading`` for the heatmap renderer.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from grafli.format import Board
from grafli.heat import HeatDetail, HeatLegend, HeatReading
from grafli.resources import res_dir

SUFFIX = ".overlay.json"


@dataclass
class Category:
    id: str
    label: str
    color: str


@dataclass
class Scale:
    min: float
    max: float
    low: str = "Low"
    high: str = "High"


@dataclass
class Entry:
    value: float | None = None
    category: str = ""
    note: str = ""
    refs: list[str] = field(default_factory=list)


@dataclass
class Overlay:
    name: str
    title: str
    kind: str                      # "category" | "value"
    entries: dict[str, Entry]
    producer: str = ""
    created: str = ""
    repo: str = ""
    revision: str = ""
    categories: list[Category] = field(default_factory=list)
    scale: Scale | None = None


def overlay_paths(grafli_path: Path) -> list[Path]:
    """The board's overlay files, in file-name order."""
    d = res_dir(grafli_path)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.name.endswith(SUFFIX) and p.is_file())


def overlay_name(path: Path) -> str:
    return path.name[:-len(SUFFIX)]


def _str(data: dict, key: str, where: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{where}'{key}' must be a string")
    return value


def _number(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number")
    return float(value)


def parse_overlay(text: str, name: str) -> Overlay:
    """Read one overlay file; ValueError names what is wrong with it."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {e.msg} (line {e.lineno})") from None
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")

    kind = data.get("kind")
    if kind not in ("category", "value"):
        raise ValueError("'kind' must be \"category\" or \"value\"")
    overlay = Overlay(name=name, title=_str(data, "title", "") or name,
                      kind=kind, entries={},
                      producer=_str(data, "producer", ""),
                      created=_str(data, "created", ""))

    source = data.get("source")
    if source is not None:
        if not isinstance(source, dict):
            raise ValueError("'source' must be an object")
        overlay.repo = _str(source, "repo", "source ")
        overlay.revision = _str(source, "revision", "source ")

    if kind == "category":
        cats = data.get("categories")
        if not isinstance(cats, list) or not cats:
            raise ValueError("a category overlay needs a 'categories' list")
        for c in cats:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str):
                raise ValueError("each category needs a string 'id'")
            where = f"category '{c['id']}': "
            color = _str(c, "color", where)
            if not color:
                raise ValueError(f"{where}'color' is missing")
            overlay.categories.append(
                Category(c["id"], _str(c, "label", where) or c["id"], color))
    else:
        scale = data.get("scale")
        if not isinstance(scale, dict):
            raise ValueError("a value overlay needs a 'scale' object")
        lo = _number(scale.get("min"), "scale 'min'")
        hi = _number(scale.get("max"), "scale 'max'")
        if hi <= lo:
            raise ValueError("scale 'max' must be above 'min'")
        overlay.scale = Scale(lo, hi, _str(scale, "low", "scale ") or "Low",
                              _str(scale, "high", "scale ") or "High")

    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("'entries' must be an object keyed by element id")
    known = {c.id for c in overlay.categories}
    for elem_id, e in entries.items():
        where = f"entry '{elem_id}': "
        if not isinstance(e, dict):
            raise ValueError(f"{where}must be an object")
        entry = Entry(note=_str(e, "note", where))
        refs = e.get("refs", [])
        if (not isinstance(refs, list)
                or not all(isinstance(r, str) for r in refs)):
            raise ValueError(f"{where}'refs' must be a list of strings")
        entry.refs = list(refs)
        if kind == "category":
            entry.category = _str(e, "category", where)
            if entry.category not in known:
                raise ValueError(
                    f"{where}unknown category '{entry.category}'")
        else:
            entry.value = _number(e.get("value"), f"{where}'value'")
        overlay.entries[elem_id] = entry
    return overlay


def load_overlay(path: Path) -> Overlay:
    """Read and parse one overlay file; ValueError on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(e.strerror or str(e)) from None
    return parse_overlay(text, overlay_name(path))


def repo_path(overlay: Overlay, base_dir: Path) -> Path | None:
    """The source repo, a relative one taken from the board's directory."""
    if not overlay.repo:
        return None
    path = Path(overlay.repo).expanduser()
    return path if path.is_absolute() else base_dir / path


def head_revision(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def stale_line(overlay: Overlay, base_dir: Path) -> str:
    """The legend's stale line, or "" while the data matches the repo.

    Revisions match when one is a prefix of the other, so a short hash in the
    file matches the full HEAD.
    """
    repo = repo_path(overlay, base_dir)
    if repo is None or not overlay.revision:
        return ""
    head = head_revision(repo)
    if head is None:
        return f"stale? cannot read the HEAD of {overlay.repo}"
    rev = overlay.revision.lower()
    if head.startswith(rev) or rev.startswith(head):
        return ""
    return f"stale: analysed at {overlay.revision[:7]}, repo is at {head[:7]}"


class OverlayProvider:
    """Reads one overlay file as a heat reading.

    A category colours its elements with the category's colour; a value maps
    onto the file's scale (not onto the board's maximum) and the heat
    gradient. Elements without an entry draw as no data.
    """

    def __init__(self, overlay: Overlay, base_dir: Path):
        self.overlay = overlay
        self.base_dir = base_dir
        self.stale = stale_line(overlay, base_dir)

    def analysable(self, board: Board) -> bool:
        return True

    def ref_base(self) -> Path:
        """Where an entry's relative ``@ref`` points into: the source repo
        when the file names one, else the board's directory."""
        return repo_path(self.overlay, self.base_dir) or self.base_dir

    def read(self, board: Board) -> HeatReading:
        ov = self.overlay
        legend = HeatLegend(ov.title, producer=ov.producer, stale=self.stale)
        reading = HeatReading(legend=legend, no_data=True)
        if ov.kind == "category":
            cats = {c.id: c for c in ov.categories}
            legend.categories = [(c.label, c.color) for c in ov.categories]
            for elem_id, e in ov.entries.items():
                reading.colors[elem_id] = cats[e.category].color
                reading.details[elem_id] = HeatDetail(
                    cats[e.category].label, e.note, e.refs)
        else:
            sc = ov.scale
            legend.low, legend.high = sc.low, sc.high
            for elem_id, e in ov.entries.items():
                heat = (e.value - sc.min) / (sc.max - sc.min)
                reading.values[elem_id] = max(0.0, min(1.0, heat))
                reading.details[elem_id] = HeatDetail(
                    f"{e.value:g}", e.note, e.refs)
        return reading
