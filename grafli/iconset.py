"""Sketchnote symbol set for grafli (visual vocabulary, issue #120).

Symbols are authored as one SVG sheet — ``assets/sketchnote_symbols.svg``,
hand-tweakable in Inkscape — and rendered by element id via QSvgRenderer, so
the set stays vector-crisp at any zoom and editable without code changes.
Boxes and notes reference symbols by name via the ``*name`` sigil (see
grafli.format). Tinting substitutes the sheet's canonical ink colour in the
SVG source; one renderer is cached per tint.

Number badges (``*0`` … ``*99``, filled: ``*solid-0`` … ``*solid-99``) are
composed at paint time (circle + digit) — a static sheet can't carry every
number. ``money`` and ``link`` predate the
sheet and remain hand-drawn painters until it gains them.

A board's own symbols are SVG files in ``<stem>-res/icons/`` (issue #299):
``icons/monitor.svg`` is ``*monitor`` on that board, in every placement.
``BoardIcons`` lists that folder; each function here takes it as ``icons``
and looks a name up among the built-in symbols first, then there. Its
``currentColor``, its black and an unset fill take the tint, so it draws in
the ink a built-in symbol draws in.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPen,
                           QPixmap)
from PySide6.QtSvg import QSvgRenderer

from grafli import theme
from grafli.constants import NOTE_FONT_FAMILY
from grafli.format import ICON_ALIASES, SOLID_NUMBER_PREFIX
from grafli.resources import res_dir

_SHEET = Path(__file__).parent / "assets" / "sketchnote_symbols.svg"
# Canonical ink colour of the sheet; tinting substitutes this in the source.
_SHEET_INK = "#2d3033"

# Display order for the picker grid; also the set of valid (non-digit) names.
SEMANTIC_NAMES = [
    "person", "robot", "gear", "database", "document", "cloud", "globe",
    "target", "lightbulb", "question", "warning", "check", "cross", "flag",
    "clock", "calendar", "magnifier", "puzzle", "lock", "plant",
]
EMPHASIS_NAMES = [
    "star", "heart", "flame", "exclamation", "brain", "lightning",
    "repeat", "exercise", "performance",
]
LEGACY_NAMES = ["money", "link"]
# Legacy names group with the semantic block (they are semantic symbols).
ICON_NAMES = SEMANTIC_NAMES + LEGACY_NAMES + EMPHASIS_NAMES

_SHEET_NAMES = frozenset(SEMANTIC_NAMES + EMPHASIS_NAMES)

_sheet_bytes: bytes | None = None
_renderers: dict[int, QSvgRenderer] = {}
_pixmap_cache: dict[tuple, QPixmap] = {}


# ── a board's own symbols: <stem>-res/icons/<name>.svg ──

BOARD_ICON_DIR = "icons"
# A file's stem is its symbol name when a ``*name`` token can spell it.
_RE_BOARD_ICON_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def board_icon_dir(grafli_path: Path) -> Path:
    """The folder that holds the board's own symbols."""
    return res_dir(Path(grafli_path)) / BOARD_ICON_DIR


class BoardIcons:
    """The SVG symbols in one board's icon folder, by name. The folder is
    listed again whenever it changes, so an icon added while the board is
    open shows up without reloading it."""

    _by_folder: dict[Path, "BoardIcons"] = {}

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._stamp: int | None = None
        self._paths: dict[str, Path] = {}

    @classmethod
    def of(cls, grafli_path: Path | None) -> "BoardIcons | None":
        """The icons of the board at *grafli_path* (one per folder), None
        for a board without a file."""
        if grafli_path is None:
            return None
        folder = board_icon_dir(grafli_path).resolve()
        icons = cls._by_folder.get(folder)
        if icons is None:
            icons = cls._by_folder[folder] = cls(folder)
        return icons

    def _listing(self) -> dict[str, Path]:
        try:
            stamp = self.folder.stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp != self._stamp:
            self._stamp = stamp
            self._paths = {}
            if stamp is not None:
                for f in sorted(self.folder.glob("*.svg")):
                    if (_RE_BOARD_ICON_NAME.match(f.stem)
                            and not _is_number_name(f.stem) and f.is_file()):
                        self._paths[f.stem] = f
        return self._paths

    def names(self) -> list[str]:
        """The folder's symbol names, sorted; a name a built-in symbol
        already has is left out — the built-in one wins — and so is a file
        that is not a readable SVG."""
        return [n for n in self._listing() if self.path(n) is not None]

    def _file(self, name: str) -> Path | None:
        """The folder's file for *name*, readable or not; None for a
        built-in name."""
        return None if _builtin(name) else self._listing().get(name)

    def path(self, name: str) -> Path | None:
        """The file of icon *name*, None when there is none or it is not a
        readable SVG (it would draw nothing)."""
        f = self._file(name)
        return f if f is not None and _readable(f) else None

    def unreadable(self, name: str) -> Path | None:
        """The file for *name* when it is in the folder but is not a
        readable SVG — what ``diagnose`` names; None otherwise."""
        f = self._file(name)
        return f if f is not None and not _readable(f) else None

    def __contains__(self, name: str) -> bool:
        return self.path(name) is not None


_board_renderers: dict[tuple, QSvgRenderer] = {}
# A colour value an icon's own SVG draws its ink with: these take the tint.
_RE_INK = re.compile(
    r"((?:fill|stroke|color)\s*[=:]\s*[\"']?\s*)"
    r"(currentcolor|#000000|#000|black|" + _SHEET_INK + r")\b",
    re.IGNORECASE)
_RE_SVG_TAG = re.compile(rb"<svg\b[^>]*>", re.IGNORECASE)


def tint_svg(data: bytes, tint: str) -> bytes:
    """*data*, an SVG, drawn in *tint*: ``currentColor``, black and the
    sheet's ink become the tint, and so does a fill left unset (SVG's
    default is black). Any other colour stays as it is drawn."""
    text = data.decode("utf-8", errors="replace")
    text = _RE_INK.sub(lambda m: m.group(1) + tint, text)
    out = text.encode("utf-8")
    tag = _RE_SVG_TAG.search(out)
    if tag is not None:
        attrs = tag.group(0)
        extra = b""
        if not re.search(rb"[\s\"';]fill\s*[=:]", attrs):
            extra += b' fill="' + tint.encode() + b'"'
        if not re.search(rb"\scolor\s*=", attrs):
            extra += b' color="' + tint.encode() + b'"'
        if extra:
            end = tag.end() - (2 if attrs.endswith(b"/>") else 1)
            out = out[:end] + extra + out[end:]
    return out


def _board_renderer(path: Path, color: QColor) -> QSvgRenderer | None:
    """A renderer of the board icon at *path* tinted to *color*, cached per
    file version and tint; None when the file can't be read as an SVG."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), stamp, color.rgba())
    renderer = _board_renderers.get(key)
    if renderer is None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        renderer = QSvgRenderer(QByteArray(tint_svg(data, color.name())))
        _board_renderers[key] = renderer
    return renderer if renderer.isValid() else None


def _readable(path: Path) -> bool:
    """True when the file at *path* parses as an SVG."""
    return _board_renderer(path, QColor(_SHEET_INK)) is not None


def _is_number_name(name: str) -> bool:
    digits = (name[len(SOLID_NUMBER_PREFIX):]
              if name.startswith(SOLID_NUMBER_PREFIX) else name)
    return digits.isdigit()


def _builtin(name: str) -> str:
    """Canonical name of a built-in symbol or number badge, "" if none."""
    name = ICON_ALIASES.get(name, name)
    if name in _SHEET_NAMES or name in _LEGACY_PAINTERS:
        return name
    solid = name.startswith(SOLID_NUMBER_PREFIX)
    digits = name[len(SOLID_NUMBER_PREFIX):] if solid else name
    if digits.isdigit() and int(digits) <= 99:
        return (SOLID_NUMBER_PREFIX if solid else "") + str(int(digits))
    return ""


def resolve_icon(name: str, icons: BoardIcons | None = None) -> str:
    """Canonical name for ``name`` — alias-aware (``bulb`` → ``lightbulb``);
    number badges 0–99, outlined or ``solid-``, pass through zero-stripped;
    then a symbol of the board's own *icons*. "" if unknown."""
    builtin = _builtin(name)
    if builtin:
        return builtin
    if icons is not None and name in icons:
        return name
    return ""


def number_badge(name: str) -> tuple[str, bool] | None:
    """(digits, filled) for a number badge name, None for any other name."""
    name = resolve_icon(name)
    if name.startswith(SOLID_NUMBER_PREFIX):
        return name[len(SOLID_NUMBER_PREFIX):], True
    return (name, False) if name.isdigit() else None


def has_icon(name: str, icons: BoardIcons | None = None) -> bool:
    return bool(resolve_icon(name, icons))


def _board_icon(name: str, icons: BoardIcons | None) -> Path | None:
    """The file of board symbol *name*, None for a built-in or unknown."""
    return icons.path(name) if icons is not None else None


def _element_id(name: str) -> str:
    return name.capitalize()


def _renderer_for(color: QColor) -> QSvgRenderer:
    """A renderer of the sheet tinted to ``color`` (cached per tint)."""
    global _sheet_bytes
    key = color.rgba()
    renderer = _renderers.get(key)
    if renderer is None:
        if _sheet_bytes is None:
            _sheet_bytes = _SHEET.read_bytes()
        data = _sheet_bytes
        tint = color.name().encode()
        if tint != _SHEET_INK.encode():
            data = data.replace(_SHEET_INK.encode(), tint)
        renderer = QSvgRenderer(QByteArray(data))
        _renderers[key] = renderer
    return renderer


def icon_aspect(name: str, icons: BoardIcons | None = None) -> float:
    """Width/height ratio of the symbol's drawing (1.0 for digits/legacy) —
    for layout that reserves non-square room (e.g. the lead gutter)."""
    own = _board_icon(name, icons)
    if own is not None:
        renderer = _board_renderer(own, QColor(_SHEET_INK))
        if renderer is not None:
            box = renderer.viewBoxF()
            if box.height() > 0:
                return box.width() / box.height()
        return 1.0
    name = resolve_icon(name)
    if name in _SHEET_NAMES:
        b = _renderer_for(QColor(_SHEET_INK)).boundsOnElement(_element_id(name))
        if b.height() > 0:
            return b.width() / b.height()
    return 1.0


def _fitted(bounds: QRectF, rect: QRectF) -> QRectF:
    """*bounds*' shape scaled to fit *rect*, centred in it."""
    s = min(rect.width() / bounds.width(), rect.height() / bounds.height())
    w, h = bounds.width() * s, bounds.height() * s
    return QRectF(rect.left() + (rect.width() - w) / 2,
                  rect.top() + (rect.height() - h) / 2, w, h)


def paint_icon(painter: QPainter, name: str, rect: QRectF,
               color: QColor, icons: BoardIcons | None = None) -> None:
    """Draw ``name`` aspect-fitted and centred into ``rect`` in the painter's
    current coordinate system. Resolution-independent — stays crisp at any
    zoom (use this on the canvas; a cached pixmap would pixelate)."""
    own = _board_icon(name, icons)
    name = resolve_icon(name, icons)
    if not name or rect.width() <= 0 or rect.height() <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    number = number_badge(name)
    if own is not None:
        renderer = _board_renderer(own, color)
        if renderer is not None:
            box = renderer.viewBoxF()
            if box.width() > 0 and box.height() > 0:
                renderer.render(painter, _fitted(box, rect))
    elif number is not None:
        _paint_number(painter, *number, rect, color)
    elif name in _LEGACY_PAINTERS:
        _paint_legacy(painter, name, rect, color)
    else:
        renderer = _renderer_for(color)
        eid = _element_id(name)
        bounds = renderer.boundsOnElement(eid)
        if bounds.width() > 0 and bounds.height() > 0:
            renderer.render(painter, eid, _fitted(bounds, rect))
    painter.restore()


def icon_pixmap(name: str, color: QColor, size: float,
                dpr: float = 1.0,
                icons: BoardIcons | None = None) -> QPixmap | None:
    """Return a cached, tinted pixmap for ``name`` at ``size`` logical px.

    For fixed-size UI (the picker grid); on the canvas use ``paint_icon`` so
    the symbol stays vector-crisp under zoom.
    """
    if not has_icon(name, icons):
        return None
    own = _board_icon(name, icons)
    name = resolve_icon(name, icons)
    size = max(4.0, float(size))
    # A board's own icon is keyed by its file and version, not its name.
    source = ((str(own), own.stat().st_mtime_ns) if own is not None
              and own.exists() else name)
    key = (source, color.rgba(), round(size, 1), round(dpr, 2))
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached

    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    # The pixmap carries the dpr, so the painter works in logical units.
    paint_icon(p, name, QRectF(0, 0, size, size), color, icons)
    p.end()

    _pixmap_cache[key] = pm
    return pm


def paint_badge(painter: QPainter, name: str, rect: QRectF,
                color: QColor, icons: BoardIcons | None = None) -> None:
    """Corner-badge rendering (``*badge:`` placement, issue #122): the symbol
    sits on a soft paper disc so it stays legible on any node fill."""
    if (not has_icon(name, icons) or rect.width() <= 0
            or rect.height() <= 0):
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    plate = QColor(theme.ICON_BADGE_PLATE)
    plate.setAlphaF(0.95)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(plate)
    painter.drawEllipse(rect)
    painter.restore()
    inset = min(rect.width(), rect.height()) * badge_inset(name)
    paint_icon(painter, name, rect.adjusted(inset, inset, -inset, -inset),
               color, icons)


def badge_inset(name: str) -> float:
    """How far a badge's symbol sits inside its paper disc, as a fraction of
    the disc: a number's ring hugs the disc's rim so its digits get the room
    (issue #305), any other symbol keeps a margin."""
    return _NUMBER_BADGE_INSET if number_badge(name) else 0.16


def number_badge_side(name: str, cap_px: float) -> float:
    """The corner-badge side at which number badge ``name`` draws its digits
    at least ``cap_px`` tall — the cap height of the label beside it, so the
    order reads at board zoom (issue #305). 0 for any other name."""
    number = number_badge(name)
    if number is None:
        return 0.0
    return number_side(number[0], cap_px) / (1 - 2 * _NUMBER_BADGE_INSET)


# ── number badges (composed: circle + digit) ──

# A number badge's ring sits this far inside its corner disc (of the side).
_NUMBER_BADGE_INSET = 0.05
# The digits' pixel size as a fraction of the circle, one digit and two.
_DIGIT_SCALE = {1: 0.6, 2: 0.48}
_DIGIT_MARGIN = 1.06
_digit_cap_ratio: float | None = None


def _digit_font(px: float) -> QFont:
    font = QFont(NOTE_FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, math.ceil(px)))
    return font


def _cap_ratio() -> float:
    """Cap height over pixel size of the digits' face."""
    global _digit_cap_ratio
    if _digit_cap_ratio is None:
        cap = QFontMetricsF(_digit_font(100)).capHeight()
        _digit_cap_ratio = cap / 100 if cap > 0 else 0.7
    return _digit_cap_ratio


def number_side(digits: str, cap_px: float) -> float:
    """The circle side at which ``digits`` draw at least ``cap_px`` tall.
    The face's cap height is a metric, a drawn digit's ink can fall a
    little short of it: the margin keeps the ink at full height."""
    return (cap_px * _DIGIT_MARGIN / _cap_ratio()
            / _DIGIT_SCALE[min(len(digits), 2)])


def _paint_number(p: QPainter, digits: str, filled: bool, rect: QRectF,
                  color: QColor):
    """An outlined circle around the digits, or for ``filled`` a disc in
    ``color`` with the digits knocked out in the ink that reads on it."""
    side = min(rect.width(), rect.height())
    stroke = max(1.2, side * 0.055)
    square = QRectF(rect.left() + (rect.width() - side) / 2,
                    rect.top() + (rect.height() - side) / 2, side, side)
    inset = stroke / 2 + side * 0.02
    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(color if filled else Qt.BrushStyle.NoBrush)
    p.drawEllipse(square.adjusted(inset, inset, -inset, -inset))
    if filled:
        p.setPen(theme.ink_on(color))
    p.setFont(_digit_font(side * _DIGIT_SCALE[min(len(digits), 2)]))
    p.drawText(square, Qt.AlignmentFlag.AlignCenter, digits)


# ── legacy painters (24-unit viewBox) — until the sheet gains these ──

_VIEWBOX = 24.0
_STROKE = 1.8


def _dot(p: QPainter, cx: float, cy: float, r: float):
    """A small filled disc in the current pen colour."""
    color = p.pen().color()
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    p.restore()


def _money(p: QPainter):
    # banknote: rounded rect + a centre coin
    p.drawRoundedRect(QRectF(2.5, 7.0, 19.0, 10.0), 2.0, 2.0)
    p.drawEllipse(QRectF(10.0, 9.5, 4.0, 4.0))
    _dot(p, 5.6, 12.0, 0.7)
    _dot(p, 18.4, 12.0, 0.7)


def _link(p: QPainter):
    p.drawRoundedRect(QRectF(3.5, 9.0, 10.0, 6.0), 3.0, 3.0)
    p.drawRoundedRect(QRectF(10.5, 9.0, 10.0, 6.0), 3.0, 3.0)


_LEGACY_PAINTERS = {"money": _money, "link": _link}


def _paint_legacy(p: QPainter, name: str, rect: QRectF, color: QColor):
    side = min(rect.width(), rect.height())
    p.translate(rect.left() + (rect.width() - side) / 2,
                rect.top() + (rect.height() - side) / 2)
    p.scale(side / _VIEWBOX, side / _VIEWBOX)
    pen = QPen(color, _STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _LEGACY_PAINTERS[name](p)
