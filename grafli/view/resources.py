"""Resource attachments for GrafliView (mixin).

Attaching and opening node resources: the inline resource-type picker,
markdown / grafli / file attachments in the board's vault, image paste and
drop, and launching the right editor or viewer for each kind. The host
GrafliView provides the scene, board model, and undo machinery.
"""

from __future__ import annotations


import re as _re
import shlex
import shutil
import subprocess
from PySide6.QtCore import QPoint, QSettings, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QGraphicsProxyWidget,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QPushButton,
)
from grafli.constants import ARROW_LABEL_FONT_SIZES, FONT_FAMILY
from grafli.format import Arrow
from grafli.items import BoxItem, ImageItem, LabelItem, NoteItem
from grafli.md_note import note_is_md, toggle_task
from pathlib import Path
from textli import InlineVimEditor, ZenMarkdownEditor


class _InlineEditorItem(QGraphicsTextItem):
    """Inline label editor with a soft paper backdrop, so the text being
    typed stays readable on any node fill or connector line (issue #126)."""

    def paint(self, painter, option, widget=None):
        bg = QColor("#F2F0EB")
        bg.setAlphaF(0.92)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(self.boundingRect(), 4, 4)
        super().paint(painter, option, widget)


class _ResourcePicker(QPushButton):
    """Inline popup letting the user pick a resource type to create."""

    resource_selected = Signal(str)

    _STYLE = (
        "QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border};"
        " border-radius: 6px; padding: 6px 10px; font-family: {font}; font-size: 12px; }}"
        "QPushButton:hover {{ background: {hover}; }}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setText("  [m]arkdown    [g]rafli    [f]ile  ")
        self.setStyleSheet(self._STYLE.format(
            bg="#2A2D2E", fg="#D4D4D4", border="#555",
            hover="#3A3D3E", font=FONT_FAMILY,
        ))

    def sizeHint(self):
        return super().sizeHint()

    def keyPressEvent(self, event):
        key = event.text().lower()
        if key == "m":
            self.resource_selected.emit("markdown")
            self.close()
        elif key == "g":
            self.resource_selected.emit("grafli")
            self.close()
        elif key == "f":
            self.resource_selected.emit("file")
            self.close()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class ResourcesMixin:
    # ── Resource handling ────────────────────────────────────────

    @staticmethod
    def _has_attachment(el) -> bool:
        # A doc-bodied note may carry the bare ``&doc`` form (empty url).
        return bool(el.url) or el.attach_kind == "doc"

    def _open_attachment(self, el):
        """Open an element's attachment by its kind: a vault doc in the zen
        editor, a vault sub-board in the app, anything else (links, legacy
        untyped urls) through the url path."""
        window = self.window()
        grafli_path = getattr(window, "_file_path", None)
        if el.attach_kind == "doc" and grafli_path:
            from grafli.format import doc_name
            from grafli.resources import doc_path
            self._open_md_zen(doc_path(Path(grafli_path), doc_name(el)))
            return
        if el.attach_kind == "graph" and grafli_path:
            from grafli.resources import graph_path
            if hasattr(window, "_open_file"):
                window._open_file(graph_path(Path(grafli_path), el.url))
            return
        if el.url:
            self._open_url_string(el.url)

    def _open_resource(self):
        """Open resource for the selected element, or show picker if none."""
        if self._selected_arrow:
            arrow = self._selected_arrow
            if self._has_attachment(arrow):
                self._open_attachment(arrow)
            else:
                self._open_resource_picker_for_arrow(arrow)
            return
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                if self._has_attachment(item.box):
                    self._open_attachment(item.box)
                else:
                    self._open_resource_picker(item, item.box.id)
                return
            if isinstance(item, NoteItem):
                if self._has_attachment(item.note):
                    self._open_attachment(item.note)
                else:
                    self._open_resource_picker(item, item.note.id)
                return
            if isinstance(item, ImageItem):
                if self._has_attachment(item.image):
                    self._open_attachment(item.image)
                else:
                    self._open_resource_picker(item, item.image.id)
                return

    def _open_code_ref(self, ref: str):
        """Open an ``@path[:line]`` reference from a code-mode note.

        Resolution order: configured editor command from QSettings,
        then auto-detected ``code``/``cursor``/``subl``, finally OS open.
        Relative paths are resolved against the .grafli file's directory.
        """
        target = ref[1:] if ref.startswith("@") else ref
        line_no: int | None = None
        m = _re.match(r"^(.+):(\d+)$", target)
        if m:
            target = m.group(1)
            line_no = int(m.group(2))

        path = Path(target).expanduser()
        if not path.is_absolute():
            window = self.window()
            if hasattr(window, "_file_path") and window._file_path:
                path = Path(window._file_path).parent / path
        path = path.resolve()

        cmd_template = QSettings("Grafli", "Grafli").value(
            "editor/command", "", type=str,
        ) or ""
        if not cmd_template:
            for candidate in ("code", "cursor", "subl"):
                if shutil.which(candidate):
                    cmd_template = (
                        f"{candidate} -g {{path}}:{{line}}"
                        if candidate != "subl"
                        else "subl {path}:{line}"
                    )
                    break

        if cmd_template:
            try:
                rendered = cmd_template.format(
                    path=str(path),
                    line=line_no if line_no is not None else 1,
                )
                subprocess.Popen(shlex.split(rendered), start_new_session=True)
                return
            except (OSError, ValueError, KeyError):
                pass

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_url_string(self, url_str: str):
        """Open a URL string, handling .md and .grafli files specially."""
        resolved = self._resolve_url(url_str)
        if resolved.isLocalFile():
            local = resolved.toLocalFile()
            if local.endswith(".md"):
                self._open_md_zen(
                    Path(local), anchor=resolved.fragment() or "",
                )
                return
            if local.endswith(".grafli"):
                window = self.window()
                if hasattr(window, '_open_file'):
                    window._open_file(Path(local))
                return
        QDesktopServices.openUrl(resolved)

    def _open_resource_picker(self, item, element_id: str):
        """Show the inline resource picker near the given item."""
        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        picker = _ResourcePicker(self.viewport())
        item_rect = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
        pw = picker.sizeHint().width()
        ph = picker.sizeHint().height()
        px = int(item_rect.center().x()) - pw // 2
        py = int(item_rect.top()) - ph - 8
        if py < 0:
            py = int(item_rect.bottom()) + 8
        vp = self.viewport().rect()
        px = max(0, min(px, vp.width() - pw))
        picker.move(self.viewport().mapToGlobal(QPoint(px, py)))
        picker.resource_selected.connect(
            lambda kind: self._create_resource(item, element_id, kind)
        )
        picker.show()

    def _open_resource_picker_for_arrow(self, arrow):
        """Show inline resource picker for an arrow."""
        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        aid = f"{arrow.from_id}--{arrow.to_id}"
        # Position near arrow label or midpoint
        picker = _ResourcePicker(self.viewport())
        center = self.viewport().rect().center()
        for it in self._arrow_items:
            if isinstance(it, LabelItem) and it.data(0) is arrow:
                center = self.mapFromScene(it.pos()).toPoint()
                break
        pw = picker.sizeHint().width()
        ph = picker.sizeHint().height()
        px = center.x() - pw // 2
        py = center.y() - ph - 8
        vp = self.viewport().rect()
        px = max(0, min(px, vp.width() - pw))
        py = max(0, py)
        picker.move(self.viewport().mapToGlobal(QPoint(int(px), int(py))))
        picker.resource_selected.connect(
            lambda kind: self._create_arrow_resource(arrow, aid, kind)
        )
        picker.show()

    def _create_resource(self, item, element_id: str, kind: str):
        """Create a vault attachment for a node and set its typed reference."""
        from grafli.md_note import is_md_note, md_body
        from grafli.resources import ensure_res_dir
        window = self.window()
        grafli_path = window._file_path
        rd = ensure_res_dir(grafli_path)

        if kind == "markdown":
            md_path = rd / f"{element_id}.md"
            if isinstance(item, NoteItem):
                # On a note, "attach markdown" means: become doc-bodied — the
                # doc IS the body, seeded with the note's current text.
                note = item.note
                if not md_path.exists():
                    body = md_body(note.text) if is_md_note(note.text) \
                        else note.text
                    md_path.write_text(body, encoding="utf-8")
                self._push_undo()
                note.text = md_path.read_text(encoding="utf-8")
                note.attach_kind, note.url = "doc", ""
                item._update_url_indicator()
                item.update()
                self.mark_dirty()
            else:
                if not md_path.exists():
                    label = self._element_label(item)
                    md_path.write_text(f"# {label}\n\n", encoding="utf-8")
                self._set_element_attachment(item, "doc", element_id)
            self._open_md_zen(md_path)
        elif kind == "grafli":
            sub_path = rd / f"{element_id}.grafli"
            if not sub_path.exists():
                label = self._element_label(item)
                sub_path.write_text(
                    f"#!grafli v1\n# {label}\n", encoding="utf-8",
                )
            self._set_element_attachment(item, "graph", element_id)
            window._open_file(sub_path)
        elif kind == "file":
            self._set_url()

    def _create_arrow_resource(self, arrow, aid: str, kind: str):
        """Create a vault attachment for an arrow and set its typed reference."""
        from grafli.resources import ensure_res_dir
        window = self.window()
        grafli_path = window._file_path
        rd = ensure_res_dir(grafli_path)

        if kind == "markdown":
            md_path = rd / f"{aid}.md"
            if not md_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                md_path.write_text(f"# {title}\n\n", encoding="utf-8")
            self._push_undo()
            arrow.attach_kind, arrow.url = "doc", aid
            self._redraw_arrows()
            self.mark_dirty()
            self._open_md_zen(md_path)
        elif kind == "grafli":
            sub_path = rd / f"{aid}.grafli"
            if not sub_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                sub_path.write_text(
                    f"#!grafli v1\n# {title}\n", encoding="utf-8",
                )
            self._push_undo()
            arrow.attach_kind, arrow.url = "graph", aid
            self._redraw_arrows()
            self.mark_dirty()
            window._open_file(sub_path)
        elif kind == "file":
            self._set_url()

    def _element_label(self, item) -> str:
        """Extract a label string from a graphics item."""
        if isinstance(item, BoxItem):
            return item.box.label.replace("\n", " ")
        if isinstance(item, NoteItem):
            return item.note.text.replace("\n", " ")[:40]
        if isinstance(item, ImageItem):
            return item.image.id
        return ""

    def _set_element_attachment(self, item, kind: str, value: str):
        """Set a typed attachment on a graphics item, push undo, refresh."""
        el = (item.box if isinstance(item, BoxItem)
              else item.note if isinstance(item, NoteItem)
              else item.image if isinstance(item, ImageItem) else None)
        if el is None:
            return
        self._push_undo()
        el.attach_kind, el.url = kind, value
        item._update_url_indicator()
        item.update()
        self.mark_dirty()

    def _quick_edit_markdown(self):
        """Quick-create/open markdown resource for the selected element."""
        if self._zen_editor:
            return

        # A note is its own text — edit it in the zen editor in memory.
        # This works even on an unsaved diagram (no resource file needed),
        # so it runs before the grafli-file guard below.
        if not self._selected_arrow:
            for item in self._scene.selectedItems():
                if isinstance(item, NoteItem):
                    self._zen_edit_note(item)
                    return

        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        grafli_path = window._file_path

        if self._selected_arrow:
            arrow = self._selected_arrow
            aid = f"{arrow.from_id}--{arrow.to_id}"
            if arrow.url and arrow.url.endswith(".md"):
                resolved = self._resolve_url(arrow.url)
                self._open_md_zen(Path(resolved.toLocalFile()))
                return
            from grafli.resources import ensure_res_dir
            rd = ensure_res_dir(grafli_path)
            md_path = rd / f"{aid}.md"
            if not md_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                md_path.write_text(f"# {title}\n\n", encoding="utf-8")
            rel = f"{rd.name}/{md_path.name}"
            self._push_undo()
            arrow.url = rel
            self._redraw_arrows()
            self.mark_dirty()
            self._open_md_zen(md_path)
            return

        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, ImageItem)):
                url = ""
                element_id = ""
                if isinstance(item, BoxItem):
                    url = item.box.url
                    element_id = item.box.id
                elif isinstance(item, ImageItem):
                    url = item.image.url
                    element_id = item.image.id
                if url and url.endswith(".md"):
                    resolved = self._resolve_url(url)
                    self._open_md_zen(Path(resolved.toLocalFile()))
                    return
                if not url:
                    self._create_resource(item, element_id, "markdown")
                return

    def _cancel_zen_edit(self):
        """Discard zen editor."""
        self._zen_editor = None
        self._zen_target = None

    def _resolve_url(self, raw: str) -> QUrl:
        """Resolve a raw URL or local path to a QUrl for opening."""
        url = QUrl(raw)
        if url.isValid() and url.scheme() in ("http", "https", "ftp", "mailto"):
            return url
        # Split off #fragment before path resolution
        fragment = ""
        if "#" in raw:
            raw, fragment = raw.rsplit("#", 1)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            window = self.window()
            if hasattr(window, '_file_path') and window._file_path:
                path = Path(window._file_path).parent / path
        path = path.resolve()
        result = QUrl.fromLocalFile(str(path))
        if fragment:
            result.setFragment(fragment)
        return result

    def _open_url(self):
        """Open URL or local file of the first selected box or note."""
        for item in self._scene.selectedItems():
            url_str = None
            if isinstance(item, BoxItem) and item.box.url:
                url_str = item.box.url
            elif isinstance(item, NoteItem) and item.note.url:
                url_str = item.note.url
            if url_str:
                resolved = self._resolve_url(url_str)
                if resolved.isLocalFile() and resolved.toLocalFile().endswith(".md"):
                    self._open_md_zen(
                        Path(resolved.toLocalFile()),
                        anchor=resolved.fragment() or "",
                    )
                    return
                QDesktopServices.openUrl(resolved)
                return

    def _open_md_zen(self, path: Path, anchor: str = ""):
        """Open a local markdown file in the zen editor."""
        if self._zen_editor:
            return
        if not path.exists():
            path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        self._zen_editor = ZenMarkdownEditor(
            parent=self.window(), text=text, title=path.name,
            file_path=path, anchor=anchor, canvas=self,
        )
        self._zen_editor.cancelled.connect(self._cancel_zen_edit)

    def _zen_edit_note(self, item: NoteItem):
        """Edit a note's own text in the full-window zen editor.

        Unlike boxes/images, a note *is* its text — so the zen experience
        edits the note in memory rather than spawning an attached markdown
        file. Saved text is written straight back to the note.
        """
        if self._zen_editor:
            return
        self._zen_target = item
        self._zen_editor = ZenMarkdownEditor(
            parent=self.window(), text=item.note.text, title=item.note.id,
            file_path=None, canvas=self,
        )
        self._zen_editor.finished.connect(self._commit_zen_note)
        self._zen_editor.cancelled.connect(self._cancel_zen_edit)

    def _commit_zen_note(self, text: str):
        item = self._zen_target
        self._zen_editor = None
        self._zen_target = None
        if not isinstance(item, NoteItem):
            return
        new_text = text.strip()
        if new_text and new_text != item.note.text:
            self._push_undo()
            item.update_text(new_text)
            self.mark_dirty()

    def _edit_selected(self):
        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, NoteItem)):
                self._start_editing(item)
                return

    def _toggle_minimap(self):
        self._minimap_visible = not self._minimap_visible
        self.viewport().update()

    def _minimap_selected_ids(self) -> set[str]:
        """Ids of the currently selected boxes, notes and images — the set
        the minimap rings with a glow."""
        ids = {bid for bid, it in self._box_items.items() if it.isSelected()}
        ids |= {nid for nid, it in self._note_items.items() if it.isSelected()}
        ids |= {iid for iid, it in self._image_items.items() if it.isSelected()}
        return ids

    def _refresh_minimap(self):
        """Repaint just the minimap panel (e.g. after a selection change) so
        its highlight updates without redrawing the whole board."""
        if not self._minimap_visible:
            return
        r = self._minimap_panel_rect
        if r is not None and not r.isNull():
            self.viewport().update(r.toRect().adjusted(-2, -2, 2, 2))
        else:
            self.viewport().update()

    def _start_editing(self, target: BoxItem | NoteItem):
        self._commit_editor()
        self._edit_target = target

        if isinstance(target, NoteItem):
            self._start_note_editing(target)
            return

        text = target.box.label
        pos = target.scenePos()
        rect = target.rect()
        font = target._box_font()
        target._label.setVisible(False)

        editor = _InlineEditorItem(text)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        editor.setTextWidth(rect.width() - 16)
        br = editor.boundingRect()

        anchor = target._get_effective_anchor()
        if anchor == "topleft":
            editor.setPos(pos.x() + 8, pos.y() + 8)
        elif anchor == "topcenter":
            editor.setPos(
                pos.x() + (rect.width() - br.width()) / 2,
                pos.y() + 8,
            )
        else:
            editor.setPos(
                pos.x() + rect.width() / 2 - br.width() / 2,
                pos.y() + rect.height() / 2 - br.height() / 2,
            )

        self._scene.addItem(editor)
        editor.setZValue(1000)
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        self._editor = editor

    def _start_note_editing(self, target: NoteItem):
        """Edit a note in place with the vim-capable inline editor.

        The editor is a plain `QPlainTextEdit` (vim keys, no grafli
        coupling) hosted in a proxy so it scales/pans with the canvas. It
        opens in INSERT mode; Esc drops to NORMAL, a second Esc commits,
        Shift+Esc discards. Markdown notes get syntax highlighting.
        """
        text = target.note.text
        font = target._note_font()

        widget = InlineVimEditor(text, markdown=note_is_md(target.note),
                                 font=font)
        widget.setStyleSheet(
            "QPlainTextEdit {"
            " background: #FBFAF7; color: #2F3437;"
            " border: 1px solid #2F5D5C; border-radius: 4px; padding: 4px;"
            " selection-background-color: #B8D4E8;"
            "}"
        )

        # Width tracks the widest line (bounded by the wrap budget); the
        # widget grows its own height to fit the text as you type.
        fm = QFontMetricsF(font)
        pad = 14
        lines = text.split("\n") or [""]
        content_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
        width_px = int(min(
            max(content_w + 2 * pad + 16, 140),
            target._wrap_width_px(font) + 2 * pad,
        ))

        proxy = QGraphicsProxyWidget()
        proxy.setWidget(widget)
        proxy.setZValue(1000)
        proxy.setPos(target.scenePos())
        self._scene.addItem(proxy)
        target.setVisible(False)

        widget.fit_to_width(width_px)

        widget.committed.connect(self._commit_note_editor)
        widget.cancelled.connect(self._cancel_note_editor)
        self._note_proxy = proxy
        self._note_widget = widget

        # The view must hold Qt focus and route to the proxy as the scene's
        # focus item; the proxy then forwards focus to the embedded editor.
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        proxy.setFocus(Qt.FocusReason.OtherFocusReason)

    def _commit_note_editor(self, text: str):
        target = self._edit_target
        if not isinstance(target, NoteItem):
            return
        new_text = text.strip()
        if new_text and new_text != target.note.text:
            self._push_undo()
            target.update_text(new_text)
            self.mark_dirty()
        self._teardown_note_editor()

    def _toggle_md_task(self, item, idx: int):
        """Flip the *idx*-th task checkbox in a markdown note and persist —
        a one-character source edit, one undo step, no editor."""
        new_text, changed = toggle_task(item.note.text, idx)
        if not changed:
            return
        self._push_undo()
        item.update_text(new_text)
        self.mark_dirty()

    def _cancel_note_editor(self):
        self._teardown_note_editor()

    def _teardown_note_editor(self):
        target = self._edit_target
        proxy = self._note_proxy
        self._note_proxy = None
        self._note_widget = None
        self._edit_target = None
        if isinstance(target, NoteItem):
            target.setVisible(True)
        if proxy is not None:
            # We may be inside the widget's own key handler (Esc commits),
            # so defer removal — destroying the widget synchronously under
            # its running event handler would crash.
            proxy.setVisible(False)
            QTimer.singleShot(0, lambda p=proxy: self._safe_remove_item(p))

    def _safe_remove_item(self, item):
        if item.scene() is self._scene:
            self._scene.removeItem(item)

    def _start_editing_arrow(self, arrow: Arrow):
        self._commit_editor()
        self._edit_target = arrow
        self._clear_arrow_mode()

        mid = self._arrow_label_midpoint()
        if not mid:
            return

        font = QFont(FONT_FAMILY, ARROW_LABEL_FONT_SIZES.get(arrow.textsize, 10))
        editor = _InlineEditorItem(arrow.label)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        br = editor.boundingRect()
        editor.setPos(
            mid.x() - br.width() / 2 + arrow.label_dx,
            mid.y() - br.height() / 2 + arrow.label_dy,
        )

        # Hide existing label items for this arrow
        for gfx in self._selected_arrow_items:
            if isinstance(gfx, QGraphicsSimpleTextItem):
                gfx.setVisible(False)

        self._scene.addItem(editor)
        editor.setZValue(1000)
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        self._editor = editor

    def _commit_editor(self):
        if self._note_widget is not None:
            self._commit_note_editor(self._note_widget.toPlainText())
            return
        if not self._editor or not self._edit_target:
            return
        self._push_undo()
        text = self._editor.toPlainText().strip()
        if isinstance(self._edit_target, Arrow):
            self._edit_target.label = text
            self.mark_dirty()
            self._scene.removeItem(self._editor)
            self._editor = None
            arrow = self._edit_target
            self._edit_target = None
            self._redraw_arrows()
            self._select_arrow(arrow)
            return
        # Empty commits are normally ignored (guards against a stray edit
        # wiping a label), but a glyph element may legitimately want no
        # caption so the icon fills the node — allow clearing then.
        target = self._edit_target
        has_icon = ((isinstance(target, BoxItem) and target.box.icon)
                    or (isinstance(target, NoteItem) and target.note.icon))
        if text or has_icon:
            if isinstance(self._edit_target, BoxItem):
                self._edit_target.update_label(text)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.update_text(text)
            self.mark_dirty()
        if isinstance(self._edit_target, BoxItem):
            self._edit_target._label.setVisible(True)
        elif isinstance(self._edit_target, NoteItem):
            self._edit_target.setVisible(True)
        self._scene.removeItem(self._editor)
        self._editor = None
        self._edit_target = None

    def _cancel_editor(self):
        if self._note_widget is not None:
            self._cancel_note_editor()
            return
        if self._editor:
            if isinstance(self._edit_target, Arrow):
                self._scene.removeItem(self._editor)
                self._editor = None
                arrow = self._edit_target
                self._edit_target = None
                self._redraw_arrows()
                self._select_arrow(arrow)
                return
            if isinstance(self._edit_target, BoxItem):
                self._edit_target._label.setVisible(True)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.setVisible(True)
            self._scene.removeItem(self._editor)
            self._editor = None
            self._edit_target = None

