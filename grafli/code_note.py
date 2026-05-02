"""Code-mode rendering for text notes.

Notes whose first non-empty line starts with ``code:`` render as a
stylized pseudocode block in display mode. The ``code:`` prefix is
stripped from display; everything after it is the body.

The pseudocode is not executable — it's a minimal, scannable language
for summarizing implementations in review-oriented diagrams. The goal
is *visual* understanding at a glance; faithful syntax mirroring of
the underlying source code is a non-goal.

Syntax (v3, signature-first, colon-optional):

    <signature>           first body line, e.g. ``tokenize(raw) -> [Token]``
                          rendered bold with a divider beneath.

    if      <condition>   conditional (``if:`` colon also accepted)
    else    <action>      alternative branch
    for     <x in xs>     iteration
    while   <condition>   loop
    try                   protected block
    catch   <err -> act>  error handling
    return  <expr>        exit value

    call    <f(args)>     important call
    await   <op>          blocking / async wait
    emit    <event>       event / message emission
    state   <from -> to>  state transition / lifecycle

    pre     <condition>   precondition         ┐
    post    <condition>   postcondition        │  rendered in
    assert  <condition>   invariant            │  *contract red* —
    verify  <evidence>    test / check / trace │  things reviewers
    risk    <text>        failure mode         │  should spot first
    err     <expr>        error / raise        ┘

    out = expr            plain assignments — no keyword needed
    @path:line            clickable source reference (Cmd-click to open)
    # ...                 comment (italic, muted)
    "..."  #FFF  42  true literal values — render as plain text
                          (the syntax already self-marks them)

Style guidance:

* Prefer indentation over the ``then`` keyword to express block
  structure — Python-like layout is faster to scan.
* Favour predicates and short calls (``blank(line)``,
  ``starts_with(line, "code:")``) over long OO chains
  (``line.stripped.isEmpty``). The snippet should reveal *what
  happens*; literal source structure is not the point.
* Keep one abstraction level per snippet. Mixing real method names
  with prose verbs forces the reader to re-parse mid-line.
"""

from __future__ import annotations

import re


PREFIX = "code:"

# Keyword categorisation drives semantic colouring in the renderer.
#   struct   — control flow / signature      (cool tone)
#   effect   — side effects, calls, state    (teal)
#   contract — pre/post/risk-style claims    (warm orange)
#
# The first body line is treated as a function signature without any
# keyword prefix. Plain assignments (``out = []``) read as code, so
# there's no ``set`` keyword. Comments use ``# …`` instead of ``note``.
KEYWORD_KIND: dict[str, str] = {
    "if": "kw_struct", "then": "kw_struct",
    "else": "kw_struct", "for": "kw_struct", "while": "kw_struct",
    "try": "kw_struct", "catch": "kw_struct", "return": "kw_struct",

    "call": "kw_effect", "await": "kw_effect", "emit": "kw_effect",
    "state": "kw_effect",

    "assert": "kw_contract", "pre": "kw_contract", "post": "kw_contract",
    "verify": "kw_contract", "risk": "kw_contract", "err": "kw_contract",
}

_KEYWORDS = tuple(KEYWORD_KIND.keys())

# Trailing ``:`` is optional. ``if foo`` and ``if: foo`` both match.
_RE_KEYWORD_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<kw>(?:" + "|".join(_KEYWORDS) + r"))"
    r"(?P<colon>:?)(?P<rest>(?:\s.*)?)$"
)

# Legacy: strip a leading ``fn:`` / ``fn`` prefix from the signature line
# so existing files keep rendering cleanly.
_RE_FN_PREFIX = re.compile(r"^(?P<indent>\s*)fn\s*:?\s*")

_RE_REF = re.compile(r"@[\w./\\-]+(?::\d+)?")
_RE_STRING = re.compile(r'"[^"\n]*"')
# Hex colour literal: 3, 4, 6, or 8 hex digits after a ``#``.
_RE_HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
# Numeric literal: integer or float, isolated by word boundaries.
_RE_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_RE_BOOL = re.compile(r"\b(?:true|false|True|False)\b")


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
#   "kw_struct"    control-flow / signature keyword (fn:, if:, try: ...)
#   "kw_effect"    side-effect keyword             (call:, emit:, set: ...)
#   "kw_contract"  contract / risk keyword         (pre:, post:, risk: ...)
#   "ref"          @path:line source reference     (clickable in renderer)
#   "string"       "..." literal                   (muted green)
#   "comment"      # ...                           (dimmed, from # to EOL)
#   "text"         everything else                 (neutral pen)


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
    """Return index of the ``#`` starting a comment, or None.

    A leading ``#`` on a line is always a comment. Mid-line, ``#`` only
    starts a comment when it isn't part of a hex colour literal — so
    ``set bg = #F2F0EB`` keeps the hex value, while
    ``return out  # done`` correctly trims the trailing comment.
    """
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return len(line) - len(stripped)
    for m in re.finditer(r"\s#", line):
        if _RE_HEX.match(line, m.start() + 1):
            continue
        return m.start()
    return None


def _tokenize_code(segment: str) -> list[tuple[str, str]]:
    if not segment:
        return []
    runs: list[tuple[str, str]] = []

    m = _RE_KEYWORD_LINE.match(segment)
    if m:
        if m.group("indent"):
            runs.append(("text", m.group("indent")))
        kw = m.group("kw")
        runs.append((KEYWORD_KIND[kw], kw + (m.group("colon") or "")))
        rest = m.group("rest")
        if rest:
            runs.extend(_scan_inline(rest))
        return runs

    runs.extend(_scan_inline(segment))
    return runs


def split_signature(text: str) -> tuple[int | None, list[str]]:
    """Return ``(signature_index, body_lines)``.

    The first non-empty body line is treated as a function signature
    *unless* it starts with a recognised keyword. Any legacy ``fn:`` /
    ``fn`` prefix is stripped from that line so existing files render
    correctly without further edits.

    The returned list contains all body lines (signature in place); the
    index points to the line the renderer should enlarge.
    """
    lines = code_body(text).split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _RE_KEYWORD_LINE.match(line):
            return None, lines
        lines[i] = _RE_FN_PREFIX.sub(r"\g<indent>", line, count=1)
        return i, lines
    return None, lines


_INLINE_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("ref", _RE_REF),
    ("string", _RE_STRING),
    ("hex", _RE_HEX),
    ("number", _RE_NUMBER),
    ("bool", _RE_BOOL),
)


def _scan_inline(segment: str) -> list[tuple[str, str]]:
    """Return runs for *segment*, highlighting inline literals.

    All inline patterns (refs, strings, hex literals, numbers, bools)
    are scanned together. When two patterns claim the same position
    the earlier-listed one wins, so refs and strings — which can
    contain digits — take precedence over numbers.
    """
    if not segment:
        return []
    matches: list[tuple[int, int, str]] = []
    for kind, pattern in _INLINE_PATTERNS:
        for m in pattern.finditer(segment):
            matches.append((m.start(), m.end(), kind))
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    pruned: list[tuple[int, int, str]] = []
    last_end = 0
    for start, end, kind in matches:
        if start < last_end:
            continue
        pruned.append((start, end, kind))
        last_end = end
    runs: list[tuple[str, str]] = []
    i = 0
    for start, end, kind in pruned:
        if start > i:
            runs.append(("text", segment[i:start]))
        runs.append((kind, segment[start:end]))
        i = end
    if i < len(segment):
        runs.append(("text", segment[i:]))
    return runs
