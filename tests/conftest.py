"""Shared test fixtures."""

import gc

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


@pytest.fixture(autouse=True)
def _qt_garbage_freed_on_main_thread(request):
    """Free the Qt views earlier tests left behind before a serve test.

    A dropped ``GrafliView`` sits in a reference cycle, so only the cyclic
    garbage collector frees it — on whichever thread happens to trigger it.
    A serve test runs uvicorn in a thread; a collection there destroys Qt
    widgets off the GUI thread, and the suite died later in Qt's event
    processing (a segfault or bus error) or timed out a websocket
    handshake. Collecting on the main thread first leaves that thread
    nothing of Qt's to free."""
    module = request.node.module.__name__.rsplit(".", 1)[-1]
    if module.startswith("test_serve"):
        gc.collect()
    yield
