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

import difflib
import re
from dataclasses import dataclass

# Private-use code points used to mark a span's bounds in the text handed to
# Qt's Markdown renderer. They survive setMarkdown untouched (Markdown assigns
# them no meaning), so the read view can locate each span in the rendered
# document and then delete the markers.
SENTINEL_START = "\uE000"
SENTINEL_END = "\uE001"

# {==span==}{>>body<<} — span/body are non-greedy, may span lines, and are
# "tempered": neither may contain a marker delimiter (==}, {==, <<}, {>>), so a
# stray `{==` in prose can't make one comment swallow the next one's opening.
_RE_COMMENT = re.compile(
    r"\{==(?P<span>(?:(?!==\}|\{==).)*?)==\}"
    r"\{>>(?P<body>(?:(?!<<\}|\{>>).)*?)<<\}",
    re.DOTALL,
)

# Opening fence of a code block; closing is matched line-by-line in _code_ranges.
_RE_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# Inline code span: a backtick run, content not crossing a newline, same run.
_RE_INLINE_CODE = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")


@dataclass(frozen=True)
class Comment:
    """One inline comment, with offsets into the *source* string."""

    full_start: int   # offset of the opening '{=='
    full_end: int     # offset just past the closing '<<}'
    span_start: int   # offset of the highlighted span's first char
    span_end: int     # offset just past the span's last char
    span: str         # the highlighted text
    body: str         # the comment text


def _code_ranges(source: str) -> list[tuple[int, int]]:
    """Character ranges that are Markdown code — fenced blocks and inline code
    spans — where CriticMarkup must be left literal (it's documentation, not a
    real comment). This is what keeps the format's own ``{==…==}`` *examples*
    from being parsed as comments."""
    ranges: list[tuple[int, int]] = []
    # Fenced blocks, line by line.
    pos = 0
    fence: tuple[str, int, int] | None = None   # (marker_char, run_len, start)
    for line in source.splitlines(keepends=True):
        m = _RE_FENCE.match(line)
        marker = (m.group(1)[0], len(m.group(1))) if m else None
        if fence is None:
            if marker:
                fence = (marker[0], marker[1], pos)
        elif marker and marker[0] == fence[0] and marker[1] >= fence[1]:
            ranges.append((fence[2], pos + len(line)))
            fence = None
        pos += len(line)
    if fence is not None:
        ranges.append((fence[2], len(source)))
    # Inline code spans outside any fenced block.
    for m in _RE_INLINE_CODE.finditer(source):
        if not any(a <= m.start() < b for a, b in ranges):
            ranges.append((m.start(), m.end()))
    return ranges


def _matches(source: str) -> list[re.Match]:
    """Real comment matches, in document order. A match is skipped only when its
    delimiters sit inside a code region — i.e. it's a literal syntax *example*
    like `` `{==…==}` ``. A genuine comment whose span merely *contains* inline
    code (``{==`assembly` added==}{>>…<<}``) is kept: its markers are outside the
    code, only the span wraps around it."""
    ranges = _code_ranges(source)

    def in_code(pos):
        return any(a <= pos < b for a, b in ranges)

    out = []
    for m in _RE_COMMENT.finditer(source):
        # The structural delimiters must all be outside code; the span between
        # them may freely contain `code`.
        if (in_code(m.start())                  # {==
                or in_code(m.end("span"))       # ==}
                or in_code(m.start("body") - 3)  # {>>
                or in_code(m.end() - 1)):        # <<}
            continue
        out.append(m)
    return out


def _to_comment(m: re.Match) -> Comment:
    return Comment(
        full_start=m.start(),
        full_end=m.end(),
        span_start=m.start("span"),
        span_end=m.end("span"),
        span=m.group("span"),
        body=m.group("body"),
    )


def _rebuild(source: str, matches: list[re.Match], transform) -> str:
    """Rebuild ``source`` replacing each match with ``transform(match)`` and
    leaving everything else (including code regions) untouched."""
    out = []
    i = 0
    for m in matches:
        out.append(source[i:m.start()])
        out.append(transform(m))
        i = m.end()
    out.append(source[i:])
    return "".join(out)


def parse(source: str) -> list[Comment]:
    """Return every inline comment in ``source``, in document order. Markup
    inside code spans / fenced blocks is left literal (not a comment)."""
    return [_to_comment(m) for m in _matches(source)]


def strip(source: str) -> str:
    """``source`` with all comment markup removed: the highlighted span text is
    kept inline, the comment body is dropped. This is the plain markdown a
    reader would see with no annotations at all."""
    return _rebuild(source, _matches(source), lambda m: m.group("span"))


def classify_overlap(source: str, s0: int, s1: int):
    """Decide how a would-be new comment over ``[s0, s1)`` relates to existing
    comments — the overlap-aware, no-nesting policy.

    Returns ``("inside", idx)`` when the selection sits wholly within an existing
    comment's span (the caller should edit that comment instead of nesting),
    ``("partial", idx)`` when it straddles an existing comment's markup (refuse),
    or ``None`` when it is clear to wrap.
    """
    for i, c in enumerate(parse(source)):
        if c.span_start <= s0 and s1 <= c.span_end:
            return ("inside", i)
        if not (s1 <= c.full_start or s0 >= c.full_end):
            return ("partial", i)
    return None


_RE_ANY_MARKER = re.compile(r"\{==|==\}|\{>>|<<\}")


def contains_markup(text: str) -> bool:
    """True if ``text`` holds any CriticMarkup delimiter — e.g. a syntax example
    in a code span, or an existing comment. Such a span can't be wrapped cleanly
    (it would nest delimiters), so the caller should refuse."""
    return bool(_RE_ANY_MARKER.search(text))


def snap_out_of_code(source: str, s0: int, s1: int) -> tuple[int, int]:
    """Expand a span so neither boundary falls *inside* a code region (inline
    `` `code` `` or a fenced block). A wrapped comment's ``{==`` / ``==}`` markers
    must sit outside code — placed inside, they'd be skipped as a literal example
    and the comment wouldn't render. Each boundary snaps to the code edge."""
    for a, b in _code_ranges(source):
        if a < s0 < b:
            s0 = a
        if a < s1 < b:
            s1 = b
    return s0, s1


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


def _strip_with_map(source: str) -> tuple[str, list[int]]:
    """Return ``(clean, clean2src)``: the source with comment markup removed
    (span text kept, markers + bodies dropped) and, for each character of
    ``clean``, the index it came from in ``source``. Used to map a rendered-view
    position back to an exact source offset without comment-body noise."""
    chars: list[str] = []
    src_idx: list[int] = []
    i = 0
    for m in _matches(source):
        for k in range(i, m.start()):
            chars.append(source[k])
            src_idx.append(k)
        for k in range(m.start("span"), m.end("span")):
            chars.append(source[k])
            src_idx.append(k)
        i = m.end()
    for k in range(i, len(source)):
        chars.append(source[k])
        src_idx.append(k)
    return "".join(chars), src_idx


_RE_WORD = re.compile(r"\w+")


def _word_tokens(s: str) -> list[tuple[str, int, int]]:
    """Words in ``s`` as ``(text, start, end)`` — the stable anchors shared by
    the rendered text and the clean source (Markdown alters punctuation around
    words, never the letters inside them)."""
    return [(m.group(), m.start(), m.end()) for m in _RE_WORD.finditer(s)]


def map_rendered_span(
    rendered: str, source: str, r0: int, r1: int
) -> tuple[int, int] | None:
    """Map a rendered-view selection ``[r0, r1)`` (indices into the rendered
    plain text) to a source slice ``[s0, s1)`` suitable for :func:`wrap`.

    Works by aligning the *word sequences* of the rendered text and the clean
    source with :class:`difflib.SequenceMatcher` — robust on real documents
    (tables, links, lists) where a greedy char scan drifts. The selection snaps
    to whole words it overlaps. Returns ``None`` when it can't be mapped.
    """
    if r1 <= r0:
        return None
    clean, clean2src = _strip_with_map(source)
    if not clean2src:
        return None
    rtok = _word_tokens(rendered)
    ctok = _word_tokens(clean)
    if not rtok or not ctok:
        return None

    # First/last rendered word overlapping the selection.
    start_wi = next((i for i, t in enumerate(rtok) if t[2] > r0), None)
    end_wi = None
    for i, t in enumerate(rtok):
        if t[1] < r1:
            end_wi = i
        else:
            break
    if start_wi is None or end_wi is None or end_wi < start_wi:
        return None

    # rendered-word-index -> clean-word-index, via matching blocks.
    matcher = difflib.SequenceMatcher(
        None, [t[0] for t in rtok], [t[0] for t in ctok], autojunk=False
    )
    r2c: dict[int, int] = {}
    for blk in matcher.get_matching_blocks():
        for k in range(blk.size):
            r2c[blk.a + k] = blk.b + k

    cs = _nearest_mapped(r2c, start_wi, len(rtok), forward=True)
    ce = _nearest_mapped(r2c, end_wi, len(rtok), forward=False)
    if cs is None or ce is None or ce < cs:
        return None
    clean_start = ctok[cs][1]
    clean_end = ctok[ce][2]
    if clean_start >= len(clean2src) or clean_end - 1 >= len(clean2src):
        return None
    s0 = clean2src[clean_start]
    s1 = clean2src[clean_end - 1] + 1
    if s1 <= s0:
        return None
    return s0, s1


def _nearest_mapped(r2c: dict, wi: int, n: int, forward: bool):
    """Clean-word index for rendered word ``wi``; if that exact word didn't
    align, take the nearest aligned neighbour in the given direction."""
    step = 1 if forward else -1
    i = wi
    while 0 <= i < n:
        if i in r2c:
            return r2c[i]
        i += step
    return None


def map_position(from_text: str, to_text: str, pos: int) -> int:
    """Map a character offset in ``from_text`` to the nearest equivalent offset
    in ``to_text`` by aligning their word sequences (same robust word-diff as
    :func:`map_rendered_span`). Used to keep the caret in place when toggling
    between the source and rendered views. Falls back to 0 with no shared words."""
    ftok = _word_tokens(from_text)
    ttok = _word_tokens(to_text)
    if not ftok or not ttok:
        return 0
    matcher = difflib.SequenceMatcher(
        None, [t[0] for t in ftok], [t[0] for t in ttok], autojunk=False
    )
    f2t: dict[int, int] = {}
    for blk in matcher.get_matching_blocks():
        for k in range(blk.size):
            f2t[blk.a + k] = blk.b + k
    wi = next((i for i, t in enumerate(ftok) if t[2] > pos), len(ftok) - 1)
    tj = _nearest_mapped(f2t, wi, len(ftok), forward=True)
    if tj is None:
        tj = _nearest_mapped(f2t, wi, len(ftok), forward=False)
    return ttok[tj][1] if tj is not None else 0


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
    matches = _matches(source)
    md = _rebuild(source, matches, lambda m: f"{start}{m.group('span')}{end}")
    return md, [_to_comment(m) for m in matches]
