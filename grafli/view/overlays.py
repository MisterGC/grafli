"""Transient overlays and feedback for GrafliView (mixin).

The view's ephemeral UI layer: confirmation flashes, toasts, the shared
fade helper behind all transient micro-motion, the empty-board hint, the
debug overlay, the glyph picker, and the F1 help dialog. Nothing
here touches the board model — it is presentation-only feedback on top of
the canvas.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QRectF,
    QTimer,
    QUrl,
    QVariantAnimation,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from grafli import keymap, theme
from grafli.constants import FONT_FAMILY, MINIMAP_MARGIN
from grafli.glyphs import GlyphPicker, ensure_text_presentation


# The app's keys fill three columns; the browser tab's fewer keys two.
HELP_COLUMNS = {keymap.APP: 3, keymap.TAB: 2}


def escape_(text: str) -> str:
    return escape(text, quote=False)


def _columns(groups, n: int) -> list[list]:
    """``groups`` in order, cut into ``n`` columns of about equal rows."""
    total = sum(len(g.keys) + 1 for g in groups)
    cols, col, rows = [], [], 0
    for g in groups:
        if col and rows >= total * (len(cols) + 1) / n and len(cols) < n - 1:
            cols.append(col)
            col = []
        col.append(g)
        rows += len(g.keys) + 1
    cols.append(col)
    return cols


def cheatsheet_html(where: str, filter_text: str = "") -> str:
    """The F1 help's table of ``where``'s keys (:data:`keymap.APP` or
    :data:`keymap.TAB`), rows matching ``filter_text`` only."""
    ft = filter_text.lower()
    hdr = (
        f"color:{theme.INFO_COLOR.name()};font-weight:bold;"
        "padding-top:8px;padding-bottom:2px"
    )
    blurb = f"color:{theme.INK_FAINT.name()};padding-bottom:2px"

    def _render_column(groups):
        rows = []
        for g in groups:
            entries = [
                (keymap.compact_keys(k), k.does, k.is_gesture)
                for k in g.keys
                if not ft or ft in keymap.compact_keys(k).lower()
                or ft in k.does.lower() or ft in g.title.lower()
            ]
            if not entries:
                continue
            title = g.title.upper()
            if g.enter:
                title += f" &nbsp;({escape_(g.enter)})"
            rows.append(f"<tr><td colspan='2' style='{hdr}'>{title}</td></tr>")
            if g.blurb:
                rows.append(f"<tr><td colspan='2' style='{blurb}'>"
                            f"<i>{escape_(g.blurb)}</i></td></tr>")
            for keys, desc, is_gesture in entries:
                # Keys stay on one line; a gesture's words may wrap.
                wrap = "" if is_gesture else ";white-space:nowrap"
                rows.append(
                    "<tr>"
                    f"<td style='padding-right:12px{wrap}'>"
                    f"<b>{escape_(keys)}</b></td>"
                    f"<td width='60%' style='padding:2px 0'>"
                    f"{escape_(desc)}</td>"
                    "</tr>"
                )
        return f"<table cellpadding='2'>{''.join(rows)}</table>"

    col_html = "</td><td width='24'></td><td valign='top'>".join(
        _render_column(col)
        for col in _columns(keymap.groups(where), HELP_COLUMNS[where])
    )
    return f"<table><tr><td valign='top'>{col_html}</td></tr></table>"


class OverlaysMixin:
    # ── Transient confirmation overlays (flashes) ──

    _FLASH_BLUE = (43, 108, 176)     # bookmark goto confirmation
    _FLASH_RED = (199, 80, 80)       # delete pop

    def _spawn_flash(self, rect: QRectF, *, color, mode: str = "pulse",
                     dur: int = 200):
        """Add a transient overlay easing 0->1 then dropping itself.

        ``mode`` picks the look: ``hold`` (blue bookmark outline that holds
        then fades), ``pulse`` (a quick expanding ring — snap lock-in), or
        ``shrink`` (collapses toward its centre — delete pop).
        """
        if rect is None or rect.isNull():
            return
        entry = {"rect": QRectF(rect), "color": color, "mode": mode, "p": 0.0}
        # Cheap runaway guard: keep the overlay list bounded.
        self._flashes.append(entry)
        if len(self._flashes) > 24:
            del self._flashes[:-24]

        def _set(v):
            entry["p"] = v
            self.viewport().update()

        def _done():
            try:
                self._flashes.remove(entry)
            except ValueError:
                pass
            self.viewport().update()

        self._animate_fade(0.0, 1.0, _set, dur=dur, on_finished=_done)

    def flash_anchor(self, rect: QRectF):
        """Briefly outline a scene rect in blue, fading out — a confirmation
        of what a bookmark frames.
        """
        self._spawn_flash(rect, color=self._FLASH_BLUE, mode="hold", dur=700)

    def _draw_flashes(self, painter: QPainter):
        """Drawn while the painter is still in scene coordinates."""
        if not self._flashes:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for f in self._flashes:
            p = f["p"]
            r, g, b = f["color"]
            mode = f["mode"]
            rect = f["rect"]
            if mode == "hold":
                # Hold full strength briefly, then fade across the back half.
                op = 1.0 if p < 0.35 else max(0.0, 1.0 - (p - 0.35) / 0.65)
                grow, radius = 0.0, 8
            elif mode == "shrink":
                op = max(0.0, 1.0 - p)
                grow, radius = -min(rect.width(), rect.height()) * 0.18 * p, 6
            else:   # pulse
                op = max(0.0, 1.0 - p)
                grow, radius = 4.0 * p, 6
            if op <= 0.0:
                continue
            draw_rect = rect.adjusted(-grow, -grow, grow, grow)
            pen = QPen(QColor(r, g, b, int(220 * op)), 0)
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(r, g, b, int(36 * op))))
            painter.drawRoundedRect(draw_rect, radius, radius)
        painter.restore()

    # ── Toast (transient action feedback) ──

    def toast(self, text: str, kind: str = "info"):
        """Show a transient HUD pill confirming an action.

        ``info``/``warn`` auto-clear after a couple of seconds; ``error`` sticks
        until the next toast so a failure can't scroll past unseen.
        """
        self._toast_text = text
        self._toast_kind = kind
        if self._toast_timer is not None:
            self._toast_timer.stop()
            self._toast_timer = None
        if kind != "error":
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(2400)
            timer.timeout.connect(self._clear_toast)
            timer.start()
            self._toast_timer = timer
        self.viewport().update()

    def _clear_toast(self):
        self._toast_text = ""
        self._toast_timer = None
        self.viewport().update()

    # ── Fade helper (premium micro-motion for transient overlays) ──

    def _animate_fade(self, start, end, setter, dur: int = 110,
                      on_finished=None):
        """Ease ``setter`` from ``start`` to ``end`` over ``dur`` ms (OutCubic).

        The animation is held in ``_fade_anims`` so Qt doesn't garbage-collect it
        mid-flight, and removed on completion.
        """
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: setter(float(v)))

        def _done():
            if on_finished is not None:
                on_finished()
            self._fade_anims.discard(anim)

        anim.finished.connect(_done)
        self._fade_anims.add(anim)
        anim.start()
        return anim

    def _animate_scale(self, items, start, end, dur: int = 160):
        """Ease ``setScale`` from ``start`` to ``end`` over ``dur`` ms with an
        OutBack overshoot — a subtle 'pop' about each item's own centre."""
        live = []
        for it in items:
            try:
                it.setTransformOriginPoint(it.boundingRect().center())
                it.setScale(start)
                live.append(it)
            except RuntimeError:
                pass
        if not live:
            return

        def _set(v):
            for it in live:
                try:
                    it.setScale(v)
                except RuntimeError:
                    pass
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.valueChanged.connect(lambda v: _set(float(v)))
        anim.finished.connect(lambda: self._fade_anims.discard(anim))
        self._fade_anims.add(anim)
        anim.start()
        return anim

    def _draw_toast(self, painter: QPainter):
        if not self._toast_text:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        is_error = self._toast_kind == "error"
        is_warn = self._toast_kind == "warn"
        glyph = "⚠" if (is_error or is_warn) else "✓"  # ⚠ / ✓
        text = f"{glyph}  {self._toast_text}"

        font = QFont(FONT_FAMILY, 11)
        painter.setFont(font)
        fm = painter.fontMetrics()
        pad_x, pad_y = 14, 8
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        rw = tw + pad_x * 2
        rh = th + pad_y * 2
        vp = self.viewport().rect()
        rx = (vp.width() - rw) / 2
        ry = vp.height() - rh - 24

        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.94)
        accent = QColor(theme.NOTE_TASK_COLOR) if is_error else (
            QColor(theme.SELECT_COLOR) if is_warn else QColor(theme.HEATMAP_STOPS[1][1]))
        painter.setPen(QPen(accent, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 8, 8)
        # Border carries the status color; the text is the card's own ink, which
        # inverts with it — a fixed near-white would vanish on the light card.
        painter.setPen(QPen(theme.overlay_ink(0.92)))
        painter.drawText(QRectF(rx, ry, rw, rh), Qt.AlignmentFlag.AlignCenter,
                         text)
        painter.restore()

    # ── Empty-board hint ──

    # (line, point size) — the first keys a blank board can be started with.
    # Keys must stay in sync with the mode shortcuts in GrafliView.keyPressEvent.
    _EMPTY_HINT = (
        ("n box  ·  t note  ·  i image", 15),
        ("F1 all keys", 11),
    )

    def _empty_hint_lines(self) -> tuple[tuple[str, int], ...]:
        """Return the starting hint's (line, size) pairs, () when it is off.

        A board with nothing on it offers no way in to a keyboard-driven
        canvas (#153); the moment the first element lands the hint has done
        its job and the board speaks for itself.
        """
        board = self._board
        if board is None:
            return ()
        if board.boxes or board.notes or board.images or board.arrows:
            return ()
        return self._EMPTY_HINT

    def _draw_empty_hint(self, painter: QPainter):
        """Paint the starting hint in the middle of the viewport.

        Painted rather than a widget, so it takes no clicks and — like the
        grid dots — stays out of exports, which render the scene, not the view.
        """
        lines = self._empty_hint_lines()
        if not lines:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(QPen(QColor(theme.INK_MUTED)))
        gap = 12
        heights = []
        for _, size in lines:
            painter.setFont(QFont(FONT_FAMILY, size))
            heights.append(painter.fontMetrics().height())
        vp = self.viewport().rect()
        y = vp.center().y() - (sum(heights) + gap * (len(lines) - 1)) / 2
        for (text, size), h in zip(lines, heights):
            painter.setFont(QFont(FONT_FAMILY, size))
            painter.drawText(QRectF(0, y, vp.width(), h),
                             Qt.AlignmentFlag.AlignCenter, text)
            y += h + gap
        painter.restore()

    # ── Debug overlay ──

    def _record_shortcut(self, label: str):
        """Record a shortcut label for the debug overlay."""
        self._debug_last_shortcut = label
        if self._debug_fade_timer is not None:
            self._debug_fade_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(1500)
        timer.timeout.connect(self._clear_debug_overlay)
        timer.start()
        self._debug_fade_timer = timer
        self.viewport().update()

    def _clear_debug_overlay(self):
        self._debug_last_shortcut = ""
        self._debug_fade_timer = None
        self.viewport().update()

    def _draw_debug_overlay(self, painter: QPainter):
        if not self._debug_last_shortcut:
            return
        if not self._debug_overlay and not self._debug_last_shortcut.startswith("DEBUG"):
            return
        painter.resetTransform()
        font = QFont(FONT_FAMILY, 11)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text = self._debug_last_shortcut
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x, pad_y = 12, 6
        rx = MINIMAP_MARGIN
        ry = MINIMAP_MARGIN
        rw = tw + pad_x * 2
        rh = th + pad_y * 2
        bg = QColor(30, 30, 30, 180)
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255, 220)))
        painter.drawText(
            QRectF(rx, ry, rw, rh),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # ── Glyph picker ──

    def _open_glyph_picker(self):
        picker = GlyphPicker(self.viewport())
        vp = self.viewport().rect()
        pw = 420
        ph = 460

        # Position near the active item
        anchor = None
        if self._editor and self._editor.parentItem():
            anchor = self._editor.parentItem()
        else:
            sel = self._scene.selectedItems()
            if sel:
                anchor = sel[0]

        if anchor is not None:
            item_rect = self.mapFromScene(anchor.sceneBoundingRect()).boundingRect()
            px = item_rect.center().x() - pw // 2
            py = item_rect.top() - ph - 8
            if py < 0:
                py = item_rect.bottom() + 8
        else:
            px = (vp.width() - pw) // 2
            py = 60

        px = max(0, min(px, vp.width() - pw))
        py = max(0, min(py, vp.height() - ph))
        picker.move(self.viewport().mapToGlobal(QPoint(int(px), int(py))))

        picker.glyph_selected.connect(self._insert_glyph)
        picker.show()

    def _insert_glyph(self, char: str):
        if self._editor:
            char = ensure_text_presentation(char)
            cursor = self._editor.textCursor()
            cursor.insertText(char)
            self._editor.setTextCursor(cursor)
            self._editor.setFocus()

    # ── Cheatsheet (F1) ──

    def _show_cheatsheet(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Help")

        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            w = min(900, int(geo.width() * 0.75))
            h = int(geo.height() * 0.70)
        else:
            w, h = 900, 600
        dlg.resize(w, h)

        tabs = QTabWidget(dlg)
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {theme.INFO_COLOR.name()};"
            f" background: {theme.HELP_BG.name()}; }}"
            f" QTabBar::tab {{ background: {theme.HELP_BG.name()};"
            f" color: {theme.HELP_FG.name()};"
            f" padding: 6px 14px; border: 1px solid {theme.HELP_BORDER.name()}; }}"
            f" QTabBar::tab:selected {{ background: {theme.HELP_TAB_SELECTED.name()};"
            f" border-bottom-color: {theme.INFO_COLOR.name()}; }}"
        )

        # ── Tab 1: shortcuts ──
        shortcuts_tab = QWidget(tabs)
        filter_input = QLineEdit(shortcuts_tab)
        filter_input.setPlaceholderText("Type to filter shortcuts\u2026")
        filter_input.setStyleSheet(
            f"QLineEdit {{ background: {theme.HELP_BG.name()};"
            f" color: {theme.HELP_FG.name()};"
            f" border: 1px solid {theme.INFO_COLOR.name()}; padding: 4px; }}"
        )
        browser = QTextBrowser(shortcuts_tab)
        browser.setOpenLinks(False)
        font = browser.font()
        font.setPointSize(13)
        browser.setFont(font)
        browser.setStyleSheet(
            f"QTextBrowser {{ background: {theme.HELP_BG.name()};"
            f" color: {theme.HELP_FG.name()}; border: none; }}"
        )
        browser.setHtml(cheatsheet_html(keymap.APP))
        filter_input.textChanged.connect(
            lambda t: browser.setHtml(cheatsheet_html(keymap.APP, t))
        )
        sc_layout = QVBoxLayout(shortcuts_tab)
        sc_layout.addWidget(filter_input)
        sc_layout.addWidget(browser, 1)
        tabs.addTab(shortcuts_tab, "Shortcuts")

        # ── Tab 2: the browser tab of grafli serve ──
        tab_browser = QTextBrowser(tabs)
        tab_browser.setOpenLinks(False)
        tab_browser.setFont(font)
        tab_browser.setStyleSheet(
            f"QTextBrowser {{ background: {theme.HELP_BG.name()};"
            f" color: {theme.HELP_FG.name()}; border: none; }}"
        )
        tab_browser.setHtml(cheatsheet_html(keymap.TAB))
        tabs.addTab(tab_browser, "Browser Tab")

        # ── Tab 3: text annotation formats ──
        notes_browser = QTextBrowser(tabs)
        notes_browser.setOpenLinks(False)
        notes_browser.setFont(font)
        notes_browser.setStyleSheet(
            f"QTextBrowser {{ background: {theme.HELP_BG.name()};"
            f" color: {theme.HELP_FG.name()}; border: none;"
            " padding: 8px; }}"
        )
        notes_browser.setHtml(self._notes_help_html())
        tabs.addTab(notes_browser, "Text Annotations")
        # The Markdown editor (textli) owns its own help now — press F1 while the
        # zen editor is open to see it. grafli's F1 covers only the diagram.

        page_btn = QPushButton("grafli at a glance \u2197", dlg)
        page_btn.setObjectName("at_a_glance")
        page_btn.setToolTip("How to work with grafli and your agent, and "
                            "every key by mode, in your browser")
        page_btn.clicked.connect(self._open_help_page)
        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(page_btn)
        buttons.addStretch(1)
        buttons.addWidget(btn)

        layout = QVBoxLayout(dlg)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)

        filter_input.setFocus()
        dlg.exec()

    def _open_help_page(self):
        """Write the "grafli at a glance" page for this version and open it
        in the browser: it needs no internet and matches the keys here."""
        from grafli import helppage
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(helppage.local_copy())))

    def _notes_help_html(self) -> str:
        hdr = (
            f"color:{theme.INFO_COLOR.name()};font-weight:bold;"
            "padding-top:10px;padding-bottom:4px"
        )
        kw = f"color:{theme.INFO_COLOR.name()};font-weight:bold"
        code_bg = (
            f"background:{theme.HELP_CODE_BG.name()};color:{theme.HELP_FG.name()};"
            "padding:8px;"
            "font-family:monospace;white-space:pre;display:block;"
            f"border-left:3px solid {theme.INFO_COLOR.name()}"
        )
        mono = "font-family:monospace"
        dim = f"color:{theme.INK_DISABLED.name()}"
        kw_blue = f"color:{theme.NOTE_COLOR.name()};font-weight:bold"
        kw_red = f"color:{theme.NOTE_TASK_COLOR.name()};font-weight:bold"
        return f"""
        <p style='{hdr}'>TEXT ANNOTATIONS</p>
        <p>Grafli text can annotate nodes, edges, and local logic. Edit mode
        always shows the raw text; display mode adds visual treatment for the
        conventions below.</p>

        <p style='{hdr}'>Informational &mdash; plain text</p>
        <p>Default note. Blue text on a light badge-style background.</p>

        <p style='{hdr}'>Task &mdash; <span style='{mono}'>T:</span> /
           <span style='{mono}'>TODO:</span></p>
        <p>Red badge + body. Also accepts <span style='{mono}'>t:</span> /
        <span style='{mono}'>todo:</span> &mdash; case-insensitive. The
        rendered badge is normalised to <span style='{mono}'>T:</span>.
        Use for todos that an agent can act on.</p>

        <p style='{hdr}'>Question &mdash; <span style='{mono}'>Q:</span> /
           <span style='{mono}'>QUESTION:</span></p>
        <p>Purple badge + body. Also accepts <span style='{mono}'>q:</span> /
        <span style='{mono}'>question:</span>. Normalised to
        <span style='{mono}'>Q:</span>. Use for questions an agent can
        answer inline.</p>

        <p style='{hdr}'>Discussion &mdash;
           <span style='{mono}'>Alice: &hellip; \\n Bob: &hellip;</span></p>
        <p>Two or more speakers render as a threaded conversation with
        per-speaker colored badges. A speaker prefix is a name that starts
        with an uppercase letter, 1&ndash;16 chars of letters/digits/<span
        style='{mono}'>_</span>/<span style='{mono}'>-</span>, followed by
        <span style='{mono}'>:</span> and a space.</p>

        <p style='{hdr}'>Code &mdash; <span style='{mono}'>code:</span></p>
        <p>A note whose first non-empty line is
        <span style='{mono}'>code:</span> renders as a stylized pseudocode
        block. The pseudocode is <b>not</b> real source code &mdash; it's a
        minimal language for summarizing implementations at a glance.</p>
        <ul>
          <li><b>First body line is the function signature</b> &mdash;
              rendered bold with a divider rule beneath.</li>
          <li><b>Indentation carries block structure</b> (2 spaces per
              level). Indent guides are drawn automatically.</li>
          <li>Trailing <span style='{mono}'>:</span> on keywords is
              optional &mdash; <span style='{mono}'>if cond</span> and
              <span style='{mono}'>if: cond</span> render the same.</li>
          <li>Plain assignments need no keyword:
              <span style='{mono}'>out = []</span>.</li>
        </ul>

        <p style='{kw_blue}'>Flow keywords (blue, bold)</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>if</td><td>condition</td></tr>
          <tr><td style='{mono}'>else</td><td>alternative branch</td></tr>
          <tr><td style='{mono}'>for</td>
              <td>iteration &mdash;
                  <span style='{mono}'>for x in xs</span></td></tr>
          <tr><td style='{mono}'>while</td><td>loop</td></tr>
          <tr><td style='{mono}'>try</td><td>protected block</td></tr>
          <tr><td style='{mono}'>catch</td><td>error handling</td></tr>
          <tr><td style='{mono}'>return</td><td>exit value</td></tr>
          <tr><td style='{mono}'>call</td><td>important call</td></tr>
          <tr><td style='{mono}'>await</td><td>async wait / blocking op</td></tr>
          <tr><td style='{mono}'>emit</td><td>event / message emission</td></tr>
          <tr><td style='{mono}'>state</td><td>state transition (<span style='{mono}'>from -&gt; to</span>)</td></tr>
        </table>

        <p style='{kw_red}'>Contract keywords (red, bold) &mdash; reviewer&rsquo;s eye lands here first</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>pre</td><td>precondition</td></tr>
          <tr><td style='{mono}'>post</td><td>postcondition</td></tr>
          <tr><td style='{mono}'>assert</td><td>invariant / expected fact</td></tr>
          <tr><td style='{mono}'>verify</td><td>test / trace that proves behavior</td></tr>
          <tr><td style='{mono}'>risk</td><td>failure mode / review risk</td></tr>
          <tr><td style='{mono}'>err</td><td>error / raise</td></tr>
        </table>

        <p style='{kw}'>Inline elements</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>@path:line</td>
              <td>clickable reference &mdash; opens the file at that line in your editor; a relative path starts at the board's <span style='{mono}'># source:</span> repo; opening the board warns when that repo moved on from its <span style='{mono}'>@ rev</span></td></tr>
          <tr><td style='{mono}'># &hellip;</td>
              <td>comment (italic, muted)</td></tr>
          <tr><td style='{mono}'>"..."  #FFF  42  true</td>
              <td>literal values render as plain text</td></tr>
        </table>

        <p style='{kw}'>Example</p>
        <div style='{code_bg}'>code:
tokenize(raw) -&gt; [Token]
if raw.len &gt; MAX:
  err too-long
out = []
for ch in raw:
  # skip whitespace
  out += make_tok(ch)
return out  @parser.py:44</div>

        <p style='{dim}'>Style guidance: prefer short predicates and named
        operations over long OO chains
        (<span style='{mono}'>blank(line)</span> reads faster than
        <span style='{mono}'>line.stripped.isEmpty</span>) &mdash; the
        snippet should reveal <i>what happens</i>, not literally mirror
        the source.</p>

        <p style='{hdr}'>Edge Labels &mdash; relationship kinds</p>
        <p>Arrow labels can start with a relationship kind such as
        <span style='{mono}'>data: payload</span>,
        <span style='{mono}'>call: validate()</span>, or
        <span style='{mono}'>step: 1</span>. Known prefixes color the edge and
        render as small chips beside the remaining label text. The raw label
        stays directly editable with <span style='{mono}'>e</span>. Supported kinds:
        <span style='{mono}'>call</span>, <span style='{mono}'>data</span>,
        <span style='{mono}'>event</span>, <span style='{mono}'>state</span>,
        <span style='{mono}'>step</span>, <span style='{mono}'>verify</span>,
        <span style='{mono}'>owns</span>, <span style='{mono}'>depends</span>,
        <span style='{mono}'>risk</span>, <span style='{mono}'>note</span>.</p>

        <p style='{hdr}'>Block Text</p>
        <p>Notes can use triple-quoted text in the file format when the text
        contains quotes or should stay readable across multiple lines. In the
        canvas this is still just an ordinary editable note.</p>
        """

    def _show_graph_stats_dialog(self):
        hdr = f"color:{theme.INFO_COLOR.name()};font-weight:bold;font-size:13px"
        cell = "padding:4px 8px"
        html = f"""
        <p style='{hdr}'>GRAPH COMPLEXITY METRICS</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr>
            <td style='{cell}'><b>N (Nodes)</b></td>
            <td style='{cell}'>Number of boxes in the diagram.</td>
          </tr>
          <tr>
            <td style='{cell}'><b>E (Edges)</b></td>
            <td style='{cell}'>Number of arrows / connections.</td>
          </tr>
          <tr>
            <td style='{cell}'><b>C (Cyclomatic)</b></td>
            <td style='{cell}'>
              E &minus; N + 2P &nbsp;(P = connected components).<br>
              Measures independent paths through the graph;<br>
              higher values indicate more interconnection.
            </td>
          </tr>
        </table>
        <br>
        <p style='{hdr}'>FUZZY LABEL THRESHOLDS</p>
        <table border='1' cellpadding='4' cellspacing='0'
               style='border-collapse:collapse;margin-left:8px;
                      border-color:{theme.HELP_BORDER.name()}'>
          <tr style='background:{theme.HELP_TAB_SELECTED.name()};
                     color:{theme.HELP_FG.name()}'>
            <th style='{cell}'>Label</th>
            <th style='{cell}'>Nodes (N)</th>
            <th style='{cell}'>Cyclomatic (C)</th>
          </tr>
          <tr>
            <td style='{cell};color:#7fb97f'><b>Simple</b></td>
            <td style='{cell}'>&le; 8</td>
            <td style='{cell}'>&le; 3</td>
          </tr>
          <tr>
            <td style='{cell};color:#c9b84e'><b>Moderate</b></td>
            <td style='{cell}'>9 &ndash; 20</td>
            <td style='{cell}'>4 &ndash; 8</td>
          </tr>
          <tr>
            <td style='{cell};color:#d4883a'><b>Intricate</b></td>
            <td style='{cell}'>21 &ndash; 40</td>
            <td style='{cell}'>9 &ndash; 15</td>
          </tr>
          <tr>
            <td style='{cell};color:#c75050'><b>Dense</b></td>
            <td style='{cell}'>&gt; 40</td>
            <td style='{cell}'>&gt; 15</td>
          </tr>
        </table>
        <br>
        <p style='color:{theme.STATUS_DIM.name()};font-size:11px;margin-left:8px'>
          The overall label is the <i>maximum</i> tier from N and C.
        </p>
        """

        dlg = QDialog(self)
        dlg.setWindowTitle("Graph Complexity")
        dlg.setFixedWidth(480)

        browser = QTextBrowser(dlg)
        browser.setOpenLinks(False)
        browser.setHtml(html)

        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)

        layout = QVBoxLayout(dlg)
        layout.addWidget(browser)
        layout.addWidget(btn)

        dlg.exec()

