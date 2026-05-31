"""Markdown rendering for text notes.

Notes whose first non-empty line starts with ``md:`` (or ``markdown:``)
render as a small block of formatted Markdown in display mode. The
prefix is stripped from display; everything after it is the body.

This is for prose annotations with light structure — a sibling to the
``code:`` note. It is *not* meant to grow into a document: the
recommended subset is the GFM-flavoured one documented in
``docs/text-annotations.md`` (headings, lists, task lists, blockquotes,
horizontal rules, fenced code, plus inline bold / italic / code / links
/ strikethrough). Anything heavier (tables, images, raw HTML) is parsed
by Qt's Markdown engine if present but is not part of the supported
surface and may not fit a canvas annotation.

The body is rendered with ``QTextDocument.setMarkdown`` in the renderer
(see ``items.NoteItem._paint_markdown``); this module only handles
detection and prefix stripping, mirroring ``code_note``.
"""

from __future__ import annotations


# Recognised prefixes, longest first so ``markdown:`` is matched before
# the shorter ``md:`` could partially apply.
PREFIXES = ("markdown:", "md:")


def _matched_prefix(stripped: str) -> str | None:
    for prefix in PREFIXES:
        if stripped.startswith(prefix):
            return prefix
    return None


def is_md_note(text: str) -> bool:
    """Return True if *text* is a Markdown-mode note."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return _matched_prefix(stripped) is not None
    return False


def md_body(text: str) -> str:
    """Return the Markdown body with the ``md:`` prefix line stripped.

    The first non-empty line's prefix is removed. Any content on the
    same line after the prefix is preserved as the first body line.
    """
    lines = text.splitlines()
    out: list[str] = []
    consumed = False
    for line in lines:
        if not consumed:
            prefix = _matched_prefix(line.strip())
            if prefix is not None:
                rest = line.strip()[len(prefix):].lstrip()
                if rest:
                    out.append(rest)
                consumed = True
                continue
        if consumed or line.strip():
            out.append(line)
            consumed = True
    return "\n".join(out)
