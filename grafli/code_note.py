"""Code-mode rendering for text notes.

Notes whose first non-empty line starts with ``code:`` render as a
stylized pseudocode block in display mode. The ``code:`` prefix is
stripped from display; everything after it is the body.

The pseudocode is not executable — it's a minimal, scannable language
for summarizing implementations in review-oriented diagrams.

Syntax (v2, keyword-led, one instruction per line):

    fn:     <name(args) -> Result>    function signature
    if:     <condition>               condition
    then:   <action>                  consequence of preceding if:
    else:   <action>                  alternative branch
    for:    <x in xs>                 iteration
    while:  <condition>               loop
    set:    <x = expr>                assignment
    return: <expr>                    exit value
    err:    <expr>                    error / raise
    note:   <text>                    review note / assumption
    @path:line                        reference to real source
    # ...                             comment (dimmed)

Plain lines (no leading keyword) render as ordinary actions. Object
orientation is expressed naturally via dot syntax: ``obj.method(args)``.
"""

from __future__ import annotations

import re


PREFIX = "code:"

_KEYWORDS = (
    "fn", "if", "then", "else", "for", "while",
    "set", "return", "err", "note",
)

_RE_KEYWORD_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<kw>(?:" + "|".join(_KEYWORDS) + r")):(?P<rest>(?:\s.*)?)$"
)

_RE_REF = re.compile(r"@[\w./\\-]+(?::\d+)?")


def is_code_note(text: str) -> bool:
    """Return True if *text* is a code-mode note."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(PREFIX)
    return False


def code_body(text: str) -> str:
    """Return the code body with the ``code:`` prefix line stripped.

    The first non-empty line's ``code:`` is removed. Any content on the
    same line after ``code:`` is preserved as the first body line.
    """
    lines = text.splitlines()
    out: list[str] = []
    consumed = False
    for line in lines:
        if not consumed and line.strip().startswith(PREFIX):
            rest = line.strip()[len(PREFIX):].lstrip()
            if rest:
                out.append(rest)
            consumed = True
            continue
        if consumed or line.strip():
            out.append(line)
            consumed = True
    return "\n".join(out)


# ── Tokenizer ──────────────────────────────────────────────────

# Token kinds:
#   "kw"      keyword marker (leading "keyword:") and refs
#   "comment" # ...            (dimmed, from # to end of line)
#   "text"    everything else  (neutral pen)


def tokenize_line(line: str) -> list[tuple[str, str]]:
    """Return a list of (kind, text) runs for a single line.

    The concatenation of the returned texts equals the input line.
    """
    comment_start = _find_comment(line)
    if comment_start is not None:
        head = line[:comment_start]
        tail = line[comment_start:]
        runs = _tokenize_code(head)
        if tail:
            runs.append(("comment", tail))
        return runs
    return _tokenize_code(line)


def _find_comment(line: str) -> int | None:
    """Return index of the ``#`` starting a comment, or None."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return len(line) - len(stripped)
    m = re.search(r"\s#", line)
    return m.start() if m else None


def _tokenize_code(segment: str) -> list[tuple[str, str]]:
    if not segment:
        return []
    runs: list[tuple[str, str]] = []

    m = _RE_KEYWORD_LINE.match(segment)
    if m:
        if m.group("indent"):
            runs.append(("text", m.group("indent")))
        runs.append(("kw", m.group("kw") + ":"))
        rest = m.group("rest")
        if rest:
            runs.extend(_scan_refs(rest))
        return runs

    runs.extend(_scan_refs(segment))
    return runs


def _scan_refs(segment: str) -> list[tuple[str, str]]:
    """Return runs for *segment*, highlighting ``@path:line`` refs."""
    if not segment:
        return []
    runs: list[tuple[str, str]] = []
    i = 0
    for m in _RE_REF.finditer(segment):
        start, end = m.span()
        if start > i:
            runs.append(("text", segment[i:start]))
        runs.append(("kw", segment[start:end]))
        i = end
    if i < len(segment):
        runs.append(("text", segment[i:]))
    return runs
