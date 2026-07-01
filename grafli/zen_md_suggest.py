"""Animated accept/reject for the reading view's track-changes.

The gesture reads as *settling a proposal into the prose*: on accept, the
struck-out removal fades away while the blue addition settles into body ink; on
reject, the blue addition fades away while the struck-out original un-strikes
back to body text. Fading the leaving text *before* the source is mutated hides
the reflow (it collapses on already-invisible characters).

Pure animation over the rendered ``QTextDocument`` — it tweens character formats
on the removed/added sub-ranges, then calls back to run the (undoable) source
edit. Kept out of ``zen_md`` so that file stays a coordinator.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor

DURATION_MS = 200
_FONT_SWAP_AT = 0.5   # midpoint: handwriting -> typeset / strike lifts


def _scaled_alpha(color: QColor, frac: float) -> QColor:
    """``color`` with its alpha scaled by ``frac`` (fade to transparent)."""
    c = QColor(color)
    c.setAlpha(int(c.alpha() * max(0.0, min(1.0, frac))))
    return c


def _lerp(c1: QColor, c2: QColor, t: float) -> QColor:
    """Linear blend from ``c1`` to ``c2`` at ``t`` in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


class SuggestionAnimator:
    """Runs one accept/reject animation on a read view, then fires ``on_finish``.

    ``body_color`` / ``body_family`` are the typeset prose ink and font the
    settling text converges to; ``del_color`` / ``add_color`` are the struck-red
    and handwriting-blue the leaving text fades from.
    """

    def __init__(self, view, *, body_color, body_family, del_color, add_color,
                 duration_ms: int = DURATION_MS):
        self._view = view
        self._body_color = QColor(body_color)
        self._body_family = body_family
        self._del_color = QColor(del_color)
        self._add_color = QColor(add_color)
        self._duration = duration_ms
        self._anim: QVariantAnimation | None = None
        self._on_finish = None

    def busy(self) -> bool:
        return self._anim is not None

    def _style(self, rng, fmt: QTextCharFormat):
        if rng is None:
            return
        cur = QTextCursor(self._view.document())
        cur.setPosition(rng[0])
        cur.setPosition(rng[1], QTextCursor.MoveMode.KeepAnchor)
        cur.mergeCharFormat(fmt)

    def _leave(self, rng, color: QColor, t: float):
        """Fade a range that is going away: its ink dissolves to transparent."""
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(_scaled_alpha(color, 1.0 - t)))
        self._style(rng, fmt)

    def _settle(self, rng, from_color: QColor, t: float, drop_strike: bool):
        """Converge a range that stays toward typeset body: ink blends to the body
        colour, and at the midpoint the font becomes body / the strike lifts."""
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(_lerp(from_color, self._body_color, t)))
        if t >= _FONT_SWAP_AT:
            fmt.setFontFamilies([self._body_family])
            if drop_strike:
                fmt.setFontStrikeOut(False)
                fmt.setFontWeight(QFont.Weight.Normal)   # un-bold the strong strike
        self._style(rng, fmt)

    def run(self, *, accept: bool, removed, added, on_finish):
        """Animate one accept/reject over the given rendered sub-ranges (either
        may be None), then call ``on_finish`` to mutate the source."""
        self.finish()   # complete any in-flight animation first
        self._on_finish = on_finish

        def tick(t: float):
            if accept:
                self._leave(removed, self._del_color, t)                 # old goes
                self._settle(added, self._add_color, t, drop_strike=False)  # new stays
            else:
                self._leave(added, self._add_color, t)                   # new goes
                self._settle(removed, self._del_color, t, drop_strike=True)  # old stays

        anim = QVariantAnimation(self._view)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(self._duration)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.valueChanged.connect(lambda v: tick(float(v)))
        anim.finished.connect(self._done)
        self._anim = anim
        anim.start()

    def _done(self):
        cb, self._on_finish = self._on_finish, None
        self._anim = None
        if cb is not None:
            cb()

    def finish(self):
        """Complete any running animation immediately (settling the source edit).
        Idempotent — a no-op when idle."""
        if self._anim is not None:
            anim, self._anim = self._anim, None
            anim.stop()
            cb, self._on_finish = self._on_finish, None
            if cb is not None:
                cb()
