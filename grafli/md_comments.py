"""Inline comment format for the markdown editor — CriticMarkup span comments.

A comment is stored inline in the markdown as a CriticMarkup highlight directly
followed by a comment::

    The {==quarterly numbers==}{>>are these pre-audit?<<} look off here.

`{==…==}` marks the highlighted span; `{>>…<<}` is the comment body. The two are
written adjacent (the comment tool always emits them that way). This module is
the single source of truth for that format: parsing it, stripping it for a plain
render, and preparing a sentinel-wrapped variant the read view can highlight.

Pure text logic only — no Qt — so it is cheap to unit-test and reusable by any
render or export path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Private-use code points used to mark a span's bounds in the text handed to
# Qt's Markdown renderer. They survive setMarkdown untouched (Markdown assigns
# them no meaning), so the read view can locate each span in the rendered
# document and then delete the markers.
SENTINEL_START = "\uE000"
SENTINEL_END = "\uE001"

# {==span==}{>>body<<} — span and body are non-greedy and may span lines.
_RE_COMMENT = re.compile(r"\{==(?P<span>.*?)==\}\{>>(?P<body>.*?)<<\}", re.DOTALL)


@dataclass(frozen=True)
class Comment:
    """One inline comment, with offsets into the *source* string."""

    full_start: int   # offset of the opening '{=='
    full_end: int     # offset just past the closing '<<}'
    span_start: int   # offset of the highlighted span's first char
    span_end: int     # offset just past the span's last char
    span: str         # the highlighted text
    body: str         # the comment text


def parse(source: str) -> list[Comment]:
    """Return every inline comment in ``source``, in document order."""
    return [
        Comment(
            full_start=m.start(),
            full_end=m.end(),
            span_start=m.start("span"),
            span_end=m.end("span"),
            span=m.group("span"),
            body=m.group("body"),
        )
        for m in _RE_COMMENT.finditer(source)
    ]


def strip(source: str) -> str:
    """``source`` with all comment markup removed: the highlighted span text is
    kept inline, the comment body is dropped. This is the plain markdown a
    reader would see with no annotations at all."""
    return _RE_COMMENT.sub(lambda m: m.group("span"), source)


def render_comment(span: str, body: str) -> str:
    """The inline form for a span comment: ``{==span==}{>>body<<}``."""
    return f"{{=={span}==}}{{>>{body}<<}}"


def set_body(source: str, comment: Comment, body: str) -> str:
    """Return ``source`` with ``comment``'s body replaced, span unchanged."""
    return (
        source[:comment.full_start]
        + render_comment(comment.span, body)
        + source[comment.full_end:]
    )


def remove(source: str, comment: Comment) -> str:
    """Return ``source`` with ``comment`` unwrapped to its plain span text —
    the highlight and the comment body are both dropped."""
    return source[:comment.full_start] + comment.span + source[comment.full_end:]


def wrap(source: str, span_start: int, span_end: int, body: str) -> str:
    """Return ``source`` with the slice ``[span_start, span_end)`` wrapped as a
    span comment carrying ``body``. The wrapped text becomes the highlight span."""
    span = source[span_start:span_end]
    return (
        source[:span_start]
        + render_comment(span, body)
        + source[span_end:]
    )


def to_sentineled(
    source: str,
    start: str = SENTINEL_START,
    end: str = SENTINEL_END,
) -> tuple[str, list[Comment]]:
    """Prepare ``source`` for the read view's Markdown renderer.

    Each ``{==span==}{>>body<<}`` becomes ``<start>span<end>`` — the comment body
    is removed and the span is wrapped in sentinel markers. Returns the rewritten
    markdown plus the comments in document order, so the caller can pair the Nth
    sentinel span found in the rendered document with the Nth comment's body.
    """
    md = _RE_COMMENT.sub(lambda m: f"{start}{m.group('span')}{end}", source)
    return md, parse(source)
