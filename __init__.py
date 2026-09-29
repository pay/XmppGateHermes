"""Hermes XMPP platform plugin entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Hermes loads directory plugins as hermes_plugins.<slug> from __init__.py.
# Add this plugin directory so sibling package hermes_xmpp is importable without
# requiring an editable pip install.
_plugin_dir = str(Path(__file__).resolve().parent)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from hermes_xmpp.adapter import register

__all__ = ["register"]
