"""Content-addressed workflow artifact lineage contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_sha256,
    require_text,
)

_CACHE_DISPOSITIONS = frozenset({"produced", "reused"})


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    artifactId: str
    contentHash: str
    schemaVersion: str
    producerNodeRunId: str
    producerAttempt: int
    inputSnapshotHash: str
    configHash: str
    environmentSnapshotHash: str
    toolVersionHash: str
    sourceArtifactIds: tuple[str, ...]
    cacheDisposition: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ArtifactManifest:
        cache_disposition = require_text(payload, "cacheDisposition")
        if cache_disposition not in _CACHE_DISPOSITIONS:
            raise ContractValidationError("cacheDisposition must be produced or reused")
        source_ids = tuple(
            str(item).strip()
            for item in require_list(payload, "sourceArtifactIds")
            if str(item).strip()
        )
        if cache_disposition == "reused" and not source_ids:
            raise ContractValidationError("reused artifacts require sourceArtifactIds")
        return cls(
            artifactId=require_text(payload, "artifactId"),
            contentHash=require_sha256(payload, "contentHash"),
            schemaVersion=require_text(payload, "schemaVersion"),
            producerNodeRunId=require_text(payload, "producerNodeRunId"),
            producerAttempt=require_int(payload, "producerAttempt", minimum=1),
            inputSnapshotHash=require_sha256(payload, "inputSnapshotHash"),
            configHash=require_sha256(payload, "configHash"),
            environmentSnapshotHash=require_sha256(payload, "environmentSnapshotHash"),
            toolVersionHash=require_sha256(payload, "toolVersionHash"),
            sourceArtifactIds=source_ids,
            cacheDisposition=cache_disposition,
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["sourceArtifactIds"] = list(self.sourceArtifactIds)
        return value
