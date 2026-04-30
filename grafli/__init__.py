"""grafli — keyboard-driven plain-text diagram tool."""

from __future__ import annotations

try:
    from grafli._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
