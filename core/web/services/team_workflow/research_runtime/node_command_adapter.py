"""Node-level command adapter for research workflow runs.

Every command the frontend may render has a REAL backend handler here, or is
declared explicitly unavailable with a reason. The frontend never derives the
next node or fakes success: it renders only commands the adapter reports as
available (via node_command_capabilities) and executes them through
apply_node_command — no self-computed transitions.

Current wiring:
- start_agent_task -> research project Agent task only for roles with a
                       concrete task-kind mapping;
- rebind_node      -> controlled rebind keeping snapshot lineage (handled by
                       the runtime service);
- session navigation is reported separately by the runtime service once the
  full session/task/turn anchor exists;
- smoke, controlled-run, artifact and roadmap actions are not advertised
  until their node-specific UI contract supplies the required context.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.definition_registry import resolve_definition_for_run_record
from core.research.workflow.models import ActorKind

from .agent_node_execution import (
    PROJECT_NODE_TASKS,
    SOURCE_NODE_TASKS,
    AgentNodeExecutionError,
    start_agent_node_execution,
)
from .agent_start_contract import (
    AgentStartContractError,
    build_agent_start_contract,
)
from .node_execution_support import NodeExecutionError
from .retry_policy import retry_is_available


class NodeCommandUnavailable(Exception):
    def __init__(self, message: str, *, code: str = "node_command_unavailable"):
        super().__init__(message)
        self.code = code


class NodeCommandError(Exception):
    def __init__(self, message: str, *, code: str = "node_command_error"):
        super().__init__(message)
        self.code = code


def _node_spec(record: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    definition = resolve_definition_for_run_record(
        record,
        expected_node_ids=[node_id],
    )
    return next((n.to_dict() for n in definition.nodes if n.nodeId == node_id), None)


def _snapshot_agent_id(record: dict[str, Any], node_id: str) -> str:
    for snap in record.get("bindingSnapshots") or []:
        if str(snap.get("nodeId") or "") == node_id:
            return str(snap.get("agentId") or "").strip()
    return ""


def _retry_execution_capability(
    record: dict[str, Any],
    node_id: str,
) -> dict[str, Any] | None:
    node_runs = [
        dict(item)
        for item in record.get("nodeRuns") or []
        if str(item.get("nodeId") or "") == node_id
    ]
    if not node_runs:
        return None
    latest = node_runs[-1]
    if str(latest.get("status") or "") not in {"blocked", "failed"}:
        return None
    attempt = int(latest.get("attempt") or 0)
    available, retry_kind = retry_is_available(record, node_id, latest)
    return {
        "command": "retry_execution",
        "available": available,
        "reason": "" if available else "节点重试预算已耗尽",
        "idempotencyKey": (
            f"retry-node:{latest.get('nodeRunId')}:a{attempt + 1}"
        ),
        "payload": {"retryKind": retry_kind},
    }


def _evidence_remediation_capability(
    record: dict[str, Any],
    node_id: str,
) -> dict[str, Any] | None:
    if node_id != "source_extraction":
        return None
    node_runs = [
        dict(item)
        for item in record.get("nodeRuns") or []
        if str(item.get("nodeId") or "") == node_id
    ]
    if not node_runs:
        return None
    latest = node_runs[-1]
    if (
        str(latest.get("status") or "") != "blocked"
        or str(latest.get("failureCode") or "") != "external_task_needs_review"
    ):
        return None
    failure_context = (
        latest.get("failureContext")
        if isinstance(latest.get("failureContext"), dict)
        else {}
    )
    candidate_ids = sorted(
        {
            str(item).strip()
            for item in list(failure_context.get("evidenceGapCandidateIds") or [])
            if str(item).strip()
        }
    )
    available = bool(candidate_ids)
    return {
        "command": "fork_evidence_remediation",
        "available": available,
        "reason": "" if available else "失败任务没有固化可审计的证据缺口候选",
        "idempotencyKey": (
            f"fork-evidence-remediation:{latest.get('nodeRunId')}"
        ),
        "payload": {
            "evidenceGapCandidateIds": candidate_ids,
            "scopeCandidateIds": candidate_ids,
        },
    }


def node_command_capabilities(
    record: dict[str, Any],
    node_id: str,
    *,
    research_ledger: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-node capability list driving the frontend (no fake buttons)."""
    node = _node_spec(record, node_id)
    if node is None:
        return []
    actor_kind = str(node.get("actorKind") or "")
    closeout = record.get("stageOneCloseout")
    if (
        isinstance(closeout, dict)
        and closeout.get("status") == "program_review_required"
        and str(record.get("completionState") or "") != "STAGE1_G1_ACCEPTED"
    ):
        handoff = record.get("programCandidateHandoff")
        return [
            {
                "command": (
                    "finalize_stage_one"
                    if isinstance(handoff, dict)
                    else "build_stage_one_package"
                ),
                "available": True,
                "reason": "",
            },
            {"command": "view_artifacts", "available": True, "reason": ""},
        ]

    if actor_kind == ActorKind.AGENT.value:
        supplemental: list[dict[str, Any]] = []
        if node_id == "evidence_relations":
            from .evidence_graph_projection import evidence_graph_availability

            available, reason = evidence_graph_availability(record)
            supplemental = [
                {
                    "command": "open_evidence_graph",
                    "available": available,
                    "reason": reason,
                }
            ]
        retry = _retry_execution_capability(record, node_id)
        if retry is not None:
            remediation = (
                _evidence_remediation_capability(record, node_id)
                if not retry.get("available")
                else None
            )
            return [*supplemental, retry, *([remediation] if remediation else [])]
        if node_id not in SOURCE_NODE_TASKS and node_id not in PROJECT_NODE_TASKS:
            return supplemental
        agent_id = _snapshot_agent_id(record, node_id)
        if not agent_id:
            return [
                *supplemental,
                {
                    "command": "start_agent_task",
                    "available": False,
                    "reason": "节点尚未绑定 Agent，先完成绑定",
                },
            ]
        if not str(record.get("projectId") or "").strip():
            return [
                *supplemental,
                {
                    "command": "start_agent_task",
                    "available": False,
                    "reason": "运行尚无 research project 上下文（缺少 projectId）",
                },
            ]
        try:
            start_contract = build_agent_start_contract(record, node_id)
        except AgentStartContractError as exc:
            return [
                *supplemental,
                {
                    "command": "start_agent_task",
                    "available": False,
                    "reason": str(exc),
                },
            ]
        return [
            *supplemental,
            {
                "command": "start_agent_task",
                "available": True,
                "reason": "",
                **start_contract,
            },
        ]

    if actor_kind == ActorKind.HUMAN.value and any(
        str(task.get("nodeId") or "") == node_id
        and str(task.get("status") or "") == "pending"
        for task in record.get("humanTasks") or []
        if isinstance(task, dict)
    ):
        capabilities = [
            {"command": command, "available": True, "reason": ""}
            for command in ("accept_handoff", "reject_handoff", "revise")
        ]
        if node_id == "smoke_gate":
            passed_smoke = any(
                item.get("nodeId") == "smoke_gate"
                and item.get("command") == "run_smoke"
                and item.get("status") == "succeeded"
                and (item.get("observation") or {}).get("status") == "passed"
                for item in record.get("systemActions") or []
            )
            capabilities[0] = {
                "command": "accept_handoff",
                "available": passed_smoke,
                "reason": "" if passed_smoke else "需要先完成并通过真实 Smoke",
            }
            capabilities.insert(
                0,
                {"command": "run_smoke", "available": True, "reason": ""},
            )
        return capabilities

    if actor_kind == ActorKind.SYSTEM.value and node_id == "controlled_run":
        ready = any(
            item.get("nodeId") == node_id and item.get("status") == "ready"
            for item in record.get("nodeRuns") or []
        )
        passed_smoke = any(
            item.get("nodeId") == "smoke_gate"
            and item.get("command") == "run_smoke"
            and item.get("status") == "succeeded"
            and (item.get("observation") or {}).get("status") == "passed"
            for item in record.get("systemActions") or []
        )
        return [
            {
                "command": "start_controlled_run",
                "available": ready and passed_smoke,
                "reason": (
                    "" if ready and passed_smoke else "需要受控运行节点 ready 且 Smoke 已放行"
                ),
            }
        ]

    if actor_kind == ActorKind.SYSTEM.value and node_id == "result_package":
        from .result_package import (
            ResultPackageError,
            result_package_availability,
            terminal_package_candidate,
        )

        try:
            candidate = terminal_package_candidate(record)
            available, reason = result_package_availability(
                candidate,
                research_ledger=research_ledger,
            )
        except ResultPackageError as exc:
            available, reason = False, str(exc)
        return [
            {"command": "build_package", "available": available, "reason": reason},
            {"command": "view_artifacts", "available": True, "reason": ""},
        ]
    return []


def apply_node_command(
    *,
    store: Any,
    checkpoint_path: str,
    record: dict[str, Any],
    node_id: str,
    command: str,
    payload: dict[str, Any] | None = None,
    research_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one node command against a real backend handler."""
    payload = payload or {}
    node = _node_spec(record, node_id)
    if node is None:
        raise NodeCommandError(f"Unknown nodeId: {node_id}", code="unknown_node")
    if command == "open_session":
        raise NodeCommandUnavailable(
            "会话入口必须通过节点详情中的精确链接打开", code="navigation_only"
        )
    if command in {"accept_handoff", "reject_handoff", "revise"}:
        raise NodeCommandUnavailable(
            "人工任务必须通过人工任务接口处理", code="human_task_resolution_required"
        )
    # System adapters own their state and idempotency validation. Dispatching
    # before the UI capability check permits an exact replay after the node has
    # already advanced, while a new key still fails against the durable state.
    if command == "run_smoke":
        from .smoke_system_adapter import execute_smoke_action
        from .system_action_records import SystemActionError

        try:
            return execute_smoke_action(store, record=record, payload=payload)
        except SystemActionError as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    if command == "start_controlled_run":
        from .controlled_run_system_adapter import execute_controlled_run_action
        from .system_action_records import SystemActionError

        try:
            return execute_controlled_run_action(
                store,
                checkpoint_path=checkpoint_path,
                record=record,
                payload=payload,
            )
        except (SystemActionError, AgentNodeExecutionError) as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    if command == "build_package":
        from .result_package_system_adapter import execute_result_package_action
        from .system_action_records import SystemActionError

        if research_ledger is None:
            raise NodeCommandError(
                "build_package requires the canonical ResearchLedger projection",
                code="research_ledger_required",
            )
        try:
            return execute_result_package_action(
                store,
                checkpoint_path=checkpoint_path,
                record=record,
                research_ledger=research_ledger,
                payload=payload,
            )
        except SystemActionError as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    if command == "finalize_stage_one":
        from .stage_one_closeout import finalize_stage_one_closeout

        try:
            return finalize_stage_one_closeout(
                store,
                record=record,
                payload=payload,
            )
        except NodeExecutionError as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    if command == "build_stage_one_package":
        from .result_package_system_adapter import execute_stage_one_package_action
        from .system_action_records import SystemActionError

        try:
            return execute_stage_one_package_action(
                store,
                record=record,
                payload=payload,
            )
        except SystemActionError as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    # Agent execution owns durable replay validation. Dispatch before the UI
    # capability check so a repeated, already-committed request can return its
    # exact task/session anchor after the NodeRun has advanced to running.
    if command == "start_agent_task":
        try:
            return start_agent_node_execution(
                store,
                record=record,
                node_id=node_id,
                payload=payload,
            )
        except AgentNodeExecutionError as exc:
            raise NodeCommandError(str(exc), code=exc.code) from exc
    capability = next(
        (
            item
            for item in node_command_capabilities(
                record,
                node_id,
                research_ledger=research_ledger,
            )
            if item["command"] == command
        ),
        None,
    )
    if capability is None:
        raise NodeCommandUnavailable(
            "该命令不适用于当前节点", code="command_not_allowed_for_node"
        )
    if not capability["available"]:
        reason = str(capability["reason"] or "该命令当前不可用")
        code = (
            "no_project_context"
            if "projectId" in reason
            else "unbound_node"
            if "绑定 Agent" in reason
            else "node_command_unavailable"
        )
        raise NodeCommandUnavailable(reason, code=code)
    if command == "view_artifacts":
        return _view_artifacts(record, node_id)
    if command == "open_evidence_graph":
        return _open_evidence_graph(record)
    if command == "rebind_node":
        raise NodeCommandError(
            "rebind_node is handled by the runtime service command path",
            code="delegate_to_runtime_command",
        )
    raise NodeCommandError(f"Unknown node command: {command}", code="unknown_command")


def _view_artifacts(record: dict[str, Any], node_id: str) -> dict[str, Any]:
    artifacts = (record.get("langGraph") or {}).get("artifacts") or {}
    return {
        "command": "view_artifacts",
        "nodeId": node_id,
        "artifacts": artifacts,
    }


def _open_evidence_graph(record: dict[str, Any]) -> dict[str, Any]:
    from .evidence_graph_projection import project_evidence_graph

    graph = project_evidence_graph(record)
    return {"command": "open_evidence_graph", "graph": graph}
