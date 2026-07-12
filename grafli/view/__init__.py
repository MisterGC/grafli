"""Interactive board view for grafli.

``GrafliView`` is the central canvas widget; its implementation is split
across focused mixin modules in this package, composed in ``core``.
"""

from grafli.constants import Mode
from grafli.view.core import GrafliView

__all__ = ["GrafliView", "Mode"]
