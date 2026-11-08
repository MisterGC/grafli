"""Shared test fixtures."""

import pytest

from grafli import theme


@pytest.fixture(autouse=True)
def _pinned_theme():
    """Run every test against the light theme.

    MainWindow restores the theme from QSettings, so without this a developer
    who left the app in dark mode would see colour assertions fail — the suite
    must not depend on machine state. Tests that exercise the dark theme opt in
    by calling ``theme.set_theme`` themselves.
    """
    theme.set_theme("light")
    theme.set_map_palette({})
    yield
    theme.set_theme("light")
    theme.set_map_palette({})


@pytest.fixture(autouse=True)
def _private_serve_state(tmp_path_factory, monkeypatch):
    """Keep ``grafli serve``'s state file (its agent key) out of the real
    ``~/.local/state``: a test that runs the server writes it here, and a
    ``grafli agent`` on this machine never finds a test's server."""
    monkeypatch.setenv("GRAFLI_STATE_DIR",
                       str(tmp_path_factory.mktemp("serve-state")))
