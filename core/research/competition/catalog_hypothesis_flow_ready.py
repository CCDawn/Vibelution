"""DEV-only readiness for the catalog hypothesis flow.

This is the upper-level directory-flow gate described by the 125-question
execution protocol.  It composes existing, authoritative platform/resource
checks; it does not duplicate the platform report, start a real batch, call
Qwen, access the network, or treat a readiness snapshot as authorization.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.competition.catalog_execution import dev_plan
from core.research.competition.delivery import export_results
from core.research.competition.platform_flow_ready import (
    gate_catalog_resume,
    gate_model_receipt,
    gate_product_projection,
    gate_r0,
    gate_r1,
)
from core.research.competition.resources import (
    CATALOG_QUESTION_COUNT,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_science_question_catalog,
)
from core.research.workflow.contracts import (
    CATALOG_HYPOTHESIS_FLOW_G1_ACTION,
    CATALOG_HYPOTHESIS_FLOW_GATE_IDS,
    CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
    CatalogHypothesisFlowReadinessReport,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind

REPORT_KIND = CATALOG_HYPOTHESIS_FLOW_REPORT_KIND
REPORT_SCHEMA_VERSION = 1
DEV_ONLY_MODE = "dev"

# The current workflow definition has more than six concrete nodes/role keys.
# The protocol's six-role prerequisite is a capability grouping over those
# canonical roles.  Keeping the mapping here makes the migration explicit and
# lets a role-key drift fail closed instead of silently producing an unbound
# flow.  BUG-10's contract test locks the concrete definition names separately.
CATALOG_HYPOTHESIS_ROLE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("coordination", ("research_owner", "challenge_cup_coordinator")),
    (
        "knowledge_collection",
        ("source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"),
    ),
    ("hypothesis_and_protocol", ("experiment_planner",)),
    ("experiment_evidence", ("experiment_ledger", "formal_runner")),
    ("iteration_governance", ("iteration_planner", "iteration_versioning")),
    ("delivery", ("package_builder",)),
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _gate(gate_id: str, status: str, detail: str) -> dict[str, str]:
    return {
        "gateId": gate_id,
        "status": str(status or "").upper(),
        "detail": str(detail or "").strip(),
    }


def _platform_gate_status(
    platform_report: Mapping[str, Any] | None,
    gate_id: str,
) -> dict[str, Any] | None:
    if not isinstance(platform_report, Mapping):
        return None
    for item in platform_report.get("gates") or ():
        if isinstance(item, Mapping) and str(item.get("gateId") or "") == gate_id:
            return dict(item)
    return None


def gate_six_role_prerequisites() -> dict[str, str]:
    """Check the canonical six capability groups against the fixed definition."""

    try:
        definition = build_challenge_cup_workflow_definition()
        role_keys = {
            str(node.primaryRoleKey or "").strip()
            for node in definition.nodes
            if node.actorKind is ActorKind.AGENT or str(node.primaryRoleKey or "").strip()
        }
        missing = [
            group_id
            for group_id, aliases in CATALOG_HYPOTHESIS_ROLE_GROUPS
            if not any(alias in role_keys for alias in aliases)
        ]
        if missing:
            return _gate(
                "six_role_prerequisites",
                "FAIL",
                "canonical workflow definition is missing role groups: " + ", ".join(missing),
            )
        if len(CATALOG_HYPOTHESIS_ROLE_GROUPS) != 6:
            return _gate(
                "six_role_prerequisites",
                "FAIL",
                "catalog hypothesis flow requires exactly six capability groups",
            )
        return _gate(
            "six_role_prerequisites",
            "PASS",
            "six capability groups resolve to canonical workflow primaryRoleKey values",
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _gate("six_role_prerequisites", "FAIL", f"role contract unavailable: {exc}")


def gate_schema_batch_export() -> dict[str, str]:
    """Reuse frozen resources, DEV batch resume, and formal export fail-closed checks."""

    try:
        program = load_competition_program_core()
        policy = load_full_catalog_execution_core()
        catalog = load_science_question_catalog()
        questions = catalog.get("questions")
        if not isinstance(questions, list) or len(questions) != CATALOG_QUESTION_COUNT:
            return _gate("schema_batch_export", "FAIL", "frozen catalog does not contain 125 questions")
        if program.get("contractVersion") != "2.2.0" or policy.get("version") != "1.2.0":
            return _gate("schema_batch_export", "FAIL", "frozen program/policy version drifted")
        if dev_plan("dev-1").question_count != 1 or dev_plan("dev-5").question_count != 5:
            return _gate("schema_batch_export", "FAIL", "DEV batch plans no longer match the bounded fixture contract")
        resume = gate_catalog_resume()
        if resume.get("status") != "PASS":
            return _gate("schema_batch_export", "FAIL", str(resume.get("detail") or "DEV batch resume failed"))
        formal = export_results(
            {"approvedQuestionCount": 0, "r0": "FAIL", "r1": "FAIL"},
            mode="formal",
        )
        preview = export_results({"approvedQuestionCount": 0}, mode="preview")
        if formal.get("status") != "refused" or not formal.get("blockers"):
            return _gate("schema_batch_export", "FAIL", "formal export did not remain fail-closed")
        if preview.get("status") != "preview" or preview.get("final") is not False:
            return _gate("schema_batch_export", "FAIL", "DEV preview export contract drifted")
    except Exception as exc:  # noqa: BLE001 - resource validators intentionally fail closed
        return _gate("schema_batch_export", "FAIL", str(exc)[:500])
    return _gate(
        "schema_batch_export",
        "PASS",
        "question schema, bounded DEV batches, and preview/formal export boundaries are valid",
    )


def gate_question_model_receipts() -> dict[str, str]:
    """Require a question-scoped, round-trippable model receipt fixture."""

    try:
        base = gate_model_receipt()
        if base.get("status") != "PASS":
            return _gate("question_model_receipts", "FAIL", str(base.get("detail") or "model receipt gate failed"))
        receipt = ModelInvocationReceipt.from_invocation(
            receipt_id="catalog-hypothesis-invocation-1",
            run_id="catalog-hypothesis-run-1",
            node_run_id="catalog-hypothesis-node-1",
            scope={
                "teamId": "dev-platform",
                "runId": "catalog-hypothesis-run-1",
                "questionId": "SCI-001",
                "nodeId": "hypothesis_design",
                "stageId": "experiment_design",
            },
            provider="offline-fake",
            model="qwen-dev-fixture",
            model_version="fixture-v1",
            requested_model="qwen-dev-fixture",
            status=ModelInvocationStatus.SUCCEEDED,
            request_content="CATALOG_HYPOTHESIS_DEV_PROMPT",
            response_content="CATALOG_HYPOTHESIS_DEV_RESPONSE",
            started_at_ms=1000,
            finished_at_ms=1100,
            token_usage={"inputTokens": 4, "outputTokens": 8, "totalTokens": 12},
            evidence_locator={"kind": "offline", "relativePath": "offline/catalog-hypothesis-receipt"},
        )
        restored = ModelInvocationReceipt.from_dict(receipt.to_dict())
        if restored.scope.get("questionId") != "SCI-001":
            return _gate("question_model_receipts", "FAIL", "model receipt has no question-level reference")
        if restored.status is not ModelInvocationStatus.SUCCEEDED:
            return _gate("question_model_receipts", "FAIL", "question-level model receipt is not succeeded")
    except Exception as exc:  # noqa: BLE001 - receipt gate fails closed on fixture drift
        return _gate("question_model_receipts", "FAIL", str(exc)[:500])
    return _gate(
        "question_model_receipts",
        "PASS",
        "every direct DEV model fixture is represented by a question-scoped auditable receipt",
    )


def gate_api_frontend_r0_r1(
    repo: Path,
    *,
    clone_dest: Path | None = None,
    require_clean: bool = True,
    run_pytest: bool = True,
    platform_report: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Compose the existing R0/R1/product projection gates without reimplementing them."""

    if isinstance(platform_report, Mapping):
        if (
            str(platform_report.get("status") or "") != "READY"
            or str(platform_report.get("mode") or "").strip().lower() != DEV_ONLY_MODE
            or platform_report.get("realCampaignAllowed") is not False
        ):
            return _gate(
                "api_frontend_r0_r1",
                "FAIL",
                "platform readiness report is not a valid DEV-only READY report",
            )
        selected = {
            key: _platform_gate_status(platform_report, key)
            for key in ("r0_source_integrity", "r1_clean_clone", "product_projection")
        }
        missing = [key for key, item in selected.items() if item is None]
        if missing:
            return _gate("api_frontend_r0_r1", "FAIL", f"platform report is missing gates: {missing}")
        failures = [
            f"{key}={item.get('status')} {item.get('detail') or ''}".strip()
            for key, item in selected.items()
            if str(item.get("status") or "") != "PASS"
        ]
        if failures:
            return _gate("api_frontend_r0_r1", "FAIL", "; ".join(failures)[:500])
        return _gate(
            "api_frontend_r0_r1",
            "PASS",
            "typed DEV API, product projection, R0, and R1 are already PASS in the platform report",
        )

    try:
        r0 = gate_r0(repo, require_clean=require_clean)
        if r0.get("status") != "PASS":
            return _gate("api_frontend_r0_r1", "FAIL", str(r0.get("detail") or "R0 failed"))
        r1 = gate_r1(
            repo,
            clone_dest or (repo / ".runtime" / "catalog-hypothesis-r1-clone"),
            require_clean=require_clean,
            run_pytest=run_pytest,
        )
        if r1.get("status") != "PASS":
            return _gate("api_frontend_r0_r1", "FAIL", str(r1.get("detail") or "R1 failed"))
        product = gate_product_projection(repo, run_frontend_checks=run_pytest)
        if product.get("status") != "PASS":
            return _gate("api_frontend_r0_r1", "FAIL", str(product.get("detail") or "product projection failed"))
    except Exception as exc:  # noqa: BLE001 - composed readiness gates fail closed
        return _gate("api_frontend_r0_r1", "FAIL", str(exc)[:500])
    return _gate(
        "api_frontend_r0_r1",
        "PASS",
        "typed DEV API/product projection and clean source-boundary R0/R1 checks passed",
    )


def gate_human_authorization(
    *,
    human_authorized: bool | None = None,
    platform_report: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Check the explicit human-gate wiring without granting real execution.

    ``None`` means this DEV-only report is auditing the presence of the
    authorization boundary (the default platform report is required to be
    ``researchAuthorizationRequired=true``).  Callers that have a concrete
    operator decision pass ``False``/``True``; ``False`` remains fail-closed.
    This distinction keeps a readiness report from becoming a formal
    ``CatalogRunAuthorization`` record.
    """

    if human_authorized is False:
        return _gate(
            "human_authorization",
            "FAIL",
            "operator has not approved the bounded DEV G1 pilot",
        )
    if isinstance(platform_report, Mapping) and platform_report.get("researchAuthorizationRequired") is not True:
        return _gate(
            "human_authorization",
            "FAIL",
            "platform report did not preserve the explicit human authorization boundary",
        )
    if human_authorized is True:
        detail = "bounded DEV G1 pilot authorization is explicit; real campaign authorization remains required"
    else:
        detail = "explicit human authorization boundary is wired; readiness is not a real campaign authorization"
    return _gate("human_authorization", "PASS", detail)


def build_catalog_hypothesis_flow_readiness_report(
    repo: Path,
    *,
    clone_dest: Path | None = None,
    require_clean: bool = True,
    run_pytest: bool = True,
    mode: str = DEV_ONLY_MODE,
    platform_report: Mapping[str, Any] | None = None,
    human_authorized: bool | None = None,
) -> dict[str, Any]:
    """Build the five-gate DEV report; never starts real research."""

    if str(mode or "").strip().lower() != DEV_ONLY_MODE:
        raise ValueError(
            "CatalogHypothesisFlowReadinessReport is DEV-only; formal modes are not authorized."
        )
    root = Path(repo).resolve()
    gates = [
        gate_six_role_prerequisites(),
        gate_schema_batch_export(),
        gate_question_model_receipts(),
        gate_api_frontend_r0_r1(
            root,
            clone_dest=clone_dest,
            require_clean=require_clean,
            run_pytest=run_pytest,
            platform_report=platform_report,
        ),
        gate_human_authorization(
            human_authorized=human_authorized,
            platform_report=platform_report,
        ),
    ]
    report = CatalogHypothesisFlowReadinessReport.build(gates=gates, generated_at=_now())
    payload = report.to_dict()
    # These evidence pointers are additive to the contract and intentionally
    # non-authorizing.  They make the report's role as an upper-level audit
    # supplement visible to dev-controls consumers.
    payload["programContract"] = {
        "coreBehaviorHash": CORE_BEHAVIOR_HASH,
    }
    payload["catalogPolicy"] = {
        "corePolicyHash": CORE_POLICY_HASH,
    }
    payload["source"] = "CatalogHypothesisFlowReadinessReport"
    if platform_report is not None:
        payload["platformReadiness"] = {
            "reportKind": str(platform_report.get("reportKind") or ""),
            "status": str(platform_report.get("status") or ""),
            "sourceCommit": str(platform_report.get("sourceCommit") or ""),
        }
    # Keep the import-level action visible for static contract checks and avoid
    # accidental changes to the all-pass successor while this report remains a
    # DEV-only supplement.
    if report.status == "READY" and report.nextLegalAction != CATALOG_HYPOTHESIS_FLOW_G1_ACTION:
        raise RuntimeError("catalog hypothesis readiness all-pass action drifted")
    if len(report.gates) != len(CATALOG_HYPOTHESIS_FLOW_GATE_IDS):
        raise RuntimeError("catalog hypothesis readiness gate count drifted")
    return payload


# Keep the shorter ``FlowReady`` spelling available for callers following the
# existing ``platform_flow_ready.py`` module name.
build_catalog_hypothesis_flow_ready_report = build_catalog_hypothesis_flow_readiness_report


__all__ = [
    "CATALOG_HYPOTHESIS_ROLE_GROUPS",
    "DEV_ONLY_MODE",
    "REPORT_KIND",
    "REPORT_SCHEMA_VERSION",
    "build_catalog_hypothesis_flow_readiness_report",
    "build_catalog_hypothesis_flow_ready_report",
    "gate_api_frontend_r0_r1",
    "gate_human_authorization",
    "gate_question_model_receipts",
    "gate_schema_batch_export",
    "gate_six_role_prerequisites",
]
