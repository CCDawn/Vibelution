from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.research.competition.result_set import CatalogScope
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.question_result_package_adapter import (
    QuestionResultPackageAdapterError,
    adapt_question_result_package,
)
from tests.test_challenge_question_result_package import (
    _model_policy,
    _receipt,
    _scope,
    _valid_payload,
)
from tests.test_challenge_question_runs import (
    _append_canonical_turn_output,
    _challenge_task,
    _citation_checks,
    _isolate_store,
    _output,
)


def _package_inputs() -> tuple[dict, dict, dict, list[dict]]:
    output = _output(1)
    payload = _valid_payload()
    payload["question_id"] = output["identity"]["question_id"]
    payload["run_id"] = output["run"]["run_id"]
    for field in (
        "hypotheses",
        "dimension_reviews",
        "selection",
        "research_plan",
        "feedback_iterations",
        "result_classification",
        "competition_result_view",
    ):
        payload[field] = deepcopy(output[field])
    policy = payload["model_policy"]
    output_hash = challenge_question_runs._output_sha256(output)
    evidence: list[dict] = []
    for stage, receipt in payload["model_invocation_receipts"].items():
        evidence_id = f"official-{stage}"
        task_id = f"task-{stage}"
        turn_id = f"turn-{stage}"
        session_id = f"session-{stage}"
        receipt["runId"] = payload["run_id"]
        receipt["scope"].update(
            {
                "questionId": payload["question_id"],
                "runId": payload["run_id"],
                "taskId": task_id,
                "turnId": turn_id,
            }
        )
        output_ref = challenge_question_runs._canonical_output_ref(
            session_id,
            payload["run_id"],
            task_id,
            turn_id,
        )
        receipt["evidenceLocator"] = {
            "kind": "official_model_evidence",
            "evidenceId": evidence_id,
            "outputRef": output_ref,
            "outputSha256": output_hash,
        }
        evidence.append(
            {
                "schemaVersion": 2,
                "evidenceId": evidence_id,
                "receiptId": receipt["receiptId"],
                "questionId": payload["question_id"],
                "sourceRunId": payload["run_id"],
                "sourceSessionId": session_id,
                "taskId": task_id,
                "turnId": turn_id,
                "stageId": stage,
                "modelPolicySha256": policy["policySha256"],
                "modelProvider": "dashscope",
                "modelId": "qwen3.6-plus",
                "status": "canonical_success",
                "outputSha256": output_hash,
                "outputRef": output_ref,
            }
        )
    return (
        output,
        payload,
        {"questionId": payload["question_id"], "runId": payload["run_id"]},
        evidence,
    )


def _canonical_resolver(output: dict):
    def resolve(row: dict) -> dict:
        return {
            "questionId": output["identity"]["question_id"],
            "sourceRunId": output["run"]["run_id"],
            "taskId": row["taskId"],
            "turnId": row["turnId"],
            "outputRef": row["outputRef"],
            "outputSha256": challenge_question_runs._output_sha256(output),
            "output": deepcopy(output),
        }

    return resolve


def test_adapter_builds_canonical_package_from_complete_receipts() -> None:
    output, payload, binding, evidence = _package_inputs()

    package = adapt_question_result_package(
        output,
        catalog_scope=CatalogScope.from_tracked_resources(),
        run_binding=binding,
        authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
        result_package=payload,
        model_policy=payload["model_policy"],
        model_invocation_receipts=payload["model_invocation_receipts"],
        official_model_evidence=evidence,
        canonical_turn_resolver=_canonical_resolver(output),
    )

    assert package.question_id == payload["question_id"]
    assert package.run_id == payload["run_id"]
    assert package.canonical_hash == package.to_dict()["canonical_sha256"]
    assert package.idempotency_key == package.to_dict()["idempotency_key"]


def test_adapter_rejects_missing_receipt_stage() -> None:
    output, payload, binding, evidence = _package_inputs()
    receipts = deepcopy(payload["model_invocation_receipts"])
    del receipts["revision"]

    with pytest.raises(QuestionResultPackageAdapterError, match="revision"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            model_policy=payload["model_policy"],
            model_invocation_receipts=receipts,
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )


def test_adapter_rejects_evidence_without_policy_or_output_binding() -> None:
    output, payload, binding, evidence = _package_inputs()
    del evidence[0]["modelPolicySha256"]
    del evidence[0]["outputSha256"]

    with pytest.raises(QuestionResultPackageAdapterError, match="modelPolicySha256|outputSha256"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=payload,
            model_policy=payload["model_policy"],
            model_invocation_receipts=payload["model_invocation_receipts"],
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )


@pytest.mark.parametrize("field", ["outputRef", "outputSha256"])
def test_adapter_requires_both_receipt_locator_output_bindings(field: str) -> None:
    output, payload, binding, evidence = _package_inputs()
    receipts = deepcopy(payload["model_invocation_receipts"])
    del receipts["generation"]["evidenceLocator"][field]

    with pytest.raises(QuestionResultPackageAdapterError, match=field):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=payload,
            model_policy=payload["model_policy"],
            model_invocation_receipts=receipts,
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )


def test_adapter_rejects_three_way_output_binding_mismatch() -> None:
    output, payload, binding, evidence = _package_inputs()
    receipts = deepcopy(payload["model_invocation_receipts"])
    receipts["review"]["evidenceLocator"]["outputSha256"] = "b" * 64
    next(item for item in evidence if item["stageId"] == "review")[
        "outputSha256"
    ] = "b" * 64

    with pytest.raises(QuestionResultPackageAdapterError, match="three|disagree"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=payload,
            model_policy=payload["model_policy"],
            model_invocation_receipts=receipts,
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )


def test_adapter_rejects_duplicate_stage_in_receipt_list() -> None:
    output, payload, binding, evidence = _package_inputs()
    receipts = list(deepcopy(payload["model_invocation_receipts"]).values())
    receipts.append(deepcopy(receipts[0]))

    with pytest.raises(QuestionResultPackageAdapterError, match="duplicate stage"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=payload,
            model_policy=payload["model_policy"],
            model_invocation_receipts=receipts,
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )


def test_adapter_rejects_supplied_package_identity_conflicts() -> None:
    output, payload, binding, evidence = _package_inputs()
    valid = adapt_question_result_package(
        output,
        catalog_scope=CatalogScope.from_tracked_resources(),
        run_binding=binding,
        authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
        result_package=payload,
        model_policy=payload["model_policy"],
        model_invocation_receipts=payload["model_invocation_receipts"],
        official_model_evidence=evidence,
        canonical_turn_resolver=_canonical_resolver(output),
    )

    conflicting_hash = deepcopy(payload)
    conflicting_hash["canonical_sha256"] = valid.canonical_hash
    conflicting_hash["canonicalHash"] = "f" * 64
    with pytest.raises(QuestionResultPackageAdapterError, match="canonicalHash"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=conflicting_hash,
            model_policy=payload["model_policy"],
            model_invocation_receipts=payload["model_invocation_receipts"],
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )

    nested = deepcopy(payload)
    nested["idempotencyKey"] = "wrong-idempotency-key"
    with pytest.raises(QuestionResultPackageAdapterError, match="idempotencyKey"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package={"package": nested},
            model_policy=payload["model_policy"],
            model_invocation_receipts=payload["model_invocation_receipts"],
            official_model_evidence=evidence,
            canonical_turn_resolver=_canonical_resolver(output),
        )

    with pytest.raises(QuestionResultPackageAdapterError, match="packageId"):
        adapt_question_result_package(
            output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            result_package=payload,
            model_policy=payload["model_policy"],
            model_invocation_receipts=payload["model_invocation_receipts"],
            official_model_evidence=evidence,
            request_identity={"packageId": "conflicting-package-id"},
            canonical_turn_resolver=_canonical_resolver(output),
        )


def _registration_package() -> tuple[dict, dict, list[dict]]:
    output, package, _binding, evidence = _package_inputs()
    return output, package, evidence


def _registration_request(tmp_path, monkeypatch) -> tuple[dict, dict, list[dict], dict]:
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    output, package, evidence = _registration_package()
    for row in evidence:
        _append_canonical_turn_output(
            tmp_path,
            {
                "sessionId": row["sourceSessionId"],
                "runId": row["sourceRunId"],
                "taskId": row["taskId"],
                "turn": {"turnId": row["turnId"]},
            },
            output,
        )
    evidence_path = tmp_path / "official_model_evidence" / "index.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": evidence,
                "receipts": list(package["model_invocation_receipts"].values()),
            }
        ),
        encoding="utf-8",
    )
    request = {
        "output": output,
        "citationChecks": _citation_checks(output),
        "resultPackage": package,
        "authorizedModelPolicySha256": package["model_policy"]["policySha256"],
    }
    return output, package, evidence, request


def test_registration_persists_canonical_package_and_rejects_tampered_replay(
    tmp_path,
    monkeypatch,
) -> None:
    _output_value, package, _evidence, request = _registration_request(
        tmp_path, monkeypatch
    )

    tampered_initial = deepcopy(package)
    tampered_initial["hypotheses"][0]["statement"] = "tampered before first write"
    with pytest.raises(ValueError, match="canonical output|package"):
        challenge_question_runs.register_challenge_question_output(
            "research-team",
            {**request, "resultPackage": tampered_initial},
        )
    assert not challenge_question_runs._artifact_path(
        "research-team", "SCI-001", "run-sci-001"
    ).exists()
    assert not challenge_question_runs._result_package_artifact_path(
        "research-team", "SCI-001", "run-sci-001"
    ).exists()

    first = challenge_question_runs.register_challenge_question_output(
        "research-team", request
    )
    repeated = challenge_question_runs.register_challenge_question_output(
        "research-team", request
    )

    assert first["record"]["resultPackage"]["canonicalHash"]
    assert first["record"]["resultPackage"]["idempotencyKey"]
    assert first["record"]["resultPackage"] == repeated["record"]["resultPackage"]
    locator = first["record"]["resultPackage"]["locator"]
    assert Path(locator).exists()

    tampered = deepcopy(package)
    tampered["hypotheses"][0]["statement"] = "tampered"
    with pytest.raises(ValueError, match="immutable|canonical|package"):
        challenge_question_runs.register_challenge_question_output(
            "research-team",
            {**request, "resultPackage": tampered},
        )

    persisted = json.loads(Path(locator).read_text(encoding="utf-8"))
    persisted["hypotheses"][0]["statement"] = "persisted tamper"
    Path(locator).write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid|immutable|package"):
        challenge_question_runs.register_challenge_question_output(
            "research-team", request
        )


@pytest.mark.parametrize(
    "failing_target",
    ["run-sci-001.result-package.v2.json", "index.json"],
)
def test_registration_rolls_back_partial_artifacts_on_bundle_promotion_failure(
    tmp_path,
    monkeypatch,
    failing_target: str,
) -> None:
    _output_value, _package, _evidence, request = _registration_request(
        tmp_path, monkeypatch
    )
    store_path = challenge_question_runs._store_path("research-team")
    original_store = {
        "schemaVersion": challenge_question_runs.STORE_SCHEMA_VERSION,
        "storeKind": challenge_question_runs.STORE_KIND,
        "teamId": "research-team",
        "records": [],
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }
    challenge_question_runs._write_json(store_path, original_store)
    real_replace = challenge_question_runs._replace_staged_json
    failure_injected = False

    def fail_selected_promotion(source: Path, target: Path) -> None:
        nonlocal failure_injected
        if target.name == failing_target and not failure_injected:
            failure_injected = True
            raise OSError(f"injected promotion failure: {failing_target}")
        real_replace(source, target)

    monkeypatch.setattr(
        challenge_question_runs,
        "_replace_staged_json",
        fail_selected_promotion,
    )
    with pytest.raises(OSError, match="injected promotion failure"):
        challenge_question_runs.register_challenge_question_output(
            "research-team", request
        )

    assert not challenge_question_runs._artifact_path(
        "research-team", "SCI-001", "run-sci-001"
    ).exists()
    assert not challenge_question_runs._result_package_artifact_path(
        "research-team", "SCI-001", "run-sci-001"
    ).exists()
    assert challenge_question_runs._read_json(store_path) == original_store
    assert not list(tmp_path.rglob("*.stage"))
    assert not list(tmp_path.rglob("*.backup"))


def test_task_model_evidence_persists_three_validated_receipts_and_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    project_root = tmp_path / "project-sci-096"
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    task = _challenge_task()
    output = _output()
    output["run"]["run_id"] = task["runId"]
    _append_canonical_turn_output(tmp_path, task, output)
    usage = {
        "source": "canonical_turn_outcome",
        "provider": "dashscope_main",
        "model": "qwen3.6-plus",
        "llmModelId": "dashscope_main/qwen3.6-plus",
    }
    policy = _model_policy()
    for stage in ("generation", "review", "revision"):
        receipt = _receipt(_scope(), stage=stage, policy_sha256=policy["policySha256"], run_id=task["runId"])
        receipt["scope"].update(
            {
                "questionId": task["challengeTaskContract"]["questionId"],
                "taskId": task["taskId"],
                "turnId": task["turn"]["turnId"],
            }
        )
        receipt["evidenceLocator"] = {
            "kind": "official_model_evidence",
            "outputSha256": challenge_question_runs._output_sha256(output),
            "outputRef": challenge_question_runs._canonical_output_ref(
                task["sessionId"],
                task["runId"],
                task["taskId"],
                task["turn"]["turnId"],
            ),
        }
        first = challenge_question_runs.register_challenge_task_model_evidence(
            "research-team",
            task,
            final_status="completed",
            llm_usage=usage,
            model_invocation_receipt=receipt,
            stage_id=stage,
            model_policy_sha256=policy["policySha256"],
        )
        repeated = challenge_question_runs.register_challenge_task_model_evidence(
            "research-team",
            task,
            final_status="completed",
            llm_usage=usage,
            model_invocation_receipt=receipt,
            stage_id=stage,
            model_policy_sha256=policy["policySha256"],
        )
        assert first == repeated
        assert first["schemaVersion"] == 2
        assert first["receiptId"] == receipt["receiptId"]

    store = json.loads(
        (project_root / "official_model_evidence" / "index.json").read_text(encoding="utf-8")
    )
    assert store["schemaVersion"] == 2
    assert {item["stageId"] for item in store["evidence"]} == {
        "generation",
        "review",
        "revision",
    }
    assert len(store["receipts"]) == 3
