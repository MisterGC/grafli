"""Shift+Delete vault-doc removal reports failures instead of omitting them.

A doc the OS refuses to delete used to silently vanish from the
confirmation toast — the user read "deleted" for a file still on disk.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window(tmp: str, board_text: str):
    QApplication.instance() or QApplication([])
    f = os.path.join(tmp, "t.grafli")
    with open(f, "w") as fh:
        fh.write(board_text)
    from grafli.app import MainWindow
    w = MainWindow(f)
    w.resize(900, 600)
    return w


def test_undeletable_doc_is_named_in_the_toast(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        w = _window(tmp, '#!grafli v1\n@ box a "A" 0,0 200x80\n')

        class _Stubborn:
            def unlink(self, missing_ok=False):
                raise OSError("locked")

        monkeypatch.setattr("grafli.resources.doc_path",
                            lambda p, n: _Stubborn())
        toasts = []
        monkeypatch.setattr(
            w._view, "toast",
            lambda text, kind="info": toasts.append((text, kind)))

        w._view._handle_deleted_docs({"gone"}, with_docs=True)

        assert toasts, "a failed unlink must surface"
        text, kind = toasts[0]
        assert "could not delete" in text and "gone.md" in text
        assert kind == "warn"


def test_deletable_doc_still_reports_success(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        res = os.path.join(tmp, "t-res")
        os.makedirs(res)
        doc = os.path.join(res, "gone.md")
        with open(doc, "w") as fh:
            fh.write("body\n")
        w = _window(tmp, '#!grafli v1\n@ box a "A" 0,0 200x80\n')
        toasts = []
        monkeypatch.setattr(
            w._view, "toast",
            lambda text, kind="info": toasts.append((text, kind)))

        w._view._handle_deleted_docs({"gone"}, with_docs=True)

        assert not os.path.exists(doc)
        text, kind = toasts[0]
        assert "Deleted from vault" in text and "gone.md" in text
        assert kind == "info"
