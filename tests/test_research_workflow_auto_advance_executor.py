"""Automation policy active executor tests (gated real execution).

Covers the safety ladder and the three executable capability dispatches:

- every missing ladder rung (no policy / shadow mode / no recorded approvers /
  calibration not met / insufficient evidence / drain mode / kill switch /
  disabled capability) => record-only with a full audit record;
- ``autoCloseMeetingRound``: full-ladder execution presses the real
  ``approve_meeting_digest`` path with the system actor; digest
  re-validation failures and stale hashes never execute; replays are
  idempotent through the meeting state machine itself;
- ``autoSelectCandidates``: presses the real ``record_selection`` path,
  idempotent on replay;
- ``autoConvergeQuestion``: executes through ``record_human_adjudication``
  (which keeps its claim-belief hard gate); a blocked gate is a recorded
  skip, never a bypass;
- enabled-but-unimplemented capabilities are audited ``not_implemented``;
- every attempt appends one durable record to the dedicated
  ``policy_activation_audit.jsonl`` store with the complete field set.

All discussion content comes from fake runners; no real model, network, or
research activity is involved.
"""

from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path

import pytest
from core.research.competition.calibration_records import (
    G12CalibrationBundle,
    G12JudgementRecord,
)
from core.research.workflow.contracts import (
    AUTO_ADVANCE_CAPABILITIES,
    AutoAdvancePolicyV2,
    compute_policy_content_hash,
)
from core.research.workflow.contracts.audit_sampling import SampleKind
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow.research_runtime import (
    automation_policy_executor as executor,
    hypothesis_first_chain as chain,
    policy_shadow_evaluator as ev,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)

from tests._support.team_workflow.helpers import (
    _seed_claim_belief_gate_fixture,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_ROLES = ("coordinator", "researcher")
_QUESTION_ID = "SCI-096"
_SYSTEM_POLICY_ID = "cc-auto-advance-policy-exec-test"
_SYSTEM_ACTOR = f"system:auto-advance:{_SYSTEM_POLICY_ID}"


# ---------------------------------------------------------------------------
# policy fixtures (activation-stage documents)


def _active_policy_payload(**capability_overrides) -> dict:
    """An approved + active policy with every capability on by default."""

    capabilities = {name: True for name in sorted(AUTO_ADVANCE_CAPABILITIES)}
    capabilities.update(capability_overrides)
    payload = {
        "schemaVersion": "1.0.0",
        "policyId": _SYSTEM_POLICY_ID,
        "version": "2.0.0-candidate.1",
        "status": "approved",
        "executionMode": "active",
        "createdAt": "2026-08-31T00:00:00+08:00",
        "capabilities": capabilities,
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low_risk_standard"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
        "uiPresets": None,
        "calibrationGate": {
            "confusionMatrix": {
                "axes": ["autoAdvanceDecision", "humanReviewDecision"]
            },
            "kappaWithCI": {
                "measure": "cohens_kappa",
                "minimumKappa": 0.75,
                "confidenceInterval": "95_percent",
            },
            "stratifiedBy": ["risk_class", "catalog_domain"],
            "falseAutoApproveUpperBound": {
                "method": "wilson",
                "side": "one_sided_upper",
            },
            "sequentialSamplingDeclaration": {
                "mode": "fixed_n_then_sequential_extension",
                "declaredBeforeUnblinding": True,
            },
            "notAPermanentDelegation": True,
        },
        "supersedes": {
            "policyId": "cc-auto-advance-policy-001",
            "supersededFields": ["autoAdvanceLevel"],
        },
        "activationRequires": (
            "explicit approval recorded against policyId + version + contentHash"
        ),
        "approval": {
            "requiredApprovers": ["competition_owner"],
            "approvedBy": ["competition-owner-1"],
            "frozenAt": "2026-08-31T00:00:00Z",
            "contentHash": None,
            "contentHashRule": (
                "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), "
                "ensure_ascii=False) with contentHash set to null; uppercase hex"
            ),
        },
    }
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    return payload


def _injected_policy(**capability_overrides):
    """A contract-validated active policy + its raw payload (direct calls)."""

    payload = _active_policy_payload(**capability_overrides)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    return policy, payload


@pytest.fixture
def active_policy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "auto-advance-policy-active.json"
    path.write_text(
        json.dumps(_active_policy_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(path))
    # Isolate the operator config home: a deployed default policy file or
    # config.toml override must never shadow this fixture's document.
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "operator-config"))
    executor._DOCUMENT_CACHE.clear()
    ev._POLICY_CACHE.clear()
    return path


# ---------------------------------------------------------------------------
# calibration evidence fixtures (real decision-#13 statistics)


def _calibration_policy_mapping() -> dict:
    return {
        "policyId": _SYSTEM_POLICY_ID,
        "version": "2.0.0-candidate.1",
        "contentHash": compute_policy_content_hash(_active_policy_payload()),
        "calibrationGate": {
            "kappaWithCI": {"minimumKappa": 0.75},
            "falseAutoApproveUpperBound": {
                "method": "wilson",
                "side": "one_sided_upper",
            },
            "maxFalseAutoApproveUpperBound": 0.35,
        },
    }


def _judgement(question_id: str, *, auto: str, human: str) -> G12JudgementRecord:
    return G12JudgementRecord(
        questionId=question_id,
        sampleKind=SampleKind.G12_CALIBRATION,
        autoDecision=auto,
        humanDecision=human,
        riskClass="low",
        domain="physics",
        recordedAt="2026-08-31T01:00:00+08:00",
        evidenceRef=f"review:g12:{question_id}",
    )


def _agreed_bundle() -> G12CalibrationBundle:
    from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
        generate_g12_calibration_manifest,
    )

    pool = [
        {"questionId": f"q{index:02d}", "riskClass": "low", "catalogDomain": "physics"}
        for index in range(1, 13)
    ]
    manifest = generate_g12_calibration_manifest(
        pool=pool,
        policy={
            "policyId": _SYSTEM_POLICY_ID,
            "version": "2.0.0-candidate.1",
            "contentHash": "A" * 64,
        },
        seed="seed-auto-advance-executor",
        generated_at="2026-08-31T00:00:00+08:00",
    )
    records = [
        _judgement("q01", auto="auto_escalate", human="escalate"),
        _judgement("q02", auto="auto_escalate", human="escalate"),
    ] + [
        _judgement(f"q{index:02d}", auto="auto_approve", human="approve")
        for index in range(3, 13)
    ]
    return G12CalibrationBundle.build(manifest=manifest, records=records)


@pytest.fixture(scope="module")
def passing_calibration_verdict() -> dict:
    from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
        calibration_gate_verdict,
    )

    verdict = calibration_gate_verdict(_calibration_policy_mapping(), _agreed_bundle())
    assert verdict["passed"] is True, verdict
    return verdict


def _pending_calibration_verdict() -> dict:
    from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
        calibration_gate_verdict,
    )

    bundle = G12CalibrationBundle.build(
        manifest=_agreed_bundle().manifest, records=[]
    )
    return calibration_gate_verdict(_calibration_policy_mapping(), bundle)


# ---------------------------------------------------------------------------
# chain fixtures (mirroring the shadow evaluator suite)


class _InlineExecutor:
    """Run submitted chat-room rounds synchronously (DEV tests only)."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced via future
            future.set_exception(exc)
        return future


@pytest.fixture
def hf_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    reset_formal_write_runtime_for_tests()
    from core.web.services.team_workflow import (
        hypothesis_rounds as hrounds,
        meeting_rounds as meetings,
        personal_memory_candidates as memories,
        research_templates as templates,
    )

    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    monkeypatch.setattr(claim_ledger_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _InlineExecutor())
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    monkeypatch.delenv(executor.AUTO_ADVANCE_DISABLED_ENV, raising=False)
    # Isolate the operator config home so the activation policy resolver
    # cannot pick up a deployed default/config document in tests.
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "operator-config"))
    from config import paths as config_paths

    config_paths._AUTO_ADVANCE_POLICY_PATH_CACHE.clear()
    executor._DOCUMENT_CACHE.clear()
    ev._POLICY_CACHE.clear()
    agents: dict[str, str] = {}
    for role in (
        *_ROLES,
        "source_finder",
        "source_relation_mapper",
        "experiment_planner",
        "experiment_ledger",
    ):
        agent = agent_directory_service.create_agent_instance(
            display_name=f"executor {role}", role_key=role, created_by="executor-test"
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"executor {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="自动推进执行团队",
        purpose="auto-advance-executor",
        members=[
            {"agentId": agents[role], "role": role} for role in agents
        ],
    )["teamId"]
    return team_id, agents


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """Approve the formal v2 question artifact with hyp-a/hyp-b candidates."""

    from core.web.services.team_workflow.research_runtime import question_launch

    detail = {
        "teamId": "executor",
        "questionId": _QUESTION_ID,
        "selectedRunId": "stage1-sci-096-v1",
        "record": {
            "questionId": _QUESTION_ID,
            "runId": "stage1-sci-096-v1",
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
            "humanGates": {
                "allApproved": True,
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": _QUESTION_ID,
                "question_en": "Fixture question",
            },
            "hypotheses": [
                {"hypothesis_id": "hyp-a", "statement": "candidate hyp-a"},
                {"hypothesis_id": "hyp-b", "statement": "candidate hyp-b"},
            ],
            "selection": {"selected_hypothesis_id": "hyp-a"},
            "review": {"human_review_status": "passed"},
            "submission": {"eligible": True},
        },
        "artifact": {"sha256": "b" * 64, "immutable": True},
    }
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {_QUESTION_ID.upper(): detail},
    )


def _marker_runner(participant, prompt, context):
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        content = "AGREE: hyp-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _open_two_review_meetings(
    team_id: str, agents: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> list[dict]:
    _patch_approved_question(monkeypatch)
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope as scope,
    )

    agent_ids = [agents[role] for role in _ROLES]
    scope_fields = chain._question_scope_envelope(team_id, _QUESTION_ID)
    with scope("u-1", roles=("operator",)):
        recorded = selections.record_hypothesis_selection(
            team_id,
            {
                **scope_fields,
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "decidedBy": agent_ids[0],
            },
            agent_runner=_marker_runner,
        )
    review = recorded["reviewMeeting"]
    siblings = list(review.get("reviewMeetings") or [])
    if siblings:
        return [dict(item["meetingRound"]) for item in siblings]
    return [dict(review["meetingRound"])]


def _drive_to_awaiting_approval(
    team_id: str, meeting_round_id: str, actor: str
) -> None:
    drafted = meeting_runtime.prepare_meeting_summary_draft(
        team_id, meeting_round_id, actor=actor, force=False
    )
    assert drafted["status"] == "awaiting_approval"


def _select_decision(agent_id: str) -> dict:
    return {
        "decision": "select_candidate",
        "rationale": "hyp-a 证据最完整，收敛进入实验设计。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["evidence:review-matrix-2"],
        "status": "adopted",
    }


def _closure_payload(agent_ids: list[str], decisions: list[dict]) -> dict:
    return {
        "decisions": decisions,
        "closedBy": agent_ids[0],
        "memorySummaries": {
            agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids
        },
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }


def _audits(team_id: str) -> list[dict]:
    return executor.list_activation_audits(team_id)["audits"]


def _adjudications(team_id: str) -> list[dict]:
    return [
        record
        for record in chain._records(team_id)
        if str(record.get("recordKind") or "") == chain.HUMAN_ADJUDICATION_KIND
    ]


# ---------------------------------------------------------------------------
# ladder: every missing rung records instead of executing


def _base_attempt_kwargs():
    policy, payload = _injected_policy()
    return {"policy": policy, "payload": payload}


def test_attempt_with_no_policy_configured_is_total_noop(
    hf_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _ = hf_env
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    executor._DOCUMENT_CACHE.clear()

    result = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
    )

    assert result is None
    assert _audits(team_id) == []
    assert not executor.policy_activation_audit_store_path(team_id).exists()


def test_shadow_mode_policy_records_instead_of_executing(
    hf_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _ = hf_env
    payload = _active_policy_payload()
    payload["status"] = "candidate"
    payload["executionMode"] = "shadow"
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    path = tmp_path / "shadow-policy.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(path))
    executor._DOCUMENT_CACHE.clear()

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_activationCredential"
    assert [rung["gateId"] for rung in record["ladder"]] == [
        "killSwitch",
        "policyLoaded",
        "activationCredential",
        "calibrationGate",
        "drainMode",
    ]


def test_missing_recorded_approvers_fail_the_ladder_recheck(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy()
    tampered_payload = json.loads(json.dumps(payload))
    tampered_payload["approval"]["approvedBy"] = []

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        policy=policy,
        payload=tampered_payload,
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_activationCredential"
    credential = next(
        rung for rung in record["ladder"] if rung["gateId"] == "activationCredential"
    )
    assert credential["passed"] is False


def test_calibration_not_passed_records_instead_of_executing(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy()

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        policy=policy,
        payload=payload,
        calibration_verdict={
            "passed": False,
            "reasonCode": "calibration_evidence_unavailable",
            "reasons": ["no bundle"],
        },
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_calibrationGate"


def test_insufficient_calibration_data_records_instead_of_executing(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy()

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        policy=policy,
        payload=payload,
        calibration_verdict=_pending_calibration_verdict(),
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_calibrationGate"


def test_drain_mode_records_instead_of_executing(
    hf_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _ = hf_env
    payload = _active_policy_payload()
    payload["drainMode"] = "draining"
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    path = tmp_path / "draining-policy.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(path))
    executor._DOCUMENT_CACHE.clear()

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        calibration_verdict={"passed": True},
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_drainMode"


def test_kill_switch_has_highest_priority_and_records(
    hf_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _ = hf_env
    monkeypatch.setenv(executor.AUTO_ADVANCE_DISABLED_ENV, "1")

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        **_base_attempt_kwargs(),
        calibration_verdict={"passed": False},
    )
    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_killSwitch"
    kill = record["ladder"][0]
    assert kill["gateId"] == "killSwitch"
    assert kill["passed"] is False
    # The calibration failure is still reported in the same audit record.
    calibration = next(
        rung for rung in record["ladder"] if rung["gateId"] == "calibrationGate"
    )
    assert calibration["passed"] is False


def test_disabled_capability_records_without_executing(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy(autoCloseMeetingRound=False)

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id="meeting-x",
        policy=policy,
        payload=payload,
        calibration_verdict={"passed": True},
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "capability_disabled"
    assert record["capabilityEnabled"] is False


def test_audit_record_fields_are_complete(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy()
    executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        question_id=_QUESTION_ID,
        meeting_round_id="meeting-x",
        policy=policy,
        payload=payload,
        calibration_verdict={"passed": False},
    )

    audits = _audits(team_id)
    assert len(audits) == 1
    record = audits[0]
    assert record["schemaVersion"] == "1.0.0"
    assert record["auditId"].startswith("hfaudit-")
    assert record["teamId"] == team_id
    assert record["questionId"] == _QUESTION_ID
    assert record["decisionPoint"] == "meeting_close"
    assert record["capability"] == "autoCloseMeetingRound"
    assert record["policyId"] == _SYSTEM_POLICY_ID
    assert record["policyVersion"] == "2.0.0-candidate.1"
    assert len(record["policyContentHash"]) == 64
    assert record["policyExecutionMode"] == "active"
    assert record["policyStatus"] == "approved"
    assert record["capabilityEnabled"] is True
    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_calibrationGate"
    assert record["actor"] == _SYSTEM_ACTOR
    assert record["ref"] == {"meetingRoundId": "meeting-x"}
    assert record["executedAt"].endswith("Z")
    assert len(record["ladder"]) == 5


def test_audit_replay_does_not_duplicate_records(hf_env) -> None:
    team_id, _ = hf_env
    kwargs = {
        **_base_attempt_kwargs(),
        "calibration_verdict": {"passed": False},
        "question_id": _QUESTION_ID,
        "meeting_round_id": "meeting-x",
    }
    first = executor.attempt_capability(
        decision_point="meeting_close", team_id=team_id, **kwargs
    )
    second = executor.attempt_capability(
        decision_point="meeting_close", team_id=team_id, **kwargs
    )

    assert first["auditId"] == second["auditId"]
    assert len(_audits(team_id)) == 1


# ---------------------------------------------------------------------------
# autoCloseMeetingRound


def test_auto_close_meeting_round_executes_approval_with_system_actor(
    hf_env,
    active_policy_file: Path,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, agents = hf_env
    siblings = _open_two_review_meetings(team_id, agents, monkeypatch)
    meeting_round_id = siblings[0]["meetingRoundId"]
    _drive_to_awaiting_approval(team_id, meeting_round_id, agents["coordinator"])

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        question_id=_QUESTION_ID,
        meeting_round_id=meeting_round_id,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "executed"
    assert record["reasonCode"] == "executed"
    assert record["actor"] == _SYSTEM_ACTOR
    assert record["detail"]["meetingRoundStatus"] == "closed"
    stored = meeting_rounds.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert stored["status"] == "closed"
    assert stored["closedBy"] == _SYSTEM_ACTOR

    # Replay: the meeting is closed, a second attempt only records.
    replay = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        question_id=_QUESTION_ID,
        meeting_round_id=meeting_round_id,
        calibration_verdict=passing_calibration_verdict,
    )
    assert replay["decision"] == "skipped"
    assert replay["reasonCode"] == "meeting_not_awaiting_approval"
    executed = [
        item for item in _audits(team_id) if item["decision"] == "executed"
    ]
    assert len(executed) == 1


def test_auto_close_meeting_round_does_not_execute_on_failed_digest_revalidation(
    hf_env,
    active_policy_file: Path,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, agents = hf_env
    siblings = _open_two_review_meetings(team_id, agents, monkeypatch)
    meeting_round_id = siblings[0]["meetingRoundId"]
    _drive_to_awaiting_approval(team_id, meeting_round_id, agents["coordinator"])

    from core.research.workflow.contracts import ContractValidationError

    def _raise_missing_marker(digest, markers):
        raise ContractValidationError(
            "a disagreement from the source messages is missing in the meeting digest"
        )

    monkeypatch.setattr(meeting_rounds, "_assert_markers_preserved", _raise_missing_marker)

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        question_id=_QUESTION_ID,
        meeting_round_id=meeting_round_id,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "digest_revalidation_failed"
    stored = meeting_rounds.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert stored["status"] == "awaiting_approval"


def test_auto_close_meeting_round_records_stale_digest_without_executing(
    hf_env,
    active_policy_file: Path,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, agents = hf_env
    siblings = _open_two_review_meetings(team_id, agents, monkeypatch)
    meeting_round_id = siblings[0]["meetingRoundId"]
    _drive_to_awaiting_approval(team_id, meeting_round_id, agents["coordinator"])

    real_revalidate = executor._revalidate_digest

    def _stale_revalidate(meeting_round):
        draft, errors = real_revalidate(meeting_round)
        draft["contentHash"] = "0" * 64
        return draft, errors

    monkeypatch.setattr(executor, "_revalidate_digest", _stale_revalidate)

    record = executor.attempt_capability(
        decision_point="meeting_close",
        team_id=team_id,
        question_id=_QUESTION_ID,
        meeting_round_id=meeting_round_id,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "stale_digest"
    stored = meeting_rounds.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert stored["status"] == "awaiting_approval"


# ---------------------------------------------------------------------------
# autoSelectCandidates


def _stub_review_meeting_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the downstream meeting dispatch that record_selection triggers.

    Production behavior (auto-open the first review meeting) is desired and
    untouched; in DEV tests it would otherwise drive real agent turns, so the
    dispatch is stubbed at the chain boundary exactly like the chain suite
    stubs ``schedule_meeting_discussion``.  The selection record itself stays
    fully real.
    """

    def _fake_open(_team_id, _record, **_kwargs):
        return {
            "status": "stubbed",
            "meetingRound": {},
            "roomId": "",
            "roundId": "",
            "chatRoomRoundIds": [],
            "discussion": {},
            "roundIndex": 1,
            "reviewMeetings": [],
            "candidateCount": 0,
        }

    monkeypatch.setattr(chain, "open_review_meeting_for_selection", _fake_open)


def test_auto_select_candidates_executes_record_selection_with_system_actor(
    hf_env,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, _ = hf_env
    _patch_approved_question(monkeypatch)
    _stub_review_meeting_dispatch(monkeypatch)
    policy, payload = _injected_policy()

    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-b", "hyp-a"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "executed"
    assert record["detail"]["status"] == "created"
    selection = selections.list_hypothesis_selections(team_id)["selections"][0]
    assert selection["decidedBy"] == _SYSTEM_ACTOR
    # Digest proposal order is the rule: submitted order is preserved.
    assert selection["selectedCandidateIds"] == ["hyp-b", "hyp-a"]

    # Replay with the SAME digest order reuses the selection (idempotent).
    replay = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-b", "hyp-a"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
        calibration_verdict=passing_calibration_verdict,
    )
    assert replay["decision"] == "executed"
    assert replay["detail"]["status"] == "reused"
    assert len(selections.list_hypothesis_selections(team_id)["selections"]) == 1


def test_auto_select_candidates_with_single_candidate_records_only(
    hf_env,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, _ = hf_env
    _patch_approved_question(monkeypatch)
    _stub_review_meeting_dispatch(monkeypatch)
    policy, payload = _injected_policy()

    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-a"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "candidate_set_too_small"
    assert selections.list_hypothesis_selections(team_id)["selections"] == []


# ---------------------------------------------------------------------------
# autoConvergeQuestion


def _close_both_sibling_meetings(
    team_id: str, agents: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> dict:
    siblings = _open_two_review_meetings(team_id, agents, monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        first_id = siblings[0]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, first_id, agents["coordinator"])
        chain.close_review_meeting(
            team_id,
            first_id,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        second_id = siblings[1]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, second_id, agents["coordinator"])
        closed = chain.close_review_meeting(
            team_id,
            second_id,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
    return closed


def test_auto_converge_question_executes_adjudication_with_system_actor(
    hf_env,
    active_policy_file: Path,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, agents = hf_env
    _seed_claim_belief_gate_fixture(
        monkeypatch, team_id, _QUESTION_ID, ["hyp-a", "hyp-b"]
    )
    closed = _close_both_sibling_meetings(team_id, agents, monkeypatch)
    round_id = closed["hypothesisRound"]["roundId"]

    record = executor.attempt_capability(
        decision_point="converge_question",
        team_id=team_id,
        question_id=_QUESTION_ID,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "executed"
    assert record["detail"]["status"] == "created"
    assert record["detail"]["hypothesisRoundId"] == round_id
    adjudications = _adjudications(team_id)
    assert len(adjudications) == 1
    assert adjudications[0]["decidedBy"] == _SYSTEM_ACTOR
    assert adjudications[0]["decision"] == "accepted"

    # Replay: the same idempotency key reuses the stored adjudication.
    replay = executor.attempt_capability(
        decision_point="converge_question",
        team_id=team_id,
        question_id=_QUESTION_ID,
        calibration_verdict=passing_calibration_verdict,
    )
    assert replay["decision"] == "executed"
    assert replay["detail"]["status"] == "reused"
    assert len(_adjudications(team_id)) == 1


def test_auto_converge_question_records_claim_gate_block_without_executing(
    hf_env,
    active_policy_file: Path,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, agents = hf_env
    # No claim-belief fixture: the fail-closed gate has no supported claims
    # to evaluate, so the accepted adjudication must be blocked.
    _close_both_sibling_meetings(team_id, agents, monkeypatch)

    record = executor.attempt_capability(
        decision_point="converge_question",
        team_id=team_id,
        question_id=_QUESTION_ID,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "claim_belief_gate_blocked"
    assert record["detail"]["blockers"]
    assert _adjudications(team_id) == []


def test_chain_converge_hook_records_skip_without_calibration_evidence(
    hf_env,
    active_policy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chain hook fires by itself and skips while no G12 bundle exists."""

    team_id, agents = hf_env
    _close_both_sibling_meetings(team_id, agents, monkeypatch)

    converge_audits = [
        record
        for record in _audits(team_id)
        if record["decisionPoint"] == "converge_question"
    ]
    assert converge_audits
    latest = converge_audits[-1]
    assert latest["decision"] == "skipped"
    assert latest["reasonCode"] == "ladder_calibrationGate"
    assert latest["actor"] == _SYSTEM_ACTOR
    # Nothing was adjudicated by the hook.
    assert _adjudications(team_id) == []
    # The audit store is dedicated and separate from the shadow store.
    audit_path = executor.policy_activation_audit_store_path(team_id)
    shadow_path = ev.policy_shadow_store_path(team_id)
    assert audit_path.name == "policy_activation_audit.jsonl"
    assert audit_path != shadow_path
    assert audit_path.parent == shadow_path.parent


# ---------------------------------------------------------------------------
# enabled capabilities without an executor body


def test_unimplemented_capability_is_audited_not_implemented(hf_env) -> None:
    team_id, _ = hf_env
    policy, payload = _injected_policy()  # every switch on

    for point, capability in (
        ("evidence_repair", "autoStartEvidenceRepair"),
        ("batch_gate", "autoAdvanceBatchGate"),
    ):
        record = executor.attempt_capability(
            decision_point=point,
            team_id=team_id,
            question_id=_QUESTION_ID,
            policy=policy,
            payload=payload,
            calibration_verdict={"passed": True},
        )
        assert record["decision"] == "not_implemented"
        assert record["reasonCode"] == "capability_not_implemented"
        assert record["capability"] == capability
        assert record["capabilityEnabled"] is True
        assert "human stays in the loop" in record["detail"]["note"]

    assert len(_audits(team_id)) == 2
