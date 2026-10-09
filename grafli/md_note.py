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

import re


# Recognised prefixes, longest first so ``markdown:`` is matched before
# the shorter ``md:`` could partially apply.
PREFIXES = ("markdown:", "md:")

# A GFM task-list item: optional indent, a bullet (``-``/``*``/``+``) or an
# ordered marker (``1.``/``1)``), then a ``[ ]`` / ``[x]`` checkbox.
_TASK_LINE_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)\[([ xX])\]")


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


# A blockquote line with content: optional indent, ``>``, some text.
_QUOTE_LINE_RE = re.compile(r"^\s*>\s?\S")


def md_hard_quote_breaks(body: str) -> str:
    """Render-side transform (issue #124): authored line breaks inside a
    blockquote run become markdown hard breaks (trailing backslash), so a
    quote keeps its ragged edge on canvas and in exports. The stored note
    body is never modified — apply this only when feeding a renderer.
    """
    lines = body.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (_QUOTE_LINE_RE.match(line) and _QUOTE_LINE_RE.match(nxt)
                and not line.rstrip().endswith("\\")):
            out.append(line.rstrip() + "\\")
        else:
            out.append(line)
    return "\n".join(out)


def toggle_task(text: str, index: int) -> tuple[str, bool]:
    """Flip the *index*-th GFM task checkbox (0-based) in *text*.

    Returns ``(new_text, changed)``. Task items are matched in document
    order, so *index* lines up with the order Qt renders the checkboxes.
    Everything else in the text is left byte-identical, so a toggle is a
    one-character diff.
    """
    lines = text.split("\n")
    seen = 0
    for i, line in enumerate(lines):
        m = _TASK_LINE_RE.match(line)
        if m is None:
            continue
        if seen == index:
            done = m.group(2) in "xX"
            mark = " " if done else "x"
            lines[i] = line[:m.start(2)] + mark + line[m.end(2):]
            return "\n".join(lines), True
        seen += 1
    return text, False


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


# Inline Markdown reduced to its text, in order: images and links keep their
# text, code spans, bold, italic and strikethrough lose their markers.
_INLINE_RULES = (
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"<((?:https?|mailto):[^>]+)>"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"\1"),
    (re.compile(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
)
# CriticMarkup: comments and deletions go, additions, highlights and the
# new side of a substitution stay.
_CRITIC_RULES = (
    (re.compile(r"\{>>.*?<<\}", re.S), ""),
    (re.compile(r"\{--.*?--\}", re.S), ""),
    (re.compile(r"\{~~.*?~>(.*?)~~\}", re.S), r"\1"),
    (re.compile(r"\{\+\+(.*?)\+\+\}", re.S), r"\1"),
    (re.compile(r"\{==(.*?)==\}", re.S), r"\1"),
)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_RULE_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_BLOCK_MARKER_RE = re.compile(
    r"^\s*(?:>\s*)*(?:(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?)?")
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?=\s|$)")


def _inline_text(text: str) -> str:
    for rule, repl in _INLINE_RULES:
        text = rule.sub(repl, text)
    return " ".join(text.split())


def doc_first_sentence(body: str) -> str:
    """The first sentence of a Markdown doc as plain text (D2).

    Taken from the first paragraph of prose: front matter, headings, rules
    and fenced code are skipped, list and quote markers, inline markup and
    CriticMarkup marks are dropped. A doc without prose falls back to its
    first heading; an empty doc gives "".
    """
    for rule, repl in _CRITIC_RULES:
        body = rule.sub(repl, body)
    lines = body.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                lines = lines[i + 1:]
                break
    heading = ""
    paragraph: list[str] = []
    fenced = False
    for line in lines:
        if _FENCE_RE.match(line):
            fenced = not fenced
            if paragraph:
                break
            continue
        if fenced:
            continue
        m = _HEADING_RE.match(line)
        if not line.strip() or m or _RULE_RE.match(line):
            if paragraph:
                break
            if m and not heading:
                heading = _inline_text(m.group(1))
            continue
        paragraph.append(_BLOCK_MARKER_RE.sub("", line, count=1))
    text = _inline_text(" ".join(paragraph))
    if not text:
        return heading
    m = _SENTENCE_RE.match(text)
    return m.group(1) if m else text
