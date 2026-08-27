"""Trusted first-party Agent plugin registry."""

from __future__ import annotations

from typing import Any

from .virtual_human_life.manifest import manifest_projection as _virtual_human_manifest


def installed_plugin_catalog() -> list[dict[str, Any]]:
    """Return immutable metadata for trusted plugins shipped with Vibelution."""

    return [_virtual_human_manifest()]


def installed_plugin(plugin_id: str) -> dict[str, Any] | None:
    normalized = str(plugin_id or "").strip()
    return next(
        (item for item in installed_plugin_catalog() if item["pluginId"] == normalized),
        None,
    )


__all__ = ["installed_plugin", "installed_plugin_catalog"]
