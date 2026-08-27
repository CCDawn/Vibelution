"""Virtual Human Life trusted first-party plugin."""

from .manifest import PLUGIN_ID, PROMPT_PACK_ID, TOOL_BUNDLE_ID, manifest_projection
from .service import VirtualHumanLifeService

__all__ = [
    "PLUGIN_ID",
    "PROMPT_PACK_ID",
    "TOOL_BUNDLE_ID",
    "VirtualHumanLifeService",
    "manifest_projection",
]
