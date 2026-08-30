"""Fast LLM-layer stub for production Session/Turn gates.

Stubs ``invoke_llm_outcome`` / ``run_streaming_llm_outcome`` so the real
``submit_session_message`` → schedule → turn worker → journal path runs
without a live provider. The first outcome is a canonical
``source_collection_stage_writeback_tool`` call. The real Agent tool lifecycle
dispatches it; only the model decision is stubbed. A later invocation returns
``final_answer`` after observing the formal writeback.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from uuid import uuid4

from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, TurnOutcome

_CONTRACT_KIND = "source_collection_stage_session_task_writeback"

# Deterministic model-call facts for stub receipts.  The stub replaces only the
# model decision, so its receipts carry fixed usage/timing magnitudes that
# mirror a real stage invocation instead of random noise.
_STUB_INVOCATION_INPUT_TOKENS = 24_000
_STUB_INVOCATION_OUTPUT_TOKENS = 2_000
_STUB_INVOCATION_STARTED_AT_MS = 1_750_000_000_000


def install_fast_stage_writeback_llm_stub(monkeypatch: Any) -> dict[str, Any]:
    """Monkeypatch LLM outcome helpers; return a mutable call counter."""

    import core.llm.invocation as invocation
    from core.web.services.session.tool_approvals import ToolApprovalOutcome

    counters = {
        "invoke": 0,
        "stream": 0,
        "writeback_calls": 0,
        "final_answers": 0,
        "claim_evidence_errors": 0,
        "receipts_attached": 0,
    }

    def _invoke(
        client: Any,
        messages: list[Any],
        *,
        context: Any,
        tools: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        replay_state: Any = None,
    ) -> TurnOutcome:
        _ = (tools, replay_state)
        counters["invoke"] += 1
        outcome = _outcome_for_messages(messages, context=context, counters=counters)
        return _attach_invocation_receipt(
            client,
            outcome,
            context=context,
            messages=messages,
            metadata=metadata,
            counters=counters,
        )

    def _stream(
        client: Any,
        messages: list[Any],
        *,
        context: Any,
        on_event: Callable[[Any], None],
        tools: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        replay_state: Any = None,
    ) -> TurnOutcome:
        _ = (on_event, tools, replay_state)
        counters["stream"] += 1
        outcome = _outcome_for_messages(messages, context=context, counters=counters)
        return _attach_invocation_receipt(
            client,
            outcome,
            context=context,
            messages=messages,
            metadata=metadata,
            counters=counters,
        )

    def _auto_approve_tool(**_kwargs: Any) -> ToolApprovalOutcome:
        # High-permission writeback would otherwise block on UI approval (300s).
        return ToolApprovalOutcome(True, "t518_auto_approved")

    def _deterministic_search(**_kwargs: Any) -> str:
        return json.dumps(
            {
                "status": "completed",
                "results": [
                    {
                        "title": "T5.1 deterministic search observation",
                        "url": "https://doi.org/10.0000/t518",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(invocation, "invoke_llm_outcome", _invoke)
    monkeypatch.setattr(invocation, "run_streaming_llm_outcome", _stream)
    # Agent imports the helpers by name at module load time.
    import agent as agent_module
    import tools.Key_Tools as key_tools_module

    monkeypatch.setattr(agent_module, "invoke_llm_outcome", _invoke)
    monkeypatch.setattr(agent_module, "run_streaming_llm_outcome", _stream)
    monkeypatch.setattr(
        key_tools_module, "_batch_web_search_impl", _deterministic_search
    )
    monkeypatch.setattr(
        "core.web.services.session.tool_approvals.authorize_or_wait",
        _auto_approve_tool,
    )
    return counters


def _attach_invocation_receipt(
    client: Any,
    outcome: TurnOutcome,
    *,
    context: Any,
    messages: list[Any],
    metadata: dict[str, Any] | None,
    counters: dict[str, Any],
) -> TurnOutcome:
    """Mirror the real provider-boundary receipt attach for stubbed calls.

    The stub replaces only the model decision, so a durable Challenge Cup
    receipt must still come from the same fact source as a real invocation:
    the client's own ``_attach_model_invocation_receipt`` helper, driven by the
    server-owned binding in the ambient receipt ContextVar. Ordinary sessions
    have no binding and stay a no-op; the stub never mints a receipt itself.
    """

    attach = getattr(client, "_attach_model_invocation_receipt", None)
    if not callable(attach):
        return outcome
    from core.llm.client import _canonical_receipt_response_summary
    from core.llm.invocation import invocation_scope_from_metadata

    # Same identity merge as ``core.llm.invocation.invoke_llm_outcome`` so the
    # receipt scope matches what the real client would have derived.
    merged: dict[str, Any] = dict(metadata or {})
    try:
        merged.update(context.to_metadata(client=client))
    except (AttributeError, TypeError):
        merged.update(
            {
                key: value
                for key, value in dict(
                    getattr(context, "metadata", None) or {}
                ).items()
                if isinstance(value, (str, int, float, bool))
            }
        )
    invocation_scope = invocation_scope_from_metadata(merged)
    attached = attach(
        outcome,
        metadata=merged,
        invocation_scope=invocation_scope,
        request_content={
            "messageCount": len(list(messages or [])),
            "stubSurface": "fast_stage_writeback_llm_stub",
        },
        response_content=_canonical_receipt_response_summary(outcome),
        started_at_ms=_STUB_INVOCATION_STARTED_AT_MS,
        finished_at_ms=_STUB_INVOCATION_STARTED_AT_MS + 1_000,
        attempt=1,
        retry_count=0,
        token_usage={
            "inputTokens": _STUB_INVOCATION_INPUT_TOKENS,
            "outputTokens": _STUB_INVOCATION_OUTPUT_TOKENS,
            "totalTokens": _STUB_INVOCATION_INPUT_TOKENS
            + _STUB_INVOCATION_OUTPUT_TOKENS,
            "cachedInputTokens": 0,
            "reasoningTokens": 0,
        },
    )
    if isinstance(getattr(attached, "model_invocation_receipt", None), dict):
        counters["receipts_attached"] += 1
    return attached


def _outcome_for_messages(
    messages: list[Any],
    *,
    context: Any,
    counters: dict[str, Any],
) -> TurnOutcome:
    identity = _identity_from_context(context)
    binding = _parse_writeback_binding(messages) or _lookup_binding_by_session(
        str(getattr(context, "session_id", "") or "")
    )
    if binding is not None and not _stage_already_writeback_completed(binding):
        calls = [
            CanonicalToolCall(
                identity=identity,
                call_id=f"call-context-{binding['taskId']}",
                name="source_collection_context_tool",
                arguments={
                    "team_id": binding["teamId"],
                    "run_id": binding.get("runId", ""),
                    "stage_id": binding["stageId"],
                    "task_id": binding["taskId"],
                    "context_mode": "compact",
                },
            )
        ]
        if str(binding.get("stageId") or "").strip().lower() == "finding":
            calls.append(
                CanonicalToolCall(
                    identity=identity,
                    call_id=f"call-search-{binding['taskId']}",
                    name="batch_web_search_tool",
                    arguments={
                        "queries": json.dumps(
                            [
                                "spike coding mechanism",
                                "neural coding independent baseline",
                                "spike coding limitation null result",
                                "spike coding falsification",
                            ]
                        )
                    },
                )
            )
        calls.append(
            CanonicalToolCall(
                identity=identity,
                call_id=f"call-writeback-{binding['taskId']}",
                name="source_collection_stage_writeback_tool",
                arguments=_writeback_tool_arguments(binding),
            )
        )
        return TurnOutcome(
            kind="tool_calls",
            identity=identity,
            tool_calls=tuple(calls),
            pending_tool_call_ids=tuple(call.call_id for call in calls),
            terminal_event_seen=True,
        )

    if binding is not None:
        counters["writeback_calls"] += 1
        stage_id = str(binding.get("stageId") or "").strip().lower()
        registered = counters.setdefault("claim_evidence_registered", set())
        if stage_id == "extraction" and binding["taskId"] not in registered:
            _register_claim_evidence_cards(
                binding,
                result=_result_for_stage(
                    stage_id,
                    team_id=str(binding.get("teamId") or ""),
                    run_id=str(binding.get("runId") or ""),
                ),
            )
            registered.add(binding["taskId"])

    counters["final_answers"] += 1
    return TurnOutcome.final_answer(
        identity=identity,
        text=(
            "结论：阶段 writeback 已完成，候选/证据已物化。"
            "任务完成。in summary the stage writeback finished successfully."
        ),
    )


def _stage_already_writeback_completed(binding: dict[str, str]) -> bool:
    team_id = str(binding.get("teamId") or "").strip()
    task_id = str(binding.get("taskId") or "").strip()
    if not team_id or not task_id:
        return False
    try:
        from core.web.services import team_workflow_orchestration_service as orch

        task, _run_id = orch._find_source_collection_stage_session_task_by_id(
            team_id, task_id
        )
    except Exception:
        return False
    if not isinstance(task, dict):
        return False
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    status = str(writeback.get("status") or task.get("status") or "").strip().lower()
    return status in {"completed", "needs_review"}


def _register_claim_evidence_cards(
    binding: dict[str, str],
    *,
    result: dict[str, Any],
) -> None:
    """Materialize ClaimEvidence into the active PROJECT_ROOT evidence store."""
    team_id = str(binding.get("teamId") or "").strip()
    run_id = str(binding.get("runId") or "").strip()
    if not team_id:
        raise RuntimeError("claim evidence registration requires teamId")
    _materialize_claim_evidence_cards(
        team_id=team_id,
        run_id=run_id,
        result=result,
    )


def _materialize_claim_evidence_cards(
    *,
    team_id: str,
    run_id: str,
    result: dict[str, Any],
) -> None:
    """Write formal ClaimEvidenceStore cards from extraction writeback result.

    Stage writeback updates SC candidate metadata; relations readiness still
    requires ClaimEvidenceStore authority. Register scoped cards so the
    production Evidence Store is populated without a parallel fake store.
    """
    from core.infrastructure.path_containment import PROJECT_ROOT
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services import team_service

    root = PROJECT_ROOT or team_service.PROJECT_ROOT
    store = ClaimEvidenceStore(root)
    extractions = [
        item
        for item in list(result.get("candidateExtractions") or [])
        if isinstance(item, dict)
    ]
    registered = 0
    for index, extraction in enumerate(extractions, start=1):
        candidate_id = str(extraction.get("candidateId") or "").strip()
        if not candidate_id:
            continue
        findings = list(extraction.get("keyFindings") or [])
        finding = findings[0] if findings and isinstance(findings[0], dict) else {}
        claims = list(extraction.get("claims") or [])
        claim0 = claims[0] if claims and isinstance(claims[0], dict) else {}
        source_ref = str(
            claim0.get("sourceRef")
            or finding.get("sourceRef")
            or extraction.get("sourceRef")
            or f"https://doi.org/10.0000/t518-claim-{index}"
        ).strip()
        quote = str(
            claim0.get("claim")
            or finding.get("finding")
            or extraction.get("summary")
            or f"Extracted claim {index} for T5.1 gate."
        ).strip()
        page_raw = (
            finding.get("citationLocator")
            if isinstance(finding.get("citationLocator"), dict)
            else {}
        )
        page_text = str(
            (page_raw or {}).get("page")
            or finding.get("page")
            or claim0.get("page")
            or index
        )
        try:
            page = max(1, int(page_text))
        except (TypeError, ValueError):
            page = index
        store.register(
            team_id,
            {
                "claimId": f"claim-t518-{candidate_id}-{index}",
                "candidateId": candidate_id,
                "sourceId": source_ref,
                "sourceRevision": "sha256:" + ("d" * 64),
                "title": str(extraction.get("title") or "").strip(),
                "source_type": str(extraction.get("source_type") or "").strip(),
                "source_url": str(extraction.get("source_url") or source_ref).strip(),
                "retrieved_at": str(extraction.get("retrieved_at") or "").strip(),
                "fact": str(
                    finding.get("fact") or extraction.get("fact") or quote
                ).strip(),
                "relation": str(extraction.get("relation") or "supports").strip(),
                "verification_status": str(
                    extraction.get("verification_status") or "full_text_checked"
                ).strip(),
                "locator": {"kind": "pdf_page", "page": page},
                "quote": quote,
                "evidenceKind": "primary_result",
                "reasoningRole": "fact",
                "supportLevel": "supports"
                if index < len(extractions)
                else "contradicts",
                "extractionMethod": "manual",
                "extractorAgentId": "t518-llm-stub",
                "modelRef": "",
                "sourceCollectionRunId": run_id,
                "workflowRunId": "run-t518",
            },
        )
        registered += 1
    if registered <= 0:
        raise RuntimeError(
            "extraction writeback produced no ClaimEvidence cards for readiness"
        )


def _identity_from_context(context: Any) -> CanonicalItemIdentity:
    meta = dict(getattr(context, "metadata", None) or {})
    session_id = str(
        getattr(context, "session_id", "") or meta.get("sessionId") or "session-stub"
    )
    turn_id = str(getattr(context, "run_id", "") or meta.get("turnId") or "turn-stub")
    invocation_id = str(meta.get("invocationId") or uuid4().hex)
    return CanonicalItemIdentity(
        session_id=session_id,
        turn_id=turn_id,
        invocation_id=invocation_id,
        iteration=0,
        item_id="item-stub",
    )


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _parse_writeback_binding(messages: list[Any]) -> dict[str, str] | None:
    for message in reversed(list(messages or [])):
        content = _message_content(message)
        if _CONTRACT_KIND not in content and "writebackContract" not in content:
            continue
        # Prefer the embedded writeback contract JSON object.
        match = re.search(
            r"\{[^{}]*\"contractKind\"\s*:\s*\"source_collection_stage_session_task_writeback\"[^{}]*\}",
            content,
            flags=re.DOTALL,
        )
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = {}
            binding = _binding_from_mapping(payload)
            if binding is not None:
                return binding
        # Fallback: field scrape near known keys.
        team_id = _first_group(r'"teamId"\s*:\s*"([^"]+)"', content)
        task_id = _first_group(r'"taskId"\s*:\s*"([^"]+)"', content)
        stage_id = _first_group(r'"stageId"\s*:\s*"([^"]+)"', content)
        run_id = _first_group(r'"runId"\s*:\s*"([^"]+)"', content)
        if team_id and task_id and stage_id:
            return {
                "teamId": team_id,
                "taskId": task_id,
                "stageId": stage_id,
                "runId": run_id or "",
            }
    return None


def _binding_from_mapping(payload: dict[str, Any]) -> dict[str, str] | None:
    team_id = str(payload.get("teamId") or "").strip()
    task_id = str(payload.get("taskId") or "").strip()
    stage_id = str(payload.get("stageId") or "").strip()
    run_id = str(payload.get("runId") or "").strip()
    if not (team_id and task_id and stage_id):
        return None
    return {
        "teamId": team_id,
        "taskId": task_id,
        "stageId": stage_id,
        "runId": run_id,
    }


def _first_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return str(match.group(1) if match else "").strip()


def _lookup_binding_by_session(session_id: str) -> dict[str, str] | None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    from core.web.services import team_service
    from core.web.services import team_workflow_orchestration_service as orch

    teams_payload = team_service.list_teams()
    teams = (
        teams_payload.get("teams")
        if isinstance(teams_payload, dict)
        else teams_payload
        if isinstance(teams_payload, list)
        else []
    )
    for team in teams or []:
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or team.get("id") or "").strip()
        if not team_id:
            continue
        try:
            runs = orch.list_source_collection_runs(team_id)
        except Exception:
            continue
        run_items = (
            runs.get("runs")
            if isinstance(runs, dict)
            else runs
            if isinstance(runs, list)
            else []
        )
        for run in run_items or []:
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("runId") or "").strip()
            if not run_id:
                continue
            try:
                store = orch._load_source_collection_stage_session_task_store(
                    team_id, run_id
                )
            except Exception:
                continue
            for task in list(store.get("tasks") or []):
                if not isinstance(task, dict):
                    continue
                if str(task.get("sessionId") or "").strip() != normalized:
                    continue
                status = str(task.get("status") or "").strip().lower()
                if status in {"completed", "cancelled", "failed"}:
                    continue
                return {
                    "teamId": team_id,
                    "taskId": str(task.get("taskId") or "").strip(),
                    "stageId": str(task.get("stageId") or "").strip(),
                    "runId": run_id,
                }
    return None


def _writeback_tool_arguments(binding: dict[str, str]) -> dict[str, Any]:
    stage_id = str(binding.get("stageId") or "").strip().lower()
    team_id = str(binding.get("teamId") or "").strip()
    task_id = str(binding.get("taskId") or "").strip()
    run_id = str(binding.get("runId") or "").strip()
    result = _result_for_stage(stage_id, team_id=team_id, run_id=run_id)
    return {
        "team_id": team_id,
        "task_id": task_id,
        "status": "completed",
        "summary": f"Deterministic T5.1 stub writeback for stage={stage_id}",
        "result_json": json.dumps(result, ensure_ascii=False),
        "evidence_refs_json": "[]",
        "next_actions_json": "[]",
        "recorded_by_agent": "t518-llm-stub",
        "metadata_json": json.dumps({"stub": "llm_turn_stub"}, ensure_ascii=False),
    }


def _result_for_stage(stage_id: str, *, team_id: str, run_id: str) -> dict[str, Any]:
    if stage_id == "finding":
        return {
            "candidateLeads": [
                {
                    "leadId": "t518-lead-mechanism",
                    "title": "Spike coding mechanisms in cortical populations",
                    "locator": "https://doi.org/10.0000/t518-mechanism",
                    "sourceType": "paper",
                    "query": "spike train information coding mechanism",
                    "perspective": "mechanism",
                    "summary": "Primary mechanism evidence for T5.1 gate.",
                    "doi": "10.0000/t518-mechanism",
                },
                {
                    "leadId": "t518-lead-baseline",
                    "title": "Independent baseline for neural coding metrics",
                    "locator": "https://doi.org/10.0000/t518-baseline",
                    "sourceType": "paper",
                    "query": "neural coding independent baseline",
                    "perspective": "independent_baseline",
                    "summary": "Baseline evidence for T5.1 gate.",
                    "doi": "10.0000/t518-baseline",
                },
                {
                    "leadId": "t518-lead-falsification",
                    "title": "Null-result and limitation cases for spike coding",
                    "locator": "https://doi.org/10.0000/t518-falsification",
                    "sourceType": "paper",
                    "query": "spike coding null result limitation",
                    "perspective": "falsification",
                    "summary": "Counter-evidence / limitation candidate for T5.1 gate.",
                    "doi": "10.0000/t518-falsification",
                },
            ],
            "invalidSources": [],
            "searchTrace": [
                {
                    "perspective": "mechanism",
                    "query": "spike train information coding mechanism",
                    "status": "found",
                    "resultRefs": ["https://doi.org/10.0000/t518-mechanism"],
                },
                {
                    "perspective": "independent_baseline",
                    "query": "neural coding independent baseline",
                    "status": "found",
                    "resultRefs": ["https://doi.org/10.0000/t518-baseline"],
                },
                {
                    "perspective": "falsification",
                    "query": "spike coding null result limitation",
                    "status": "found",
                    "resultRefs": ["https://doi.org/10.0000/t518-falsification"],
                },
            ],
        }

    if stage_id == "extraction":
        candidates = _candidates_for_run(team_id, run_id)
        extractions: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates[:3], start=1):
            candidate_id = str(candidate.get("candidateId") or "").strip()
            if not candidate_id:
                continue
            claim_text = (
                f"Claim {index}: spike patterns carry measurable information."
            )
            source_ref = str(
                candidate.get("sourceUrl")
                or candidate.get("sourceRef")
                or f"https://doi.org/10.0000/t518-extract-{index}"
            )
            extractions.append(
                {
                    "candidateId": candidate_id,
                    "title": str(
                        candidate.get("title") or f"T5.1 extraction {index}"
                    ),
                    "source_type": str(
                        candidate.get("sourceType") or "peer_reviewed_paper"
                    ),
                    "source_url": source_ref,
                    "retrieved_at": "2026-08-26T00:00:00Z",
                    "fact": claim_text,
                    "relation": "supports",
                    "verification_status": "full_text_checked",
                    "decision": "keep",
                    "status": "extracted",
                    "summary": f"Extracted claim {index} for T5.1 gate.",
                    "keyFindings": [
                        {
                            "finding": claim_text,
                            "fact": claim_text,
                            "quote": (
                                f"Bounded source excerpt {index} for the T5.1 gate."
                            ),
                            "citationLocator": {"page": str(index)},
                            "sourceRef": source_ref,
                            "evidenceRef": f"page:{index}",
                        }
                    ],
                    "evidenceRefs": [
                        {"type": "page", "page": str(index), "sourceRef": source_ref}
                    ],
                }
            )
        return {
            "candidateExtractions": extractions,
            "recordExtractions": [],
            "evidenceFetchAttempts": [],
        }

    if stage_id in {"relations", "relation", "mapping"}:
        candidates = _candidates_for_run(team_id, run_id)
        node_ids = [
            str(item.get("candidateId") or "").strip()
            for item in candidates
            if str(item.get("candidateId") or "").strip()
        ][:3]
        edges: list[dict[str, Any]] = []
        if len(node_ids) >= 2:
            edges.append(
                {
                    "from": node_ids[0],
                    "to": node_ids[1],
                    "relation": "supports",
                    "evidenceRefs": [f"candidate:{node_ids[0]}"],
                }
            )
        if len(node_ids) >= 3:
            edges.append(
                {
                    "from": node_ids[2],
                    "to": node_ids[0],
                    "relation": "contradicts",
                    "evidenceRefs": [f"candidate:{node_ids[2]}"],
                }
            )
        return {
            "candidateGraph": {
                "nodes": [{"id": node_id} for node_id in node_ids],
                "edges": edges,
                "missingLinks": [{"reason": "coverage_gap", "from": "open_question"}],
                "evidenceGaps": ["Need stronger multi-lab replication."],
                "counterEvidenceRefs": [
                    f"candidate:{node_ids[-1]}" if node_ids else "candidate:none"
                ],
            }
        }

    return {"status": "completed", "notes": f"noop writeback for stage={stage_id}"}


def _candidates_for_run(team_id: str, run_id: str) -> list[dict[str, Any]]:
    if not team_id or not run_id:
        return []
    try:
        from core.web.services import team_workflow_orchestration_service as orch

        return list(orch._source_collection_candidates_for_run(team_id, run_id) or [])
    except Exception:
        return []
