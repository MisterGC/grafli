"""Markdown rendering for text notes.

A note is markdown in one of two ways:

- **Doc-bodied** (``attach_kind == "doc"``): the body lives in a vault
  ``.md`` file and is markdown by definition — no sentinel in the file.
  This is the canonical form; inline ``md:`` notes convert to it on save.
- **Inline legacy**: the first non-empty line starts with ``md:`` (or
  ``markdown:``); the prefix is stripped from display.

Use ``note_is_md`` / ``note_md_body`` when a Note object is at hand —
they cover both forms; the text-based ``is_md_note`` / ``md_body`` remain
for raw strings (editors, migration).

The recommended subset is the GFM-flavoured one documented in
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


def note_is_md(note) -> bool:
    """Return True if the Note renders as markdown (doc-bodied or ``md:``)."""
    return getattr(note, "attach_kind", "") == "doc" or is_md_note(note.text)


def note_md_body(note) -> str:
    """The Note's markdown body — doc bodies are already prefix-free."""
    if getattr(note, "attach_kind", "") == "doc":
        return note.text
    return md_body(note.text)


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
