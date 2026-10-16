"""Managed persona/task copy refresh for Challenge Cup Agents.

Covers the fourth materialized-storage copy of the 挑战杯 -> 科研 rename:
live Agent registries whose managed Agents still carry the v2 default
persona/task copy.  The refresh decouples two concerns: content migration
is exact-match only (operator-customized values stay untouched), while the
lineage stamps (``challengeCupTeamManagedVersion`` and the contract stamps)
sync unconditionally to the active contract constants so canonical
writeback never fails closed on a stale stamp.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from core.web.services import agent_directory_service
from core.web.services.agent_directory import repair_store
from core.web.services.team import team_constants

_SEEDED_UPDATED_AT = "2026-01-01T00:00:00Z"
_AGENT_CODE_COUNTER = itertools.count(1)


def _use_tmp_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)


def _legacy_profile_copy(role_key: str, functional_name: str) -> dict[str, dict[str, Any]]:
    history = repair_store._CHALLENGE_CUP_PROFILE_COPY_HISTORY[role_key]

    def _render(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("{functional_name}", functional_name)
        if isinstance(value, list):
            return [_render(item) for item in value]
        return value

    return {
        section: {key: _render(value) for key, value in fields.items()}
        for section, fields in history.items()
    }


def _managed_agent(
    *,
    agent_id: str,
    role_key: str,
    functional_name: str,
    managed_version: int,
    persona_profile: dict[str, Any] | None = None,
    task_profile: dict[str, Any] | None = None,
    responsibilities: list[str] | None = None,
    contract_stamps: bool = False,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "agentMode": "research",
        "fixedRole": True,
        "challengeCupTeamId": team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "challengeCupTeamManagedVersion": managed_version,
        "challengeCupTeamRole": role_key,
        "challengeCupTeamRoleKey": role_key,
        "researchAgentKey": role_key,
        "functionalDisplayName": functional_name,
        "displayNameSource": "responsibility",
        "managedDomain": "challenge_cup_neuro_algorithm",
    }
    if contract_stamps:
        metadata["challengeCupTeamContractVersion"] = (
            team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
        )
        metadata["challengeCupTeamRoleContractFingerprint"] = (
            team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
        )
        metadata["challengeCupTeamParticipantPolicyVersion"] = (
            team_constants.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION
        )
    if persona_profile is not None:
        metadata["personaProfile"] = copy.deepcopy(persona_profile)
    if task_profile is not None:
        metadata["taskProfile"] = copy.deepcopy(task_profile)
    if responsibilities is not None:
        metadata["responsibilities"] = list(responsibilities)
    return {
        "agentId": agent_id,
        "agentCode": f"AGT{next(_AGENT_CODE_COUNTER):03d}",
        "displayName": functional_name,
        "kind": agent_directory_service.DEFAULT_AGENT_KIND,
        "primaryMode": "research",
        "roleKey": role_key,
        "promptTemplateId": agent_directory_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS[role_key],
        "directSessionId": f"session-{agent_id}",
        "workspacePath": f"workspace/agents/{agent_id}",
        "toolPolicyId": f"tool-{agent_id}",
        "memoryPolicyId": f"memory-{agent_id}",
        "llmBindings": {"primary": {"modelId": "test-primary-model"}},
        "createdBy": "challenge_cup_team",
        "status": "active",
        "createdAt": _SEEDED_UPDATED_AT,
        "updatedAt": _SEEDED_UPDATED_AT,
        "metadata": metadata,
    }


def _seed_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agents: list[dict[str, Any]]) -> Path:
    _use_tmp_project_root(tmp_path, monkeypatch)
    path = agent_directory_service.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": agent_directory_service.AGENT_REGISTRY_VERSION,
                "updatedAt": _SEEDED_UPDATED_AT,
                "agents": copy.deepcopy(agents),
                "toolPolicies": {},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _stored_agent(registry_path: Path, agent_id: str) -> dict[str, Any]:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return next(item for item in payload["agents"] if item["agentId"] == agent_id)


def test_refresh_rewrites_old_managed_defaults_and_syncs_stamps(tmp_path, monkeypatch):
    coordinator_copy = _legacy_profile_copy("challenge_cup_coordinator", "科研协调")
    registry_path = _seed_registry(
        tmp_path,
        monkeypatch,
        [
            _managed_agent(
                agent_id="agent-coordinator",
                role_key="challenge_cup_coordinator",
                functional_name="科研协调",
                managed_version=2,
                persona_profile=coordinator_copy["personaProfile"],
                task_profile=coordinator_copy["taskProfile"],
            ),
            _managed_agent(
                agent_id="agent-search",
                role_key="challenge_cup_search",
                functional_name="搜索",
                managed_version=2,
                responsibilities=list(
                    repair_store._CHALLENGE_CUP_RESPONSIBILITIES_COPY_HISTORY["challenge_cup_search"]
                ),
            ),
        ],
    )

    agent_directory_service.repair_agent_directory()

    coordinator = _stored_agent(registry_path, "agent-coordinator")
    refreshed_persona = coordinator["metadata"]["personaProfile"]
    refreshed_task = coordinator["metadata"]["taskProfile"]
    assert refreshed_persona["background"] == "科研协调 是 AI 科研团队的协调 Agent，负责读状态和组织交接，不直接执行资料搜集。"
    assert refreshed_persona["personality"] == "清醒、克制，擅长把科研流程压缩成下一步行动。"
    assert refreshed_persona["expertise"] == ["科研流程", "阶段协调", "任务交接"]
    assert refreshed_task["mission"] == "协调科研知识搜集阶段，整理当前状态、角色交接和用户下一步。"
    assert "挑战杯" not in json.dumps(refreshed_persona, ensure_ascii=False)
    assert "挑战杯" not in json.dumps(refreshed_task, ensure_ascii=False)

    search = _stored_agent(registry_path, "agent-search")
    assert search["metadata"]["responsibilities"] == [
        "服务问题理解阶段：把知识缺口转为检索问题",
        "登记有效与无效来源",
        "保持来源可追溯",
    ]
    # The six product roles have no branded profile copy: persona stays absent.
    assert "personaProfile" not in search["metadata"]

    for agent in (coordinator, search):
        stamps = agent["metadata"]
        assert stamps["challengeCupTeamManagedVersion"] == (
            team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
        )
        assert stamps["challengeCupTeamContractVersion"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
        assert stamps["challengeCupTeamRoleContractFingerprint"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
        assert stamps["challengeCupTeamParticipantPolicyVersion"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION

    # Idempotency: a second repair must not rewrite anything.
    before = registry_path.read_bytes()
    agent_directory_service.repair_agent_directory()
    assert registry_path.read_bytes() == before


def test_refresh_leaves_operator_customized_values_untouched(tmp_path, monkeypatch):
    customized = _legacy_profile_copy("challenge_cup_coordinator", "科研协调")
    customized["personaProfile"]["personality"] += "（运营自定）"
    agent = _managed_agent(
        agent_id="agent-coordinator",
        role_key="challenge_cup_coordinator",
        functional_name="科研协调",
        managed_version=2,
        persona_profile=customized["personaProfile"],
        task_profile=customized["taskProfile"],
    )

    direct = repair_store._refresh_managed_challenge_cup_profile_copy(copy.deepcopy(agent))
    # Content is skipped, but the lineage stamps still sync: canonical writeback
    # fails closed on a stale managed version, so customized content must never
    # leave the Agent stuck at v2.
    assert direct["changed"] is True
    assert direct["skippedCustom"] is True
    assert direct["stampsSynced"] is True
    assert direct["contentMigrated"] is False

    registry_path = _seed_registry(tmp_path, monkeypatch, [agent])
    agent_directory_service.repair_agent_directory()

    stored = _stored_agent(registry_path, "agent-coordinator")
    assert stored["metadata"]["personaProfile"] == customized["personaProfile"]
    assert stored["metadata"]["taskProfile"] == customized["taskProfile"]
    stamps = stored["metadata"]
    assert stamps["challengeCupTeamManagedVersion"] == (
        team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
    )
    assert stamps["challengeCupTeamContractVersion"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
    assert stamps["challengeCupTeamRoleContractFingerprint"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
    assert stamps["challengeCupTeamParticipantPolicyVersion"] == team_constants.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION
    # The stamp sync is itself a record change.
    assert stored["updatedAt"] != _SEEDED_UPDATED_AT

    # Idempotency: with content skipped and stamps current, nothing rewrites.
    before = registry_path.read_bytes()
    agent_directory_service.repair_agent_directory()
    assert registry_path.read_bytes() == before


def test_refresh_raises_stamp_on_arbitrary_custom_persona(tmp_path, monkeypatch):
    arbitrary = {"personality": "完全自定义人格", "background": "运营手写的背景。"}
    agent = _managed_agent(
        agent_id="agent-coordinator",
        role_key="challenge_cup_coordinator",
        functional_name="科研协调",
        managed_version=2,
        persona_profile=arbitrary,
    )

    direct = repair_store._refresh_managed_challenge_cup_profile_copy(copy.deepcopy(agent))
    assert direct["changed"] is True
    assert direct["stampsSynced"] is True
    assert direct["contentMigrated"] is False
    assert direct["skippedCustom"] is True

    registry_path = _seed_registry(tmp_path, monkeypatch, [agent])
    agent_directory_service.repair_agent_directory()

    stored = _stored_agent(registry_path, "agent-coordinator")
    assert stored["metadata"]["personaProfile"] == arbitrary
    assert stored["metadata"]["challengeCupTeamManagedVersion"] == (
        team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
    )


def test_refresh_is_noop_when_already_at_current_contract(tmp_path, monkeypatch):
    current = agent_directory_service._challenge_cup_agent_profile_defaults(
        "challenge_cup_coordinator", "科研协调"
    )
    agent = _managed_agent(
        agent_id="agent-coordinator",
        role_key="challenge_cup_coordinator",
        functional_name="科研协调",
        managed_version=repair_store._challenge_cup_profile_managed_version(),
        persona_profile=current["personaProfile"],
        task_profile=current["taskProfile"],
        contract_stamps=True,
    )

    direct = repair_store._refresh_managed_challenge_cup_profile_copy(copy.deepcopy(agent))
    # skippedCustom only describes content: the current copy no longer matches
    # the v2 migration baseline either, so it can be True on a full no-op.
    assert direct["changed"] is False
    assert direct["stampsSynced"] is False
    assert direct["contentMigrated"] is False

    registry_path = _seed_registry(tmp_path, monkeypatch, [agent])
    agent_directory_service.repair_agent_directory()

    stored = _stored_agent(registry_path, "agent-coordinator")
    # Untouched means byte-identical to the seeded copy: no normalization,
    # no rewrite, no re-stamp.
    assert stored["metadata"]["personaProfile"] == current["personaProfile"]
    assert stored["metadata"]["taskProfile"] == current["taskProfile"]
    assert stored["metadata"]["challengeCupTeamManagedVersion"] == repair_store._challenge_cup_profile_managed_version()
    assert stored["updatedAt"] == _SEEDED_UPDATED_AT
