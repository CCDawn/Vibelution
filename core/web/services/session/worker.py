"""Session turn worker (run turn + internal continuation loop).

Claim scope: execute a scheduled session turn — prepare agent/context, run the
turn/continuation loop, and hand results to persist helpers. Do not put submit
validation, schedule queue policy, or SSE transport here.

Bodies late-bind ``session_service`` so facade monkeypatches (create agent,
persist, capture, live_output) remain effective.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.infrastructure.tool_execution_scope import (
    ToolExecutionScope,
    tool_execution_scope,
)
from core.orchestration.context_engine import AgentContextInterrupted
from core.web.services.session.research_thinking_budget import (
    build_research_thinking_budget_segment,
)

_STRICT_RESEARCH_TASK_KINDS = frozenset(
    {"hypothesis_design", "protocol_review", "result_evaluation"}
)

# Conservative real-time circuit-breaker line for a session turn when no
# task-owned budget request is resolvable. It bounds input+output tokens
# accumulated across the turn's continuation loop: generous enough for normal
# tasks, far smaller than an unbounded runaway loop. Budget settlement at task
# terminal state remains the authoritative accounting; this constant only
# stops live overspend early.
DEFAULT_SESSION_TOKEN_BUDGET = 2_000_000

# Minimum usable output space for one formal invocation. Real node inputs are
# ~24K tokens and reasoning models spend the whole allowance on thinking
# first, so silently clamping max_output_tokens to a sliver below this floor
# makes the model spin and return an empty answer. The invocation preflight
# must reject fail-closed instead. Override with
# VIBELUTION_MIN_INVOCATION_OUTPUT_TOKENS.
MIN_INVOCATION_OUTPUT_TOKENS = 4_096
_MIN_INVOCATION_OUTPUT_TOKENS_ENV = "VIBELUTION_MIN_INVOCATION_OUTPUT_TOKENS"

_CONTINUATION_TOOL_FAILURE_STATUSES = frozenset(
    {"error", "failed", "failure", "timeout", "timed_out"}
)


def _normalized_tool_signature_value(value: Any) -> Any:
    """Build a stable, JSON-safe tool observation without call-local noise."""

    if isinstance(value, dict):
        return {
            str(key): _normalized_tool_signature_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in {"callId", "toolCallId", "tool_call_id", "durationMs"}
        }
    if isinstance(value, (list, tuple)):
        return [_normalized_tool_signature_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = " ".join(str(value).split())
    if text.startswith(("{", "[")):
        try:
            return _normalized_tool_signature_value(json.loads(text))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return text


def _continuation_tool_observations(result: Any) -> list[tuple[str, bool]]:
    """Return ``(signature, succeeded)`` for each observable tool call.

    A signature deliberately binds the tool name, normalized arguments, and
    result/error code. Invocation ids and durations are excluded so retrying
    the same action remains detectable across model turns.
    """

    if not isinstance(result, dict):
        return []
    s = _service()
    observations: list[tuple[str, bool]] = []
    for raw in list(result.get("tool_trace") or result.get("tool_calls") or []):
        if not isinstance(raw, dict):
            continue
        name = s._tool_call_name(raw)
        if not name:
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        arguments = raw.get("arguments")
        if arguments is None:
            arguments = raw.get("args")
        if arguments is None:
            arguments = function.get("arguments")
        error_code = str(raw.get("errorCode") or raw.get("error_code") or "").strip()
        error = raw.get("error")
        result_value = raw.get("result")
        if result_value is None:
            result_value = raw.get("resultPreview") or raw.get("result_preview")
        if result_value is None:
            result_value = raw.get("summary")
        status = str(raw.get("semanticStatus") or raw.get("status") or "done").strip().lower()
        failed = bool(
            status in _CONTINUATION_TOOL_FAILURE_STATUSES
            or error_code
            or error
            or s._looks_like_tool_call_failure_summary(result_value)
        )
        signature_payload = {
            "name": name,
            "arguments": _normalized_tool_signature_value(arguments),
            "status": status,
            "observation": _normalized_tool_signature_value(
                error_code or error or result_value
            ),
        }
        encoded = json.dumps(
            signature_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        observations.append((hashlib.sha256(encoded).hexdigest(), not failed))
    return observations


def _min_invocation_output_tokens() -> int:
    raw = os.environ.get(_MIN_INVOCATION_OUTPUT_TOKENS_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return MIN_INVOCATION_OUTPUT_TOKENS
        if value > 0:
            return value
    return MIN_INVOCATION_OUTPUT_TOKENS


def _challenge_deadline_stop_reason(
    deadline_at_ms: Any,
    *,
    turn_id: str = "",
    now_ms: int | None = None,
) -> str:
    """Return a stop code only for an expired executor-carried deadline."""

    if not (
        isinstance(deadline_at_ms, int)
        and not isinstance(deadline_at_ms, bool)
        and deadline_at_ms > 0
    ):
        return ""
    effective_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    remaining_ms = deadline_at_ms - effective_now_ms
    if remaining_ms > 0:
        return ""
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_deadline_problem,
    )

    return str(
        challenge_deadline_problem(
            waited_ms=max(0, -remaining_ms),
            turn_chain=[turn_id],
        ).get("code")
        or "challenge_logical_task_deadline_exhausted"
    )


def _is_challenge_deadline_cancelled(
    context: dict[str, Any],
    exc: Exception,
    *,
    turn_id: str,
) -> bool:
    """Recognize only provider cancellation caused by an expired Challenge deadline."""

    if not context.get("_challenge_task_deadline_at_ms"):
        return False
    category = str(getattr(exc, "category", "") or "").strip().lower()
    if category != "cancelled":
        return False
    return bool(
        _challenge_deadline_stop_reason(
            context.get("_challenge_task_deadline_at_ms"),
            turn_id=turn_id,
        )
    )


def _research_task_structured_output_contract(
    context: dict[str, Any],
    *,
    session_id: str,
    turn_id: str,
):
    """Resolve strict output only from the server-owned formal task record."""

    metadata = (
        context.get("message_metadata")
        if isinstance(context.get("message_metadata"), dict)
        else {}
    )
    if str(metadata.get("kind") or "").strip() != "research_project_agent_task":
        return None
    requested_task_kind = str(metadata.get("taskKind") or "").strip()
    if requested_task_kind not in _STRICT_RESEARCH_TASK_KINDS:
        return None
    task_id = str(metadata.get("taskId") or "").strip()
    team_id = str(metadata.get("teamId") or "").strip()
    project_id = str(metadata.get("researchProjectId") or "").strip()
    if not task_id or not team_id or not project_id:
        raise RuntimeError("strict research task output binding is incomplete")
    try:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            _read_research_project_agent_task_record,
        )

        task = _read_research_project_agent_task_record(team_id, project_id, task_id)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError("strict research task output record is unavailable") from exc
    if not isinstance(task, dict):
        raise RuntimeError("strict research task output record is unavailable")
    task_kind = str(task.get("taskKind") or "").strip()
    task_turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    stored_turn_id = str(task_turn.get("turnId") or "").strip()
    if (
        task_kind not in _STRICT_RESEARCH_TASK_KINDS
        or task_kind != requested_task_kind
        or str(task.get("taskId") or "").strip() != task_id
        or str(task.get("researchProjectId") or "").strip() != project_id
        or str(task.get("sessionId") or "").strip() != str(session_id or "").strip()
        or (stored_turn_id and stored_turn_id != str(turn_id or "").strip())
    ):
        raise RuntimeError("strict research task output binding does not match the turn")
    from core.llm.semantic_messages import SemanticOutputSchema
    from core.research.workflow.contracts import (
        RESEARCH_TASK_OUTPUT_SCHEMA_VERSION,
        canonical_research_task_output_schema_bundle,
        parse_research_task_output,
    )

    schema = canonical_research_task_output_schema_bundle()["schemas"][task_kind]
    return SemanticOutputSchema(
        name=f"research_{task_kind}_v{RESEARCH_TASK_OUTPUT_SCHEMA_VERSION}",
        schema=schema,
        validator=lambda payload: parse_research_task_output(task_kind, payload),
    )


def _model_invocation_receipt_context(
    context: dict[str, Any],
    *,
    session_id: str,
    turn_id: str,
) -> dict[str, Any] | None:
    """Complete a server-created binding seed with the canonical Task/Turn."""

    metadata = (
        context.get("message_metadata")
        if isinstance(context.get("message_metadata"), dict)
        else {}
    )
    task_id = str(metadata.get("taskId") or "").strip()
    team_id = str(metadata.get("teamId") or "").strip()
    project_id = str(metadata.get("researchProjectId") or "").strip()
    if not task_id or not team_id or not project_id:
        return None
    # Metadata is only a locator. The binding itself must be read back from
    # the server-owned project task record; a client-supplied metadata object
    # must never become receipt authority.
    source_task = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
    try:
        if source_task and source_task == task_id:
            from core.web.services.team_workflow.source_collection.stage_session import (
                _read_source_collection_stage_session_task_record,
            )

            task = _read_source_collection_stage_session_task_record(
                team_id,
                task_id,
            )
        else:
            from core.web.services.team_workflow.research_project_agent_tasks import (
                _read_research_project_agent_task_record,
            )

            task = _read_research_project_agent_task_record(
                team_id,
                project_id,
                task_id,
            )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if task is None or str(task.get("sessionId") or "").strip() != str(session_id or "").strip():
        return None
    if str(task.get("researchProjectId") or "").strip() != project_id:
        return None
    task_turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    stored_turn_id = str(task_turn.get("turnId") or "").strip()
    if stored_turn_id and stored_turn_id != str(turn_id or "").strip():
        return None
    seed = task.get("modelInvocationReceiptBinding")
    if isinstance(seed, dict):
        binding = dict(seed)
    elif source_task:
        contract = (
            task.get("challengeTaskContract")
            if isinstance(task.get("challengeTaskContract"), dict)
            else {}
        )
        binding = {
            "questionStage": str(contract.get("stageId") or ""),
            "questionId": str(contract.get("questionId") or ""),
            "questionRunId": str(contract.get("workflowRunId") or ""),
            "workflowRunId": str(contract.get("workflowRunId") or ""),
            "workflowId": str(contract.get("workflowId") or ""),
            "workflowVersionId": str(contract.get("workflowVersionId") or ""),
            "formalNodeId": str(contract.get("workflowNodeId") or ""),
            "formalNodeRunId": str(contract.get("nodeRunId") or ""),
            "formalNodeAttempt": int(contract.get("nodeAttempt") or 0),
            "outcomeKinds": ["source_evidence"],
            "modelPolicySha256": str(contract.get("modelPolicySha256") or ""),
        }
    else:
        return None
    contract = task.get("challengeTaskContract") if isinstance(task.get("challengeTaskContract"), dict) else {}
    contract_fields = {
        "questionId": ("questionId", "questionId"),
        "workflowRunId": ("workflowRunId", "workflowRunId"),
        "workflowId": ("workflowId", "workflowId"),
        "workflowVersionId": ("workflowVersionId", "workflowVersionId"),
        "formalNodeId": ("workflowNodeId", "formalNodeId"),
        "formalNodeRunId": ("nodeRunId", "formalNodeRunId"),
        "formalNodeAttempt": ("nodeAttempt", "formalNodeAttempt"),
        "modelPolicySha256": ("modelPolicySha256", "modelPolicySha256"),
    }
    if not contract or any(
        not str(contract.get(contract_key) or "").strip()
        or str(binding.get(binding_key) or "").strip()
        != str(contract.get(contract_key) or "").strip()
        for contract_key, binding_key in contract_fields.values()
    ):
        return None
    effective_route = contract.get("effectiveRoute") if isinstance(contract.get("effectiveRoute"), dict) else {}
    expected_route = {
        "modelRef": str(effective_route.get("modelRef") or "").strip(),
        "providerId": str(effective_route.get("providerId") or "").strip(),
        "modelId": str(effective_route.get("modelId") or "").strip(),
    }
    if (
        not all(expected_route.values())
        or expected_route["modelRef"].partition("/")[0].lower()
        != expected_route["providerId"].lower()
    ):
        return None
    binding.update(
        {
            "sessionId": str(session_id or "").strip(),
            "turnId": str(turn_id or "").strip(),
            "taskId": task_id,
        }
    )
    try:
        from core.research.workflow.contracts.question_stage_binding import (
            QuestionStageBinding,
        )

        stage_binding = QuestionStageBinding.from_dict(binding).to_dict()
    except (TypeError, ValueError, KeyError):
        return None
    required = (
        "questionId",
        "workflowRunId",
        "workflowId",
        "workflowVersionId",
        "formalNodeId",
        "formalNodeRunId",
        "sessionId",
        "taskId",
        "turnId",
    )
    policy_sha256 = str(binding.pop("modelPolicySha256", "") or "").strip().lower()
    if (
        any(not str(binding.get(key) or "").strip() for key in required)
        or len(policy_sha256) != 64
        or any(char not in "0123456789abcdef" for char in policy_sha256)
    ):
        return None
    run_id = str(binding.get("workflowRunId") or "").strip()
    receipt_context: dict[str, Any] = {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": run_id,
        "teamId": team_id,
        "modelPolicySha256": policy_sha256,
        "questionStageBinding": stage_binding,
        "outcomeKinds": list(binding.get("outcomeKinds") or []),
        "expectedModelRoute": expected_route,
    }

    def invocation_budget_preflight(
        *, estimated_input_tokens: int, max_output_tokens: int
    ) -> dict[str, int]:
        return _challenge_invocation_budget_preflight(
            receipt_context,
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=max_output_tokens,
        )

    # Ephemeral callable: it is bound only in the current ContextVar scope and
    # is never projected into the conversation journal or task record.
    receipt_context["invocationBudgetPreflight"] = invocation_budget_preflight
    return receipt_context


def _challenge_budget_window(receipt_context: dict[str, Any]) -> dict[str, Any]:
    binding = (
        receipt_context.get("questionStageBinding")
        if isinstance(receipt_context.get("questionStageBinding"), dict)
        else {}
    )
    run_id = str(binding.get("workflowRunId") or "").strip()
    node_run_id = str(binding.get("formalNodeRunId") or "").strip()
    if not run_id or not node_run_id:
        raise RuntimeError("challenge_budget_binding_missing")
    reservation_id = f"reservation-{node_run_id}"
    from core.web.services.team_workflow.research_runtime.budget_window_resolver import (
        injected_budget_window_resolver,
    )

    resolver = injected_budget_window_resolver()
    if resolver is not None:
        # The runtime that owns the Ledger injected this resolver at assembly
        # time: embedded runtimes never register the production singleton, and
        # reaching for a global from here would be the wrong dependency
        # direction.
        return resolver(run_id, node_run_id, reservation_id)
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        read_node_budget_window,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        production_workflow_runtime,
    )

    runtime = production_workflow_runtime()
    if runtime is None:
        raise RuntimeError("challenge_budget_authority_unavailable")
    return read_node_budget_window(
        runtime.store,
        run_id,
        node_run_id,
        reservation_id,
    )


def _challenge_invocation_budget_preflight(
    receipt_context: dict[str, Any],
    *,
    estimated_input_tokens: int,
    max_output_tokens: int,
) -> dict[str, int | str | bool]:
    window = _challenge_budget_window(receipt_context)
    if str(window.get("status") or "") not in {"reserved", "consumed"}:
        raise RuntimeError("challenge_budget_reservation_terminal")
    remaining = max(0, int(window.get("remaining") or 0))
    estimated_input = max(0, int(estimated_input_tokens or 0))
    profile_limit = max(0, int(max_output_tokens or 0))
    headroom = remaining - estimated_input
    min_output = _min_invocation_output_tokens()
    budget_pressure = headroom < profile_limit
    decision: dict[str, int | str | bool] = {
        "remainingTokens": remaining,
        "estimatedInputTokens": estimated_input,
        # The reservation is an accounting/capacity signal. It must not revoke
        # a progressing formal Agent invocation by shrinking its model profile.
        "maxOutputTokens": profile_limit,
        "budgetPressure": budget_pressure,
        "softLimitExceeded": headroom < min_output,
        "requiredMinOutput": min_output,
    }
    if budget_pressure:
        decision["reason"] = (
            "input_exceeds_remaining" if headroom < 0 else "insufficient_budget"
        )
    return decision


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _raise_for_challenge_receipt_failure(
    turn_capture: Any,
) -> None:
    failure_code = str(
        getattr(turn_capture, "challenge_receipt_failure_code", "") or ""
    ).strip()
    if failure_code:
        raise RuntimeError(failure_code)


def _session_context_allows_internal_auto_continue(context: dict[str, Any]) -> bool:
    s = _service()
    explicit = s._normalize_optional_bool(context.get("allow_internal_auto_continue"))
    if explicit is not None:
        return bool(explicit)
    metadata = (
        context.get("message_metadata")
        if isinstance(context.get("message_metadata"), dict)
        else {}
    )
    if (
        str(context.get("user_message_source") or "").strip()
        == "external_agent_task"
        and str(metadata.get("source") or "").strip() == "external_agent_task"
    ):
        external_explicit = s._normalize_optional_bool(
            metadata.get("allowInternalAutoContinue")
        )
        if external_explicit is not None:
            return bool(external_explicit)
    if _is_research_project_agent_task_context(context):
        return str(context.get("user_message_source") or "").strip() == "agent_inbox"
    if not s._source_collection_stage_task_context_metadata(context):
        return False
    if str(context.get("user_message_source") or "").strip() == "agent_inbox":
        return True
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    return metadata.get("sourceCollectionStageContinuation") is True


def _is_research_project_agent_task_context(context: dict[str, Any]) -> bool:
    metadata = (
        context.get("message_metadata")
        if isinstance(context.get("message_metadata"), dict)
        else {}
    )
    return str(metadata.get("kind") or "").strip() == "research_project_agent_task"


def _session_context_internal_auto_continue_max_turns(context: dict[str, Any]) -> int:
    s = _service()
    explicit = s._coerce_nonnegative_int(
        context.get("max_internal_auto_continue_turns") or context.get("internal_auto_continue_max_turns")
    )
    if explicit:
        return max(1, explicit)
    if s._source_collection_stage_task_context_metadata(
        context
    ) or _is_research_project_agent_task_context(context):
        return s.SOURCE_COLLECTION_STAGE_TASK_AUTO_CONTINUE_MAX_TURNS
    return s.INTERNAL_AUTO_CONTINUE_MAX_TURNS


def _external_agent_runtime_permission_profile(context: dict[str, Any]) -> str:
    if str(context.get("user_message_source") or "").strip() != "external_agent_task":
        return ""
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    if str(metadata.get("source") or "").strip() != "external_agent_task":
        return ""
    profile = str(metadata.get("effectivePermissionProfile") or "").strip().lower()
    return profile if profile in {"read_only", "workspace_write", "full_access"} else ""


def _wait_for_tool_execution_quiescence(scope: ToolExecutionScope) -> None:
    """Keep the owning turn active until every scheduled tool physically exits."""

    s = _service()
    scope.seal()
    initial_snapshot = scope.snapshot()
    if scope.is_quiescent():
        return

    s._record_session_turn_lifecycle_event(
        scope.session_id,
        "tool_quiescence_wait_started",
        turn_id=scope.turn_id,
        outcome="waiting",
        fields=initial_snapshot,
    )
    extended_wait_recorded = False
    while not scope.wait_for_quiescence(timeout=1.0):
        snapshot = scope.snapshot()
        if not extended_wait_recorded and int(snapshot.get("ageMs") or 0) >= 30_000:
            extended_wait_recorded = True
            s._record_session_turn_lifecycle_event(
                scope.session_id,
                "tool_quiescence_wait_extended",
                turn_id=scope.turn_id,
                level="warning",
                outcome="waiting",
                fields=snapshot,
            )
    s._record_session_turn_lifecycle_event(
        scope.session_id,
        "tool_quiescence_wait_finished",
        turn_id=scope.turn_id,
        outcome="quiescent",
        fields=scope.snapshot(),
    )


def _attach_runtime_prompt_assembly_manifest(result: Any, runtime_agent: Any) -> Any:
    if not isinstance(result, dict):
        return result
    prompt_manager = getattr(runtime_agent, "prompt_manager", None)
    get_manifest = getattr(prompt_manager, "get_last_assembly_manifest", None)
    if not callable(get_manifest):
        return result
    try:
        manifest = get_manifest()
    except Exception:
        return result
    if isinstance(manifest, dict) and manifest:
        result["prompt_assembly"] = manifest
    return result


def _finish_session_turn_worker(
    session_id: str,
    turn_id: str,
    turn_control: Any,
) -> None:
    """Release running-turn bookkeeping after persist or an early stop abort."""

    s = _service()
    s._ensure_session_turn_terminal_fallback(
        session_id,
        turn_id,
        stop_reason=s._get_turn_control_stop_reason(turn_control),
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "worker_finished",
        turn_id=turn_id,
        outcome="finished",
        fields={
            "wasCurrentTurn": s._is_session_turn_current(session_id, turn_id),
        },
    )
    s._record_session_execution_registry_event(
        session_id,
        turn_id,
        "main_agent_loop",
        "finished",
        details={"wasCurrentTurn": s._is_session_turn_current(session_id, turn_id)},
    )
    s._set_session_running(session_id, False, turn_id=turn_id)
    s._clear_session_turn_control(session_id, turn_id=turn_id)
    s._publish_session_detail_snapshot(session_id)


def _proactive_turn_is_current(context: dict[str, Any]) -> bool:
    from core.agent_plugins.runtime_extensions import (
        agent_plugin_proactive_turn_is_current,
    )

    return bool(agent_plugin_proactive_turn_is_current(context))


def _cancel_stale_proactive_turn(context: dict[str, Any], *, reason: str) -> None:
    if str(context.get("origin") or "") != "proactive_plugin":
        return
    from core.web.services.session.proactive import cancel_proactive_turn_context

    cancel_proactive_turn_context(context, reason=reason)


def _finalize_proactive_delivery_after_persist(
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Best-effort plugin receipt after the assistant item is already durable.

    Receipt bookkeeping must never rewrite a successfully persisted Session turn as
    failed. A later heartbeat or operator action can inspect/reconcile the still-open
    delivery attempt without corrupting the conversation's terminal state.
    """

    if str(context.get("origin") or "") != "proactive_plugin":
        return None
    try:
        from core.agent_plugins.runtime_extensions import (
            finalize_agent_plugin_proactive_delivery,
        )

        return finalize_agent_plugin_proactive_delivery(context)
    except Exception:
        return None


def _abort_session_turn_for_stop(
    *,
    session_id: str,
    turn_id: str,
    turn_control: Any,
    stage: str,
    mental_model_enabled: bool,
    context: dict[str, Any],
    finish_worker: bool,
) -> bool:
    """Persist a user stop if the controller already requested one.

    ``finish_worker=True`` is for aborting *before* the main ``try/finally``
    so running-state cleanup still happens. Inside that ``try``, leave
    cleanup to ``finally``.
    """

    s = _service()
    stop_reason = s._get_turn_control_stop_reason(turn_control)
    if not stop_reason:
        return False
    s._record_session_turn_lifecycle_event(
        session_id,
        "stop_observed",
        turn_id=turn_id,
        outcome="stopped",
        fields={
            "stage": stage,
            "stopReason": trim_lines(stop_reason, max_lines=2),
        },
    )
    from core.agent_plugins.runtime_extensions import is_agent_plugin_proactive_turn

    if is_agent_plugin_proactive_turn(context):
        _cancel_stale_proactive_turn(context, reason=stop_reason or "proactive_turn_stopped")
        if finish_worker:
            _finish_session_turn_worker(session_id, turn_id, turn_control)
        return True
    s._persist_session_turn_result(
        session_id,
        s._build_stopped_turn_result(stop_reason),
        mental_model_enabled=mental_model_enabled,
        active_task_hint=context.get("active_task"),
        user_message_source=str(context.get("user_message_source") or "").strip(),
        turn_id=turn_id,
    )
    if finish_worker:
        _finish_session_turn_worker(session_id, turn_id, turn_control)
    return True


def _run_session_turn(context: dict[str, Any]) -> None:
    """Run one scheduled turn inside a scoped child trace span."""

    s = _service()

    from core.logging.trace_context import (
        TraceContext,
        bind_trace_context,
        get_current_trace_context,
        new_trace_context,
    )

    if not _proactive_turn_is_current(context):
        _cancel_stale_proactive_turn(context, reason="binding_revision_fence_before_prepare")
        turn_control = context.get("turn_control")
        if not isinstance(turn_control, s.SessionTurnControl):
            turn_control = s._get_session_turn_control(str(context.get("session_id") or "").strip())
        _finish_session_turn_worker(
            str(context.get("session_id") or "").strip(),
            str(context.get("turn_id") or "").strip(),
            turn_control,
        )
        return

    parent_context = TraceContext.from_carrier(context.get("trace_context_carrier"))
    if parent_context is None:
        parent_context = get_current_trace_context() or new_trace_context()
    child_context = parent_context.child_span()
    worker_context = dict(context)
    worker_context["trace_context_carrier"] = child_context.to_carrier()
    with bind_trace_context(child_context):
        return _run_session_turn_impl(worker_context)


def _run_session_turn_impl(context: dict[str, Any]) -> None:
    s = _service()
    prepare_started_at = s._perf_counter()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if turn_id and not s._is_session_turn_current(session_id, turn_id):
        s._record_session_turn_lifecycle_event(
            session_id,
            "skipped_stale",
            turn_id=turn_id,
            outcome="skipped",
            fields={
                "reason": "turn_id_not_current",
            },
        )
        return
    turn_control = context.get("turn_control")
    if not isinstance(turn_control, s.SessionTurnControl):
        turn_control = s._get_session_turn_control(session_id)
    turn_capture = s.SessionTurnCapture(session_id=session_id, turn_id=turn_id)
    mental_model_requested = s._normalize_optional_bool(context.get("mental_model_enabled"))
    mental_model_decision = s.resolve_feature_decision(
        "mental_model",
        config=s.get_config(),
        requested=mental_model_requested,
    )
    mental_model_enabled = mental_model_decision.effective_enabled
    if _abort_session_turn_for_stop(
        session_id=session_id,
        turn_id=turn_id,
        turn_control=turn_control,
        stage="prepare",
        mental_model_enabled=mental_model_enabled,
        context=context,
        finish_worker=True,
    ):
        return
    runtime_status_requested = s._normalize_optional_bool(context.get("runtime_status_enabled"))
    llm_slot = str(context.get("llm_slot") or s.SESSION_LLM_SLOT_DIALOGUE).strip() or s.SESSION_LLM_SLOT_DIALOGUE
    prepare_timings: dict[str, Any] = {}
    stage_started_at = s._perf_counter()
    session_workspace = s._ensure_session_workspace(session_id)
    prepare_timings["sessionWorkspaceMs"] = s._elapsed_ms(stage_started_at)
    stage_started_at = s._perf_counter()
    s._sync_agent_directory_project_root()
    prepare_timings["agentDirectorySyncMs"] = s._elapsed_ms(stage_started_at)
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    stage_started_at = s._perf_counter()
    supplied_agent = context.get("agent_snapshot") if isinstance(context.get("agent_snapshot"), dict) else None
    if supplied_agent and str(supplied_agent.get("agentId") or "").strip() != agent_id:
        supplied_agent = None
    agent_instance = supplied_agent or (s.get_agent(agent_id, include_archived=False) if agent_id else None)
    historical_agent = None if agent_instance else (s.get_agent(agent_id, include_archived=True) if agent_id else None)
    current_agent_status = ""
    if agent_id:
        try:
            current_agent_status = str(
                (s.get_agent(agent_id, include_archived=True) or {}).get("status") or ""
            ).strip().lower()
        except Exception:
            current_agent_status = ""
    try:
        from core.runtime_status_flags import is_runtime_status_inject_enabled

        runtime_status_enabled = is_runtime_status_inject_enabled(
            agent=agent_instance if isinstance(agent_instance, dict) else None,
            requested=runtime_status_requested,
        )
    except Exception:
        runtime_status_enabled = runtime_status_requested is not False
    supervised_runtime_role = s._supervised_role_for_runtime_context(context, agent_instance)
    supervised_runtime_tool_grants = s._supervised_runtime_tool_grants_for_context(
        context,
        supervised_runtime_role,
    )
    runtime_tool_grants = supervised_runtime_tool_grants
    runtime_tool_source = (
        "supervised_baseline_self_edit"
        if supervised_runtime_tool_grants is not None
        else ""
    )
    external_runtime_permission_profile = _external_agent_runtime_permission_profile(context)
    if external_runtime_permission_profile:
        from core.web.services.external_agent.policy import external_runtime_tool_grants

        runtime_tool_grants = list(external_runtime_tool_grants(external_runtime_permission_profile))
        runtime_tool_source = f"external_agent_task:{external_runtime_permission_profile}"
    runtime_metadata: dict[str, Any] = {}
    from core.agent_plugins.runtime_extensions import (
        agent_plugin_proactive_runtime_metadata,
    )

    runtime_metadata.update(agent_plugin_proactive_runtime_metadata(context))
    prepare_timings["agentLookupMs"] = s._elapsed_ms(stage_started_at)
    stage_started_at = s._perf_counter()
    prompt_snapshot_hint = (
        context.get("agent_prompt_snapshot")
        if isinstance(context.get("agent_prompt_snapshot"), dict)
        else None
    )
    challenge_deadline_at_ms = context.get("_challenge_task_deadline_at_ms")

    def interrupt_checker() -> str:
        manual_reason = s._get_turn_control_stop_reason(turn_control)
        if manual_reason:
            return manual_reason
        return _challenge_deadline_stop_reason(
            challenge_deadline_at_ms,
            turn_id=turn_id,
        )

    # The LLM adapter receives a bound ``current_stop_reason`` method, so the
    # capability marker must live on the session-owned checker before the
    # Agent wraps it. This keeps provider HTTP abort opt-in to Challenge turns
    # while ordinary turns retain cooperative stop checks without a watcher.
    interrupt_checker._vibelution_chat_provider_abort_enabled = bool(challenge_deadline_at_ms)
    try:
        agent_prompt_snapshot = (
            s._ensure_session_agent_prompt_snapshot(
                session_id,
                agent_instance,
                snapshot_hint=prompt_snapshot_hint,
                interrupt_checker=interrupt_checker,
            )
            if agent_instance
            else {}
        )
        agent_prompt_snapshot_block = s._render_agent_prompt_snapshot_block(agent_prompt_snapshot)
        prepare_timings["promptSnapshotMs"] = s._elapsed_ms(stage_started_at)
        if _abort_session_turn_for_stop(
            session_id=session_id,
            turn_id=turn_id,
            turn_control=turn_control,
            stage="prepare_prompt_snapshot",
            mental_model_enabled=mental_model_enabled,
            context=context,
            finish_worker=True,
        ):
            return
        prepare_timings["promptSnapshotIncluded"] = bool(agent_prompt_snapshot_block)
        prepare_timings["promptSnapshotReason"] = str(agent_prompt_snapshot.get("reason") or "").strip() if isinstance(agent_prompt_snapshot, dict) else ""
        stage_started_at = s._perf_counter()
        turn_attachments = s._normalize_message_attachments(context.get("attachments") or [])
        lightweight_chat_payload, lightweight_chat_payload_reason = s._lightweight_chat_payload_decision(
            context,
            attachments=turn_attachments,
        )
        prepare_timings["lightweightChatDecisionMs"] = s._elapsed_ms(stage_started_at)
        prepare_timings["lightweightChatPayload"] = lightweight_chat_payload
        prepare_timings["lightweightChatPayloadReason"] = lightweight_chat_payload_reason
        stage_started_at = s._perf_counter()
        agent_context_packet = (
            s.build_agent_context(
                agent_id,
                session_id=session_id,
                run_id=turn_id,
                agent_snapshot=agent_instance,
                include_prompt_template_context=not bool(agent_prompt_snapshot_block),
                interrupt_checker=interrupt_checker,
            )
            if agent_id
            else None
        )
        prepare_timings["agentContextBuildMs"] = s._elapsed_ms(stage_started_at)
        prepare_timings["agentContextBuildSkipped"] = bool(agent_id and agent_context_packet is None)
        if _abort_session_turn_for_stop(
            session_id=session_id,
            turn_id=turn_id,
            turn_control=turn_control,
            stage="prepare_agent_context",
            mental_model_enabled=mental_model_enabled,
            context=context,
            finish_worker=True,
        ):
            return
    except AgentContextInterrupted as exc:
        _abort_session_turn_for_stop(
            session_id=session_id,
            turn_id=turn_id,
            turn_control=turn_control,
            stage=str(exc.stage or "").strip() or "prepare",
            mental_model_enabled=mental_model_enabled,
            context=context,
            finish_worker=True,
        )
        return
    agent_context_timings = (
        dict(getattr(agent_context_packet, "timings", {}) or {})
        if agent_context_packet is not None
        else {}
    )
    for timing_key, timing_value in agent_context_timings.items():
        normalized_key = str(timing_key or "").strip()
        if not normalized_key:
            continue
        prepare_timings[f"agentContext.{normalized_key}"] = timing_value
    agent_workspace = str((agent_instance or {}).get("workspacePath") or "").strip()
    memory_policy = (
        agent_context_packet.memory_policy
        if agent_context_packet is not None
        else (s.resolve_memory_policy_for_agent(agent_id) if agent_id else {})
    )
    memory_root = str(memory_policy.get("privateMemoryRoot") or "").strip()
    agent_workspace_path = (
        s.agent_directory_service._ensure_agent_workspace(str((agent_instance or {}).get("workspacePath") or "")).resolve()
        if agent_instance and str((agent_instance or {}).get("workspacePath") or "").strip()
        else session_workspace
    )
    supervised_workspace_override = s._supervised_workspace_override_path(context)
    stage_started_at = s._perf_counter()
    if supervised_workspace_override is not None:
        workspace_decision = None
        tool_workspace = supervised_workspace_override
    else:
        workspace_decision = (
            s.evaluate_agent_workspace_write(agent_id, agent_workspace_path, purpose="chat_turn_tool_workspace")
            if agent_id
            else None
        )
        tool_workspace = agent_workspace_path if not workspace_decision or workspace_decision.allowed else session_workspace
    prepare_timings["workspacePolicyMs"] = s._elapsed_ms(stage_started_at)
    prepare_timings["supervisedWorkspaceOverride"] = str(supervised_workspace_override or "")
    stage_started_at = s._perf_counter()
    llm_key_env_sync = s.sync_llm_key_env_from_persisted_user_env(context="chat_turn")
    prepare_timings["llmKeyEnvSyncMs"] = s._elapsed_ms(stage_started_at)
    prepare_timings["llmKeyEnvSyncOk"] = bool(llm_key_env_sync.get("ok"))
    prepare_timings["llmKeyEnvSyncedCount"] = int(llm_key_env_sync.get("syncedCount") or 0)
    prepare_timings["llmKeyEnvAlreadyPresentCount"] = int(llm_key_env_sync.get("alreadyPresentCount") or 0)
    prepare_timings["llmKeyEnvMissingCount"] = int(llm_key_env_sync.get("missingCount") or 0)
    if llm_key_env_sync.get("ok"):
        s._record_session_turn_lifecycle_event(
            session_id,
            "llm_key_env_synced",
            turn_id=turn_id,
            outcome="synced",
            fields=llm_key_env_sync,
        )
    else:
        s._record_session_turn_lifecycle_event(
            session_id,
            "llm_key_env_sync_failed",
            turn_id=turn_id,
            level="warning",
            outcome="failed",
            fields=llm_key_env_sync,
        )
    resolved_agent_llm = None
    if agent_instance:
        stage_started_at = s._perf_counter()
        try:
            session_reasoning_effort = s._session_reasoning_effort_snapshot(session_id)
            resolved_agent_llm = s._resolve_session_agent_llm(
                agent_instance,
                llm_slot,
                reasoning_effort=session_reasoning_effort,
            )
        except s.SessionValidationError as exc:
            visible = str(exc)
            missing_model_id = s._extract_missing_agent_llm_model_id(visible)
            turn_error = s._make_local_runtime_turn_error(
                visible,
                lang=s.get_web_language(),
                error_type="agent_llm_resolution_failed",
                reason_code="agent_llm_model_missing" if missing_model_id else "agent_llm_resolution_failed",
                reason_summary=s.text_for(
                    s.get_web_language(),
                    zh="当前 Agent 绑定的对话模型不在模型库中",
                    en="The current Agent dialogue model is not present in the model library",
                )
                if missing_model_id
                else s.text_for(
                    s.get_web_language(),
                    zh="当前 Agent 的模型槽位无法解析",
                    en="The current Agent model slot could not be resolved",
                ),
                reason_detail=visible,
                turn_id=turn_id,
                model=missing_model_id,
                extra={"llmSlot": llm_slot, "agentId": agent_id},
            )
            s._record_session_turn_lifecycle_event(
                session_id,
                "agent_llm_resolve_failed",
                turn_id=turn_id,
                outcome="failed",
                fields={
                    "agentId": agent_id,
                    "llmSlot": llm_slot,
                    "errorType": type(exc).__name__,
                    "error": visible,
                },
            )
            s._persist_session_turn_runtime_error(
                session_id,
                turn_error,
                raw_error=visible,
                turn_id=turn_id,
                status="failed_runtime",
                work_run_summary=s.text_for(
                    s.get_web_language(),
                    zh="本轮在本地模型槽位解析阶段失败，未调用 provider。",
                    en="This turn failed while resolving the local model slot before any provider call.",
                ),
            )
            s._record_session_turn_lifecycle_event(
                session_id,
                "worker_finished",
                turn_id=turn_id,
                outcome="failed_runtime",
                fields={
                    "wasCurrentTurn": s._is_session_turn_current(session_id, turn_id),
                    "reason": "agent_llm_resolution_failed",
                },
            )
            s._set_session_running(session_id, False, turn_id=turn_id)
            s._clear_session_turn_control(session_id, turn_id=turn_id)
            s._publish_session_detail_snapshot(session_id)
            return
        prepare_timings["agentLlmResolveMs"] = s._elapsed_ms(stage_started_at)
    prepare_timings["totalPrepareMs"] = s._elapsed_ms(prepare_started_at)
    s._record_session_turn_lifecycle_event(
        session_id,
        "prepare_completed",
        turn_id=turn_id,
        outcome="completed",
        fields=s._session_turn_prepare_timing_log_fields(prepare_timings),
    )
    if _abort_session_turn_for_stop(
        session_id=session_id,
        turn_id=turn_id,
        turn_control=turn_control,
        stage="prepare_completed",
        mental_model_enabled=mental_model_enabled,
        context=context,
        finish_worker=True,
    ):
        return
    llm_model_id_for_turn = str(getattr(resolved_agent_llm, "model_id", "") or "") or s._session_agent_llm_slot_model_id(
        agent_instance or historical_agent,
        llm_slot,
    )
    llm_runtime_diagnostics = (
        resolved_agent_llm.log_fields()
        if resolved_agent_llm is not None
        else {"llmModelId": llm_model_id_for_turn}
    )
    source_collection_stage_task_auto_continue = s._source_collection_stage_task_context_metadata(context)
    source_collection_stage_task_required_tools = s._source_collection_stage_task_required_tool_names(context)
    task_workspace = s._session_task_workspace_for_turn(
        context,
        session_workspace=session_workspace,
        default_workspace=tool_workspace,
    )
    task_workspace_context = (
        s._session_tool_workspace_override(
            tool_workspace,
            memory_workspace=agent_workspace_path if agent_instance else tool_workspace,
            task_workspace=task_workspace,
        )
        if task_workspace != Path(tool_workspace)
        else s._session_tool_workspace_override(
            tool_workspace,
            memory_workspace=agent_workspace_path if agent_instance else tool_workspace,
        )
    )
    allow_internal_auto_continue = _session_context_allows_internal_auto_continue(context)
    internal_auto_continue_max_turns = _session_context_internal_auto_continue_max_turns(context)
    prompt_cache_partition = s._session_prompt_cache_partition(
        session_id=session_id,
        agent_id=agent_id,
        llm_slot=llm_slot,
        model_id=llm_model_id_for_turn,
        prompt_template_id=str((agent_instance or {}).get("promptTemplateId") or "").strip(),
        prompt_snapshot_hash=str((agent_prompt_snapshot or {}).get("contentHash") or "").strip()
        if isinstance(agent_prompt_snapshot, dict)
        else "",
    )
    prompt_cache_scope = s._session_prompt_cache_scope(agent_id=agent_id)
    s._record_session_turn_lifecycle_event(
        session_id,
        "worker_started",
        turn_id=turn_id,
        outcome="running",
        fields={
            "workspacePath": s._session_workspace_relative_path(session_id),
            "hasTurnControl": isinstance(turn_control, s.SessionTurnControl),
            "mentalModelEnabled": mental_model_enabled,
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
            "agentId": agent_id,
            "agentWorkspacePath": agent_workspace,
            "agentMemoryRoot": memory_root,
            "toolWorkspacePath": str(tool_workspace),
            "taskWorkspacePath": str(task_workspace),
            "taskWorkspaceIsolated": task_workspace != Path(tool_workspace),
            "toolWorkspaceScope": str(getattr(workspace_decision, "scope", "") or ""),
            "supervisedRuntimeRole": supervised_runtime_role,
            "supervisedRuntimeToolSource": (
                "supervised_baseline_self_edit"
                if supervised_runtime_tool_grants is not None
                else ("supervised_conversation_harness" if supervised_runtime_role else "")
            ),
            "externalRuntimePermissionProfile": external_runtime_permission_profile,
            **s._session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            "executorWaitMs": s._elapsed_ms_between(context.get("_executor_submitted_at_monotonic"), prepare_started_at),
            "schedulerToWorkerStartedMs": s._elapsed_ms_between(
                context.get("_scheduler_started_at_monotonic") or context.get("_scheduler_scheduled_at_monotonic"),
                s._perf_counter(),
            ),
            "hasAgentContextPacket": agent_context_packet is not None,
            "lightweightChatPayload": lightweight_chat_payload,
            "lightweightChatPayloadReason": lightweight_chat_payload_reason,
            "disableTools": lightweight_chat_payload,
            "internalAutoContinueAllowed": allow_internal_auto_continue,
            "internalAutoContinueMaxTurns": internal_auto_continue_max_turns,
            "sourceCollectionStageTaskAutoContinue": bool(source_collection_stage_task_auto_continue),
            "sourceCollectionStageTaskId": source_collection_stage_task_auto_continue.get("taskId", ""),
            "sourceCollectionStageRunId": source_collection_stage_task_auto_continue.get("runId", ""),
            **prepare_timings,
        },
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "agent_runtime_resolved",
        turn_id=turn_id,
        outcome="resolved" if agent_instance else "fallback",
        fields={
            "mode": "chat",
            "agentId": agent_id,
            "agentCode": str((agent_instance or {}).get("agentCode") or "").strip(),
            "dialogueModelId": s.agent_dialogue_model_id(agent_instance),
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
            "promptTemplateId": str((agent_instance or {}).get("promptTemplateId") or "").strip(),
            "roleKey": str((agent_instance or {}).get("roleKey") or "").strip(),
            "source": "AgentLlmBindings" if agent_instance else "missing_agent",
            **s._session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            **(resolved_agent_llm.log_fields() if resolved_agent_llm is not None else {}),
        },
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "prompt_cache_partition_bound",
        turn_id=turn_id,
        outcome="bound",
        fields={
            "scope": prompt_cache_scope,
            **s._session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            "agentId": agent_id,
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
        },
    )
    s._record_session_execution_registry_event(
        session_id,
        turn_id,
        "main_agent_loop",
        "running",
        details={"workspacePath": s._session_workspace_relative_path(session_id)},
    )
    s._record_session_execution_registry_event(
        session_id,
        turn_id,
        "mental_model",
        "enabled" if mental_model_enabled else "disabled",
        details={"perTurnOption": mental_model_enabled},
    )
    s._record_session_turn_trace_event(
        session_id,
        turn_id,
        "state",
        {"phase": "worker_started", "workspacePath": s._session_workspace_relative_path(session_id)},
        status="running",
        summary="Chat turn worker started.",
    )
    s._set_session_turn_progress_live_output(session_id, "agent_prepare", turn_id=turn_id)
    try:
        if agent_id and (not agent_instance or current_agent_status == "archived"):
            status = current_agent_status or str((historical_agent or {}).get("status") or "").strip().lower()
            reason = "archived_agent" if status == "archived" else "missing_agent"
            visible = s._session_agent_unavailable_message(reason, lang=s.get_web_language())
            s._record_session_agent_unavailable_event(
                session_id,
                agent_id=agent_id,
                reason=reason,
                agent_status=status,
            )
            s._persist_session_turn_result(
                session_id,
                {
                    "status": "failed_runtime",
                    "summary": visible,
                    "raw_output": visible,
                    "error": visible,
                    "outcome": "blocked",
                    "metadata": {"reason": reason},
                },
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace,
                active_task_hint=context.get("active_task"),
                user_message_source=str(context.get("user_message_source") or "").strip(),
                turn_id=turn_id,
            )
            return
        with (
            s.active_agent_runtime(
                agent_id,
                session_id=session_id,
                turn_id=turn_id,
                supervised_role=supervised_runtime_role,
                runtime_tool_grants=runtime_tool_grants,
                runtime_tool_source=runtime_tool_source,
                runtime_metadata=runtime_metadata,
            ),
            s.mental_model_enabled_override(mental_model_enabled),
            task_workspace_context,
        ):
            if _abort_session_turn_for_stop(
                session_id=session_id,
                turn_id=turn_id,
                turn_control=turn_control,
                stage="initial",
                mental_model_enabled=mental_model_enabled,
                context=context,
                finish_worker=False,
            ):
                return

            with s._capture_session_ui_stream(session_id, turn_capture, mental_model_enabled=mental_model_enabled):
                s._record_session_turn_lifecycle_event(
                    session_id,
                    "ui_capture_started",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "mentalModelEnabled": mental_model_enabled,
                    },
                )
                agent_prompt_template_id = str((agent_instance or {}).get("promptTemplateId") or "").strip()
                stage_started_at = s._perf_counter()
                runtime_agent, runtime_agent_cache = s._acquire_chat_agent_for_session(
                    session_id,
                    tool_workspace,
                    agent_instance=agent_instance,
                    llm_slot=llm_slot,
                    resolved_llm=resolved_agent_llm,
                    mode="supervised_evolution" if supervised_runtime_role else "chat",
                    prompt_snapshot_hash=str((agent_prompt_snapshot or {}).get("contentHash") or "").strip()
                    if isinstance(agent_prompt_snapshot, dict)
                    else "",
                )
                structured_output_setter = getattr(
                    runtime_agent,
                    "set_turn_structured_output_contract",
                    None,
                )
                if callable(structured_output_setter):
                    structured_output_setter(
                        _research_task_structured_output_contract(
                            context,
                            session_id=session_id,
                            turn_id=turn_id,
                        )
                    )
                agent_create_ms = s._elapsed_ms(stage_started_at)
                attachments = s._normalize_message_attachments(context.get("attachments") or [])
                resolved_llm_model_id = str(getattr(resolved_agent_llm, "model_id", "") or "").strip() or s._session_agent_llm_slot_model_id(
                    agent_instance or historical_agent,
                    llm_slot,
                )
                prompt_cache_partition = s._session_prompt_cache_partition(
                    session_id=session_id,
                    agent_id=agent_id,
                    llm_slot=llm_slot,
                    llm_model_id=resolved_llm_model_id,
                    prompt_template_id=agent_prompt_template_id,
                    prompt_snapshot_hash=str((agent_prompt_snapshot or {}).get("contentHash") or "").strip()
                    if isinstance(agent_prompt_snapshot, dict)
                    else "",
                )
                prompt_cache_scope = s._session_prompt_cache_scope(agent_id=agent_id)
                s._record_session_turn_lifecycle_event(
                    session_id,
                    "agent_created",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "agentType": type(runtime_agent).__name__,
                        "workspacePath": s._session_workspace_relative_path(session_id),
                        "toolWorkspacePath": str(tool_workspace),
                        "dialogueModelId": s.agent_dialogue_model_id(agent_instance or historical_agent),
                        "llmSlot": llm_slot,
                        "llmModelId": resolved_llm_model_id,
                        "agentId": agent_id,
                        "promptTemplateId": agent_prompt_template_id,
                        "promptSnapshotIncluded": bool(agent_prompt_snapshot_block),
                        "promptSnapshotContentHash": str((agent_prompt_snapshot or {}).get("contentHash") or "").strip()
                        if isinstance(agent_prompt_snapshot, dict)
                        else "",
                        **s._session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
                        "attachmentCount": len(attachments),
                        "agentCreateMs": agent_create_ms,
                        "agentRuntimeCacheStatus": str(runtime_agent_cache.get("status") or ""),
                        "agentRuntimeCacheHit": bool(runtime_agent_cache.get("hit")),
                        "agentRuntimeCacheEntryCount": s._coerce_nonnegative_int(
                            runtime_agent_cache.get("entryCount") or 0
                        ),
                        "lightweightChatPayload": lightweight_chat_payload,
                        "lightweightChatPayloadReason": lightweight_chat_payload_reason,
                        "disableTools": lightweight_chat_payload,
                        **(resolved_agent_llm.log_fields() if resolved_agent_llm is not None else {}),
                    },
                )
                mental_override_configurer = getattr(runtime_agent, "set_mental_model_enabled_override", None)
                if callable(mental_override_configurer):
                    mental_override_configurer(mental_model_enabled)
                runtime_status_override_configurer = getattr(
                    runtime_agent,
                    "set_runtime_status_enabled_override",
                    None,
                )
                if callable(runtime_status_override_configurer):
                    runtime_status_override_configurer(runtime_status_enabled)
                tail_config_setter = getattr(runtime_agent, "set_turn_status_tail_config", None)
                if callable(tail_config_setter):
                    raw_tail = context.get("turn_status_tail")
                    tail_config_setter(raw_tail if isinstance(raw_tail, dict) else None)
                tail_context_setter = getattr(runtime_agent, "set_turn_status_tail_context", None)
                if callable(tail_context_setter):
                    active_task = context.get("active_task")
                    task_text = ""
                    if isinstance(active_task, dict):
                        task_text = str(
                            active_task.get("title")
                            or active_task.get("summary")
                            or active_task.get("goal")
                            or ""
                        ).strip()
                    user_message = str(context.get("user_message") or "").strip()
                    if not task_text and user_message:
                        task_text = user_message[:200]
                    tail_context_setter(
                        session_id=str(session_id or "").strip(),
                        agent_id=str(agent_id or "").strip(),
                        task=task_text,
                        worktree="",
                        cache_hint=None,
                    )
                static_runtime_context_seed = getattr(runtime_agent, "seed_static_runtime_context", None)
                runtime_context_seed = getattr(runtime_agent, "seed_runtime_context", None)
                volatile_runtime_context_seed = getattr(runtime_agent, "seed_volatile_runtime_context", None)
                stop_configurer = getattr(runtime_agent, "set_turn_interrupt_checker", None)
                if callable(stop_configurer):
                    stop_configurer(interrupt_checker)
                history_assembly_started_at = s._perf_counter()
                raw_history_messages = list(context.get("history_messages") or [])
                seedable_history_messages = s._history_messages_for_agent_seed(
                    raw_history_messages,
                    exclude_turn_id=turn_id,
                )
                conversation_ledger_events = s._load_session_conversation_events_cached(session_id)
                conversation_context_events = [
                    event
                    for event in conversation_ledger_events
                    if str(getattr(event, "turn_id", "") or "").strip() != str(turn_id or "").strip()
                ]
                if not conversation_context_events:
                    conversation_context_events = None
                normalized_user_message_source = str(context.get("user_message_source") or "").strip()
                history_seed_profile = "agent_inbox" if normalized_user_message_source == "agent_inbox" else "full"
                context_assembly_kwargs = {
                    "session_id": session_id,
                    "current_turn_id": turn_id,
                    "ledger_events": conversation_context_events,
                    "history_seed_profile": history_seed_profile,
                    "tool_result_replacement_char_limit": 900 if history_seed_profile == "agent_inbox" else 12_000,
                }
                if history_seed_profile == "full":
                    context_assembly_kwargs["recent_message_limit"] = None
                context_assembly = s.assemble_conversation_context(
                    seedable_history_messages,
                    **context_assembly_kwargs,
                )
                history_messages = context_assembly.history_messages
                history_assembly_ms = s._elapsed_ms(history_assembly_started_at)
                full_history_message_count = len(seedable_history_messages)
                runtime_context_segments = (
                    s._session_context_segments_without_prompt_template(
                        getattr(agent_context_packet, "context_segments", []) if agent_context_packet is not None else []
                    )
                    if agent_context_packet is not None
                    else []
                )
                prompt_snapshot_segment = s._prompt_snapshot_context_segment(agent_prompt_snapshot_block, agent_prompt_snapshot)
                if prompt_snapshot_segment:
                    runtime_context_segments.insert(0, prompt_snapshot_segment)
                research_thinking_budget_segment = build_research_thinking_budget_segment(
                    session_id,
                    project_root=s.PROJECT_ROOT,
                    load_chat_state=s.load_session_chat_state,
                )
                if research_thinking_budget_segment:
                    # Appended last so the hard budget line sits at the tail of
                    # the static system context (recency advantage).
                    runtime_context_segments.append(research_thinking_budget_segment)
                static_runtime_context_block = s._session_context_segments_block(runtime_context_segments, "cache_prefix")
                dynamic_runtime_context_block = s._session_context_segments_block(runtime_context_segments, "volatile_turn")
                runtime_context_block = (
                    str(getattr(agent_context_packet, "context_block", "") or "").strip()
                    if agent_context_packet is not None
                    else ""
                )
                if runtime_context_block and not static_runtime_context_block and not dynamic_runtime_context_block:
                    dynamic_runtime_context_block = runtime_context_block
                supervised_workspace_context_block = ""
                if supervised_workspace_override is not None:
                    resolved_tool_workspace = Path(tool_workspace).resolve()
                    supervised_workspace_context_block = "\n".join(
                        [
                            "## Supervised Execution Workspace",
                            f"RepositoryRoot: {resolved_tool_workspace}",
                            f"ToolWorkspace: {resolved_tool_workspace}",
                            "AgentWorkspace is identity/private-memory only; do not use it as CLI cwd.",
                            "Use RepositoryRoot or ToolWorkspace for repository commands and file operations.",
                        ]
                    )
                    dynamic_runtime_context_block = "\n\n".join(
                        part
                        for part in (dynamic_runtime_context_block, supervised_workspace_context_block)
                        if str(part or "").strip()
                    ).strip()
                runtime_context_block = "\n\n".join(
                    part
                    for part in (static_runtime_context_block, dynamic_runtime_context_block)
                    if str(part or "").strip()
                ).strip()
                guidance_context_block = s._recent_session_guidance_context_block(session_id)
                skill_invocation = context.get("skill_invocation")
                skill_runtime_context_block = s._skill_runtime_context_from_invocation(skill_invocation)
                active_skill_contract = s.refresh_active_skill_contract_status(context.get("active_skill_contract"))
                active_skill_context_block = (
                    ""
                    if skill_runtime_context_block
                    else s._active_skill_runtime_context_from_contract(active_skill_contract)
                )
                skill_runtime_context_included = False
                active_skill_context_included = False
                dynamic_runtime_context_included = False
                seed_started_at = s._perf_counter()
                static_runtime_context_seed_ms = 0
                runtime_context_seed_ms = 0
                skill_context_seed_ms = 0
                active_skill_context_seed_ms = 0
                host_context_marker = getattr(runtime_agent, "mark_runtime_context_seeded_by_host", None)
                core_prompt_snapshot_marker = getattr(
                    runtime_agent,
                    "mark_core_prompt_snapshot_seeded_by_host",
                    None,
                )
                host_seeded_agent_context = False
                if static_runtime_context_block:
                    static_stage_started_at = s._perf_counter()
                    if callable(static_runtime_context_seed):
                        static_runtime_context_seed(static_runtime_context_block)
                        host_seeded_agent_context = True
                    elif callable(runtime_context_seed):
                        legacy_context_block = (
                            runtime_context_block
                            if dynamic_runtime_context_block and not callable(volatile_runtime_context_seed)
                            else static_runtime_context_block
                        )
                        runtime_context_seed(legacy_context_block)
                        host_seeded_agent_context = True
                        dynamic_runtime_context_included = legacy_context_block == runtime_context_block and bool(
                            dynamic_runtime_context_block
                        )
                    static_runtime_context_seed_ms = s._elapsed_ms(static_stage_started_at)
                if host_seeded_agent_context and callable(host_context_marker):
                    host_context_marker()
                core_prompt_snapshot_seeded = (
                    host_seeded_agent_context
                    and bool(prompt_snapshot_segment)
                    and int((agent_prompt_snapshot or {}).get("corePromptSchemaVersion") or 0) > 0
                )
                if callable(core_prompt_snapshot_marker):
                    core_prompt_snapshot_marker(core_prompt_snapshot_seeded)
                if dynamic_runtime_context_block and callable(volatile_runtime_context_seed):
                    runtime_stage_started_at = s._perf_counter()
                    volatile_runtime_context_seed(dynamic_runtime_context_block)
                    dynamic_runtime_context_included = True
                    runtime_context_seed_ms = s._elapsed_ms(runtime_stage_started_at)
                if skill_runtime_context_block:
                    skill_stage_started_at = s._perf_counter()
                    if callable(volatile_runtime_context_seed):
                        volatile_runtime_context_seed(skill_runtime_context_block)
                        skill_runtime_context_included = True
                    skill_context_seed_ms = s._elapsed_ms(skill_stage_started_at)
                    s._record_session_skill_command_event(
                        session_id,
                        turn_id=turn_id,
                        invocation=skill_invocation,
                        outcome="routed",
                    )
                if active_skill_context_block:
                    active_skill_stage_started_at = s._perf_counter()
                    if callable(volatile_runtime_context_seed):
                        volatile_runtime_context_seed(active_skill_context_block)
                        active_skill_context_included = True
                    active_skill_context_seed_ms = s._elapsed_ms(active_skill_stage_started_at)
                s._record_session_turn_lifecycle_event(
                    session_id,
                    "history_assembled",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "rawHistoryMessageCount": len(list(context.get("history_messages") or [])),
                        "fullSeedableHistoryMessageCount": full_history_message_count,
                        "assembledHistoryMessageCount": len(history_messages),
                        "historyLedgerEventCount": len(context_assembly.events),
                        "historyIncludedEventCount": len(context_assembly.included_event_ids),
                        "historyOmittedEventCount": context_assembly.omitted_event_count,
                        "historyCheckpointEventId": context_assembly.checkpoint_event_id,
                        "agentRuntimeContextIncluded": bool(static_runtime_context_block),
                        "staticRuntimeContextIncluded": bool(static_runtime_context_block),
                        "promptSnapshotIncluded": bool(agent_prompt_snapshot_block),
                        "promptSnapshotContentHash": str((agent_prompt_snapshot or {}).get("contentHash") or "").strip()
                        if isinstance(agent_prompt_snapshot, dict)
                        else "",
                        "corePromptSnapshotSeeded": core_prompt_snapshot_seeded,
                        "corePromptSchemaVersion": int(
                            (agent_prompt_snapshot or {}).get("corePromptSchemaVersion") or 0
                        ),
                        "dynamicRuntimeContextIncluded": dynamic_runtime_context_included,
                        "dynamicRuntimeContextAvailable": bool(dynamic_runtime_context_block),
                        "supervisedWorkspaceContextIncluded": bool(supervised_workspace_context_block),
                        "dynamicRuntimeContextOmittedFromModelInput": bool(dynamic_runtime_context_block)
                        and not dynamic_runtime_context_included,
                        "runtimeContextSegmentCount": len(runtime_context_segments),
                        "agentRuntimeContextSkipped": bool(lightweight_chat_payload),
                        "guidanceContextIncluded": False,
                        "guidanceContextAvailable": bool(guidance_context_block),
                        "guidanceContextOmittedFromModelInput": bool(guidance_context_block),
                        "skillRuntimeContextIncluded": skill_runtime_context_included,
                        "skillRuntimeContextAvailable": bool(skill_runtime_context_block),
                        "skillRuntimeContextOmittedFromModelInput": bool(skill_runtime_context_block)
                        and not skill_runtime_context_included,
                        "skillRuntimeContextPlacement": (
                            "before_current_user"
                            if skill_runtime_context_included
                            else "omitted_no_volatile_context_seed"
                            if skill_runtime_context_block
                            else ""
                        ),
                        "activeSkillContractAvailable": bool(active_skill_contract),
                        "activeSkillContextIncluded": active_skill_context_included,
                        "activeSkillContextAvailable": bool(active_skill_context_block),
                        "activeSkillContextOmittedFromModelInput": bool(active_skill_context_block)
                        and not active_skill_context_included,
                        "activeSkillContextPlacement": (
                            "before_current_user"
                            if active_skill_context_included
                            else "omitted_no_volatile_context_seed"
                            if active_skill_context_block
                            else ""
                        ),
                        "activeSkillContractStatus": str((active_skill_contract or {}).get("status") or "").strip(),
                        "activeSkillContractSkillHash": str((active_skill_contract or {}).get("skillHash") or "").strip(),
                        "lightweightChatPayload": lightweight_chat_payload,
                        "lightweightChatPayloadReason": lightweight_chat_payload_reason,
                        "disableTools": lightweight_chat_payload,
                        "restoreAvailable": callable(getattr(runtime_agent, "seed_chat_history", None)),
                        "staticRuntimeContextSeedAvailable": callable(static_runtime_context_seed),
                        "runtimeContextSeedAvailable": callable(runtime_context_seed),
                        "volatileRuntimeContextSeedAvailable": callable(volatile_runtime_context_seed),
                        "historyAssemblyMs": history_assembly_ms,
                        "staticRuntimeContextSeedMs": static_runtime_context_seed_ms,
                        "runtimeContextSeedMs": runtime_context_seed_ms,
                        "skillContextSeedMs": skill_context_seed_ms,
                        "activeSkillContextSeedMs": active_skill_context_seed_ms,
                        "totalSeedMs": s._elapsed_ms(seed_started_at),
                    },
                )

                preflight_stop_reason = s._get_turn_control_stop_reason(turn_control)
                if preflight_stop_reason:
                    s._record_session_turn_lifecycle_event(
                        session_id,
                        "stop_observed",
                        turn_id=turn_id,
                        outcome="stopped",
                        fields={
                            "stage": "preflight",
                            "stopReason": trim_lines(preflight_stop_reason, max_lines=2),
                        },
                    )
                    s._persist_session_turn_result(
                        session_id,
                        s._build_stopped_turn_result(preflight_stop_reason),
                        mental_model_enabled=mental_model_enabled,
                        active_task_hint=context.get("active_task"),
                        user_message_source=str(context.get("user_message_source") or "").strip(),
                        turn_id=turn_id,
                    )
                    return

                user_message = str(context.get("user_message") or "").strip()
                llm_attachments = s._build_llm_image_attachments(session_id, attachments)
                if attachments:
                    s._record_session_turn_trace_event(
                        session_id,
                        turn_id,
                        "attachments",
                        {
                            "attachmentCount": len(attachments),
                            "llmAttachmentCount": len(llm_attachments),
                            "attachments": s._safe_attachment_log_summary(attachments),
                        },
                        status="running",
                        summary="User image attachments prepared for this turn.",
                    )
                context_composition = s._build_last_context_composition(
                    conversation={
                        "id": session_id,
                        "agentId": agent_id,
                        "_agent": agent_instance or historical_agent,
                    },
                    turn_id=turn_id,
                    user_message=user_message,
                    history_messages=history_messages,
                    active_task=context.get("active_task"),
                    runtime_context_block=static_runtime_context_block,
                    dynamic_runtime_context_block=dynamic_runtime_context_block,
                    dynamic_runtime_context_included=dynamic_runtime_context_included,
                    runtime_context_segments=runtime_context_segments,
                    guidance_context_block=guidance_context_block,
                    guidance_context_included=False,
                    skill_runtime_context_block=skill_runtime_context_block,
                    skill_runtime_context_included=skill_runtime_context_included,
                    active_skill_context_block=active_skill_context_block,
                    active_skill_context_included=active_skill_context_included,
                    attachments=attachments,
                    prompt_cache_partition=prompt_cache_partition,
                )
                context_composition["contextAssembly"] = context_assembly.to_composition_patch()
                context_cache = (
                    context_composition.get("cache")
                    if isinstance(context_composition.get("cache"), dict)
                    else {}
                )
                s._append_session_conversation_event(
                    session_id,
                    turn_id,
                    s.EVENT_TURN_CONTEXT,
                    status="recorded",
                    payload={
                        "historyMessageCount": len(history_messages),
                        "ledgerEventCount": len(conversation_ledger_events),
                        "historyLedgerEventCount": len(context_assembly.events),
                        "includedEventIds": list(context_assembly.included_event_ids),
                        "omittedEventCount": context_assembly.omitted_event_count,
                        "contextAssembly": context_assembly.to_composition_patch(),
                    },
                    source="session_context_assembler",
                )
                s._record_session_turn_lifecycle_event(
                    session_id,
                    "context_composition_recorded",
                    turn_id=turn_id,
                    outcome="recorded",
                    fields={
                        "segmentCount": len(context_composition.get("segments") or []),
                        "totalChars": s._coerce_nonnegative_int(context_composition.get("totalChars") or 0),
                        "totalTokens": s._coerce_nonnegative_int(context_composition.get("totalTokens") or 0),
                        "limitTokens": s._coerce_nonnegative_int(context_composition.get("limitTokens") or 0),
                        "limitSource": str(context_composition.get("limitSource") or "").strip(),
                        "limitModelId": str(context_composition.get("limitModelId") or "").strip(),
                        "limitAgentId": str(context_composition.get("limitAgentId") or "").strip(),
                        "schemaVersion": s._coerce_nonnegative_int(context_composition.get("schemaVersion") or 0),
                        "cacheableSegmentCount": s._coerce_nonnegative_int(
                            context_cache.get("cacheableSegmentCount") or 0
                        ),
                        "volatileSegmentCount": s._coerce_nonnegative_int(
                            context_cache.get("volatileSegmentCount") or 0
                        ),
                    },
                )
                s._set_session_live_context_composition(session_id, context_composition, turn_id=turn_id)
                # Context composition is already available through live output and the
                # conversation journal.  A durable WorkRun rewrite here blocks the
                # imminent model request and is immediately superseded by model_request.
                if not _proactive_turn_is_current(context):
                    _cancel_stale_proactive_turn(
                        context,
                        reason="binding_revision_fence_before_model_request",
                    )
                    return
                tool_scope = ToolExecutionScope(session_id=session_id, turn_id=turn_id)
                with (
                    s.session_reference_context(context.get("session_references") or []),
                    tool_execution_scope(tool_scope),
                ):
                    try:
                        result = _run_session_continuation_loop(
                            runtime_agent,
                            context=context,
                            session_id=session_id,
                            turn_control=turn_control,
                            initial_prompt=user_message,
                            history_messages=history_messages,
                            attachments=llm_attachments,
                            turn_capture=turn_capture,
                            user_message_source=str(context.get("user_message_source") or "").strip(),
                            prompt_cache_partition=prompt_cache_partition,
                            prompt_cache_scope=prompt_cache_scope,
                            agent_id=agent_id,
                            llm_slot=llm_slot,
                            llm_model_id=llm_model_id_for_turn,
                            disable_tools=lightweight_chat_payload,
                            allow_internal_auto_continue=allow_internal_auto_continue,
                            max_internal_auto_continue_turns=internal_auto_continue_max_turns,
                            require_tool_progress=bool(source_collection_stage_task_auto_continue),
                            required_tool_names=source_collection_stage_task_required_tools,
                            static_runtime_context_block=(
                                static_runtime_context_block if host_seeded_agent_context else ""
                            ),
                            volatile_runtime_context_block="\n\n".join(
                                part
                                for part in (
                                    dynamic_runtime_context_block if dynamic_runtime_context_included else "",
                                    skill_runtime_context_block if skill_runtime_context_included else "",
                                    active_skill_context_block if active_skill_context_included else "",
                                )
                                if str(part or "").strip()
                            ),
                        )
                    finally:
                        _wait_for_tool_execution_quiescence(tool_scope)
                if isinstance(result, dict):
                    result = _attach_runtime_prompt_assembly_manifest(result, runtime_agent)
                    result["context_composition"] = context_composition
                    result = s._attach_session_llm_runtime_diagnostics(result, llm_runtime_diagnostics)
            result = s._attach_turn_capture_to_result(
                result,
                turn_capture,
                mental_model_enabled=mental_model_enabled,
            )
            s._record_session_turn_lifecycle_event(
                session_id,
                "capture_attached",
                turn_id=turn_id,
                outcome="recorded",
                fields={
                    "hasThought": bool(turn_capture.thought),
                    "hasContent": bool(turn_capture.content),
                    "hasMentalState": bool(turn_capture.mental_state),
                    "toolCallCount": len(turn_capture.tool_calls),
                },
            )
            if not _proactive_turn_is_current(context):
                _cancel_stale_proactive_turn(
                    context,
                    reason="binding_revision_fence_before_assistant_persist",
                )
                return
            s._persist_session_turn_result(
                session_id,
                result,
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace,
                active_task_hint=context.get("active_task"),
                user_message_source=str(context.get("user_message_source") or "").strip(),
                turn_id=turn_id,
            )
            _finalize_proactive_delivery_after_persist(context)
            if s._is_session_turn_current(session_id, turn_id):
                s._set_session_running(session_id, False, turn_id=turn_id)
                s._publish_session_detail_snapshot(session_id)
                s._record_session_turn_lifecycle_event(
                    session_id,
                    "user_visible_finished",
                    turn_id=turn_id,
                    outcome="completed",
                    fields={
                        "resultStatus": str(result.get("status") or "completed").strip()
                        if isinstance(result, dict)
                        else "completed",
                        "finalDetailPublished": True,
                    },
                )
            if agent_id and s._is_session_turn_current(session_id, turn_id):
                s.record_agent_turn_result(agent_id, session_id, result if isinstance(result, dict) else {}, run_id=turn_id)
    except Exception as exc:
        deadline_cancelled = _is_challenge_deadline_cancelled(
            context,
            exc,
            turn_id=turn_id,
        )
        s._record_session_turn_lifecycle_event(
            session_id,
            "exception",
            turn_id=turn_id,
            level="warning" if deadline_cancelled else "error",
            outcome="stopped" if deadline_cancelled else "failed",
            fields={
                "exceptionType": type(exc).__name__,
                "errorPreview": trim_lines(str(exc), max_lines=2),
                "reasonCode": (
                    "challenge_logical_task_deadline_exhausted"
                    if deadline_cancelled
                    else ""
                ),
            },
        )
        if s._is_session_turn_current(session_id, turn_id):
            if deadline_cancelled:
                s._persist_session_turn_result(
                    session_id,
                    s._build_stopped_turn_result(
                        "challenge_logical_task_deadline_exhausted"
                    ),
                    mental_model_enabled=mental_model_enabled,
                    active_task_hint=context.get("active_task"),
                    user_message_source=str(context.get("user_message_source") or "").strip(),
                    turn_id=turn_id,
                )
            else:
                s._persist_session_turn_failure(session_id, context, exc)
    finally:
        from core.agent_plugins.runtime_extensions import is_agent_plugin_proactive_turn

        if is_agent_plugin_proactive_turn(context):
            from core.web.services.session.proactive import (
                release_proactive_turn_context,
            )

            release_proactive_turn_context(context)
        _finish_session_turn_worker(session_id, turn_id, turn_control)


def _turn_llm_usage_tokens(result: Any) -> int:
    """Total input+output tokens reported by one LLM invocation receipt.

    Mirrors ``_normalize_turn_llm_usage`` key tolerance (snake/camel case) and
    falls back to the receipt's ``total_tokens`` when the split is missing.
    Non-dict or usage-less results simply contribute zero.
    """

    if not isinstance(result, dict):
        return 0
    usage = result.get("llm_usage") if isinstance(result.get("llm_usage"), dict) else {}

    def _usage_int(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return 0

    input_tokens = _usage_int("input_tokens", "inputTokens")
    output_tokens = _usage_int("output_tokens", "outputTokens")
    if input_tokens or output_tokens:
        return input_tokens + output_tokens
    return _usage_int("total_tokens", "totalTokens")


def _agent_active_turn_context_lost(agent: Any) -> bool:
    """True when the agent no longer holds same-turn conversation context.

    A chat agent that ends an iteration through its terminal lifecycle
    (``turn_complete`` carryover) wipes ``_active_turn_messages`` before the
    worker dispatches the next internal continuation prompt. That follow-up
    carryover must then be re-seeded from the unified ledger assembly;
    dispatching it while the agent context is gone sends a bare prompt
    (isolated message, no history/system context — amnesia-style replies).
    Agents without the export protocol keep the legacy in-memory behavior.
    """

    export = getattr(agent, "export_turn_carryover", None)
    if not callable(export):
        return False
    try:
        payload = export()
    except Exception:
        return False
    if not isinstance(payload, dict):
        return True
    if payload.get("terminal") is True:
        return True
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return True
    return not messages


def _reseed_agent_turn_context_blocks(agent: Any, *, static_block: str, volatile_block: str) -> None:
    """Re-apply the host runtime context seeds lost with a terminal wipe."""

    static_block = str(static_block or "").strip()
    volatile_block = str(volatile_block or "").strip()
    if static_block:
        static_seed = getattr(agent, "seed_static_runtime_context", None)
        if callable(static_seed):
            static_seed(static_block)
    if volatile_block:
        volatile_seed = getattr(agent, "seed_volatile_runtime_context", None)
        if callable(volatile_seed):
            volatile_seed(volatile_block)


def _session_turn_token_budget_line(
    receipt_context: dict[str, Any] | None,
) -> tuple[int, str]:
    """Resolve the real-time token circuit-breaker line for one session turn.

    Workflow Ledger reservations are soft accounting signals and therefore do
    not own termination. Formal Challenge turns retain the session emergency
    line; ordinary chat keeps the same default under its existing source name.
    """

    if isinstance(receipt_context, dict):
        return DEFAULT_SESSION_TOKEN_BUDGET, "challenge_emergency_default"
    return DEFAULT_SESSION_TOKEN_BUDGET, "session_default"


def _run_session_continuation_loop(
    agent: Any,
    *,
    context: dict[str, Any],
    session_id: str,
    turn_control: Any = None,
    initial_prompt: str,
    history_messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
    turn_capture: Any = None,
    user_message_source: str = "",
    prompt_cache_partition: str = "",
    prompt_cache_scope: str = "chat_session",
    agent_id: str = "",
    llm_slot: str = "dialogue",
    llm_model_id: str = "",
    disable_tools: bool = False,
    allow_internal_auto_continue: bool = False,
    max_internal_auto_continue_turns: int = 3,
    require_tool_progress: bool = False,
    required_tool_names: list[str] | None = None,
    static_runtime_context_block: str = "",
    volatile_runtime_context_block: str = "",
) -> Any:
    s = _service()
    prompt = str(initial_prompt or "").strip()
    has_initial_attachments = bool(list(attachments or []))
    normalized_user_message_source = str(user_message_source or "").strip()
    auto_continue_turn_limit = max(1, s._coerce_nonnegative_int(max_internal_auto_continue_turns) or s.INTERNAL_AUTO_CONTINUE_MAX_TURNS)
    # Real-time token fuse state: session-scoped counters for this turn's
    # continuation loop only (no cross-session or cross-turn shared state), so
    # concurrent sessions stay isolated and replays stay idempotent.
    canonical_turn_id = str(getattr(turn_control, "turn_id", "") or "").strip()
    receipt_context = _model_invocation_receipt_context(
        context,
        session_id=session_id,
        turn_id=canonical_turn_id,
    )
    token_budget_line, token_budget_source = _session_turn_token_budget_line(
        receipt_context
    )
    cumulative_session_tokens = 0
    normalized_required_tool_names = [
        str(item or "").strip()
        for item in list(required_tool_names or [])
        if str(item or "").strip()
    ]
    if (
        normalized_user_message_source == "agent_inbox"
        and not has_initial_attachments
        and not s._is_continue_request(prompt)
        and not s._is_effective_user_message(prompt)
    ):
        s._record_session_turn_lifecycle_event(
            session_id,
            "agent_inbox_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "reason": "agent_inbox_protocol_message",
                "messageLength": len(prompt),
                "fallbackSkipped": True,
            },
        )
    elif not has_initial_attachments and not s._is_effective_user_message(prompt):
        s._record_session_turn_lifecycle_event(
            session_id,
            "raw_dialogue_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "messageLength": len(prompt),
                "questionMarkCount": prompt.count("?"),
                "userMessageSource": normalized_user_message_source,
                "semanticRewriteSkipped": True,
            },
        )
    if s._is_continue_request(prompt):
        s._record_session_turn_lifecycle_event(
            session_id,
            "continue_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "messageLength": len(prompt),
                "historyMessageCount": len(history_messages),
                "semanticRewriteSkipped": True,
            },
        )

    result: Any = None
    last_visible_result: dict[str, Any] | None = None
    observed_required_tool_names: set[str] = set()
    observed_tool_signatures: set[str] = set()
    consecutive_no_progress_turns = 0
    continuation_progress_advanced = False
    if not history_messages:
        clear_provider_replay = getattr(agent, "clear_chat_provider_replay_state", None)
        if callable(clear_provider_replay):
            clear_provider_replay()
    turn_index = 0
    while True:
        turn_index += 1
        stop_reason = s._get_turn_control_stop_reason(turn_control) or s._get_session_stop_reason(session_id)
        if stop_reason:
            s._record_session_turn_lifecycle_event(
                session_id,
                "stop_observed",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="stopped",
                fields={
                    "stage": "continuation_preflight",
                    "turnIndex": turn_index,
                    "stopReason": trim_lines(stop_reason, max_lines=2),
                },
            )
            return s._build_stopped_turn_result(stop_reason)

        s._record_session_turn_lifecycle_event(
            session_id,
            "agent_turn_started",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "turnIndex": turn_index,
                "promptLength": len(prompt),
                "historyMessageCount": len(history_messages),
                "promptCacheScope": str(prompt_cache_scope or "").strip(),
                "promptCachePartition": str(prompt_cache_partition or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "llmSlot": str(llm_slot or "").strip(),
                "llmModelId": str(llm_model_id or "").strip(),
                "disableTools": bool(disable_tools),
                "internalAutoContinueAllowed": bool(allow_internal_auto_continue),
                "internalAutoContinueMaxTurns": auto_continue_turn_limit,
                "tokenBudgetLine": token_budget_line,
                "tokenBudgetSource": token_budget_source,
                "cumulativeSessionTokens": cumulative_session_tokens,
            },
        )
        s._record_session_execution_registry_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "llm_turn",
            "running",
            details={
                "turnIndex": turn_index,
                "promptLength": len(prompt),
                "disableTools": bool(disable_tools),
            },
        )
        s._record_session_turn_trace_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "state",
            {"phase": "agent_turn_started", "turnIndex": turn_index},
            status="running",
            summary="Agent turn started.",
        )
        s._set_session_turn_progress_live_output(
            session_id,
            "model_request",
            turn_id=getattr(turn_control, "turn_id", ""),
        )
        turn_attachments = list(attachments or []) if turn_index == 1 else []
        llm_started_at = s._perf_counter()
        s._set_session_model_thinking_live_output(
            session_id,
            turn_id=getattr(turn_control, "turn_id", ""),
        )
        from core.llm.client import model_invocation_receipt_context_scope

        if turn_capture is not None:
            turn_capture.model_invocation_receipt_context = receipt_context
        with model_invocation_receipt_context_scope(receipt_context):
            chat_history_ledger_fingerprint = ""
            iteration_chat_history = history_messages if turn_index == 1 else None
            if (
                iteration_chat_history is None
                and history_messages
                and _agent_active_turn_context_lost(agent)
            ):
                # The previous iteration ended through the agent's terminal
                # lifecycle, which wiped its in-memory conversation. The
                # follow-up carryover must go out through the same unified
                # ledger assembly as the first iteration instead of a bare
                # prompt; the host runtime context lost with the wipe is
                # re-seeded alongside the history.
                iteration_chat_history = history_messages
                _reseed_agent_turn_context_blocks(
                    agent,
                    static_block=static_runtime_context_block,
                    volatile_block=volatile_runtime_context_block,
                )
            if iteration_chat_history:
                from core.orchestration.turn_message_assembly import (
                    ledger_seeded_history_fingerprint,
                )

                # Provenance stamp for the send-time ledger gate: the seed
                # below is assembled from this ledger state, and windowing or
                # compaction may legally rewrite its contents.
                chat_history_ledger_fingerprint = ledger_seeded_history_fingerprint(
                    s._load_session_conversation_events_cached(session_id),
                    turn_id=canonical_turn_id,
                )
            result = s.run_existing_agent_single_turn(
                agent,
                initial_prompt=prompt,
                attachments=turn_attachments,
                disable_tools=disable_tools,
                prompt_cache_partition=prompt_cache_partition,
                turn_identity=canonical_turn_id,
                chat_history=iteration_chat_history,
                chat_history_ledger_fingerprint=chat_history_ledger_fingerprint,
            )
            # The LLM response callback cannot raise through EventBus. Convert
            # its fail-closed marker into the normal worker exception path
            # before any continuation or success persist.
            _raise_for_challenge_receipt_failure(turn_capture)
        result = s._attach_session_prompt_cache_metadata(
            result,
            prompt_cache_scope=prompt_cache_scope,
            prompt_cache_partition=prompt_cache_partition,
            llm_model_id=llm_model_id,
        )
        llm_elapsed_ms = s._elapsed_ms(llm_started_at)
        return_stop_reason = s._get_turn_control_stop_reason(turn_control) or s._get_session_stop_reason(session_id)
        if return_stop_reason:
            s._record_session_turn_lifecycle_event(
                session_id,
                "stop_observed",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="stopped",
                fields={
                    "stage": "agent_return",
                    "turnIndex": turn_index,
                    "stopReason": trim_lines(return_stop_reason, max_lines=2),
                    "llmElapsedMs": llm_elapsed_ms,
                },
            )
            return s._build_stopped_turn_result(return_stop_reason)

        # LLM receipt is in hand: fold this invocation's usage into the
        # session-turn token counter checked by the real-time fuse below.
        cumulative_session_tokens += _turn_llm_usage_tokens(result)

        result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else type(result).__name__
        result_visible_reply = s._visible_reply_candidate(result) if isinstance(result, dict) else ""
        result_contract = s.build_chat_coding_result_contract(result) if isinstance(result, dict) else {}
        observed_required_tool_names.update(
            name
            for name in s._result_tool_names(result)
            if name in normalized_required_tool_names
        )
        required_tool_progress_missing = s._required_tool_progress_missing(
            result,
            require_tool_progress=bool(require_tool_progress),
            required_tool_names=normalized_required_tool_names,
            observed_tool_names=observed_required_tool_names,
        )
        s._record_session_turn_lifecycle_event(
            session_id,
            "agent_turn_returned",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome=result_status or "returned",
            fields={
                "turnIndex": turn_index,
                "resultStatus": result_status,
                "toolCallCount": s._coerce_nonnegative_int(result.get("tool_call_count") or 0) if isinstance(result, dict) else 0,
                "hasVisibleReply": bool(result_visible_reply),
                "contractOutcome": str(result_contract.get("outcome") or "").strip().lower(),
                "explicitOutcome": s._explicit_chat_result_outcome(result) if isinstance(result, dict) else "",
                "outcomeSource": s._chat_result_outcome_source(result) if isinstance(result, dict) else "",
                "visibleHasConclusion": s.has_conclusion_signal(result_visible_reply),
                "visibleHasNextAction": s.has_next_action_signal(result_visible_reply),
                "isProviderFailed": s._is_provider_failed_result(result),
                "llmElapsedMs": llm_elapsed_ms,
                "promptCacheScope": str(prompt_cache_scope or "").strip(),
                "promptCachePartition": str(prompt_cache_partition or "").strip(),
                "llmModelId": str(llm_model_id or "").strip(),
                "requiredToolProgressMissing": bool(required_tool_progress_missing),
            },
        )
        s._record_session_execution_registry_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "llm_turn",
            result_status or "returned",
            details={
                "turnIndex": turn_index,
                "resultStatus": result_status,
                "toolCallCount": s._coerce_nonnegative_int(result.get("tool_call_count") or 0) if isinstance(result, dict) else 0,
                "durationMs": llm_elapsed_ms,
            },
        )
        if not required_tool_progress_missing:
            last_visible_result = s._remember_continuation_visible_result(result, last_visible_result)
        if s._is_provider_failed_result(result):
            s._record_session_turn_circuit_breaker_event(
                session_id,
                result,
                turn_id=getattr(turn_control, "turn_id", ""),
                turn_index=turn_index,
            )
            return s._annotate_continuation_result(result, turn_index, reached_limit=False)
        if s._is_session_turn_terminal(result) and not required_tool_progress_missing:
            result = s._merge_continuation_visible_result(result, last_visible_result)
            terminal_visible_reply = s._visible_reply_candidate(result) if isinstance(result, dict) else ""
            terminal_contract = s.build_chat_coding_result_contract(result) if isinstance(result, dict) else {}
            s._record_session_turn_lifecycle_event(
                session_id,
                "terminal_result",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="completed",
                fields={
                    "turnIndex": turn_index,
                    "resultStatus": result_status,
                    "contractOutcome": str(terminal_contract.get("outcome") or "").strip().lower(),
                    "explicitOutcome": s._explicit_chat_result_outcome(result) if isinstance(result, dict) else "",
                    "outcomeSource": s._chat_result_outcome_source(result) if isinstance(result, dict) else "",
                    "visibleHasConclusion": s.has_conclusion_signal(terminal_visible_reply),
                    "visibleHasNextAction": s.has_next_action_signal(terminal_visible_reply),
                },
            )
            return s._annotate_continuation_result(result, turn_index, reached_limit=False)
        if cumulative_session_tokens >= token_budget_line:
            # Real-time token fuse: stop the turn through the same graceful
            # paused_limit path as the auto-continue ceiling so the model's
            # current text wraps the turn up instead of a hard kill mid-flight.
            paused_result = s._build_auto_continue_paused_result(
                result,
                last_visible_result,
                turn_index,
                pause_reason="token_budget_exhausted",
                status="paused_limit",
                fallback_visible="本轮 token 预算已达到熔断线，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
                internal_auto_continue_blocked=False,
                reached_limit=True,
            )
            s._record_session_turn_lifecycle_event(
                session_id,
                "followup_prompt_blocked",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="paused_limit",
                fields={
                    "turnIndex": turn_index,
                    "reason": "token_budget_exhausted",
                    "cumulativeSessionTokens": cumulative_session_tokens,
                    "tokenBudgetLine": token_budget_line,
                    "tokenBudgetSource": token_budget_source,
                },
            )
            return paused_result
        if required_tool_progress_missing:
            s._record_session_turn_lifecycle_event(
                session_id,
                "required_tool_progress_missing",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="needs_continue",
                fields={
                    "turnIndex": turn_index,
                    "resultStatus": result_status,
                    "requiredToolNames": normalized_required_tool_names[:12],
                    "visibleReplyLength": len(result_visible_reply),
                },
            )

        tool_observations = _continuation_tool_observations(result)
        canonical_progress_advanced = any(
            succeeded and signature not in observed_tool_signatures
            for signature, succeeded in tool_observations
        )
        repeated_tool_observation = any(
            signature in observed_tool_signatures
            for signature, _succeeded in tool_observations
        )
        observed_tool_signatures.update(
            signature for signature, _succeeded in tool_observations
        )
        if canonical_progress_advanced:
            continuation_progress_advanced = True
            consecutive_no_progress_turns = 0
        else:
            consecutive_no_progress_turns += 1

        if not allow_internal_auto_continue:
            paused_result = s._build_auto_continue_paused_result(result, last_visible_result, turn_index)
            s._record_session_turn_lifecycle_event(
                session_id,
                "followup_prompt_blocked",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="paused",
                fields={
                    "turnIndex": turn_index,
                    "reason": "internal_auto_continue_not_authorized",
                    "userMessageSource": normalized_user_message_source,
                },
            )
            return paused_result

        if consecutive_no_progress_turns >= auto_continue_turn_limit:
            paused_result = s._build_auto_continue_paused_result(
                result,
                last_visible_result,
                turn_index,
                pause_reason="runaway_no_progress",
                status="paused_limit",
                fallback_visible="连续多轮没有产生新的任务进展，已保留当前执行进度；发送“继续”可在修正后衔接上一轮。",
                internal_auto_continue_blocked=False,
                reached_limit=True,
            )
            if isinstance(paused_result, dict):
                metadata = (
                    dict(paused_result.get("metadata") or {})
                    if isinstance(paused_result.get("metadata"), dict)
                    else {}
                )
                metadata["continuation_no_progress_count"] = (
                    consecutive_no_progress_turns
                )
                metadata["continuation_progress_advanced"] = (
                    continuation_progress_advanced
                )
                paused_result["metadata"] = metadata
            s._record_session_turn_lifecycle_event(
                session_id,
                "followup_prompt_blocked",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="paused_limit",
                fields={
                    "turnIndex": turn_index,
                    "reason": "runaway_no_progress",
                    "userMessageSource": normalized_user_message_source,
                    "internalAutoContinueMaxTurns": auto_continue_turn_limit,
                    "consecutiveNoProgressTurns": consecutive_no_progress_turns,
                    "canonicalProgressAdvanced": canonical_progress_advanced,
                    "repeatedToolObservation": repeated_tool_observation,
                },
            )
            return paused_result

        required_tool_guidance = s._required_tool_progress_followup_guidance(normalized_required_tool_names)
        guidance_summaries = s._recent_session_guidance_summaries(
            session_id,
            turn_id=getattr(turn_control, "turn_id", ""),
            limit=3,
        )
        if required_tool_progress_missing and required_tool_guidance:
            guidance_summaries = [required_tool_guidance, *guidance_summaries]
        prompt = s._build_followup_prompt(
            original_prompt=initial_prompt,
            effective_prompt=prompt,
            latest_result=result,
            history_messages=history_messages,
            turn_index=turn_index,
            guidance_summaries=guidance_summaries,
        )
        s._set_session_turn_progress_live_output(
            session_id,
            "followup_prepare",
            turn_id=getattr(turn_control, "turn_id", ""),
        )
        s._record_session_turn_lifecycle_event(
            session_id,
            "followup_prompt_built",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "turnIndex": turn_index,
                "nextPromptLength": len(prompt),
                "consecutiveNoProgressTurns": consecutive_no_progress_turns,
                "canonicalProgressAdvanced": canonical_progress_advanced,
                "repeatedToolObservation": repeated_tool_observation,
            },
        )
