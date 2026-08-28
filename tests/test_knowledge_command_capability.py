"""Knowledge command facade + workflow-owned capability policy (plan Task 4).

Covers:
- ensure/inspect_knowledge_collection commands: team-authorized (never
  operator-only), idempotent (same request replays the same invocation and
  never a second child run), envelope/roots mapped into fingerprints;
- the capability policy matrix: auto_allowed / human_gate / operator_only /
  blocked, plus expiry, budget, run/node binding and root whitelist all
  failing closed;
- the unattended path: every child-run stage action is authorized through
  the capability entry without ever consulting tool approvals, while the
  ad-hoc Agent tool path stays globally fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_NODE_IDS,
)

from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
    KnowledgeCommandError,
    TeamScopeMismatchError,
)
from core.web.services.team_workflow.research_runtime.knowledge_capability import (
    ARCHIVE_RUN,
    AUTO_ALLOWED_ACTIONS,
    BLOCKED_ACTIONS,
    CHANGE_PERMISSIONS,
    CONTROLLED_SEARCH,
    KNOWLEDGE_HANDOFF,
    READ_MANAGED_ROOT,
    RESOLVE_EVIDENCE_TYPE,
    RETRY_WITHIN_BUDGET,
    RUN_EXECUTABLE,
    STAGE_DATA_RECORD,
    CapabilityDecision,
    CapabilityPolicyClass,
    KnowledgeCapability,
    KnowledgeCapabilityBudget,
    StageActionContext,
    authorize_stage_action,
    issue_knowledge_capability,
    record_stage_action,
)

from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_knowledge_sideflow_run import (
    _invoke,
    _seed_parent,
    _walk_child_to_handoff,
)

from tests._support.graph_helpers import GraphHarness


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    register_or_resolve(build_challenge_cup_workflow_definition())
    # These tests exercise the ensure/inspect command surface itself, which is
    # rollout-gated server-side; run them with the sideflow fully on.
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            research=SimpleNamespace(
                knowledge_sideflow=SimpleNamespace(mode="on")
            )
        ),
    )
    yield
    reset_registry_for_tests()


def _main_version_id() -> str:
    return register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId


def _seeded_harness(tmp_path: Path) -> GraphHarness:
    harness = GraphHarness(tmp_path)
    harness.commands.seed_run(
        "run-parent",
        workflow_id="challenge-cup-research",
        workflow_version_id=_main_version_id(),
        status="running",
    )
    return harness


def _ensure_request(
    harness: GraphHarness,
    *,
    node_id: str | None = "hypothesis_design",
    payload: dict | None = None,
    idempotency_key: str = "kc:ensure:1",
    team_id: str = "research-team",
    expected_run_version: int = 1,
):
    return harness.commands.request(
        command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
        node_id=node_id,
        run_id="run-parent",
        team_id=team_id,
        expected_run_version=expected_run_version,
        idempotency_key=idempotency_key,
        payload=payload
        or {
            "questionId": "SCI-096",
            "searchEnvelope": {
                "keywords": ["evaporation", "cooling"],
                "evidenceTypes": ["dataset"],
                "timeWindow": {"from": "2024-01-01"},
            },
            "requirements": {"minSources": 3},
            "sourcePolicyVersion": "1",
            "managedSourceRootIds": ["Root-A", "root-b", "root-a"],
        },
    )


def _child_rows(harness: GraphHarness):
    return harness.commands.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT run_id FROM workflow_runs WHERE workflow_id = "
            "'challenge-cup-knowledge-sideflow' ORDER BY run_id"
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)


# --------------------------------------------------------------------------
# Command facade: ensure / inspect
# --------------------------------------------------------------------------


def test_ensure_command_creates_invocation_child_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    harness = _seeded_harness(tmp_path)
    try:
        store = harness.commands.store
        before = store.get_run("run-parent")
        receipt = harness.commands.command_service.submit(_ensure_request(harness))
        assert receipt.status == "accepted"
        # The parent runVersion never moves for knowledge flow commands.
        assert receipt.accepted_run_version == before.run_version
        result = receipt.result
        assert result["replayed"] is False
        assert result["reused"] is False
        assert result["childRunId"]
        assert result["managedSourceRootIds"] == ["root-a", "root-b"]

        invocation_id = result["invocationId"]
        child_run_id = result["childRunId"]
        assert len(_child_rows(harness)) == 1

        replay = harness.commands.command_service.submit(_ensure_request(harness))
        assert replay.result["replayed"] is True
        assert replay.result["invocationId"] == invocation_id
        assert replay.result["childRunId"] == child_run_id
        assert len(_child_rows(harness)) == 1
        assert replay.accepted_run_version == before.run_version
    finally:
        harness.close()


def test_ensure_payload_fingerprints_change_request_not_child_count(
    tmp_path: Path,
) -> None:
    harness = _seeded_harness(tmp_path)
    try:
        first = harness.commands.command_service.submit(
            _ensure_request(harness, idempotency_key="kc:ensure:a")
        )
        changed_envelope = _ensure_request(
            harness,
            payload={
                "questionId": "SCI-096",
                "searchEnvelope": {
                    "keywords": ["different"],
                    "evidenceTypes": [],
                    "timeWindow": {},
                },
                "managedSourceRootIds": ["root-a"],
            },
            idempotency_key="kc:ensure:b",
        )
        second = harness.commands.command_service.submit(changed_envelope)
        assert second.result["invocationId"] != first.result["invocationId"]
        # A different request is a different invocation: new child run.
        assert len(_child_rows(harness)) == 2
    finally:
        harness.close()


def test_inspect_command_reports_invocation_child_and_recovery(tmp_path: Path) -> None:
    harness = _seeded_harness(tmp_path)
    try:
        ensure = harness.commands.command_service.submit(_ensure_request(harness))
        invocation_id = ensure.result["invocationId"]
        inspect = harness.commands.command_service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
                node_id=None,
                run_id="run-parent",
                idempotency_key="kc:inspect:1",
                payload={"invocationId": invocation_id},
            )
        )
        result = inspect.result
        assert result["invocations"][0]["invocationId"] == invocation_id
        child = result["childRun"]
        assert child["runId"] == ensure.result["childRunId"]
        assert set(child["nodes"]) == set(KNOWLEDGE_SIDEFLOW_NODE_IDS)
        assert child["nodes"]["source_finding"]["status"] == "starting"
        assert child["nodes"]["knowledge_handoff"]["status"] == "not_started"
        assert isinstance(child["budget"], dict) and child["budget"]
        assert result["recoveryActions"] == ["none"]

        unknown = harness.commands.request(
            command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
            node_id=None,
            run_id="run-parent",
            idempotency_key="kc:inspect:2",
            payload={"invocationId": "kinv-missing"},
        )
        with pytest.raises(KnowledgeCommandError, match="kinv-missing"):
            harness.commands.command_service.submit(unknown)
    finally:
        harness.close()


def test_ensure_rejects_question_mismatch_terminal_run_and_unknown_node(
    tmp_path: Path,
) -> None:
    harness = _seeded_harness(tmp_path)
    try:
        with pytest.raises(KnowledgeCommandError) as mismatch:
            harness.commands.command_service.submit(
                _ensure_request(
                    harness,
                    payload={"questionId": "SCI-OTHER"},
                    idempotency_key="kc:ensure:mismatch",
                )
            )
        assert mismatch.value.code == "question_mismatch"

        with pytest.raises(KnowledgeCommandError) as unknown_node:
            harness.commands.command_service.submit(
                _ensure_request(
                    harness,
                    node_id="not_a_definition_node",
                    idempotency_key="kc:ensure:node",
                )
            )
        assert unknown_node.value.code == "unknown_node"

        harness.commands.seed_run(
            "run-done",
            workflow_id="challenge-cup-research",
            workflow_version_id=_main_version_id(),
            status="succeeded",
        )
        from core.research.workflow.ledger import CommandNotAllowedError

        with pytest.raises(CommandNotAllowedError):
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                    node_id="hypothesis_design",
                    run_id="run-done",
                    idempotency_key="kc:ensure:done",
                    payload={"questionId": "SCI-096"},
                )
            )
    finally:
        harness.close()


def test_command_authorization_matrix_team_vs_operator_only(tmp_path: Path) -> None:
    """ensure/inspect are team-authorized; operator-only semantics unchanged."""
    harness = _seeded_harness(tmp_path)
    try:
        # No operator context at all: knowledge flow commands are allowed for
        # the authorized team session, while cancel_run stays forbidden.
        harness.commands.command_service.submit(_ensure_request(harness))
        harness.commands.command_service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
                node_id=None,
                run_id="run-parent",
                idempotency_key="kc:inspect:no-op",
                payload={},
            )
        )
        with pytest.raises(CommandForbiddenError):
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.CANCEL_RUN,
                    node_id=None,
                    run_id="run-parent",
                    idempotency_key="kc:cancel:no-op",
                    payload={"reason": "x"},
                )
            )

        # Viewer-role operator: knowledge flow commands stay allowed;
        # high-impact commands still require privileged roles.
        from core.web.services.team_workflow.research_runtime.operator_authorization import (
            server_operator_scope,
        )

        with server_operator_scope("viewer-1", roles=("viewer",)):
            harness.commands.command_service.submit(
                _ensure_request(harness, idempotency_key="kc:ensure:viewer")
            )
            with pytest.raises(CommandForbiddenError):
                harness.commands.command_service.submit(
                    harness.commands.request(
                        command=WorkflowCommandKind.CANCEL_RUN,
                        node_id=None,
                        run_id="run-parent",
                        idempotency_key="kc:cancel:viewer",
                        payload={"reason": "x"},
                    )
                )

        # Team scope mismatch is rejected for the new commands too.
        with pytest.raises(TeamScopeMismatchError):
            harness.commands.command_service.submit(
                _ensure_request(harness, team_id="other-team")
            )
    finally:
        harness.close()


# --------------------------------------------------------------------------
# Capability policy matrix
# --------------------------------------------------------------------------


def _context(run_id: str = "run-kc", node_id: str = "source_finding", **overrides):
    kwargs = {
        "run_id": run_id,
        "node_id": node_id,
        "now_ms": FIXED_NOW_MS + 1,
        "root_id": "",
        "human_gate_receipt_id": "",
    }
    kwargs.update(overrides)
    return StageActionContext(**kwargs)


def _capability(run_id: str = "run-kc", node_id: str = "source_finding", **overrides):
    kwargs = {
        "run_id": run_id,
        "node_id": node_id,
        "root_ids": ["root-a", "root-b"],
        "issued_at_ms": FIXED_NOW_MS,
        "max_actions": 8,
        "max_retries": 1,
        "ttl_ms": 60_000,
    }
    kwargs.update(overrides)
    return issue_knowledge_capability(**kwargs)


def test_capability_matrix_auto_allowed_actions_pass() -> None:
    capability = _capability()
    assert capability.actions == AUTO_ALLOWED_ACTIONS
    for action in sorted(AUTO_ALLOWED_ACTIONS):
        root_id = "root-a" if action in {READ_MANAGED_ROOT, STAGE_DATA_RECORD} else ""
        decision = authorize_stage_action(capability, action, _context(root_id=root_id))
        assert decision.allowed is True, (action, decision)
        assert decision.policy_class is CapabilityPolicyClass.AUTO_ALLOWED


def test_capability_matrix_human_gate_operator_only_and_blocked_fail_closed() -> None:
    capability = _capability()

    # Blocked: never grantable, never executable.
    for action in sorted(BLOCKED_ACTIONS):
        decision = authorize_stage_action(capability, action, _context())
        assert decision.allowed is False
        assert decision.code == "policy_blocked"
        assert decision.policy_class is CapabilityPolicyClass.BLOCKED

    # Operator-only: redirected to the operator command path.
    for action in (ARCHIVE_RUN, CHANGE_PERMISSIONS):
        decision = authorize_stage_action(capability, action, _context())
        assert decision.allowed is False
        assert decision.code == "operator_command_required"

    # Human gate: needs a durable human-gate receipt, and stage capabilities
    # never carry gate actions anyway (issuance refuses them).
    decision = authorize_stage_action(capability, KNOWLEDGE_HANDOFF, _context())
    assert decision.allowed is False
    assert decision.code == "human_gate_required"
    gate_capability = KnowledgeCapability(
        capability_id="kcap-gate",
        run_id="run-kc",
        node_id="knowledge_handoff",
        actions=frozenset({KNOWLEDGE_HANDOFF}),
        allowed_root_ids=frozenset(),
        budget=KnowledgeCapabilityBudget(max_actions=2, expires_at_ms=FIXED_NOW_MS + 1000),
    )
    assert (
        authorize_stage_action(gate_capability, KNOWLEDGE_HANDOFF, _context()).allowed
        is False
    )
    allowed = authorize_stage_action(
        gate_capability,
        KNOWLEDGE_HANDOFF,
        _context(
            node_id="knowledge_handoff",
            human_gate_receipt_id="task-accepted-1",
        ),
    )
    assert allowed.allowed is True

    # Issuance can never be tricked into granting privileged actions.
    with pytest.raises(ValueError, match="not grantable"):
        issue_knowledge_capability(
            run_id="run-kc",
            node_id="source_finding",
            actions=frozenset({CONTROLLED_SEARCH, ARCHIVE_RUN}),
            issued_at_ms=FIXED_NOW_MS,
        )


def test_capability_expiry_budget_binding_and_roots_fail_closed() -> None:
    capability = _capability()

    # Unknown actions (including raw tool names) are not stage actions.
    decision = authorize_stage_action(
        capability, "research_knowledge_collection_tool", _context()
    )
    assert decision.allowed is False
    assert decision.code == "unknown_action"

    # Run / node binding.
    assert (
        authorize_stage_action(capability, CONTROLLED_SEARCH, _context(run_id="other")).code
        == "run_binding_mismatch"
    )
    assert (
        authorize_stage_action(
            capability, CONTROLLED_SEARCH, _context(node_id="knowledge_handoff")
        ).code
        == "node_binding_mismatch"
    )

    # Expiry.
    expired = _capability(ttl_ms=1)
    decision = authorize_stage_action(
        expired, CONTROLLED_SEARCH, _context(now_ms=FIXED_NOW_MS + 10_000)
    )
    assert decision.allowed is False
    assert decision.code == "capability_expired"

    # Root scope: unspecified and outside-the-whitelist roots are denied.
    assert (
        authorize_stage_action(capability, READ_MANAGED_ROOT, _context()).code
        == "root_not_specified"
    )
    assert (
        authorize_stage_action(
            capability, READ_MANAGED_ROOT, _context(root_id="root-z")
        ).code
        == "root_outside_allowlist"
    )
    # Non-root-scoped actions need no root.
    assert (
        authorize_stage_action(capability, CONTROLLED_SEARCH, _context()).allowed
        is True
    )

    # Budget: consumption is explicit; exhaustion denies and recording refuses.
    tiny = _capability(max_actions=1)
    first = authorize_stage_action(tiny, CONTROLLED_SEARCH, _context())
    assert first.allowed is True
    consumed = record_stage_action(tiny, CONTROLLED_SEARCH)
    retry_consumed = record_stage_action(tiny, RETRY_WITHIN_BUDGET, retry=True)
    assert retry_consumed.budget.retries_used == 1
    assert consumed.budget.actions_used == 1
    decision = authorize_stage_action(
        consumed,
        CONTROLLED_SEARCH,
        _context(now_ms=tiny.issued_at_ms + 1),
    )
    assert decision.allowed is False
    assert decision.code == "budget_exhausted"
    with pytest.raises(ValueError, match="budget"):
        record_stage_action(consumed, CONTROLLED_SEARCH)
    retry_tiny = _capability(max_actions=8, max_retries=1)
    retry_tiny = record_stage_action(retry_tiny, RETRY_WITHIN_BUDGET, retry=True)
    with pytest.raises(ValueError, match="retry budget"):
        record_stage_action(retry_tiny, RETRY_WITHIN_BUDGET, retry=True)
    with pytest.raises(ValueError, match="not granted"):
        record_stage_action(tiny, KNOWLEDGE_HANDOFF)


# --------------------------------------------------------------------------
# Unattended child run: capability path never waits for tool approvals
# --------------------------------------------------------------------------


def test_unattended_child_stage_actions_authorized_without_tool_approvals(
    tmp_path: Path, monkeypatch
) -> None:
    from core.web.services.session import tool_approvals

    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "unattended capability path must never consult tool approvals"
        )

    monkeypatch.setattr(tool_approvals, "_can_auto_approve", _boom)

    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]

        # The server issues one capability per sideflow stage node; every
        # auto-allowed stage action authorizes cleanly for the whole walk.
        for node_id in KNOWLEDGE_SIDEFLOW_NODE_IDS[:-1]:
            capability = issue_knowledge_capability(
                run_id=child_run_id,
                node_id=node_id,
                root_ids=["root-a"],
                issued_at_ms=FIXED_NOW_MS,
            )
            for action in sorted(AUTO_ALLOWED_ACTIONS):
                root_id = (
                    "root-a" if action in {READ_MANAGED_ROOT, STAGE_DATA_RECORD} else ""
                )
                decision = authorize_stage_action(
                    capability,
                    action,
                    StageActionContext(
                        run_id=child_run_id,
                        node_id=node_id,
                        now_ms=FIXED_NOW_MS + 1,
                        root_id=root_id,
                    ),
                )
                assert decision.allowed is True, (node_id, action, decision)
                capability = record_stage_action(capability, action)

        # The child advances to the human-gate terminal with zero approval
        # interactions (the monkeypatch above fails the test if any occur).
        pending = _walk_child_to_handoff(harness, child_run_id)
        assert pending is not None
    finally:
        harness.close()


def test_capability_cannot_be_replayed_as_adhoc_tool_approval(tmp_path: Path) -> None:
    """The ad-hoc Agent tool path stays globally fail-closed."""
    capability = _capability()

    # Capability actions are not tool names and vice versa: the vocabularies
    # are disjoint, so a capability id/action can never satisfy a tool check.
    from core.web.services.tool_catalog import EXPLICIT_ALLOW_TOOLS

    assert not (set(AUTO_ALLOWED_ACTIONS) & EXPLICIT_ALLOW_TOOLS)
    assert not (set(AUTO_ALLOWED_ACTIONS) & {"cli_tool", "exec_command"})

    # The knowledge collection/request tools keep their explicit-allow gate:
    # a capability grants stage actions, never these tool calls.
    assert "research_knowledge_collection_tool" in EXPLICIT_ALLOW_TOOLS
    assert "research_knowledge_request_tool" in EXPLICIT_ALLOW_TOOLS

    from core.web.services.session.tool_approvals import _can_auto_approve

    assert (
        _can_auto_approve(
            permission_preset="standard",
            tool_name="research_knowledge_collection_tool",
            tool_args={},
            approval="once",
            risk="high",
        )
        is False
    )
