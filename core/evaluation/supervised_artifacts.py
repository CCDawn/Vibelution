# -*- coding: utf-8 -*-
"""Shared supervised artifact readers.

These helpers keep dashboard, workbench, and Web surfaces on the same
decision/proposal artifact interpretation without changing ownership of the
underlying records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SupervisedPolicyProposalArtifact:
    path: str
    payload: dict[str, Any]


def resolve_project_artifact_path(raw_path: Any, *, project_root: Path) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None
    return resolved


def policy_target_key(payload: dict[str, Any]) -> str | None:
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    if not target:
        return None
    try:
        return "target:" + json.dumps(target, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(target)


def load_policy_proposal_artifact(
    decision_payload: dict[str, Any],
    *,
    project_root: Path,
) -> SupervisedPolicyProposalArtifact | None:
    policy_action = (
        decision_payload.get("policy_action")
        if isinstance(decision_payload.get("policy_action"), dict)
        else {}
    )
    raw_paths = policy_action.get("proposal_paths") if isinstance(policy_action.get("proposal_paths"), list) else []
    for raw_path in raw_paths:
        proposal_path = resolve_project_artifact_path(raw_path, project_root=project_root)
        if proposal_path is None or not proposal_path.exists():
            continue
        try:
            proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(proposal_payload, dict):
            return SupervisedPolicyProposalArtifact(
                path=str(proposal_path),
                payload=proposal_payload,
            )
    return None


__all__ = [
    "SupervisedPolicyProposalArtifact",
    "load_policy_proposal_artifact",
    "policy_target_key",
    "resolve_project_artifact_path",
]
