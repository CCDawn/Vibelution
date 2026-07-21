"""Runtime scene package-index sidecar sync helpers.

Claim scope: detect stale package_index.json vs in-memory package index and
refresh lightweight sidecar + manifest package fields.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _service():
    from core.web.services import runtime_scene_service

    return runtime_scene_service


def _sync_runtime_scene_package_index_if_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    s = _service()
    if not s._runtime_scene_package_index_sidecar_is_stale(scene_dir, manifest, package_index):
        return
    try:
        s._save_runtime_scene_lightweight_package_index(scene_dir, package_index)
        s._update_runtime_scene_manifest_package_index_fields(scene_dir, manifest, package_index)
    except OSError:
        return


def _runtime_scene_package_index_sidecar_is_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> bool:
    s = _service()
    expected_index = s._runtime_scene_sidecar_compare_payload(
        s._runtime_scene_lightweight_package_index_payload(package_index)
    )
    actual_index = s._runtime_scene_sidecar_compare_payload(
        s._load_scene_json(scene_dir / s.PACKAGE_INDEX_PATH)
    )
    for key, expected_value in expected_index.items():
        if actual_index.get(key) != expected_value:
            return True

    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    expected_package_values = s._runtime_scene_manifest_package_index_values(package_index)
    return any(package.get(key) != expected_value for key, expected_value in expected_package_values.items())


def _update_runtime_scene_manifest_package_index_fields(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    s = _service()
    package = manifest.get("package")
    if not isinstance(package, dict):
        package = {}
    package.update({"schema_version": 2, **s._runtime_scene_manifest_package_index_values(package_index)})
    package["updated_at"] = s._now_utc()
    manifest["package"] = package
    s._save_scene_manifest(scene_dir, manifest)
