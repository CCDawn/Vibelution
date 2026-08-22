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


def _package_inputs() -> tuple[dict, dict, list[dict]]:
    payload = _valid_payload()
    policy = payload["model_policy"]
    evidence: list[dict] = []
    for stage, receipt in payload["model_invocation_receipts"].items():
        evidence_id = f"official-{stage}"
        receipt["evidenceLocator"] = {
            "kind": "official_model_evidence",
            "evidenceId": evidence_id,
            "outputRef": f"evidence://{stage}",
            "outputSha256": "a" * 64,
        }
        evidence.append(
            {
                "schemaVersion": 2,
                "evidenceId": evidence_id,
                "questionId": payload["question_id"],
                "sourceRunId": payload["run_id"],
                "taskId": f"task-{stage}",
                "turnId": f"turn-{stage}",
                "stageId": stage,
                "modelPolicySha256": policy["policySha256"],
                "modelProvider": "dashscope",
                "modelId": "qwen3.6-plus",
                "status": "canonical_success",
                "outputSha256": "a" * 64,
                "outputRef": f"evidence://{stage}",
            }
        )
    return payload, {"questionId": payload["question_id"], "runId": payload["run_id"]}, evidence


def test_adapter_builds_canonical_package_from_complete_receipts() -> None:
    payload, binding, evidence = _package_inputs()

    package = adapt_question_result_package(
        payload,
        catalog_scope=CatalogScope.from_tracked_resources(),
        run_binding=binding,
        authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
        model_policy=payload["model_policy"],
        model_invocation_receipts=payload["model_invocation_receipts"],
        official_model_evidence=evidence,
    )

    assert package.question_id == payload["question_id"]
    assert package.run_id == payload["run_id"]
    assert package.canonical_hash == package.to_dict()["canonical_sha256"]
    assert package.idempotency_key == package.to_dict()["idempotency_key"]


def test_adapter_rejects_missing_receipt_stage() -> None:
    payload, binding, evidence = _package_inputs()
    receipts = deepcopy(payload["model_invocation_receipts"])
    del receipts["revision"]

    with pytest.raises(QuestionResultPackageAdapterError, match="revision"):
        adapt_question_result_package(
            payload,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            model_policy=payload["model_policy"],
            model_invocation_receipts=receipts,
            official_model_evidence=evidence,
        )


def test_adapter_rejects_evidence_without_policy_or_output_binding() -> None:
    payload, binding, evidence = _package_inputs()
    del evidence[0]["modelPolicySha256"]
    del evidence[0]["outputSha256"]

    with pytest.raises(QuestionResultPackageAdapterError, match="modelPolicySha256|outputSha256"):
        adapt_question_result_package(
            payload,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding=binding,
            authorized_model_policy_sha256=payload["model_policy"]["policySha256"],
            model_policy=payload["model_policy"],
            model_invocation_receipts=payload["model_invocation_receipts"],
            official_model_evidence=evidence,
        )


def _registration_package() -> tuple[dict, dict, list[dict]]:
    package, binding, evidence = _package_inputs()
    package["run_id"] = "run-sci-001"
    for stage, receipt in package["model_invocation_receipts"].items():
        receipt["runId"] = "run-sci-001"
        receipt["scope"]["runId"] = "run-sci-001"
        evidence_stage = next(item for item in evidence if item["stageId"] == stage)
        evidence_stage["sourceRunId"] = "run-sci-001"
    binding["runId"] = "run-sci-001"
    return package, binding, evidence


def test_registration_persists_canonical_package_and_rejects_tampered_replay(
    tmp_path,
    monkeypatch,
) -> None:
    _isolate_store(tmp_path, monkeypatch)
    package, _binding, evidence = _registration_package()
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
    output = _output(1)
    request = {
        "output": output,
        "citationChecks": _citation_checks(output),
        "resultPackage": package,
        "authorizedModelPolicySha256": package["model_policy"]["policySha256"],
    }

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
