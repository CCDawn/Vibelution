"""Validate content-addressed ArtifactManifest reuse against source lineage."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import ArtifactManifest


class ArtifactReuseError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


_MATCH_FIELDS = (
    "contentHash",
    "inputSnapshotHash",
    "configHash",
    "environmentSnapshotHash",
    "toolVersionHash",
)


def validate_artifact_reuse(
    manifests: list[ArtifactManifest],
    *,
    source_manifests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_by_id = {
        str(item.get("artifactId") or ""): item for item in source_manifests
    }
    reused: list[dict[str, Any]] = []
    for manifest in manifests:
        if manifest.cacheDisposition != "reused":
            continue
        sources = [source_by_id.get(item) for item in manifest.sourceArtifactIds]
        if not sources or any(source is None for source in sources):
            raise ArtifactReuseError(
                "reused ArtifactManifest references an unknown source artifact",
                code="artifact_reuse_source_missing",
            )
        source = sources[0] or {}
        mismatches = [
            field
            for field in _MATCH_FIELDS
            if str(source.get(field) or "") != str(getattr(manifest, field))
        ]
        if mismatches:
            raise ArtifactReuseError(
                "artifact reuse signature mismatch: " + ", ".join(mismatches),
                code="artifact_reuse_mismatch",
            )
        reused.append(
            {
                "artifactId": manifest.artifactId,
                "sourceArtifactIds": list(manifest.sourceArtifactIds),
            }
        )
    return reused
