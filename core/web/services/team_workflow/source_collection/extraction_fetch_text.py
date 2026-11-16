"""Read original text from successful fetch receipts in the Session Journal.

The Session Journal remains the authority. Candidate summaries and Agent
writeback metadata cannot manufacture a fetch receipt or its source text.
Every turn of the task's session is in supply scope: the agent may fetch in
an earlier turn or in a continuation turn (after a remediation parking), and
those receipts must not vanish at the turn boundary. For formal extraction,
the accepted finding handoff can also supply receipts for its own candidates.
A cross-host
redirect parking message additionally registers its original URL as an alias
of an already-fetched redirect target, so a candidate locator parked at the
redirect still quotes the text actually fetched at the landing page.
"""

from __future__ import annotations

import json
from sqlite3 import Error as SQLiteError
from typing import Any, Iterable

from core.research.workflow.ledger.errors import WorkflowLedgerError

# web_fetch_tool 成功回执的两种前缀（tools/web_search_tool.web_fetch）：
# HTML 走 [网页内容]，PDF 走 [PDF 文本]。PDF 回执同样携带真实抓取原文，
# 必须进入 quotable 供给——只认 HTML 前缀会让纯 PDF 来源（如 arXiv /pdf/）
# 即使抓取成功也必然 no_quotable_text。
_RECEIPT_PREFIXES = ("[网页内容] ", "[PDF 文本] ")
REUSED_FINDING_TEXT_PREFIX = "[已复用搜集原文] "
_REUSED_EXTRACTION_TEXT_PREFIX = "[已复用提炼原文] "

# 跨主机重定向停靠消息（tools/web_search_tool.web_fetch 按安全策略停止跟随）。
# 它不是内容回执，禁止进入 _RECEIPT_PREFIXES——只作为 (原 URL → 重定向目标)
# 别名对的解析来源。
_REDIRECT_PARKING_PREFIX = "[网页抓取] "
_REDIRECT_ORIGINAL_LABEL = "原 URL"
_REDIRECT_TARGET_LABEL = "重定向目标"


def _labeled_url(line: str, label: str) -> str:
    """One labeled URL value from a parking-message line, or ``""``.

    Tolerates stray whitespace around the label and both ASCII/full-width
    colons; a label line without a usable value parses as empty.
    """
    stripped = line.strip()
    if not stripped.startswith(label):
        return ""
    value = stripped[len(label):].strip()
    if value.startswith((':', '：')):
        return value[1:].strip()
    return ""


def _redirect_alias_pair(result: str) -> tuple[str, str]:
    """Parse a redirect parking message into ``(original, target)``.

    Only ``[网页抓取] ``-prefixed tool results count.  Line order and extra
    whitespace are tolerated; when either URL line is missing or
    unparseable the pair comes back empty and the receipt is skipped —
    parsing never raises.
    """
    if not result.startswith(_REDIRECT_PARKING_PREFIX):
        return "", ""
    original = ""
    target = ""
    for line in result.splitlines():
        original = original or _labeled_url(line, _REDIRECT_ORIGINAL_LABEL)
        target = target or _labeled_url(line, _REDIRECT_TARGET_LABEL)
        if original and target:
            break
    return original, target


def task_fetched_text(task: dict[str, Any]) -> dict[str, dict[str, str]]:
    from core.web.services import team_workflow_orchestration_service as s

    turn = task.get("turn") or {}
    session_id = str(task.get("sessionId") or turn.get("sessionId") or "").strip()
    if not session_id:
        return {}
    return _session_fetched_text(s._source_collection_stage_conversation_events(session_id), session_id)


def _session_fetched_text(events: list[Any], session_id: str) -> dict[str, dict[str, str]]:
    from core.web.services import team_workflow_orchestration_service as s

    texts: dict[str, dict[str, str]] = {}
    for event in events:
        if str(getattr(event, "event_type", "")) != "tool_result":
            continue
        # 本 stage task 会话内的全部 turn 都在供给范围内：修正停靠后 agent
        # 在新 turn 继续、或复看早前 turn 的抓取时，回执不因 turn 边界丢失；
        # 同一 locator 的重复抓取按 Journal 顺序后者覆盖前者。
        for call in s._source_collection_stage_tool_calls_from_event(event):
            if s._source_collection_stage_tool_call_name(call) != "web_fetch_tool":
                continue
            if not s._source_collection_stage_tool_call_succeeded(call):
                continue
            args = s._source_collection_stage_tool_call_args(call)
            locator = str(args.get("url") or "").strip()
            result = call.get("result")
            if not locator or not isinstance(result, str):
                continue
            receipt_prefix = next(
                (prefix for prefix in _RECEIPT_PREFIXES if result.startswith(prefix)),
                None,
            )
            if not receipt_prefix:
                continue
            header, separator, body = result.partition("\n\n")
            if not separator or not body.strip():
                continue
            # Keep fetched text only, excluding the tool's truncation notice.
            original, truncated, tail = body.rpartition("\n\n... [截断，原内容 ")
            body = original if truncated else tail
            body = body.strip()
            if not body:
                continue
            texts[locator] = {
                "text": body,
                "locator": locator,
                "resolvedUrl": header.splitlines()[0].removeprefix(receipt_prefix),
                "eventId": str(getattr(event, "event_id", "")),
                "sessionId": session_id,
                "turnId": str(getattr(event, "turn_id", "")),
            }
            if truncated:
                texts[locator]["truncated"] = "true"
    # 第二遍扫描：跨主机重定向停靠消息携带 (原 URL → 重定向目标)。代理按提示
    # 抓到落地页后，原定位键（如 DOI 链接）也要能命中那份真实抓取的原文，
    # 否则候选的 DOI 定位键永远 quoteAvailable=false（结构性死锁）。别名条目
    # 是 target 条目的浅拷贝：出处字段沿用 target 的真实抓取（诚实出处），
    # 只有 locator 换成原 URL 并加 aliasOf 标注；直接抓取优先，别名只填空，
    # target 未成功抓取时不做别名、也不多跳。
    for event in events:
        if str(getattr(event, "event_type", "")) != "tool_result":
            continue
        for call in s._source_collection_stage_tool_calls_from_event(event):
            if s._source_collection_stage_tool_call_name(call) != "web_fetch_tool":
                continue
            if not s._source_collection_stage_tool_call_succeeded(call):
                continue
            result = call.get("result")
            if not isinstance(result, str):
                continue
            original, target = _redirect_alias_pair(result)
            if not original or not target:
                continue
            if str(s._source_collection_stage_tool_call_args(call).get("url") or "").strip() != original:
                continue
            if texts.get(original):
                continue
            fetched = texts.get(target)
            if not fetched or not str(fetched.get("text") or "").strip():
                continue
            alias = dict(fetched)
            alias["locator"] = original
            alias["aliasOf"] = target
            texts[original] = alias
    return texts


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finding_handoff(repo, team_id: str, run_id: str, task: dict[str, Any]):
    """Resolve the accepted upstream attempt from server-owned ledger records."""
    from .stage_reconcile import _source_collection_stage_task_idempotency_key

    workflow_run_id = task["workflowRunId"]
    run = repo.get_run(workflow_run_id)
    if not run or run.team_id != team_id:
        return None
    snapshot = _object(json.loads(run.input_snapshot_json))
    if snapshot.get("sourceCollectionRunId") != run_id:
        return None
    operator = _object(task.get("operatorSourceAuthority"))
    contract = _object(task.get("challengeTaskContract"))
    node_run_id = operator.get("formalNodeRunId") or contract.get("nodeRunId")
    extraction = (
        repo.get_attempt(node_run_id) if node_run_id
        else repo.latest_attempt(workflow_run_id, "source_extraction")
    )
    if not extraction or extraction.run_id != workflow_run_id or extraction.node_id != "source_extraction":
        return None
    frozen_operator = _object(snapshot.get("operatorSourceAuthorities")).get(extraction.node_run_id)
    if (operator or frozen_operator) and (
        operator != frozen_operator
        or operator.get("formalNodeId") != extraction.node_id
        or operator.get("workflowRunId") != workflow_run_id
        or operator.get("agentId") != task.get("agentId")
        or operator.get("agentRole") != task.get("agentRole")
    ):
        return None
    expected_key = _source_collection_stage_task_idempotency_key(
        team_id=team_id, run_id=run_id, stage_id="extraction", agent_id=task["agentId"],
        agent_role=task["agentRole"], task_id="", requested_key=f"agent-task:{extraction.node_run_id}",
    )
    if task.get("idempotencyKey") != expected_key:
        return None

    finding = repo.latest_attempt(workflow_run_id, "source_finding")
    if (
        not finding or finding.status != "succeeded" or finding.finished_at_ms is None
        or finding.finished_at_ms > extraction.started_at_ms
    ):
        return None
    handoffs = [
        row for row in repo.list_handoffs_for_node(workflow_run_id, extraction.node_id)
        if row[3] == finding.node_run_id and row[8] == "accepted"
        and (not row[5] or row[5] == extraction.node_run_id)
    ]
    if len(handoffs) != 1:
        return None
    anchor = repo.get_anchor_by_node_run(finding.node_run_id)
    if not anchor or anchor[0] != finding.execution_anchor_id or not all(anchor[index] for index in (3, 4, 5, 7, 8)):
        return None
    receipts = [
        row for receipt_id in repo.list_handoff_receipts(handoffs[0][0])
        if (row := repo.get_artifact_receipt(receipt_id))
        and row[1:5] == (workflow_run_id, finding.node_run_id, team_id, "source_candidate_batch")
        and row[9] == 1
    ]
    if len(receipts) != 1:
        return None
    return finding.node_run_id, anchor, receipts[0]


def _finding_task_events(
    finding_task: dict[str, Any], session_id: str, turn_id: str, node_run_id: str,
) -> list[Any]:
    """Read the accepted final turn and its verified predecessors in Journal order."""
    from core.web.services import team_workflow_orchestration_service as s
    from .stage_reconcile import (
        _source_collection_stage_event_metadata,
        _source_collection_stage_task_turn_ids,
    )

    events = s._source_collection_stage_conversation_events(session_id)
    # Manual continue submits inherit the original stage task scope but have
    # no explicit predecessor. Only the persisted stage task's adopted turn
    # list can connect those legacy turns. Formal continues carry their edge.
    adopted = list(dict.fromkeys(_source_collection_stage_task_turn_ids(finding_task)))
    legacy_parents = dict(zip(adopted[1:], adopted))
    messages: dict[str, tuple[int, str]] = {}
    for index, event in enumerate(events):
        message_turn_id = getattr(event, "turn_id", "")
        if not message_turn_id or getattr(event, "event_type", "") != "user_message":
            continue
        metadata = _source_collection_stage_event_metadata(event)
        if (
            metadata.get("kind") != s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND
            or metadata.get("sourceCollectionStageTaskId") != finding_task["taskId"]
            or metadata.get("teamId") != finding_task["teamId"]
        ):
            continue
        surface = metadata.get("sourceSurface")
        if surface == "team_workflow_agent_turn_continuation":
            if (
                metadata.get("workflowRunId") != finding_task["workflowRunId"]
                or metadata.get("workflowNodeId") != "source_finding"
                or metadata.get("nodeRunId") != node_run_id
                or metadata.get("taskId") != finding_task["taskId"]
                or _object(getattr(event, "payload", {})).get("source") != "agent_inbox"
            ):
                continue
            predecessor = metadata.get("continuationOfTurnId")
            if not isinstance(predecessor, str) or not predecessor:
                continue
        else:
            if (
                surface != "team_workflow_stage_task"
                or not all(metadata.get(key) == finding_task.get(key) for key in ("runId", "stageId", "agentId", "agentRole"))
                or metadata.get("sourceCollectionStageTaskKey") != finding_task.get("idempotencyKey")
            ):
                continue
            if metadata.get("sourceCollectionStageContinuation") is True:
                predecessor = legacy_parents.get(message_turn_id, "")
            elif metadata.get("workflowRunId") == finding_task["workflowRunId"]:
                predecessor = ""
            else:
                continue
        messages.setdefault(message_turn_id, (index, predecessor))

    turn_ids = {turn_id}
    current = messages.get(turn_id)
    while current:
        position, predecessor = current
        previous = messages.get(predecessor)
        if not previous or previous[0] >= position:
            break
        turn_ids.add(predecessor)
        current = previous
    return [event for event in events if getattr(event, "turn_id", "") in turn_ids]


def finding_fetched_text_by_source(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    candidates: Iterable[dict[str, Any]] | None = None,
) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    """Give each source only the accepted finding task's own matching text."""
    if (
        task.get("teamId") != team_id or task.get("runId") != run_id or task.get("stageId") != "extraction"
        or not all(task.get(key) for key in ("workflowRunId", "taskId", "agentId", "agentRole"))
    ):
        return {}
    selected_ids = (
        {candidate.get("candidateId") for candidate in candidates if isinstance(candidate, dict)} - {None, ""}
        if candidates is not None else None
    )
    if selected_ids == set():
        return {}

    from core.web.services import team_workflow_orchestration_service as s
    from ..research_runtime.artifact_readback_registry import (
        _source_finding_candidate_source,
        load_scoped_artifact_payload,
        parse_canonical_ref,
    )
    from ..research_runtime.formal_read_runtime import FormalReadRuntimeUnavailable, get_formal_read_store
    from ..research_runtime.formal_write_runtime import WorkflowMigrationRequired
    from .extraction_quote_anchor_supply import linked_source_record_id, matching_source_fetch_receipts
    from .search_execution import (
        _source_finding_candidate_receipt_is_bound,
        _source_finding_receipt_binding_keys,
        _source_finding_trace_receipt_ref_sets,
        project_source_collection_search_trace,
    )

    try:
        binding = get_formal_read_store().read(lambda repo: _finding_handoff(repo, team_id, run_id, task))
        if binding is None:
            return {}
        node_run_id, anchor, receipt = binding
        ref = parse_canonical_ref(_object(json.loads(receipt[5])).get("canonicalRef") or "")
    except (SQLiteError, WorkflowLedgerError, FormalReadRuntimeUnavailable, WorkflowMigrationRequired, ValueError):
        return {}
    if ref != {
        "kind": "source_candidate_batch", "teamId": team_id,
        "authorityRunId": run_id, "contentHash": receipt[7],
    }:
        return {}

    agent_id, agent_role, session_id, _, task_id, turn_id = anchor[3:9]
    if session_id == task.get("sessionId"):
        return {}
    finding_task, stored_run_id = s._find_source_collection_stage_session_task_by_id(team_id, task_id)
    if stored_run_id != run_id or not isinstance(finding_task, dict) or any(
        finding_task.get(key) != value for key, value in {
            "teamId": team_id, "runId": run_id, "workflowRunId": task["workflowRunId"], "stageId": "finding",
            "taskId": task_id, "sessionId": session_id, "agentId": agent_id, "agentRole": agent_role,
            "status": "completed",
        }.items()
    ) or _object(finding_task.get("turn")).get("turnId") != turn_id:
        return {}

    # The batch hash is a receipt of what finding accepted, not a pin on the
    # mutable candidate store (extraction itself updates it). Join the stored
    # materialization lineage by candidate AND record ID, then check the
    # current authoritative locator against one real grouped search result.
    materialized = _object(_object(finding_task.get("writeback")).get("materializedSources"))
    lineage: dict[str, set[str]] = {}
    for entry in materialized.get("lineage") or []:
        candidate = _object(_object(entry).get("candidate"))
        candidate_id = candidate.get("candidateId")
        record_id = _object(_object(entry).get("record")).get("recordId")
        if (
            candidate_id and record_id and candidate.get("status") in {"created", "reused"}
            and (selected_ids is None or candidate_id in selected_ids)
        ):
            lineage.setdefault(candidate_id, set()).add(record_id)
    if not lineage:
        return {}

    events = _finding_task_events(finding_task, session_id, turn_id, node_run_id)
    fetched = {
        locator: {**value, "findingNodeRunId": node_run_id, "findingTaskId": task_id, "findingArtifactReceiptId": receipt[0]}
        for locator, value in _session_fetched_text(events, session_id).items()
        if value.get("eventId")
    }
    if not fetched:
        return {}
    candidate_batch = load_scoped_artifact_payload(
        "source_candidate_batch", team_id=team_id, authority_run_id=run_id, workflow_run_id=task["workflowRunId"],
    ) or {}
    search_trace = project_source_collection_search_trace(team_id, run_id)
    groups = _source_finding_trace_receipt_ref_sets(search_trace)
    fetch_keys = {locator: _source_finding_receipt_binding_keys(locator) for locator in fetched}
    by_source: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for candidate in candidate_batch.get("candidates") or []:
        candidate_id = candidate.get("candidateId")
        record_id = linked_source_record_id(candidate)
        if not record_id or record_id not in lineage.get(candidate_id, ()):
            continue
        projected = _source_finding_candidate_source(candidate)
        matching_groups = [group for group in groups if _source_finding_candidate_receipt_is_bound(projected, [group])]
        if not matching_groups:
            continue
        matched = {
            locator: value for locator, value in fetched.items()
            if any(fetch_keys[locator] & group for group in matching_groups)
            and next(matching_source_fetch_receipts(projected, {locator: value}), None) is not None
        }
        if matched:
            by_source[("candidate", candidate_id)] = matched
            by_source.setdefault(("record", record_id), {}).update(matched)
    return by_source


def finding_fetched_text_for_task(task: dict[str, Any]) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    """Resolve scoped finding receipts at an extraction evidence read point."""
    return finding_fetched_text_by_source(
        str(task.get("teamId") or ""), str(task.get("runId") or ""), task,
    )


def reuse_bound_extraction_text(runtime: dict[str, Any], url: str, max_chars: int) -> str | None:
    """Prefer the accepted finding body, then reuse any completed supplemental fetch."""
    scope = _object(_object(runtime.get("runtimeMetadata")).get("sourceCollectionExtraction"))
    if scope.get("stageId") not in {None, "", "extraction"} or not all(
        scope.get(key) for key in ("teamId", "taskId")
    ) or not all(runtime.get(key) for key in ("sessionId", "turnId", "agentId")):
        return None

    from .stage_session import _read_source_collection_stage_session_task_record

    task = _read_source_collection_stage_session_task_record(scope["teamId"], scope["taskId"])
    if (not task or task.get("stageId") != "extraction"
            or any(task.get(key) != scope[key] for key in ("teamId", "taskId"))
            or (scope.get("runId") and task.get("runId") != scope["runId"])):
        return None
    if any(task.get(key) != runtime[key] for key in ("sessionId", "agentId")):
        return None
    if task.get("status") not in {"queued", "running", "needs_review"}:
        return None
    if _object(task.get("turn")).get("turnId") != runtime["turnId"]:
        # A continuation can start before the canonical task adopts its new
        # turn. Verify that its persisted user message references this task.
        from core.web.services import team_workflow_orchestration_service as s

        if not s._source_collection_stage_session_task_turn_references_task(task, runtime["sessionId"], runtime["turnId"]):
            return None

    finding_receipts = (
        receipts for (kind, _), receipts in finding_fetched_text_for_task(task).items() if kind == "candidate"
    )
    previous = _source_fetch_replay(url, max_chars, finding_receipts)
    if previous is not None:
        address, event_id, body = previous
        return f"{REUSED_FINDING_TEXT_PREFIX}{address}\n搜集抓取回执: {event_id}\n\n{body}"
    previous = _source_fetch_replay(url, max_chars, (task_fetched_text(task),))
    if previous is not None:
        address, event_id, body = previous
        return f"{_REUSED_EXTRACTION_TEXT_PREFIX}{address}\n提炼抓取回执: {event_id}\n\n{body}"
    return None


def _source_fetch_replay(
    url: str, max_chars: int, scoped_receipts: Iterable[dict[str, dict[str, str]]],
) -> tuple[str, str, str] | None:
    from .extraction_quote_anchor_supply import _arxiv_locator, matching_source_fetch_receipts, receipt_citation_url

    requested = _arxiv_locator(url)
    matches = {}
    for scoped in scoped_receipts:
        for receipt in matching_source_fetch_receipts({"sourceUrl": url}, scoped):
            citation_url = receipt_citation_url(receipt)
            actual = _arxiv_locator(citation_url)
            if requested and actual and requested[2] != "doi" and requested[2] != actual[2]:
                continue
            if not receipt.get("eventId"):
                continue
            body = receipt["text"]
            if receipt.get("truncated") and len(body) < max_chars:
                continue
            matches[(citation_url, body)] = receipt
    if len(matches) != 1:
        # In particular, a versionless request must not choose arbitrarily
        # between two editions or two observed bodies.
        return None
    (citation_url, body), receipt = next(iter(matches.items()))
    return citation_url, receipt["eventId"], body[:max_chars]
