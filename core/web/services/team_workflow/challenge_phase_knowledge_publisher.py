"""Publish an approved Challenge Cup phase-one package to Team Knowledge."""

from __future__ import annotations

import json
from typing import Any

from core.web.services import team_knowledge_service, team_service
from core.web.services.team_workflow.challenge_phase_boundary import (
    ChallengePhaseBoundaryError,
    approve_current_phase_one_manifest,
    get_challenge_phase_boundary_status,
    record_phase_one_knowledge_applied_receipt,
)

KNOWLEDGE_BASE_NAME = "Knowledge Expansion Library"
PHASE_ONE_KNOWLEDGE_TAG = "challenge-phase-one-manifest"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _agent_id(member: dict[str, Any]) -> str:
    return _text(member.get("agentId"))


def _role(member: dict[str, Any]) -> str:
    return _text(member.get("roleKey") or member.get("role"))


def _publication_agents(team: dict[str, Any]) -> tuple[str, str]:
    members = [item for item in team.get("members") or [] if isinstance(item, dict)]
    reviewer_id = next(
        (
            _agent_id(item)
            for item in members
            if _role(item) == "challenge_cup_knowledge_manager" and _agent_id(item)
        ),
        "",
    )
    proposer_id = next(
        (
            _agent_id(item)
            for item in members
            if _agent_id(item) and _agent_id(item) != reviewer_id
        ),
        "",
    )
    if not reviewer_id:
        raise ChallengePhaseBoundaryError("challenge_cup_knowledge_manager_missing")
    if not proposer_id:
        raise ChallengePhaseBoundaryError("phase_one_knowledge_proposer_missing")
    return proposer_id, reviewer_id


def _manifest_tag(manifest: dict[str, Any]) -> str:
    return f"{PHASE_ONE_KNOWLEDGE_TAG}:{_text(manifest.get('manifestSha256'))}"


def _knowledge_content(manifest: dict[str, Any]) -> str:
    refs = [item for item in manifest.get("resultRefs") or [] if isinstance(item, dict)]
    lines = [
        "挑战杯第一阶段 125 题结果整包索引。",
        f"manifestSha256: {_text(manifest.get('manifestSha256'))}",
        f"contentSha256: {_text(manifest.get('contentSha256'))}",
        f"questionCount: {int(manifest.get('questionCount') or 0)}",
    ]
    for offset in range(0, len(refs), 4):
        group = refs[offset : offset + 4]
        lines.append(
            " | ".join(
                f"{_text(item.get('questionId'))}:{_text(item.get('runId'))}:{_text(item.get('outputSha256'))}"
                for item in group
            )
        )
    return "\n".join(lines)


def _existing_applied_item(
    knowledge_service: Any,
    knowledge_base_id: str,
    reviewer_id: str,
    manifest_tag: str,
) -> dict[str, Any] | None:
    payload = knowledge_service.list_knowledge_items(
        knowledge_base_id,
        agent_id=reviewer_id,
    )
    for item in payload.get("items") or []:
        if isinstance(item, dict) and manifest_tag in list(item.get("tags") or []):
            return item
    return None


def _publish_approved_phase_one_to_team_knowledge(
    team_id: str,
    *,
    question_run_summary: dict[str, Any] | None = None,
    knowledge_service: Any = team_knowledge_service,
    team_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotently publish the currently approved immutable package."""

    boundary = get_challenge_phase_boundary_status(
        team_id,
        question_run_summary=question_run_summary,
    )
    if boundary.get("phase1Approved") is not True:
        raise ChallengePhaseBoundaryError("phase_one_approval_required")
    manifest = boundary["manifest"]
    team = team_snapshot if isinstance(team_snapshot, dict) else team_service.get_team(team_id)
    proposer_id, reviewer_id = _publication_agents(team)
    resolved = knowledge_service.get_or_create_team_knowledge_base(
        team_id,
        name=KNOWLEDGE_BASE_NAME,
        description="挑战杯团队正式知识库",
        actor_agent_id=proposer_id,
    )
    knowledge_base = resolved.get("knowledgeBase") or {}
    knowledge_base_id = _text(knowledge_base.get("knowledgeBaseId"))
    if not knowledge_base_id:
        raise ChallengePhaseBoundaryError("phase_one_knowledge_base_missing")
    knowledge_service.ensure_knowledge_base_review_grant(knowledge_base_id, reviewer_id)
    knowledge_service.ensure_owner_source_review_grant("team", team_id, reviewer_id)
    manifest_tag = _manifest_tag(manifest)
    existing = _existing_applied_item(
        knowledge_service,
        knowledge_base_id,
        reviewer_id,
        manifest_tag,
    )
    if existing is None:
        source = knowledge_service.collect_source_to_inbox(
            "team",
            team_id,
            source_type="agent_authored",
            source_ref={
                "agentId": proposer_id,
                "manifestSha256": manifest["manifestSha256"],
                "contentSha256": manifest["contentSha256"],
            },
            original_content=json.dumps(manifest, ensure_ascii=False, indent=2),
            original_filename=f"challenge-phase-one-{manifest['manifestSha256']}.json",
            captured_by=proposer_id,
            source_hash=manifest["manifestSha256"],
            title="挑战杯第一阶段 125 题结果整包",
            summary="经真实操作者整包批准的第一阶段结果索引与不可变内容哈希。",
            actor_agent_id=proposer_id,
        )
        reviewed = knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=reviewer_id,
            resolution_note="Apply the operator-approved phase-one package without a second human gate.",
            ingest_on_accept=True,
            knowledge_base_id=knowledge_base_id,
            knowledge_title="挑战杯第一阶段 125 题结果包",
            knowledge_summary="125 题内容已整包批准；本条目绑定精确 manifest 与内容哈希。",
            knowledge_content=_knowledge_content(manifest),
            tags=["challenge-cup", "phase-one", manifest_tag],
        )
        direct = reviewed.get("directIngestion") or {}
        batch = direct.get("batch") or {}
        existing = direct.get("item") or {}
        if _text(batch.get("status")) != "applied" or not _text(existing.get("knowledgeItemId")):
            raise ChallengePhaseBoundaryError("phase_one_knowledge_application_failed")
    batch_id = _text(existing.get("batchId"))
    item_id = _text(existing.get("knowledgeItemId"))
    if not batch_id or not item_id:
        raise ChallengePhaseBoundaryError("phase_one_knowledge_applied_receipt_missing")
    receipt = {
        "receiptId": f"team-knowledge:{batch_id}:{item_id}",
        "status": "applied",
        "manifestSha256": manifest["manifestSha256"],
        "contentSha256": manifest["contentSha256"],
        "knowledgeBaseId": knowledge_base_id,
        "knowledgeItemIds": [item_id],
        "batchId": batch_id,
        "appliedAt": _text(existing.get("appliedAt") or existing.get("updatedAt")),
    }
    return record_phase_one_knowledge_applied_receipt(
        team_id,
        receipt,
        question_run_summary=question_run_summary,
    )


def publish_approved_phase_one_to_team_knowledge(
    team_id: str,
    *,
    question_run_summary: dict[str, Any] | None = None,
    knowledge_service: Any = team_knowledge_service,
    team_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _publish_approved_phase_one_to_team_knowledge(
            team_id,
            question_run_summary=question_run_summary,
            knowledge_service=knowledge_service,
            team_snapshot=team_snapshot,
        )
    except (team_knowledge_service.TeamKnowledgeError, OSError) as exc:
        raise ChallengePhaseBoundaryError(
            f"phase_one_knowledge_publish_failed: {exc}"
        ) from exc


def approve_and_publish_current_phase_one_manifest(
    team_id: str,
    *,
    operator_id: str,
    operator_display_name: str = "",
    note: str = "",
) -> dict[str, Any]:
    approve_current_phase_one_manifest(
        team_id,
        operator_id=operator_id,
        operator_display_name=operator_display_name,
        note=note,
    )
    return publish_approved_phase_one_to_team_knowledge(
        team_id,
        question_run_summary=None,
    )
