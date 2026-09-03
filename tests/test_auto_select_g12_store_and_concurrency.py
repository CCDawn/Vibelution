"""Bounded auto-selection + store-backed G12 gate + concurrency elevation.

Regression coverage for the autoSelectCandidates cost bound and the
satisfiable-but-still-fail-closed G12 calibration gate:

- ``candidateSelection`` contract: default (maxSelected=2,
  digest_proposal_order), floor of 2, unknown rules rejected;
- the executor truncates the generation digest's proposal order to
  ``maxSelected``, keeps the order deterministic, and records the rule,
  the cap and the truncation fact in the audit detail;
- the G12 judgement-record store: empty store stays fail-closed
  ("calibration evidence unavailable"); operator-recorded manifests +
  judgements make the unchanged gate logic pass; identical re-records are
  idempotent; conflicting judgements are rejected, never overwritten;
- the executor's default calibration read consumes the store (no injected
  verdict needed) and a full ladder attempt executes;
- concurrency: 3-4 stay rejected without completed G12 evidence and pass
  with it; only the real-125 plan may exceed the frozen default.

All discussion content is stubbed; no real model, network, or research
activity is involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.research.competition.real_control_batch import (
    RealBatchError,
    validate_real_concurrency,
)
from core.research.workflow.contracts import (
    AUTO_ADVANCE_CAPABILITIES,
    AutoAdvancePolicyV2,
    CANDIDATE_SELECTION_DEFAULT_MAX,
    CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
    compute_policy_content_hash,
)
from core.research.workflow.contracts.audit_sampling import SampleKind
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import challenge_cup_real_batch as real_batch
from core.web.services.team_workflow.research_runtime import (
    automation_policy_executor as executor,
    g12_calibration_store as g12_store,
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
    generate_g12_calibration_manifest,
)

from tests._support.team_workflow.helpers import _use_tmp_project_root

_QUESTION_ID = "SCI-096"
_ROLES = (
    "coordinator",
    "researcher",
    "source_finder",
    "source_relation_mapper",
    "experiment_planner",
    "experiment_ledger",
)
_SYSTEM_POLICY_ID = "cc-auto-select-g12-test"


# ---------------------------------------------------------------------------
# fixtures


def _policy_payload(
    *,
    candidate_selection: dict | None = None,
    declared_max_false_auto_approve: float | None = None,
) -> dict:
    """An approved + active policy, optionally declaring G12 thresholds."""

    capabilities = {name: True for name in sorted(AUTO_ADVANCE_CAPABILITIES)}
    calibration_gate = {
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
    }
    if declared_max_false_auto_approve is not None:
        calibration_gate["maxFalseAutoApproveUpperBound"] = (
            declared_max_false_auto_approve
        )
    payload = {
        "schemaVersion": "1.0.0",
        "policyId": _SYSTEM_POLICY_ID,
        "version": "2.0.0-approved.1",
        "status": "approved",
        "executionMode": "active",
        "createdAt": "2026-09-02T00:00:00+08:00",
        "capabilities": capabilities,
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low_risk_standard"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
        "uiPresets": None,
        "calibrationGate": calibration_gate,
        "supersedes": {"policyId": "cc-auto-advance-policy-001"},
        "activationRequires": (
            "explicit approval recorded against policyId + version + contentHash"
        ),
        "approval": {
            "requiredApprovers": ["competition_owner"],
            "approvedBy": ["operator"],
            "frozenAt": "2026-09-02T00:00:00+08:00",
            "contentHash": None,
            "contentHashRule": (
                "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), "
                "ensure_ascii=False) with contentHash set to null; uppercase hex"
            ),
        },
    }
    if candidate_selection is not None:
        payload["candidateSelection"] = candidate_selection
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    return payload


@pytest.fixture
def g12_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated project root + operator config home (no policy configured)."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "operator-config"))
    from config import paths as config_paths

    config_paths._AUTO_ADVANCE_POLICY_PATH_CACHE.clear()
    monkeypatch.delenv(
        "VIBELUTION_AUTO_ADVANCE_POLICY_PATH", raising=False
    )
    monkeypatch.delenv(executor.AUTO_ADVANCE_DISABLED_ENV, raising=False)
    executor._DOCUMENT_CACHE.clear()
    return tmp_path


@pytest.fixture(scope="module")
def passing_calibration_verdict() -> dict:
    """A real decision-#13 verdict for ladder injection (agreed 12 pilot)."""

    from core.research.competition.calibration_records import G12CalibrationBundle
    from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
        calibration_gate_verdict,
    )

    pool = [
        {"questionId": f"q{index:02d}", "riskClass": "low", "catalogDomain": "physics"}
        for index in range(1, 13)
    ]
    manifest = generate_g12_calibration_manifest(
        pool=pool,
        policy={"policyId": _SYSTEM_POLICY_ID, "version": "2.0.0-approved.1", "contentHash": "A" * 64},
        seed="seed-truncation",
        generated_at="2026-09-02T00:00:00+08:00",
    )
    records = _agreed_judgements(list(manifest.questionIds))
    bundle = G12CalibrationBundle.build(manifest=manifest, records=records)
    verdict = calibration_gate_verdict(
        {
            "policyId": _SYSTEM_POLICY_ID,
            "version": "2.0.0-approved.1",
            "contentHash": "A" * 64,
            "calibrationGate": {
                "kappaWithCI": {"minimumKappa": 0.75},
                "falseAutoApproveUpperBound": {
                    "method": "wilson",
                    "side": "one_sided_upper",
                },
                "maxFalseAutoApproveUpperBound": 0.35,
            },
        },
        bundle,
    )
    assert verdict["passed"] is True, verdict
    return verdict


def _seed_team() -> str:
    agents: dict[str, str] = {}
    for role in _ROLES:
        agent = agent_directory_service.create_agent_instance(
            display_name=f"g12 {role}", role_key=role, created_by="g12-test"
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"g12 {role}"
        )
        agents[role] = agent["agentId"]
    return team_service.create_team(
        name="G12 自动选择测试团队",
        purpose="auto-select-g12",
        members=[{"agentId": agent_id, "role": role} for role, agent_id in agents.items()],
    )["teamId"]


def _patch_approved_question(
    monkeypatch: pytest.MonkeyPatch, hypothesis_ids: list[str]
) -> None:
    """Approve the formal v2 question artifact with the given candidates."""

    from core.web.services.team_workflow.research_runtime import question_launch

    detail = {
        "teamId": "g12",
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
                {"hypothesis_id": item, "statement": f"candidate {item}"}
                for item in hypothesis_ids
            ],
            "selection": {"selected_hypothesis_id": hypothesis_ids[0]},
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


def _stub_review_meeting_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the downstream review meeting dispatch (selection stays real)."""

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


def _agreed_judgements(question_ids: list[str]) -> list[dict]:
    """Zero-false-approve pilot: everything agreed, two escalations."""

    escalations = set(question_ids[:2])
    records = []
    for question_id in question_ids:
        records.append(
            {
                "questionId": question_id,
                "sampleKind": SampleKind.G12_CALIBRATION.value,
                "autoDecision": (
                    "auto_escalate" if question_id in escalations else "auto_approve"
                ),
                "humanDecision": (
                    "escalate" if question_id in escalations else "approve"
                ),
                "riskClass": "low",
                "domain": "physics",
                "recordedAt": "2026-09-02T01:00:00+08:00",
                "evidenceRef": f"review:g12:{question_id}",
            }
        )
    return records


def _record_passing_g12_evidence(
    team_id: str,
    payload: dict,
    policy: AutoAdvancePolicyV2,
) -> dict:
    """Record a complete agreed pilot bound to the policy identity."""

    pool = [
        {"questionId": f"q{index:02d}", "riskClass": "low", "catalogDomain": "physics"}
        for index in range(1, 13)
    ]
    manifest = generate_g12_calibration_manifest(
        pool=pool,
        policy={
            "policyId": payload["policyId"],
            "version": payload["version"],
            "contentHash": payload["approval"]["contentHash"],
        },
        seed="seed-auto-select-g12",
        generated_at="2026-09-02T00:00:00+08:00",
    )
    recorded = g12_store.record_g12_calibration_manifest(
        team_id, manifest.to_dict(), recorded_by="operator-1"
    )
    assert recorded["status"] == "recorded"
    judgements = _agreed_judgements(list(manifest.questionIds))
    return g12_store.record_g12_judgements(
        team_id,
        {"manifestId": manifest.manifestId, "judgements": judgements},
        recorded_by="operator-1",
    )


# ---------------------------------------------------------------------------
# A: candidateSelection contract + bounded deterministic selection


def test_candidate_selection_contract_defaults_floor_and_rules() -> None:
    # Absent -> frozen default (keeps existing documents valid).
    policy = AutoAdvancePolicyV2.from_dict(_policy_payload(), stage="activation")
    assert policy.candidateSelection == {
        "maxSelected": CANDIDATE_SELECTION_DEFAULT_MAX,
        "selectionRule": CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
    }
    # Explicit values pass through.
    policy = AutoAdvancePolicyV2.from_dict(
        _policy_payload(candidate_selection={"maxSelected": 5}),
        stage="activation",
    )
    assert policy.candidateSelection["maxSelected"] == 5
    # Floor: below 2 breaks the review comparable-pair gate -> rejected.
    from core.research.workflow.contracts.automation_policy import (
        AutomationPolicyValidationError,
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(
            _policy_payload(candidate_selection={"maxSelected": 1}),
            stage="activation",
        )
    assert any(
        item["field"] == "candidateSelection.maxSelected"
        for item in excinfo.value.errors
    )
    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(
            _policy_payload(
                candidate_selection={
                    "maxSelected": 3,
                    "selectionRule": "editorial_pick",
                }
            ),
            stage="activation",
        )
    assert any(
        item["field"] == "candidateSelection.selectionRule"
        for item in excinfo.value.errors
    )


def test_candidate_selection_truncates_to_max_selected_in_digest_order(
    g12_env,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = _seed_team()
    _patch_approved_question(
        monkeypatch,
        ["hyp-a", "hyp-b", "hyp-c", "hyp-d", "hyp-e", "hyp-f"],
    )
    _stub_review_meeting_dispatch(monkeypatch)
    payload = _policy_payload(candidate_selection={"maxSelected": 2})
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")

    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-e", "hyp-a", "hyp-f", "hyp-b", "hyp-c", "hyp-d"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "executed", record
    detail = record["detail"]
    # Digest proposal order, capped at the policy bound: first two kept.
    assert detail["candidateIds"] == ["hyp-e", "hyp-a"]
    assert detail["selectionRule"] == CANDIDATE_SELECTION_RULE_DIGEST_ORDER
    assert detail["maxSelected"] == 2
    assert detail["totalCandidates"] == 6
    assert detail["truncated"] is True
    assert "proposedCandidates" in detail["selectionSource"]
    stored = selections.list_hypothesis_selections(team_id)["selections"]
    # record_selection preserves the submitted (proposal) order.
    assert [item["selectedCandidateIds"] for item in stored] == [
        ["hyp-e", "hyp-a"]
    ]
    # Exactly one review fan-out, not six.
    assert len(stored) == 1
    audits = executor.list_activation_audits(team_id)["audits"]
    assert audits[-1]["detail"]["truncated"] is True


def test_candidate_selection_without_policy_field_uses_default_two(
    g12_env,
    passing_calibration_verdict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = _seed_team()
    _patch_approved_question(
        monkeypatch, ["hyp-a", "hyp-b", "hyp-c", "hyp-d"]
    )
    _stub_review_meeting_dispatch(monkeypatch)
    payload = _policy_payload()
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    assert "candidateSelection" not in payload

    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-d", "hyp-c", "hyp-b", "hyp-a"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
        calibration_verdict=passing_calibration_verdict,
    )

    assert record["decision"] == "executed", record
    assert record["detail"]["candidateIds"] == ["hyp-d", "hyp-c"]
    assert record["detail"]["maxSelected"] == CANDIDATE_SELECTION_DEFAULT_MAX
    assert record["detail"]["truncated"] is True


# ---------------------------------------------------------------------------
# B: G12 store — fail-closed without records, judged by records


def test_g12_store_fail_closed_without_records(g12_env) -> None:
    team_id = _seed_team()
    payload = _policy_payload(declared_max_false_auto_approve=0.35)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")

    assert g12_store.load_g12_calibration_bundle(team_id, policy=policy) is None
    verdict = g12_store.g12_calibration_gate_verdict_for_team(team_id, policy=policy)
    assert verdict["passed"] is False
    assert verdict["reasonCode"] == "calibration_evidence_unavailable"

    default_verdict = executor.default_calibration_gate_verdict(
        policy, team_id=team_id
    )
    assert default_verdict["passed"] is False
    assert default_verdict["reasonCode"] == "calibration_evidence_unavailable"

    # Full ladder without injected evidence: record-only skip, no execution.
    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-a", "hyp-b"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
        policy=policy,
        payload=payload,
    )
    assert record["decision"] == "skipped"
    assert record["reasonCode"] == "ladder_calibrationGate"


def test_g12_store_records_evidence_and_gate_passes(
    g12_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _seed_team()
    payload = _policy_payload(declared_max_false_auto_approve=0.35)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")

    projection = _record_passing_g12_evidence(team_id, payload, policy)
    assert projection["recordedCount"] == 12
    assert projection["bundleStatus"] == "complete"
    assert projection["pending"] == []

    verdict = g12_store.g12_calibration_gate_verdict_for_team(
        team_id, policy=policy
    )
    assert verdict["passed"] is True, verdict
    # The executor's default read now finds the evidence (no injection).
    assert (
        executor.default_calibration_gate_verdict(policy, team_id=team_id)[
            "passed"
        ]
        is True
    )

    # Other (empty) teams stay fail-closed: evidence is team-scoped.
    other_team = _seed_team()
    assert (
        g12_store.g12_calibration_gate_verdict_for_team(
            other_team, policy=policy
        )["passed"]
        is False
    )


def test_g12_store_full_ladder_executes_with_store_backed_verdict(
    g12_env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = _seed_team()
    payload = _policy_payload(declared_max_false_auto_approve=0.35)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    _record_passing_g12_evidence(team_id, payload, policy)

    _patch_approved_question(monkeypatch, ["hyp-a", "hyp-b"])
    _stub_review_meeting_dispatch(monkeypatch)
    policy_file = tmp_path / "operator-config" / "auto-advance-policy.active.json"
    policy_file.parent.mkdir(parents=True, exist_ok=True)
    policy_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = executor.attempt_capability(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=_QUESTION_ID,
        candidate_ids=["hyp-a", "hyp-b"],
        selection_scope=chain._question_scope_envelope(team_id, _QUESTION_ID),
    )
    assert record["decision"] == "executed", record
    calibration_rung = next(
        item
        for item in record["ladder"]
        if item["gateId"] == "calibrationGate"
    )
    assert calibration_rung["passed"] is True


def test_g12_store_idempotent_reuse_and_conflict_rejection(g12_env) -> None:
    team_id = _seed_team()
    payload = _policy_payload(declared_max_false_auto_approve=0.35)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    pool = [
        {"questionId": f"q{index:02d}", "riskClass": "low", "catalogDomain": "physics"}
        for index in range(1, 4)
    ]
    manifest = generate_g12_calibration_manifest(
        pool=pool,
        policy={
            "policyId": payload["policyId"],
            "version": payload["version"],
            "contentHash": payload["approval"]["contentHash"],
        },
        seed="seed-idempotent",
        generated_at="2026-09-02T00:00:00+08:00",
    )
    first = g12_store.record_g12_calibration_manifest(
        team_id, manifest.to_dict(), recorded_by="operator-1"
    )
    assert first["status"] == "recorded"
    replay = g12_store.record_g12_calibration_manifest(
        team_id, manifest.to_dict(), recorded_by="operator-2"
    )
    assert replay["status"] == "reused"

    judgement = _agreed_judgements(list(manifest.questionIds))[0]
    args = {"manifestId": manifest.manifestId, "judgements": [judgement]}
    recorded = g12_store.record_g12_judgements(
        team_id, args, recorded_by="operator-1"
    )
    assert recorded["status"] == "recorded"
    assert recorded["recordedCount"] == 1
    reused = g12_store.record_g12_judgements(
        team_id, args, recorded_by="operator-1"
    )
    assert reused["status"] == "reused"
    assert reused["skippedDuplicateCount"] == 1

    conflict = dict(judgement)
    conflict["humanDecision"] = (
        "approve" if judgement["humanDecision"] == "escalate" else "escalate"
    )
    with pytest.raises(g12_store.G12CalibrationStoreError) as excinfo:
        g12_store.record_g12_judgements(
            team_id,
            {"manifestId": manifest.manifestId, "judgements": [conflict]},
            recorded_by="operator-1",
        )
    assert excinfo.value.code == "judgement_conflict"


# ---------------------------------------------------------------------------
# B: concurrency elevation — 3-4 need completed G12 evidence


def test_real_concurrency_bounds_at_contract_level() -> None:
    assert validate_real_concurrency(2, above_default_allowed=False) == 2
    with pytest.raises(RealBatchError):
        validate_real_concurrency(3, above_default_allowed=False)
    with pytest.raises(RealBatchError):
        validate_real_concurrency(4, above_default_allowed=False)
    assert validate_real_concurrency(3, above_default_allowed=True) == 3
    assert validate_real_concurrency(4, above_default_allowed=True) == 4
    with pytest.raises(RealBatchError):
        validate_real_concurrency(5, above_default_allowed=True)


def test_concurrency_elevation_requires_completed_g12_evidence(
    g12_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _seed_team()
    # Plan restriction unchanged: only the real-125 plan may elevate.
    assert real_batch._concurrency_elevation_allowed(team_id, "G12") is False
    # No evidence, no policy configured -> fail-closed even for real-125.
    assert real_batch._concurrency_elevation_allowed(team_id, "G125") is False

    payload = _policy_payload(declared_max_false_auto_approve=0.35)
    policy = AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    _record_passing_g12_evidence(team_id, payload, policy)
    # Evidence exists but is bound to the recorded policy; with no loadable
    # policy document the frozen defaults still reject a small pilot.
    monkeypatch.delenv("VIBELUTION_AUTO_ADVANCE_POLICY_PATH", raising=False)
    executor._DOCUMENT_CACHE.clear()
    from config import paths as config_paths

    config_paths._AUTO_ADVANCE_POLICY_PATH_CACHE.clear()
    assert real_batch._concurrency_elevation_allowed(team_id, "G125") is False

    # With the matching active policy document loadable (config-first
    # resolution: the config home file), the same evidence passes 3-4.
    policy_file = tmp_path / "operator-config" / "auto-advance-policy.active.json"
    policy_file.parent.mkdir(parents=True, exist_ok=True)
    policy_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    executor._DOCUMENT_CACHE.clear()
    assert real_batch._concurrency_elevation_allowed(team_id, "G125") is True
    # Validated against the frozen hard cap: 4 passes, 5 does not.
    assert validate_real_concurrency(4, above_default_allowed=True) == 4
