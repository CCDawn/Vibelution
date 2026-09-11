"""Shadow→G12 judgement conversion: mapping, filtering, aggregation, payloads."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.contracts.policy_shadow import derive_shadow_agreement
from scripts import shadow_to_g12_judgements as tool

POLICY_ID = "cc-auto-advance-policy-002"
POLICY_VERSION = "2.1.0-approved.1"
POLICY_HASH = "FA0361A52A217541FBD546E8E221AF68F0366AC994924BD8DF763B0714548923"

TARGET = (POLICY_ID, POLICY_VERSION, POLICY_HASH)


def _policy() -> SimpleNamespace:
    return SimpleNamespace(
        policyId=POLICY_ID, version=POLICY_VERSION, declaredContentHash=POLICY_HASH
    )


def _record(
    *,
    question_id: str = "SCI-096",
    would_decide: str = "auto_close",
    outcome_class: str = "acted",
    mode: str = "platform",
    policy_version: str = POLICY_VERSION,
    policy_hash: str = POLICY_HASH,
    decision_point: str = "meeting_close",
    record_id: str = "pshadow-1",
) -> dict:
    return {
        "recordId": record_id,
        "questionId": question_id,
        "decisionPoint": decision_point,
        "wouldDecide": would_decide,
        "policyId": POLICY_ID,
        "policyVersion": policy_version,
        "policyContentHash": policy_hash,
        "policyExecutionMode": "shadow",
        "agreement": derive_shadow_agreement(would_decide, outcome_class),
        "actualOutcome": {"outcomeClass": outcome_class, "outcome": "x", "command": "y"},
        "scope": {"mode": mode, "program": "XH-202619"},
    }


def _write_store(tmp_path: Path, records: list[dict]) -> Path:
    store = tmp_path / "policy_shadow_evaluations.jsonl"
    store.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return store


def _pool_file(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "pool.json"
    path.write_text(json.dumps({"pool": entries}, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# mapping table


@pytest.mark.parametrize(
    ("would_decide", "outcome_class", "expected_auto", "expected_human"),
    (
        ("auto_close", "acted", "auto_approve", "approve"),
        ("auto_close", "escalated", "auto_approve", "escalate"),
        ("auto_close", "vetoed", "auto_approve", "escalate"),
        ("hold", "acted", "auto_escalate", "approve"),
        ("hold", "escalated", "auto_escalate", "escalate"),
    ),
)
def test_mapping_table_reproduces_the_contract_agreement(
    would_decide: str, outcome_class: str, expected_auto: str, expected_human: str
) -> None:
    """The derived pair must reproduce the agreement the contract itself stores."""

    auto = tool.map_auto_decision(would_decide)
    human = tool.map_human_decision(outcome_class)

    assert auto == expected_auto
    assert human == expected_human
    assert tool.agreement_for_mapping(auto, human) == derive_shadow_agreement(
        would_decide, outcome_class
    )


def test_mapping_rejects_a_non_comparable_outcome_class() -> None:
    with pytest.raises(ValueError):
        tool.map_human_decision("none")


# ---------------------------------------------------------------------------
# filtering


def test_dev_scoped_records_are_never_usable_evidence() -> None:
    usable, exclusions, _ = tool.partition_records(
        [_record(mode="dev", record_id="dev-1")], TARGET
    )

    assert usable == []
    assert exclusions == {tool.EXCLUSION_DEV_SCOPE: 1}


def test_records_from_another_policy_identity_are_excluded_and_named() -> None:
    """A pair produced under a different configuration cannot authorize this one."""

    stale = _record(
        policy_version="2.0.0-candidate.1",
        policy_hash="9A6225065A736490E3DB28788F53034B3C5974A9BF6229100562F08FB21D5F81",
    )
    usable, exclusions, by_identity = tool.partition_records([stale], TARGET)

    assert usable == []
    assert exclusions == {tool.EXCLUSION_IDENTITY: 1}
    assert list(by_identity) == ["cc-auto-advance-policy-002 v2.0.0-candidate.1 9A6225065A73…"]


def test_a_record_without_a_comparable_human_outcome_is_excluded() -> None:
    record = _record(outcome_class="none")
    usable, exclusions, _ = tool.partition_records([record], TARGET)

    assert usable == []
    assert exclusions == {tool.EXCLUSION_NO_OUTCOME: 1}


# ---------------------------------------------------------------------------
# aggregation


def test_aggregation_is_conservative_on_both_sides() -> None:
    """One hold moves the automation side; one escalation moves the human side."""

    judgements = tool.aggregate_per_question(
        [
            _record(decision_point="meeting_close", would_decide="auto_close"),
            _record(decision_point="converge_question", would_decide="hold", record_id="p2"),
        ]
    )

    assert judgements["SCI-096"]["autoDecision"] == "auto_escalate"
    assert judgements["SCI-096"]["humanDecision"] == "approve"
    assert judgements["SCI-096"]["decisionPoints"] == ["converge_question", "meeting_close"]
    assert judgements["SCI-096"]["recordIds"] == ["pshadow-1", "p2"]


def test_aggregation_reports_auto_approve_only_when_every_record_acted() -> None:
    judgements = tool.aggregate_per_question(
        [
            _record(decision_point="meeting_close", would_decide="auto_close"),
            _record(
                decision_point="converge_question",
                would_decide="auto_converge",
                outcome_class="escalated",
                record_id="p2",
            ),
        ]
    )

    assert judgements["SCI-096"]["autoDecision"] == "auto_approve"
    assert judgements["SCI-096"]["humanDecision"] == "escalate"


# ---------------------------------------------------------------------------
# payloads


def test_manifest_and_judgements_are_built_from_the_declared_pool(tmp_path: Path) -> None:
    pool = [
        {"questionId": "SCI-096", "riskClass": "low_risk_standard", "catalogDomain": "neuroscience"},
        {"questionId": "SCI-091", "riskClass": "low_risk_standard", "catalogDomain": "information_science"},
    ]
    judgements = tool.aggregate_per_question(
        [
            _record(question_id="SCI-096", would_decide="auto_close", record_id="p-a"),
            _record(
                question_id="SCI-091",
                would_decide="hold",
                outcome_class="escalated",
                record_id="p-b",
            ),
        ]
    )

    manifest, payloads, missing, undeclared = tool.build_manifest_and_judgements(
        team_id="research-team",
        pool=pool,
        policy=_policy(),
        judgements=judgements,
        seed="test-seed",
        manifest_id="g12-test",
    )

    assert missing == [] and undeclared == []
    assert manifest["manifestId"] == "g12-test"
    assert manifest["gate"] == "G12"
    assert manifest["policyId"] == POLICY_ID
    assert manifest["policyVersion"] == POLICY_VERSION
    assert manifest["policyContentHash"] == POLICY_HASH
    assert sorted(manifest["questionIds"]) == ["SCI-091", "SCI-096"]

    by_question = {item["questionId"]: item for item in payloads}
    assert by_question["SCI-096"]["autoDecision"] == "auto_approve"
    assert by_question["SCI-096"]["humanDecision"] == "approve"
    assert by_question["SCI-096"]["riskClass"] == "low_risk_standard"
    assert by_question["SCI-096"]["domain"] == "neuroscience"
    assert by_question["SCI-096"]["sampleKind"] == "g12_calibration"
    assert by_question["SCI-096"]["evidenceRef"] == "policy_shadow:p-a"
    assert by_question["SCI-091"]["autoDecision"] == "auto_escalate"
    assert by_question["SCI-091"]["humanDecision"] == "escalate"


def test_a_declared_question_without_evidence_is_dropped_and_named(tmp_path: Path) -> None:
    pool = [
        {"questionId": "SCI-096", "riskClass": "r", "catalogDomain": "d"},
        {"questionId": "SCI-091", "riskClass": "r", "catalogDomain": "d"},
    ]
    judgements = tool.aggregate_per_question([_record(question_id="SCI-096")])

    manifest, payloads, missing, undeclared = tool.build_manifest_and_judgements(
        team_id="research-team",
        pool=pool,
        policy=_policy(),
        judgements=judgements,
        seed="s",
    )

    assert missing == ["SCI-091"]
    assert undeclared == []
    assert [item["questionId"] for item in payloads] == ["SCI-096"]
    assert manifest["questionIds"] == ["SCI-096"]


def test_only_declared_questions_enter_the_manifest() -> None:
    judgements = tool.aggregate_per_question(
        [_record(question_id="SCI-096"), _record(question_id="SCI-099", record_id="p2")]
    )

    manifest, payloads, missing, undeclared = tool.build_manifest_and_judgements(
        team_id="research-team",
        pool=[{"questionId": "SCI-096", "riskClass": "r", "catalogDomain": "d"}],
        policy=_policy(),
        judgements=judgements,
        seed="s",
    )

    assert undeclared == ["SCI-099"]
    assert [item["questionId"] for item in payloads] == ["SCI-096"]
    assert manifest["questionIds"] == ["SCI-096"]


# ---------------------------------------------------------------------------
# command behaviour


def test_self_check_flags_a_record_whose_agreement_disagrees(tmp_path: Path, capsys) -> None:
    record = _record(would_decide="hold", outcome_class="acted")
    record["agreement"] = "agree"  # the contract would derive false_escalate

    code = tool.main(
        ["--team-id", "research-team", "--store", str(_write_store(tmp_path, [record])), "--self-check"]
    )

    assert code == tool.EXIT_GAPS
    assert "DISAGREES" in capsys.readouterr().out


def test_self_check_passes_on_records_the_contract_derived(tmp_path: Path, capsys) -> None:
    records = [
        _record(would_decide="auto_close", outcome_class="acted"),
        _record(would_decide="hold", outcome_class="acted", record_id="p2"),
        _record(would_decide="auto_close", outcome_class="escalated", record_id="p3"),
        _record(would_decide="hold", outcome_class="escalated", record_id="p4"),
    ]

    code = tool.main(
        ["--team-id", "research-team", "--store", str(_write_store(tmp_path, records)), "--self-check"]
    )

    assert code == tool.EXIT_OK
    assert "reproduces" in capsys.readouterr().out


def test_dry_run_reports_the_gap_when_only_stale_records_exist(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The live shape: pairs exist, but none belong to the target policy."""

    from core.web.services.team_workflow.research_runtime import automation_policy_executor

    monkeypatch.setattr(
        automation_policy_executor, "load_active_policy_from_environment", lambda: _policy()
    )

    stale = _record(
        policy_version="2.0.0-candidate.1",
        policy_hash="9A6225065A736490E3DB28788F53034B3C5974A9BF6229100562F08FB21D5F81",
    )
    pool = _pool_file(
        tmp_path,
        [{"questionId": "SCI-096", "riskClass": "low_risk_standard", "catalogDomain": "neuroscience"}],
    )

    code = tool.main(
        [
            "--team-id",
            "research-team",
            "--store",
            str(_write_store(tmp_path, [stale])),
            "--pool",
            str(pool),
        ]
    )

    output = capsys.readouterr().out
    assert code == tool.EXIT_GAPS
    assert "excluded (policy_identity_mismatch): 1" in output
    assert "from cc-auto-advance-policy-002 v2.0.0-candidate.1" in output
    assert "judged questions: 0" in output
    assert "declared but with no usable pair (dropped): ['SCI-096']" in output
    assert "dry run" in output


def test_pool_is_required_because_strata_are_never_invented(
    tmp_path: Path, capsys
) -> None:
    code = tool.main(
        ["--team-id", "research-team", "--store", str(_write_store(tmp_path, [_record()]))]
    )

    assert code == tool.EXIT_INPUT
    assert "--pool is required" in capsys.readouterr().err


def test_write_requires_an_operator_identity(tmp_path: Path, capsys) -> None:
    pool = _pool_file(
        tmp_path, [{"questionId": "SCI-096", "riskClass": "r", "catalogDomain": "d"}]
    )
    records = [_record()]

    code = tool.main(
        [
            "--team-id",
            "research-team",
            "--store",
            str(_write_store(tmp_path, records)),
            "--pool",
            str(pool),
            "--write",
        ]
    )

    assert code == tool.EXIT_INPUT
    assert "--recorded-by" in capsys.readouterr().err


def test_write_records_the_manifest_then_the_judgements(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Wiring check: the store is called with the built payloads, in order."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
        g12_calibration_store,
    )

    monkeypatch.setattr(
        automation_policy_executor, "load_active_policy_from_environment", lambda: _policy()
    )
    calls: list[tuple[str, dict]] = []

    def _record_manifest(team_id, payload, *, recorded_by):
        calls.append(("manifest", {"teamId": team_id, "recordedBy": recorded_by, **payload}))
        return {"status": "recorded", "manifestId": payload["manifestId"], "totalRequired": 1}

    def _record_judgements(team_id, payload, *, recorded_by):
        calls.append(("judgements", {"teamId": team_id, "recordedBy": recorded_by, **payload}))
        return {"status": "recorded", "recordedCount": len(payload["judgements"])}

    monkeypatch.setattr(g12_calibration_store, "record_g12_calibration_manifest", _record_manifest)
    monkeypatch.setattr(g12_calibration_store, "record_g12_judgements", _record_judgements)

    pool = _pool_file(
        tmp_path, [{"questionId": "SCI-096", "riskClass": "low_risk_standard", "catalogDomain": "neuroscience"}]
    )

    code = tool.main(
        [
            "--team-id",
            "research-team",
            "--store",
            str(_write_store(tmp_path, [_record()])),
            "--pool",
            str(pool),
            "--write",
            "--recorded-by",
            "operator",
            "--manifest-id",
            "g12-write-test",
        ]
    )

    assert code == tool.EXIT_OK
    assert [kind for kind, _ in calls] == ["manifest", "judgements"]
    manifest_call = calls[0][1]
    assert manifest_call["recordedBy"] == "operator"
    assert manifest_call["manifestId"] == "g12-write-test"
    assert manifest_call["gate"] == "G12"
    judgements_call = calls[1][1]
    assert judgements_call["manifestId"] == "g12-write-test"
    assert judgements_call["judgements"] == [
        {
            "questionId": "SCI-096",
            "sampleKind": "g12_calibration",
            "autoDecision": "auto_approve",
            "humanDecision": "approve",
            "riskClass": "low_risk_standard",
            "domain": "neuroscience",
            "recordedAt": judgements_call["judgements"][0]["recordedAt"],
            "evidenceRef": "policy_shadow:pshadow-1",
        }
    ]
    assert "write: recorded" in capsys.readouterr().out
