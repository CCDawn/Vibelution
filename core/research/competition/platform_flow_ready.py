"""DEV-only PlatformFlowReady report for Challenge Cup platform development.

This report never starts real research: no network, Qwen, DANDI download, GPU
benchmark or 125/125 formal submission. READY means the control flow can be
exercised with fixtures. It is not competition completion.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.competition.catalog_execution import (
    CatalogExecutionState,
    dev_plan,
    run_pending_batch,
)
from core.research.competition.resources import (
    CATALOG_QUESTION_COUNT,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_science_question_catalog,
)
from core.research.competition.result_set import CatalogScope, QuestionResult
from core.research.competition.source_boundary import (
    evaluate_clean_clone,
    evaluate_source_integrity,
)
from core.research.experiment_adapters import (
    ControlledLocator,
    ExperimentContract,
    ExperimentDispatcher,
    ExperimentOutcome,
    challenge_cup_dispatcher,
)
from core.research.workflow.contracts import (
    MIN_CANDIDATES,
    ClaimLedgerEntry,
    ContractValidationError,
    MeetingDigest,
    PersonalMemoryCandidate,
    ResearchScopeEnvelope,
    TemplateAddendum,
    TemplateBaseline,
    scope_hash_for,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.research.workflow.contracts.multimodal_validation import (
    CitationLocator,
    ClaimVerdict,
    Modality,
    MultimodalValidationReport,
    Verdict,
)

PROGRAM_CONTRACT_VERSION = "2.2.0"
CATALOG_POLICY_VERSION = "1.2.0"
REPORT_KIND = "ChallengeCupPlatformDevelopmentReadinessReport"
GPU_ADAPTER = "gpu_operator_benchmark"
NEURAL_ADAPTER = "neural_spike_coding"
CONTROL_FLOW_TEST_FILES: tuple[str, ...] = (
    "tests/test_research_workflow_hypothesis_rounds.py",
    "tests/test_research_workflow_research_templates.py",
    "tests/test_research_claim_ledger.py",
    "tests/test_research_personal_memory_scope.py",
    "tests/test_challenge_cup_role_capabilities.py",
    "tests/test_platform_flow_readiness.py",
)

GPU_ENVELOPE = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": "SCI-091",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-dev-platform",
    "mode": "dev",
    "scopeHash": "a" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'a' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'a' * 64}",
    "cacheKey": f"scope:{'a' * 64}:main:agent-dev-platform",
}
NEURAL_ENVELOPE = {
    **GPU_ENVELOPE,
    "theme": "cc-neural-information-001",
    "campaign": "cc-campaign-neural-spike-001",
    "question": "SCI-096",
    "scopeHash": "b" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'b' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'b' * 64}",
    "cacheKey": f"scope:{'b' * 64}:main:agent-dev-platform",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _gate(gate_id: str, status: str, detail: str) -> dict[str, str]:
    return {"gateId": gate_id, "status": status, "detail": detail}


def _scope(payload: dict[str, str]) -> ResearchScopeEnvelope:
    return ResearchScopeEnvelope.from_dict(payload)


def _contract(*, plan_id: str, method: str, question: str, run_mode: str = "dev_fixture", extra: dict[str, Any] | None = None) -> ExperimentContract:
    config = {"runMode": run_mode, "dataset": "synthetic"}
    if extra:
        config.update(extra)
    return ExperimentContract.from_payload(
        {
            "schemaVersion": 2,
            "planId": plan_id,
            "teamId": "dev-platform",
            "experimentMethod": method,
            "researchQuestion": question,
            "methodConfig": config,
            "metricContract": {
                "primaryMetric": "fixture_score",
                "metrics": [{"name": "fixture_score"}],
            },
        }
    )


def gate_program_hash() -> dict[str, str]:
    try:
        program = load_competition_program_core()
        policy = load_full_catalog_execution_core()
        catalog = load_science_question_catalog()
    except Exception as exc:
        return _gate("program_hash", "FAIL", str(exc))
    questions = catalog.get("questions")
    if program.get("contractVersion") != PROGRAM_CONTRACT_VERSION:
        return _gate("program_hash", "FAIL", "program contract version drifted")
    if policy.get("version") != CATALOG_POLICY_VERSION:
        return _gate("program_hash", "FAIL", "catalog policy version drifted")
    if not isinstance(questions, list) or len(questions) != CATALOG_QUESTION_COUNT:
        return _gate("program_hash", "FAIL", "catalog is not 125 questions")
    return _gate("program_hash", "PASS", "frozen program, policy and 125-question catalog match")


def gate_r0(repo: Path, *, require_clean: bool = True) -> dict[str, str]:
    report = evaluate_source_integrity(repo, require_clean=require_clean)
    if report["source_integrity"] != "PASS":
        return _gate("r0_source_integrity", "FAIL", "; ".join(report["failures"])[:500])
    gate = _gate(
        "r0_source_integrity",
        "PASS",
        f"source_integrity=PASS entries={report['entryCount']} require_clean={require_clean}",
    )
    gate["sourceCommit"] = str(report["sourceCommit"])
    return gate


def gate_r1(
    repo: Path,
    dest: Path,
    *,
    require_clean: bool = True,
    run_pytest: bool = True,
) -> dict[str, str]:
    if not run_pytest:
        return _gate(
            "r1_clean_clone",
            "BLOCKED",
            "R1 pytest was skipped; READY is not allowed",
        )
    report = evaluate_clean_clone(
        repo,
        dest,
        require_clean=require_clean,
        run_pytest=True,
        python=sys.executable,
    )
    if report["clean_clone_reproduction"] != "PASS":
        return _gate(
            "r1_clean_clone",
            "FAIL",
            "; ".join(report["failures"])[:500],
        )
    return _gate(
        "r1_clean_clone",
        "PASS",
        "clean_clone_reproduction=PASS including R1 pytest",
    )


def gate_adapters() -> dict[str, str]:
    dispatcher = challenge_cup_dispatcher()
    gpu = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(
            plan_id="plan-gpu",
            method="computational_kernel_benchmark",
            question="SCI-091 fixture",
        ),
        locator=ControlledLocator(kind="offline", relativePath="offline/gpu-fixture"),
        adapter_id=GPU_ADAPTER,
    )
    neural = dispatcher.dispatch(
        scope=_scope(NEURAL_ENVELOPE),
        contract=_contract(
            plan_id="plan-neural",
            method="dataset_analysis_benchmark",
            question="SCI-096 fixture",
        ),
        locator=ControlledLocator(kind="offline", relativePath="offline/neural-fixture"),
        adapter_id=NEURAL_ADAPTER,
    )
    cross = dispatcher.dispatch(
        scope=_scope(NEURAL_ENVELOPE),
        contract=_contract(
            plan_id="plan-gpu",
            method="computational_kernel_benchmark",
            question="SCI-091 fixture",
        ),
        locator=ControlledLocator(kind="offline", relativePath="offline/gpu-cross"),
        adapter_id=GPU_ADAPTER,
    )
    real = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(
            plan_id="plan-gpu",
            method="computational_kernel_benchmark",
            question="SCI-091 fixture",
            run_mode="full",
        ),
        locator=ControlledLocator(kind="offline", relativePath="offline/gpu-full"),
        adapter_id=GPU_ADAPTER,
    )
    default = ExperimentDispatcher()
    if gpu.outcome is not ExperimentOutcome.COMPLETED:
        return _gate("adapters_dev_isolated", "FAIL", f"gpu fixture outcome={gpu.outcome}")
    if neural.outcome is not ExperimentOutcome.COMPLETED:
        return _gate("adapters_dev_isolated", "FAIL", f"neural fixture outcome={neural.outcome}")
    if cross.outcome is ExperimentOutcome.COMPLETED:
        return _gate("adapters_dev_isolated", "FAIL", "gpu adapter accepted neural scope")
    if real.outcome is not ExperimentOutcome.UNAVAILABLE:
        return _gate("adapters_dev_isolated", "FAIL", "full GPU run was not unavailable")
    default_ids = default.adapters()
    if GPU_ADAPTER in default_ids or NEURAL_ADAPTER in default_ids:
        return _gate("adapters_dev_isolated", "FAIL", "default dispatcher registered challenge adapters")
    return _gate(
        "adapters_dev_isolated",
        "PASS",
        "GPU and neural DEV fixtures complete, stay isolated, and refuse real runs",
    )


def gate_catalog_resume() -> dict[str, str]:
    scope = CatalogScope.from_tracked_resources()

    def execute(question_id: str) -> QuestionResult:
        return QuestionResult.create(
            scope=scope,
            question_id=question_id,
            model_receipt_locator=f"model-receipt://dev/{question_id}",
            knowledge_locator=f"knowledge://dev/{question_id}",
        )

    one = CatalogExecutionState(plan=dev_plan("dev-1"), scope=scope)
    run_pending_batch(one, execute)
    if one.outcome_summary().get("succeeded") != 1:
        return _gate("catalog_batch_resume", "FAIL", "dev-1 did not succeed")

    five = CatalogExecutionState(plan=dev_plan("dev-5"), scope=scope)
    run_pending_batch(five, execute, max_items=2)
    restored = CatalogExecutionState.from_checkpoint(five.to_checkpoint())
    run_pending_batch(restored, execute)
    summary = restored.outcome_summary()
    if summary.get("succeeded") != 5 or restored.pending_question_ids():
        return _gate("catalog_batch_resume", "FAIL", f"dev-5 resume incomplete: {summary}")
    return _gate("catalog_batch_resume", "PASS", "dev-1 and interrupted dev-5 resume succeeded")


def gate_model_receipt() -> dict[str, str]:
    scope = {
        "teamId": "dev-platform",
        "runId": "run-dev-fixture",
        "nodeRunId": "nr-dev-1",
        "nodeId": "hypothesis_design",
        "attempt": "1",
    }
    receipt = ModelInvocationReceipt.from_invocation(
        receipt_id="inv-dev-1",
        run_id="run-dev-fixture",
        node_run_id="nr-dev-1",
        scope=scope,
        provider="offline-fake",
        model="fake-model-v2",
        model_version="2.0",
        requested_model="fake-model-v2",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content="DEV_FIXTURE_PROMPT",
        response_content="DEV_FIXTURE_RESPONSE",
        started_at_ms=1000,
        finished_at_ms=1100,
        token_usage={"inputTokens": 8, "outputTokens": 4, "totalTokens": 12},
        cost={"currency": "USD", "totalCost": 0},
        metadata={"apiKey": "sk-should-redact"},
        evidence_locator={"kind": "offline", "relativePath": "offline/model-receipt"},
    )
    payload = receipt.to_dict()
    if "sk-should-redact" in str(payload):
        return _gate("model_receipt", "FAIL", "secret leaked into receipt")
    missing = ModelInvocationReceipt.from_invocation(
        receipt_id="inv-dev-unconfigured",
        run_id="run-dev-fixture",
        node_run_id="nr-dev-2",
        scope=scope,
        provider="",
        model="",
        model_version="",
        requested_model="qwen-plus",
        status=ModelInvocationStatus.NOT_CONFIGURED,
        request_content="",
        response_content="",
        started_at_ms=1000,
        finished_at_ms=1000,
        token_usage={"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
        cost={"currency": "USD", "totalCost": 0},
        metadata={},
        evidence_locator={"kind": "offline", "relativePath": "offline/model-unconfigured"},
    )
    if missing.status is not ModelInvocationStatus.NOT_CONFIGURED:
        return _gate("model_receipt", "FAIL", "missing Qwen did not stay not_configured")
    return _gate("model_receipt", "PASS", "fake receipt is bounded; missing Qwen is not_configured")


def gate_multimodal() -> dict[str, str]:
    citation = CitationLocator(
        citation_id="cite-dev-1",
        modality=Modality.TEXT,
        offset=0,
        length=8,
        source_ref="source-package:dev-fixture",
        snippet_hash="a" * 64,
    )
    report = MultimodalValidationReport(
        report_id="mm-dev-1",
        run_id="run-dev-fixture",
        node_run_id="nr-dev-1",
        scope={
            "teamId": "dev-platform",
            "runId": "run-dev-fixture",
            "nodeRunId": "nr-dev-1",
            "nodeId": "source_extraction",
        },
        input_types=(Modality.TEXT,),
        parsed=True,
        parse_error="",
        input_byte_size=32,
        input_max_bytes=1024,
        citations=(citation,),
        verdicts=(
            ClaimVerdict(
                claim_ref="claim-dev-1",
                verdict=Verdict.SUPPORTS,
                evidence_refs=("source-package:dev-fixture",),
                rationale="DEV fixture citation locates the claim.",
            ),
        ),
        failures=(),
        verdict=Verdict.SUPPORTS,
        valid=True,
        created_at_ms=1000,
    )
    if report.valid is not True:
        return _gate("multimodal", "FAIL", "fixture multimodal report is invalid")
    return _gate("multimodal", "PASS", "multimodal fixture report is auditable")


def gate_product_projection(repo: Path) -> dict[str, str]:
    panel = repo / "web" / "src" / "routes" / "teams" / "research-workflow" / "ChallengeMvpProgressPanel.tsx"
    styles = repo / "web" / "src" / "routes" / "teams" / "research-workflow" / "ChallengeMvpProgressPanel.styles.ts"
    panel_test = repo / "web" / "src" / "routes" / "teams" / "research-workflow" / "ChallengeMvpProgressPanel.test.tsx"
    inspector = repo / "web" / "src" / "routes" / "teams" / "research-workflow" / "ResearchProcessInspectorPane.tsx"
    types = repo / "web" / "src" / "api" / "types" / "challengeCup.ts"
    api = repo / "web" / "src" / "api" / "teamExperiment.ts"
    api_test = repo / "web" / "src" / "api" / "teamExperiment.test.ts"
    query_keys = repo / "web" / "src" / "api" / "queryKeys.ts"
    product_files = (panel, styles, panel_test, inspector, types, api, api_test, query_keys)
    missing = [str(path.relative_to(repo)) for path in product_files if not path.is_file()]
    if missing:
        return _gate("product_projection", "FAIL", f"missing {missing}")
    panel_text = panel.read_text(encoding="utf-8")
    inspector_text = inspector.read_text(encoding="utf-8")
    types_text = types.read_text(encoding="utf-8")
    api_text = api.read_text(encoding="utf-8")
    query_keys_text = query_keys.read_text(encoding="utf-8")
    if "competitionProgramProjection" not in panel_text or "requiredDeepExperiments" not in panel_text:
        return _gate("product_projection", "FAIL", "progress panel does not project Program v2")
    if "CompetitionProgramProjection" not in types_text:
        return _gate("product_projection", "FAIL", "challenge cup API types are missing")
    for marker in (
        "fetchChallengeCupDevControlSnapshot",
        "runChallengeCupDevReadiness",
        "runChallengeCupDevBatch",
        "ChallengeCupDevControlSnapshot",
        "/dev-controls",
    ):
        if marker not in api_text:
            return _gate("product_projection", "FAIL", f"typed DEV API is missing {marker!r}")
    for marker in (
        "ChallengeCupDevControlSnapshot",
        "ChallengeCupDevNextLegalAction",
        "ChallengeCupDevBatchProjection",
        "ChallengeCupDevReadinessProjection",
    ):
        if marker not in types_text:
            return _gate("product_projection", "FAIL", f"typed DEV projection is missing {marker!r}")
    if "useQuery" not in panel_text or "challengeCupDevControlsSnapshot" not in panel_text:
        return _gate("product_projection", "FAIL", "panel does not load the DEV snapshot through React Query")
    if "ChallengeMvpProgressPanel.styles" not in panel_text:
        return _gate("product_projection", "FAIL", "DEV panel styles are not mounted")
    if "challengeCupDevControlsSnapshot" not in query_keys_text:
        return _gate("product_projection", "FAIL", "DEV snapshot query key is missing")
    if (
        "ChallengeMvpProgressPanel" not in inspector_text
        or "<ChallengeMvpProgressPanel" not in inspector_text
    ):
        return _gate("product_projection", "FAIL", "DEV panel is not mounted in the inspector")
    for marker in (
        "nextLegalAction",
        "run_dev_1_fixture_batch",
        "run_dev_5_fixture_batch",
        "RESEARCH_AUTHORIZATION_REQUIRED",
    ):
        if marker not in panel_text:
            return _gate("product_projection", "FAIL", f"DEV nextLegalAction marker is missing {marker!r}")
    if "data-dev-controls" not in panel_text:
        return _gate("product_projection", "FAIL", "DEV controls product markers are missing")
    return _gate(
        "product_projection",
        "PASS",
        "Program v2, typed DEV API and DEV control projection are present",
    )


def _dev_scope_identity() -> tuple[dict[str, str], str]:
    identity = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-dev-platform",
        "mode": "dev",
    }
    digest = scope_hash_for(
        program=identity["program"],
        theme=identity["theme"],
        campaign=identity["campaign"],
        question=identity["question"],
        branch=identity["branch"],
        workflow=identity["workflow"],
        agent_id=identity["agentId"],
        mode=identity["mode"],
    )
    return identity, digest


def gate_control_flow_contracts(repo: Path) -> dict[str, str]:
    missing = [path for path in CONTROL_FLOW_TEST_FILES if not (repo / path).is_file()]
    if missing:
        return _gate("control_flow_contracts", "FAIL", f"missing {missing}")
    if MIN_CANDIDATES < 2:
        return _gate("control_flow_contracts", "FAIL", "hypothesis rounds allow fewer than two candidates")
    try:
        from core.web.services import agent_role_tool_profile_service as role_svc

        profile = role_svc.role_tool_profile_for_role(
            "research_knowledge_collector",
            primary_mode="research",
        )
        allowed = set(profile["allowedTools"]) if profile else set()
        if allowed != {"research_knowledge_collection_tool"}:
            return _gate("control_flow_contracts", "FAIL", "collection role is not limited to the facade tool")
        identity, digest = _dev_scope_identity()
        TemplateBaseline.from_dict(
            {
                **identity,
                "baselineId": "baseline-dev-1",
                "templateId": "template-dev",
                "version": 1,
                "parentVersion": 0,
                "status": "frozen",
                "content": {"hypothesisFormat": "claim-rationale-falsifier"},
                "scopeHash": digest,
                "approvedBy": "operator",
                "approvedAt": "2026-08-18T00:00:00Z",
                "approvalRef": "approval://dev-baseline",
                "frozenAt": "2026-08-18T00:00:00Z",
                "createdAt": "2026-08-18T00:00:00Z",
            }
        )
        try:
            TemplateAddendum.from_dict(
                {
                    "addendumId": "addendum-semantic",
                    "baselineId": "baseline-dev-1",
                    "templateId": "template-dev",
                    "version": 1,
                    "reason": "rewrite method",
                    "deltas": {"hypothesisFormat": "replacement"},
                    "semanticChange": True,
                    "appendedBy": "agent-dev-platform",
                    "appendedAt": "2026-08-18T00:00:00Z",
                    "status": "active",
                }
            )
        except ContractValidationError:
            pass
        else:
            return _gate("control_flow_contracts", "FAIL", "semantic template rewrite was accepted as addendum")
        MeetingDigest.from_dict(
            {
                "digestId": "digest-dev-1",
                "meetingRoundId": "meeting-dev-1",
                "scopeHash": digest,
                "summary": "DEV fixture meeting closed two hypothesis candidates.",
                "participantAgentIds": ["agent-dev-platform"],
                "discussionTopics": ["hypothesis_round"],
                "decisionRefs": ["decision-dev-1"],
                "closedBy": "agent-dev-platform",
                "createdAt": "2026-08-18T00:00:00Z",
            }
        )
        try:
            ClaimLedgerEntry.from_dict(
                {
                    **identity,
                    "claimId": "claim-meeting-invalid",
                    "claim": "Meeting text is not evidence.",
                    "scopeHash": digest,
                    "status": "proposed",
                    "source": "meeting",
                    "evidenceRefs": [
                        {
                            "claimEvidenceId": "evidence-1",
                            "scopeHash": digest,
                            "reviewStatus": "accepted",
                            "supportLevel": "supports",
                            "sourceId": "artifact:evidence-1",
                        }
                    ],
                    "counterEvidenceRefs": [],
                    "meetingPromotionAllowed": False,
                    "createdBy": "agent-dev-platform",
                    "createdAt": "2026-08-18T00:00:00Z",
                }
            )
        except ContractValidationError:
            pass
        else:
            return _gate("control_flow_contracts", "FAIL", "meeting-sourced claim accepted evidence refs")
        neural_hash = scope_hash_for(
            program=identity["program"],
            theme="cc-neural-information-001",
            campaign="cc-campaign-neural-spike-001",
            question="SCI-096",
            branch=identity["branch"],
            workflow=identity["workflow"],
            agent_id=identity["agentId"],
            mode=identity["mode"],
        )
        memory = PersonalMemoryCandidate.from_dict(
            {
                "memoryCandidateId": "memory-dev-1",
                "agentId": identity["agentId"],
                "theme": identity["theme"],
                "campaign": identity["campaign"],
                "scopeHash": digest,
                "targetTheme": "cc-neural-information-001",
                "targetCampaign": "cc-campaign-neural-spike-001",
                "targetScopeHash": neural_hash,
                "sourceRefs": ["meeting://digest-dev-1"],
                "memoryClass": "lesson",
                "reusePolicy": "advisory_only",
                "evidenceStatus": "reported",
                "summary": "Cross-theme memory stays advisory.",
                "needsRevalidation": True,
                "advisoryOnly": True,
                "accepted": False,
                "injected": False,
                "createdAt": "2026-08-18T00:00:00Z",
            }
        )
        if not memory.is_cross_theme() or memory.injected:
            return _gate("control_flow_contracts", "FAIL", "cross-theme memory was not advisory-only")
    except (
        AttributeError,
        ContractValidationError,
        ImportError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _gate("control_flow_contracts", "FAIL", str(exc)[:500])
    return _gate(
        "control_flow_contracts",
        "PASS",
        "role tools, frozen template, meeting digest, claim and memory contracts stay fail-closed",
    )


def overall_status(gates: list[dict[str, str]]) -> str:
    statuses = {item["status"] for item in gates}
    if "FAIL" in statuses:
        return "NOT_READY"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if statuses and statuses <= {"PASS"}:
        return "READY"
    return "NOT_READY"


def build_platform_flow_readiness_report(
    repo: Path,
    *,
    clone_dest: Path | None = None,
    require_clean: bool = True,
    run_pytest: bool = True,
    mode: str = "dev",
) -> dict[str, Any]:
    if str(mode or "").strip().lower() != "dev":
        raise ValueError(
            "ChallengeCupPlatformDevelopmentReadinessReport is DEV-only; "
            "formal modes are not authorized."
        )
    repo = repo.resolve()
    dest = clone_dest or (repo / ".runtime" / "challenge-cup-platform-flow-clone")
    gates = [
        gate_program_hash(),
        gate_r0(repo, require_clean=require_clean),
        gate_r1(repo, dest, require_clean=require_clean, run_pytest=run_pytest),
        gate_adapters(),
        gate_catalog_resume(),
        gate_control_flow_contracts(repo),
        gate_model_receipt(),
        gate_multimodal(),
        gate_product_projection(repo),
    ]
    status = overall_status(gates)
    r0_gate = next(item for item in gates if item["gateId"] == "r0_source_integrity")
    return {
        "schemaVersion": 1,
        "reportKind": REPORT_KIND,
        "status": status,
        "programContract": {
            "version": PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        "catalogPolicy": {
            "version": CATALOG_POLICY_VERSION,
            "corePolicyHash": CORE_POLICY_HASH,
        },
        "sourceCommit": str(r0_gate.get("sourceCommit") or ""),
        "mode": "dev",
        "researchAuthorizationRequired": True,
        "realCampaignAllowed": False,
        "gates": gates,
        "nextLegalAction": (
            "RESEARCH_AUTHORIZATION_REQUIRED"
            if status == "READY"
            else "repair_failed_platform_gates"
        ),
        "generatedAt": _now(),
    }
