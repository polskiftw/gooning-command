"""GParty local R2 deduper."""

__version__ = "0.1.0"

# Install review queue stability guards before the application classes are used.
from . import review_ui as _review_ui  # noqa: E402,F401
