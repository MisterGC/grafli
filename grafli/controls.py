"""The control scheme the desktop app is driven by (#352).

grafli has two:

* ``vim`` — single keys and modes (``n`` a box, ``s c`` a colour, ``g d``
  into a board), the scheme grafli was built with;
* ``standard`` — the menus, a toolbar, right-click menus and the shortcuts
  people know from other apps (Ctrl/⌘+C, Delete, F2 …). No plain letter key
  runs a command there.

The scheme is process-wide state, like :mod:`grafli.theme`: ``main()``
restores the saved choice (or asks for one on the first start) before the
window is built, and the window switches it in place without a restart. The
window itself never reads the saved choice, so a test that builds a window
runs the vim scheme unless it asks for the other one.
"""

from __future__ import annotations

VIM = "vim"
STANDARD = "standard"
SCHEMES = (VIM, STANDARD)

TITLES = {VIM: "Vim keys", STANDARD: "Standard"}
BLURBS = {
    VIM: "Single keys and modes, the way vim works: n makes a box, s c "
         "colours it, g d goes into its board. Fast once learnt; nothing "
         "shows on screen.",
    STANDARD: "Menus, a toolbar and right-click menus, with the shortcuts "
              "you know from other apps: Ctrl/⌘+C and V, Ctrl/⌘+Z, "
              "Delete, F2 to rename. No single letter runs a command.",
}

SETTINGS_KEY = "controls/scheme"
# Settings grafli wrote before there was a choice of scheme: one of them
# means the app has been used, on the vim keys. (Not all keys: on macOS
# those include the system's own.)
_EARLIER_USE_KEYS = ("theme/name", "window/geometry", "sidepanel/visible",
                     "sidepanel/width", "grid/mode")

_scheme = VIM


def scheme() -> str:
    return _scheme


def is_standard() -> bool:
    return _scheme == STANDARD


def set_scheme(name: str) -> str:
    """Make ``name`` the active scheme (an unknown name keeps vim)."""
    global _scheme
    _scheme = name if name in SCHEMES else VIM
    return _scheme


def _settings():
    """Where the choice is kept, next to the theme (a seam tests replace)."""
    from PySide6.QtCore import QSettings
    return QSettings("Grafli", "Grafli")


def saved_scheme() -> str | None:
    """The scheme chosen earlier, or None before the first choice."""
    value = _settings().value(SETTINGS_KEY, "", type=str)
    return value if value in SCHEMES else None


def save_scheme(name: str) -> None:
    settings = _settings()
    settings.setValue(SETTINGS_KEY, name)
    settings.sync()


def first_choice_default() -> str:
    """What the first-start question falls back on when it is closed
    without an answer. Someone who has used grafli before (it kept a theme,
    a window, a grid) has been on the vim keys, and keeps them; a new user
    gets the standard scheme, the one that shows its commands."""
    settings = _settings()
    used = any(settings.contains(k) for k in _EARLIER_USE_KEYS)
    return VIM if used else STANDARD


def ask_scheme(parent=None, default: str = STANDARD) -> str:
    """Ask which scheme to use, ``default`` if the question is closed
    unanswered (a seam tests replace)."""
    from grafli.standard_ui import SchemeDialog
    dlg = SchemeDialog(parent, current=default)
    dlg.exec()
    return dlg.choice


def restore_or_ask(parent=None) -> str:
    """At start-up: the saved scheme, or — the first time only — the one
    the user picks, saved so the question never comes again."""
    saved = saved_scheme()
    if saved is None:
        default = first_choice_default()
        saved = ask_scheme(parent, default=default)
        if saved not in SCHEMES:
            saved = default
        save_scheme(saved)
    return set_scheme(saved)
