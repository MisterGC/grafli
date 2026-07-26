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
    yield
    theme.set_theme("light")
