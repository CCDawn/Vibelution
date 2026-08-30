"""T5 contract tests for the six Challenge Cup role context policies.

Pins the versioned custom compression policy migration, the hard input-limit
budget formula (configurable protocol reserve), compression retention
validation (including paired preservation of unresolved tool calls), the
fail-closed ``context_budget_exhausted`` path, and snapshot/rollback safety
(rollback must never restore ``inherit``).
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.orchestration import turn_compression
from core.orchestration.agent_modes import AgentMode
from core.orchestration.turn_compression import compress_turn_messages
from core.web.services import agent_directory_service, team_service
from core.web.services.team import challenge_cup_context_policy as ccp

CONTEXT_WINDOW = 262_144
RESERVED_MAX_OUTPUT = 32_768
PROTOCOL_RESERVE = 8_192
HARD_LIMIT = 221_184
TRIGGER = 204_800
POST_TARGET = 147_456


def _use_tmp_project_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def _seed_role_agent(role_key: str, *, policy=None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    agent = agent_directory_service.create_agent_instance(
        display_name=f"Ctx {role_key}",
        llm_bindings={"dialogue": {"modelId": f"ctx-model-{role_key}"}},
        primary_mode="research",
        role_key=role_key,
        prompt_template_id="prompt-chat-default",
        direct_session_id=f"ctx-session-{role_key}",
        created_by=team_service.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
        metadata={
            "challengeCupTeamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
            "challengeCupTeamManagedVersion": 2,
            "challengeCupTeamRole": role_key,
            "challengeCupTeamRoleKey": role_key,
        },
    )
    if policy is not None:
        agent_directory_service.update_agent_instance(
            agent["agentId"],
            context_compression_policy=copy.deepcopy(policy),
        )
    return agent_directory_service.get_agent(agent["agentId"])


def _legacy_drift_policies() -> dict[str, dict | None]:
    """Mirror the observed operator-registry drift (plan §2.4)."""

    return {
        # inherit/legacy defaults observed in the operator registry; new
        # registry assets materialize the creation default instead, which is
        # equally drifted (full-window limit, no trigger/target contract).
        "challenge_cup_search": None,
        "challenge_cup_extractor": {"mode": "custom", "enabled": False, "maxTokenLimit": 262_144},
        "challenge_cup_knowledge_manager": None,
        "challenge_cup_evaluator": None,
        "challenge_cup_experiment_revision": {
            "mode": "custom",
            "enabled": False,
            "maxTokenLimit": 1_000_000,
        },
        "challenge_cup_execution_steward": {
            "mode": "custom",
            "enabled": True,
            "maxTokenLimit": 262_144,
        },
    }


def _seed_all_roles(monkeypatch, tmp_path) -> dict[str, dict]:
    agents: dict[str, dict] = {}
    for role_key, policy in _legacy_drift_policies().items():
        agents[role_key] = _seed_role_agent(
            role_key, policy=policy, monkeypatch=monkeypatch, tmp_path=tmp_path
        )
    return agents


# ---------------------------------------------------------------------------
# 1) Hard-limit budget formula (configurable reserve, versioned defaults)
# ---------------------------------------------------------------------------


def test_budget_formula_matches_frozen_first_round_values():
    budget = ccp.challenge_cup_context_budget(context_window=CONTEXT_WINDOW)
    assert budget["contextWindow"] == CONTEXT_WINDOW
    assert budget["reservedMaxOutputTokens"] == RESERVED_MAX_OUTPUT
    assert budget["protocolAndSafetyReserveTokens"] == PROTOCOL_RESERVE
    assert budget["effectiveInputHardLimit"] == HARD_LIMIT
    assert budget["compressionTriggerTokenLimit"] == TRIGGER
    assert budget["postCompressionTargetTokenLimit"] <= POST_TARGET
    assert budget["effectiveInputHardLimit"] == (
        budget["contextWindow"]
        - budget["reservedMaxOutputTokens"]
        - budget["protocolAndSafetyReserveTokens"]
    )


def test_budget_reserve_is_configurable():
    budget = ccp.challenge_cup_context_budget(
        context_window=CONTEXT_WINDOW,
        protocol_and_safety_reserve_tokens=16_384,
    )
    assert budget["protocolAndSafetyReserveTokens"] == 16_384
    assert budget["effectiveInputHardLimit"] == CONTEXT_WINDOW - RESERVED_MAX_OUTPUT - 16_384
    assert budget["compressionTriggerTokenLimit"] < budget["effectiveInputHardLimit"]
    assert budget["postCompressionTargetTokenLimit"] < budget["compressionTriggerTokenLimit"]


def test_budget_reads_configurable_reserve_from_operator_config(monkeypatch):
    from config import get_config

    cc = get_config().context_compression
    monkeypatch.setattr(cc, "protocol_and_safety_reserve_tokens", 12_288)
    budget = ccp.challenge_cup_context_budget(context_window=CONTEXT_WINDOW)
    assert budget["protocolAndSafetyReserveTokens"] == 12_288
    assert budget["effectiveInputHardLimit"] == CONTEXT_WINDOW - RESERVED_MAX_OUTPUT - 12_288


def test_budget_rejects_non_positive_window():
    with pytest.raises(ValueError):
        ccp.challenge_cup_context_budget(context_window=0)


# ---------------------------------------------------------------------------
# 2) Six role policies: explicit, versioned, enabled, no legacy residue
# ---------------------------------------------------------------------------


def test_all_six_roles_have_explicit_enabled_custom_policy():
    assert set(ccp.CHALLENGE_CUP_CONTEXT_POLICY_ROLES) == set(_legacy_drift_policies())
    for role_key in ccp.CHALLENGE_CUP_CONTEXT_POLICY_ROLES:
        policy = ccp.challenge_cup_role_context_policy(role_key)
        assert policy is not None, role_key
        assert policy["mode"] == "custom"
        assert policy["enabled"] is True
        assert int(policy.get("policyVersion") or 0) >= ccp.CHALLENGE_CUP_CONTEXT_POLICY_VERSION
        assert int(policy["maxTokenLimit"]) == HARD_LIMIT
        assert int(policy["compressionTriggerTokenLimit"]) == TRIGGER
        assert int(policy["postCompressionTargetTokenLimit"]) <= POST_TARGET


def test_role_policies_carry_shared_retention_and_role_focus():
    shared_markers = (
        "scope",
        "task_contract",
        "unresolved_tool_call",
        "evidence_locator",
        "writeback_contract",
        "compression_generation",
    )
    for role_key, focus_markers in ccp.CHALLENGE_CUP_ROLE_RETENTION_FOCUS.items():
        policy = ccp.challenge_cup_role_context_policy(role_key)
        assert policy is not None
        retention = [str(item) for item in policy["preservation"].get("retentionFocus") or []]
        for marker in shared_markers:
            assert marker in retention, (role_key, marker)
        for marker in focus_markers:
            assert marker in retention, (role_key, marker)


def test_legacy_one_million_and_full_window_thresholds_are_gone():
    for role_key in ccp.CHALLENGE_CUP_CONTEXT_POLICY_ROLES:
        policy = ccp.challenge_cup_role_context_policy(role_key)
        assert policy is not None
        assert int(policy["maxTokenLimit"]) != 1_000_000
        assert int(policy["maxTokenLimit"]) != CONTEXT_WINDOW
        assert int(policy["compressionTriggerTokenLimit"]) != CONTEXT_WINDOW
        assert int(policy["maxTokenLimit"]) < CONTEXT_WINDOW


def test_inherit_still_reports_migration_required_until_migrated():
    """Unmigrated agents keep the diagnostic; migrated roles must never hit it."""

    effective = agent_directory_service.effective_agent_context_compression_policy(
        {"contextCompressionPolicy": {"mode": "inherit"}},
        None,
        context_window_limit=CONTEXT_WINDOW,
    )
    assert effective["source"] == "migration_required"
    assert effective.get("enabled") is False


def test_apply_migrates_all_roles_and_resolution_never_reports_migration_required(
    monkeypatch, tmp_path
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agents = _seed_all_roles(monkeypatch, tmp_path)
    before_snapshot = ccp.export_challenge_cup_context_policy_snapshot()
    assert {entry["role"] for entry in before_snapshot["agents"]} == set(agents)
    # The pre-migration snapshot keeps prior policies verbatim for rollback.
    extractor_entry = next(
        entry
        for entry in before_snapshot["agents"]
        if entry["role"] == "challenge_cup_extractor"
    )
    assert extractor_entry["policy"]["enabled"] is False

    result = ccp.apply_challenge_cup_context_policies()
    assert result["migratedCount"] == len(agents)
    assert set(result["migratedRoles"]) == set(agents)
    assert result["snapshotExported"] is True
    for role_key, agent in agents.items():
        stored = agent_directory_service.get_agent(agent["agentId"])
        stored_policy = stored.get("contextCompressionPolicy")
        assert isinstance(stored_policy, dict)
        assert stored_policy.get("mode") == "custom", role_key
        assert stored_policy.get("enabled") is True
        assert int(stored_policy.get("compressionTriggerTokenLimit") or 0) == TRIGGER
        assert int(stored_policy.get("maxTokenLimit") or 0) == HARD_LIMIT
        effective = agent_directory_service.effective_agent_context_compression_policy(
            stored,
            None,
            context_window_limit=CONTEXT_WINDOW,
        )
        assert effective["mode"] == "custom"
        assert effective["source"] != "migration_required"
        assert effective.get("enabled") is True
        assert int(effective.get("compressionTriggerTokenLimit") or 0) == TRIGGER
        assert int(effective.get("effectiveTokenLimit") or 0) == HARD_LIMIT

    # Version-gated idempotence: the second apply is a read-only no-op that
    # classifies every role as already current and writes nothing.
    second = ccp.apply_challenge_cup_context_policies()
    assert second["migratedCount"] == 0
    assert set(second["skippedCurrentRoles"]) == set(agents)
    assert second["skippedCustomRoles"] == []
    assert second.get("snapshotExported") is False


def test_non_challenge_role_policy_contract_does_not_cover_other_roles():
    assert ccp.challenge_cup_role_context_policy("source_finder") is None
    assert ccp.challenge_cup_role_context_policy("") is None


def test_version_gate_migrates_v1_v2_and_unversioned_policies(monkeypatch, tmp_path):
    """Policies without a version or below v3 are migrated exactly once."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    versioned = {
        "challenge_cup_search": {"mode": "custom", "enabled": True, "policyVersion": 1, "maxTokenLimit": 262_144},
        "challenge_cup_extractor": {"mode": "custom", "enabled": False, "policyVersion": 2, "maxTokenLimit": 1_000_000},
        "challenge_cup_knowledge_manager": {"mode": "custom", "enabled": True, "maxTokenLimit": 262_144},
    }
    seeded = {
        role_key: _seed_role_agent(role_key, policy=policy, monkeypatch=monkeypatch, tmp_path=tmp_path)
        for role_key, policy in versioned.items()
    }
    assert ccp.challenge_cup_context_policies_outdated() is True

    result = ccp.apply_challenge_cup_context_policies()
    assert result["migratedCount"] == 3
    assert set(result["migratedRoles"]) == set(seeded)
    # The snapshot was exported before the first write and keeps priors verbatim.
    search_entry = next(
        entry
        for entry in result["snapshot"]["agents"]
        if entry["role"] == "challenge_cup_search"
    )
    assert search_entry["policy"]["policyVersion"] == 1

    for agent in seeded.values():
        stored = agent_directory_service.get_agent(agent["agentId"])
        policy = stored.get("contextCompressionPolicy")
        assert int(policy.get("policyVersion") or 0) == ccp.CHALLENGE_CUP_CONTEXT_POLICY_VERSION
        assert int(policy["compressionTriggerTokenLimit"] or 0) == TRIGGER
        assert int(policy["maxTokenLimit"] or 0) == HARD_LIMIT
    assert ccp.challenge_cup_context_policies_outdated() is False


def test_operator_customized_v3_policy_is_never_overwritten(monkeypatch, tmp_path):
    """A current-version policy that drifts from canonical is operator intent."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    canonical = ccp.challenge_cup_role_context_policy("challenge_cup_search")
    assert canonical is not None
    customized = dict(canonical)
    customized["maxCompressionsPerSession"] = 25
    agent = _seed_role_agent(
        "challenge_cup_search", policy=customized, monkeypatch=monkeypatch, tmp_path=tmp_path
    )

    updates: list[str] = []
    original_update = agent_directory_service.update_agent_instance

    def _tracking_update(agent_id, *args, **kwargs):
        updates.append(str(agent_id))
        return original_update(agent_id, *args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "update_agent_instance", _tracking_update)
    result = ccp.apply_challenge_cup_context_policies()
    assert result["migratedCount"] == 0
    assert result["skippedCustomRoles"] == ["challenge_cup_search"]
    assert result["skippedCurrentRoles"] == []
    assert updates == [], "operator customization must not be rewritten"
    assert result.get("snapshotExported") is False

    stored = agent_directory_service.get_agent(agent["agentId"])
    assert int(stored["contextCompressionPolicy"]["maxCompressionsPerSession"]) == 25
    assert ccp.challenge_cup_context_policies_outdated() is False


def test_rollback_survives_next_version_gated_apply(monkeypatch, tmp_path):
    """§10.2: a rolled-back explicit custom policy must not be re-migrated."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _seed_role_agent(
        "challenge_cup_extractor",
        policy={"mode": "custom", "enabled": False, "maxTokenLimit": 262_144},
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    snapshot = ccp.export_challenge_cup_context_policy_snapshot()
    ccp.apply_challenge_cup_context_policies()

    rollback = ccp.rollback_challenge_cup_context_policies(snapshot)
    assert rollback["restoredCount"] == 1
    restored = agent_directory_service.get_agent(agent["agentId"])
    restored_policy = restored["contextCompressionPolicy"]
    assert restored_policy["enabled"] is False
    assert int(restored_policy.get("policyVersion") or 0) == ccp.CHALLENGE_CUP_CONTEXT_POLICY_VERSION

    result = ccp.apply_challenge_cup_context_policies()
    assert result["migratedCount"] == 0
    assert result["skippedCustomRoles"] == ["challenge_cup_extractor"]
    after = agent_directory_service.get_agent(agent["agentId"])
    assert after["contextCompressionPolicy"]["enabled"] is False


# ---------------------------------------------------------------------------
# 3) Snapshot / rollback safety: rollback never restores inherit
# ---------------------------------------------------------------------------


def test_rollback_restores_previous_custom_policy_and_never_inherit(monkeypatch, tmp_path):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agents = _seed_all_roles(monkeypatch, tmp_path)
    before_snapshot = ccp.export_challenge_cup_context_policy_snapshot()
    # Simulate a genuinely inherit-shaped prior policy (legacy registry data):
    next(
        entry
        for entry in before_snapshot["agents"]
        if entry["role"] == "challenge_cup_knowledge_manager"
    )["policy"] = {"mode": "inherit"}

    ccp.apply_challenge_cup_context_policies()
    drifted = agent_directory_service.get_agent(agents["challenge_cup_search"]["agentId"])
    assert drifted["contextCompressionPolicy"]["mode"] == "custom"

    result = ccp.rollback_challenge_cup_context_policies(before_snapshot)
    assert result["restoredCount"] == len(agents)
    for role_key, agent in agents.items():
        stored = agent_directory_service.get_agent(agent["agentId"])
        policy = stored.get("contextCompressionPolicy")
        assert isinstance(policy, dict), role_key
        assert policy.get("mode") == "custom", role_key
    # Explicit prior custom policies come back verbatim (disabled stays
    # disabled); the inherit-shaped prior must fall back to the canonical
    # versioned custom policy instead of reviving inherit.
    extractor = agent_directory_service.get_agent(agents["challenge_cup_extractor"]["agentId"])
    assert extractor["contextCompressionPolicy"]["enabled"] is False
    knowledge = agent_directory_service.get_agent(
        agents["challenge_cup_knowledge_manager"]["agentId"]
    )
    knowledge_policy = knowledge["contextCompressionPolicy"]
    assert knowledge_policy.get("enabled") is True
    assert int(knowledge_policy.get("compressionTriggerTokenLimit") or 0) == TRIGGER
    assert int(knowledge_policy.get("policyVersion") or 0) >= ccp.CHALLENGE_CUP_CONTEXT_POLICY_VERSION


def test_rollback_ignores_foreign_snapshot_agents(monkeypatch, tmp_path):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agents = _seed_all_roles(monkeypatch, tmp_path)
    ccp.apply_challenge_cup_context_policies()
    snapshot = {
        "schemaVersion": 1,
        "agents": [
            {"agentId": "agent-does-not-exist", "role": "challenge_cup_search", "policy": None},
        ],
    }
    result = ccp.rollback_challenge_cup_context_policies(snapshot)
    assert result["restoredCount"] == 0
    stored = agent_directory_service.get_agent(agents["challenge_cup_search"]["agentId"])
    assert stored["contextCompressionPolicy"]["mode"] == "custom"


# ---------------------------------------------------------------------------
# 4) Compression retention validation + context_budget_exhausted fail-closed
# ---------------------------------------------------------------------------


class _FakeUi:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.events: list[dict] = []

    def add_log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((level, message))

    def note_context_compression_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class _FakePromptManager:
    def __init__(self) -> None:
        self.updates: list[str] = []

    def update_state_memory(self, text: str) -> None:
        self.updates.append(text)


class _TailKeepingCompressor:
    """Compress that keeps the last three messages (unresolved tail survives)."""

    def compress(self, messages, **kwargs):
        from tools.token_manager import CompressionResult

        kept = list(messages[-3:])
        return kept, CompressionResult("压缩摘要", 10_000, 100, 1, "standard")


class _ChainBreakingCompressor:
    """Compress that introduces a fresh unresolved tool call."""

    def compress(self, messages, **kwargs):
        from tools.token_manager import CompressionResult

        kept = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "web_search_tool", "args": {}, "id": "call-9"},
                ],
            ),
        ]
        return kept, CompressionResult("broken summary", 10_000, 10, 1, "standard")


class _NonShrinkingCompressor:
    def compress(self, messages, **kwargs):
        from tools.token_manager import CompressionResult

        return list(messages), CompressionResult("", 10_000, 10_000, 0, "standard")


class _RecordingSummaryCompressor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def compress(self, messages, **kwargs):
        from tools.token_manager import CompressionResult

        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        kept = list(messages[:2])
        return kept, CompressionResult("compressed", 10_000, 10, 1, "standard")


class _FakeStrategy:
    def __init__(self, level=None) -> None:
        self.level = level

    def determine_level_with_iteration(self, *args):
        from tools.compression_strategy import CompressionLevel

        return self.level or CompressionLevel.STANDARD

    def get_config(self, level, current_tokens, budget):
        from tools.compression_strategy import CompressionConfig

        return CompressionConfig(level=level, summary_max_chars=80, keep_ai_messages=2)


def _feature_config(*, enabled: bool = True):
    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=False),
        context_compression=SimpleNamespace(
            enabled=enabled,
            max_compressions_per_session=3,
            effectiveness_threshold=0.0,
        ),
        pet=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(
            semantic_memory_enabled=False,
            llm_extraction_enabled=False,
            llm_summary_enabled=False,
        ),
        supervised_evolution=SimpleNamespace(enabled=False, mental_model_enabled=False),
        agent=SimpleNamespace(
            modes=SimpleNamespace(
                supervised_evolution_enabled=False,
                self_evolution_enabled=False,
            )
        ),
    )


def _estimate(messages) -> int:
    return sum(len(str(getattr(item, "content", "") or "")) for item in messages)


def _run_compress(
    *,
    messages,
    compressor,
    context_input_hard_limit: int = 0,
    post_compression_target_tokens: int = 0,
    retention_contract: dict | None = None,
    prompt_manager=None,
):
    events: list[dict] = []
    ui = _FakeUi()

    def recorder(scene, action, *, message="", outcome="observed", fields=None, **kwargs):
        events.append({"scene": scene, "action": action, "outcome": outcome, "fields": fields or {}})

    result = compress_turn_messages(
        messages=messages,
        iteration=4,
        reason="test",
        token_compressor=compressor,
        config=_feature_config(),
        effective_max_token_limit=HARD_LIMIT,
        threshold_tokens=TRIGGER,
        runtime_agent_binding={"agentId": "a1", "directSessionId": "s1"},
        project_root="",
        mode=AgentMode.CHAT,
        compression_strategy=_FakeStrategy(),
        prompt_manager=prompt_manager,
        estimate_tokens_fn=_estimate,
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: SimpleNamespace(set_state=lambda *a, **k: None),
        scene_recorder_fn=recorder,
        context_input_hard_limit=context_input_hard_limit,
        post_compression_target_tokens=post_compression_target_tokens,
        retention_contract=retention_contract,
    )
    return result, events, ui


def _unresolved_pair_messages() -> list:
    """History with resolved pairs plus one still-unresolved trailing call."""
    return [
        SystemMessage(content="stable system prefix"),
        HumanMessage(content="研究任务合同：scope=challenge-sci-001 stage=search"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "web_search_tool", "args": {"query": "challenge"}, "id": "call-1"},
            ],
        ),
        ToolMessage(content="evidence locator=doi:10.1234/x", tool_call_id="call-1"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "fetch_tool", "args": {"url": "https://x"}, "id": "call-2"},
            ],
        ),
        ToolMessage(content="evidence body " + "x" * 2000, tool_call_id="call-2"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "open_tool", "args": {"url": "https://y"}, "id": "call-3"},
            ],
        ),
        ToolMessage(content="later evidence body " + "y" * 2000, tool_call_id="call-3"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "search_more_tool", "args": {}, "id": "call-open"},
            ],
        ),
    ]


def test_unresolved_tool_call_pairs_are_preserved_pairwise():
    messages = _unresolved_pair_messages()
    (compressed, should_break, _applied, _count, _last_iter), events, _ui = _run_compress(
        messages=messages,
        compressor=_TailKeepingCompressor(),
        context_input_hard_limit=HARD_LIMIT,
        post_compression_target_tokens=POST_TARGET,
    )
    assert should_break is False
    before = turn_compression._tool_call_pairing_snapshot(messages)
    after = turn_compression._tool_call_pairing_snapshot(compressed)
    assert before["unresolvedCallIds"] == ["call-open"]
    # The still-unresolved call survives verbatim; no new broken chain appears.
    assert after["unresolvedCallIds"] == before["unresolvedCallIds"]
    assert after["orphanResultCount"] == 0
    assert not any(
        event["action"] == "agent.context_budget_exhausted" for event in events
    )


def test_compression_fails_closed_when_chain_breaks():
    messages = _unresolved_pair_messages()
    (compressed, should_break, _applied, _count, _last_iter), events, _ui = _run_compress(
        messages=messages,
        compressor=_ChainBreakingCompressor(),
        context_input_hard_limit=HARD_LIMIT,
        post_compression_target_tokens=POST_TARGET,
    )
    assert should_break is True
    exhausted = [
        event
        for event in events
        if event["action"] == "agent.context_budget_exhausted"
    ]
    assert exhausted, "broken retention chain must fail closed"
    assert exhausted[0]["fields"].get("guardReason") == "retention_missing"
    # Fail-closed returns the original messages; the model must not see them.
    assert compressed == messages


def test_compression_fails_closed_when_still_over_hard_limit():
    messages = _unresolved_pair_messages()
    (compressed, should_break, _applied, _count, _last_iter), events, _ui = _run_compress(
        messages=messages,
        compressor=_NonShrinkingCompressor(),
        context_input_hard_limit=50,
        post_compression_target_tokens=40,
    )
    assert should_break is True
    exhausted = [
        event
        for event in events
        if event["action"] == "agent.context_budget_exhausted"
    ]
    assert exhausted
    assert exhausted[0]["fields"].get("guardReason") == "post_compression_over_hard_limit"
    assert compressed == messages


def test_compression_summary_carries_retention_contract_fields():
    messages = _unresolved_pair_messages()
    compressor = _RecordingSummaryCompressor()
    prompt_manager = _FakePromptManager()
    retention_contract = {
        "agentId": "agent-x",
        "sessionId": "session-x",
        "researchProjectId": "challenge-sci-001",
        "roleKey": "challenge_cup_search",
    }
    _run_compress(
        messages=messages,
        compressor=compressor,
        context_input_hard_limit=HARD_LIMIT,
        post_compression_target_tokens=POST_TARGET,
        retention_contract=retention_contract,
        prompt_manager=prompt_manager,
    )
    assert prompt_manager.updates, "summary must be persisted via the prompt manager"
    persisted = prompt_manager.updates[-1]
    for marker in (
        "challenge-sci-001",
        "session-x",
        "compressionGeneration=",
        "unresolvedToolCallIds=call-open",
        "iteration=4",
        f"hardLimit={HARD_LIMIT}",
    ):
        assert marker in persisted, marker


def test_preflight_gate_blocks_only_over_limit_inputs():
    ok = turn_compression.evaluate_context_budget_preflight(
        estimated_tokens=HARD_LIMIT, context_input_hard_limit=HARD_LIMIT
    )
    assert ok["exhausted"] is False
    blocked = turn_compression.evaluate_context_budget_preflight(
        estimated_tokens=HARD_LIMIT + 1, context_input_hard_limit=HARD_LIMIT
    )
    assert blocked["exhausted"] is True
    assert blocked["guardReason"] == "input_over_hard_limit"
    disabled = turn_compression.evaluate_context_budget_preflight(
        estimated_tokens=10_000_000, context_input_hard_limit=0
    )
    assert disabled["exhausted"] is False


# ---------------------------------------------------------------------------
# 5) Policy normalization keeps versioned fields
# ---------------------------------------------------------------------------


def test_normalize_keeps_versioned_compression_fields():
    normalized = agent_directory_service.normalize_agent_context_compression_policy(
        {
            "mode": "custom",
            "enabled": True,
            "policyVersion": 3,
            "maxTokenLimit": HARD_LIMIT,
            "compressionTriggerTokenLimit": TRIGGER,
            "postCompressionTargetTokenLimit": POST_TARGET,
        }
    )
    assert normalized["mode"] == "custom"
    assert int(normalized["policyVersion"]) == 3
    assert int(normalized["compressionTriggerTokenLimit"]) == TRIGGER
    assert int(normalized["postCompressionTargetTokenLimit"]) == POST_TARGET
    # Old custom policies stay valid and untouched (fields default to unset).
    legacy = agent_directory_service.normalize_agent_context_compression_policy(
        {"mode": "custom", "enabled": True, "maxTokenLimit": 16_000}
    )
    assert int(legacy.get("policyVersion") or 0) == 0
    assert int(legacy.get("compressionTriggerTokenLimit") or 0) == 0


def test_effective_policy_carries_explicit_trigger_and_target():
    agent_policy = ccp.challenge_cup_role_context_policy("challenge_cup_search")
    assert agent_policy is not None
    effective = agent_directory_service.effective_agent_context_compression_policy(
        {"contextCompressionPolicy": agent_policy},
        None,
        context_window_limit=CONTEXT_WINDOW,
    )
    assert effective["mode"] == "custom"
    assert int(effective["compressionTriggerTokenLimit"]) == TRIGGER
    assert int(effective["postCompressionTargetTokenLimit"]) <= POST_TARGET
    assert int(effective["effectiveTokenLimit"]) == HARD_LIMIT


# ---------------------------------------------------------------------------
# 6) Bootstrap hook: fail-soft, version-gated one-time migration
# ---------------------------------------------------------------------------


def _reset_bootstrap_state() -> None:
    with team_service._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        team_service._TEAM_SYSTEM_BOOTSTRAP_THREAD = None
        team_service._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
            {
                "status": "idle",
                "requiredSteps": [],
                "reason": "",
                "startedAt": "",
                "finishedAt": "",
                "lastError": "",
                "elapsedMs": 0,
                "attempt": 0,
                "requestId": "",
                "checkedAtMonotonic": 0.0,
            }
        )


def _stub_team_checks_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(team_service, "evolution_system_teams_missing", lambda: False)
    monkeypatch.setattr(team_service, "ai_search_system_team_missing", lambda: False)
    monkeypatch.setattr(team_service, "challenge_cup_research_team_missing", lambda: False)
    monkeypatch.setattr(
        team_service, "knowledge_expansion_team_agents_need_repair", lambda: False
    )


def test_bootstrap_required_steps_fail_soft_when_registry_read_fails(monkeypatch, tmp_path):
    from core.web.services.team import system_bootstrap

    _use_tmp_project_root(tmp_path, monkeypatch)
    _stub_team_checks_absent(monkeypatch)

    def _registry_boom() -> bool:
        raise RuntimeError("agent registry read failed")

    monkeypatch.setattr(ccp, "challenge_cup_context_policies_outdated", _registry_boom)
    events: list[str] = []
    monkeypatch.setattr(
        system_bootstrap,
        "_record_system_team_bootstrap_event",
        lambda code, **kwargs: events.append(code),
    )

    steps = system_bootstrap._system_team_bootstrap_required_steps()

    assert "challenge_cup_context_policy_migration" not in steps
    assert steps == []
    assert "team.system_bootstrap.context_policy_check_failed" in events


def test_bootstrap_request_survives_registry_read_failure(monkeypatch, tmp_path):
    """A broken agent registry must not fail startup (status stays ready)."""

    from core.web.services.team import system_bootstrap

    _use_tmp_project_root(tmp_path, monkeypatch)
    _reset_bootstrap_state()
    _stub_team_checks_absent(monkeypatch)

    def _registry_boom() -> bool:
        raise RuntimeError("agent registry read failed")

    monkeypatch.setattr(ccp, "challenge_cup_context_policies_outdated", _registry_boom)
    monkeypatch.setattr(
        system_bootstrap,
        "_record_system_team_bootstrap_event",
        lambda code, **kwargs: None,
    )

    payload = team_service.request_system_team_bootstrap(reason="team_list")

    assert payload["status"] == "ready"
    assert payload["requiredSteps"] == []


def test_bootstrap_run_applies_version_gated_migration(monkeypatch, tmp_path):
    from core.web.services.team import system_bootstrap

    _use_tmp_project_root(tmp_path, monkeypatch)
    _stub_team_checks_absent(monkeypatch)
    state = {"outdated": True}
    applied: list[dict] = []
    monkeypatch.setattr(
        ccp, "challenge_cup_context_policies_outdated", lambda: state["outdated"]
    )

    def _apply(*, snapshot=None):
        applied.append({"snapshot": snapshot})
        state["outdated"] = False
        return {
            "policyVersion": ccp.CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
            "migratedRoles": ["challenge_cup_search", "challenge_cup_evaluator"],
            "skippedCustomRoles": ["challenge_cup_extractor"],
            "migratedCount": 2,
        }

    monkeypatch.setattr(ccp, "apply_challenge_cup_context_policies", _apply)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        system_bootstrap,
        "_record_system_team_bootstrap_event",
        lambda code, **kwargs: events.append((code, kwargs)),
    )

    system_bootstrap._run_system_team_bootstrap(
        "request-policy-test", ["challenge_cup_context_policy_migration"], "team_list"
    )

    assert applied and applied[0]["snapshot"] is None
    migrated_events = [
        kwargs for code, kwargs in events if code == "team.challenge_cup_context_policy_migrated"
    ]
    assert migrated_events, "successful migration must be recorded as an event"
    assert migrated_events[0]["fields"]["migratedCount"] == 2
    assert migrated_events[0]["fields"]["migratedRoles"] == [
        "challenge_cup_search",
        "challenge_cup_evaluator",
    ]
    assert migrated_events[0]["fields"]["skippedCustomRoles"] == ["challenge_cup_extractor"]
    with team_service._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        assert team_service._TEAM_SYSTEM_BOOTSTRAP_STATE.get("status") == "ready"


def test_bootstrap_run_never_raises_when_migration_fails(monkeypatch, tmp_path):
    from core.web.services.team import system_bootstrap

    _use_tmp_project_root(tmp_path, monkeypatch)
    _stub_team_checks_absent(monkeypatch)
    monkeypatch.setattr(ccp, "challenge_cup_context_policies_outdated", lambda: True)

    def _apply_boom(*, snapshot=None):
        raise RuntimeError("policy write failed")

    monkeypatch.setattr(ccp, "apply_challenge_cup_context_policies", _apply_boom)
    events: list[str] = []
    monkeypatch.setattr(
        system_bootstrap,
        "_record_system_team_bootstrap_event",
        lambda code, **kwargs: events.append(code),
    )

    # Must not raise: the migration failure is recorded, never propagated.
    system_bootstrap._run_system_team_bootstrap(
        "request-policy-fail", ["challenge_cup_context_policy_migration"], "team_list"
    )

    assert "team.challenge_cup_context_policy_migration_failed" in events
    with team_service._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        status = team_service._TEAM_SYSTEM_BOOTSTRAP_STATE.get("status")
    assert status != "failed"
