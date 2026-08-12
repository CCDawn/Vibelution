"""Canonical Artifact kind → Domain Store read-back registry (T5.1-2).

Materialized artifacts live under each authority's content-addressed root.
Ledger receipts only store refs; this module is the sole read-back path for
production RealDomainPorts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core.web.services.team_workflow.research_runtime.domain_ports import ArtifactReadBack
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)

Authority = Literal[
    "source_collection",
    "evidence",
    "knowledge",
    "experiment",
    "promotion",
    "result_package",
    "workflow_system",
]


@dataclass(frozen=True)
class ArtifactAuthoritySpec:
    kind: str
    authority: Authority


ARTIFACT_AUTHORITY: dict[str, ArtifactAuthoritySpec] = {
    "source_candidate_batch": ArtifactAuthoritySpec("source_candidate_batch", "source_collection"),
    "evidence_card_batch": ArtifactAuthoritySpec("evidence_card_batch", "source_collection"),
    "evidence_relation_graph": ArtifactAuthoritySpec("evidence_relation_graph", "evidence"),
    "knowledge_package_draft": ArtifactAuthoritySpec("knowledge_package_draft", "knowledge"),
    "knowledge_package": ArtifactAuthoritySpec("knowledge_package", "knowledge"),
    "hypothesis_set": ArtifactAuthoritySpec("hypothesis_set", "experiment"),
    "protocol_draft": ArtifactAuthoritySpec("protocol_draft", "experiment"),
    "protocol_review_report": ArtifactAuthoritySpec("protocol_review_report", "experiment"),
    "frozen_protocol": ArtifactAuthoritySpec("frozen_protocol", "experiment"),
    "smoke_evidence": ArtifactAuthoritySpec("smoke_evidence", "experiment"),
    "smoke_release": ArtifactAuthoritySpec("smoke_release", "experiment"),
    "run_artifacts": ArtifactAuthoritySpec("run_artifacts", "experiment"),
    "evaluation_report": ArtifactAuthoritySpec("evaluation_report", "experiment"),
    "iteration_decision": ArtifactAuthoritySpec("iteration_decision", "experiment"),
    "version_governance_record": ArtifactAuthoritySpec(
        "version_governance_record", "experiment"
    ),
    "promotion_proposal": ArtifactAuthoritySpec("promotion_proposal", "promotion"),
    "research_result_package": ArtifactAuthoritySpec(
        "research_result_package", "result_package"
    ),
}


def resolve_artifact_authority(kind: str) -> ArtifactAuthoritySpec | None:
    return ARTIFACT_AUTHORITY.get(str(kind or "").strip())


def required_artifact_kinds(node_id: str) -> tuple[str, ...]:
    from core.research.workflow.definition import build_challenge_cup_workflow_definition

    node = next(
        (
            item
            for item in build_challenge_cup_workflow_definition().nodes
            if item.nodeId == node_id
        ),
        None,
    )
    if node is None:
        return ()
    return tuple(node.producesArtifactKinds)


def default_artifact_root() -> Path:
    from core.infrastructure.path_containment import PROJECT_ROOT

    return Path(PROJECT_ROOT) / "data" / "domain_artifacts"


def _authority_root(root: Path, authority: Authority) -> Path:
    return root / authority


def build_canonical_ref(
    *,
    kind: str,
    team_id: str,
    authority_run_id: str,
    content_hash: str,
) -> str:
    return (
        f"{kind}://{team_id}/{authority_run_id}/{content_hash}"
    )


def parse_canonical_ref(canonical_ref: str) -> dict[str, str] | None:
    text = str(canonical_ref or "").strip()
    if "://" not in text:
        # Legacy short form kind:prefix — not addressable without store lookup.
        if ":" in text:
            kind, identity = text.split(":", 1)
            if resolve_artifact_authority(kind) is None:
                return None
            return {"kind": kind, "identity": identity, "legacy": "1"}
        return None
    kind, rest = text.split("://", 1)
    if resolve_artifact_authority(kind) is None:
        return None
    parts = [p for p in rest.split("/") if p]
    if len(parts) < 3:
        return None
    team_id, authority_run_id, content_hash = parts[0], parts[1], parts[2]
    if len(content_hash) < 16:
        return None
    return {
        "kind": kind,
        "teamId": team_id,
        "authorityRunId": authority_run_id,
        "contentHash": content_hash,
    }


def _payload_path(
    root: Path,
    *,
    authority: Authority,
    team_id: str,
    authority_run_id: str,
    kind: str,
    content_hash: str,
) -> Path:
    # Keep paths short for Windows MAX_PATH; identity remains in the envelope
    # and canonical ref (kind://team/run/hash).
    _ = (team_id, authority_run_id, kind)
    return _authority_root(root, authority) / content_hash[:2] / f"{content_hash}.json"


def materialize_domain_artifact(
    *,
    kind: str,
    payload: dict[str, Any],
    team_id: str,
    authority_run_id: str,
    root: Path | None = None,
    schema_version: str = "1.0.0",
) -> dict[str, str]:
    """Write payload into the kind's domain authority and return a verified ref."""
    spec = resolve_artifact_authority(kind)
    if spec is None:
        raise RuntimeError(f"unknown artifact kind: {kind}")
    if not team_id or not authority_run_id:
        raise RuntimeError("team_id and authority_run_id are required to materialize")
    content_hash = canonical_sha256(payload)
    base = root or default_artifact_root()
    path = _payload_path(
        base,
        authority=spec.authority,
        team_id=team_id,
        authority_run_id=authority_run_id,
        kind=kind,
        content_hash=content_hash,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    domain_revision = canonical_sha256(
        {
            "kind": kind,
            "teamId": team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": schema_version,
        }
    )[:32]
    envelope = {
        "kind": kind,
        "teamId": team_id,
        "authorityRunId": authority_run_id,
        "schemaVersion": schema_version,
        "contentHash": content_hash,
        "domainRevision": domain_revision,
        "authority": spec.authority,
        "payload": payload,
    }
    path.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    canonical_ref = build_canonical_ref(
        kind=kind,
        team_id=team_id,
        authority_run_id=authority_run_id,
        content_hash=content_hash,
    )
    return {
        "canonicalRef": canonical_ref,
        "kind": kind,
        "sha256": content_hash,
        "version": schema_version,
        "domainRevision": domain_revision,
    }


def read_domain_artifact(
    canonical_ref: str,
    *,
    root: Path | None = None,
) -> ArtifactReadBack | None:
    """Read-back from the unique domain authority for the artifact kind."""
    parsed = parse_canonical_ref(canonical_ref)
    if parsed is None:
        return None
    if parsed.get("legacy") == "1":
        # Short refs are not authoritative without a full locator.
        return None
    kind = parsed["kind"]
    spec = resolve_artifact_authority(kind)
    if spec is None:
        return None
    content_hash = parsed["contentHash"]
    path = _payload_path(
        root or default_artifact_root(),
        authority=spec.authority,
        team_id=parsed["teamId"],
        authority_run_id=parsed["authorityRunId"],
        kind=kind,
        content_hash=content_hash,
    )
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    stored_hash = str(envelope.get("contentHash") or "")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    recomputed = canonical_sha256(payload)
    if stored_hash != content_hash or recomputed != content_hash:
        return None
    version = str(envelope.get("schemaVersion") or "").strip()
    domain_revision = str(envelope.get("domainRevision") or "").strip()
    if not version or not domain_revision or not stored_hash:
        return None
    return ArtifactReadBack(
        canonical_ref=build_canonical_ref(
            kind=kind,
            team_id=parsed["teamId"],
            authority_run_id=parsed["authorityRunId"],
            content_hash=content_hash,
        ),
        version=version,
        content_hash=stored_hash,
        domain_revision=domain_revision,
    )
