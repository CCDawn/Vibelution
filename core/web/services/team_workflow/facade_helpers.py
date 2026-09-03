"""Team workflow residual facade helpers.

Claim scope: remaining orchestration private helpers for workflow document
normalize/repair, stage readiness/planning, JSON/text I/O, and small validators
left on the facade after Phase 15 residual packs.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _active_research_loop_projection(team_id: str) -> dict[str, Any] | None:
    s = _service()
    active_project = s.get_active_research_project(team_id)
    active_project_id = str(active_project.get("projectId") or "")
    store = s._read_json(
        s.resolve_team_program_root(team_id) / "research_loops" / "index.json"
    )
    loops = [
        item
        for item in list(store.get("loops") or [])
        if isinstance(item, dict)
        and (
            str(item.get("researchProjectId") or "") == active_project_id
            or (
                active_project_id == s.LEGACY_PROJECT_ID
                and not str(item.get("researchProjectId") or "")
            )
        )
    ]
    active_loop_id = str(store.get("activeLoopId") or "")
    for loop in loops:
        if str(loop.get("loopId") or "") == active_loop_id:
            return loop
    return loops[-1] if loops else None


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _best_research_loop_evidence_id(loop: dict[str, Any] | None) -> str:
    s = _service()
    evidence_records = [item for item in list((loop or {}).get("evidenceRecords") or []) if isinstance(item, dict)]
    for evidence_type in ("benchmark_result", "full_run_result", "metric_report"):
        for evidence in reversed(evidence_records):
            if (
                str(evidence.get("evidenceType") or "") == evidence_type
                and str(evidence.get("status") or "").lower() == "passed"
            ):
                return str(evidence.get("evidenceId") or evidence.get("resultId") or "")
    return ""


def _bounded_log_items(value: Any, keys: tuple[str, ...], *, max_items: int) -> list[dict[str, Any]]:
    s = _service()
    items: list[dict[str, Any]] = []
    for item in list(value or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        bounded: dict[str, Any] = {}
        for key in keys:
            raw = item.get(key)
            if isinstance(raw, list):
                text_items = s._bounded_text_items(raw, max_items=12, max_length=160)
                if text_items:
                    bounded[key] = text_items
            elif isinstance(raw, (int, float, bool)) or raw is None:
                if raw is not None:
                    bounded[key] = raw
            else:
                text = s._trim_text(raw, max_length=240 if key in {"title", "error"} else 160)
                if text:
                    bounded[key] = text
        if bounded:
            items.append(bounded)
    return items


def _bounded_text_items(value: Any, *, max_items: int, max_length: int) -> list[str]:
    s = _service()
    return [
        s._trim_text(item, max_length=max_length)
        for item in list(value or [])[:max_items]
        if s._trim_text(item, max_length=max_length)
    ]


def _candidate_needs_rework(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> bool:
    s = _service()
    state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if "needs_revision" in state or quality_status == "needs_revision":
        return True
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if isinstance(output.get("requiredChanges"), list) and output.get("requiredChanges"):
        return True
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    return bool(validation and not validation.get("valid", True))


def _clamp_score(value: int) -> int:
    s = _service()
    return max(0, min(int(value or 0), 100))


def _compact_text(value: Any, *, max_length: int) -> str:
    s = _service()
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_length]


def _crossref_search_url(query_text: str, *, rows: int) -> str:
    s = _service()
    params = urllib.parse.urlencode(
        {
            "query": query_text,
            "rows": str(rows),
            "select": "DOI,title,URL,container-title,published-print,published-online,issued,author,type,abstract,score",
        }
    )
    return f"https://api.crossref.org/works?{params}"


_ARXIV_QUERY_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ARXIV_QUERY_MAX_TOKENS = 8


def _arxiv_search_query(query_text: str) -> str:
    """Build an arXiv ``search_query`` expression from a plan query text.

    Query tokens are AND-joined behind the ``all:`` field prefix so the
    arXiv API treats them as conjunctive keyword filters, mirroring how the
    Crossref branch posts the raw query text.
    """
    s = _service()
    text = s._trim_text(query_text, max_length=1000)
    tokens: list[str] = []
    for match in _ARXIV_QUERY_TOKEN_PATTERN.finditer(text):
        token = match.group(0).strip("._-")
        if len(token) < 2:
            continue
        if token.lower() in s._SOURCE_COLLECTION_GENERIC_SEARCH_TERMS:
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= _ARXIV_QUERY_MAX_TOKENS:
            break
    if not tokens:
        return s._trim_text(text, max_length=400)
    return " AND ".join(f"all:{token}" for token in tokens)


def _arxiv_search_url(query_text: str, *, start: int, max_results: int) -> str:
    params = urllib.parse.urlencode(
        {
            "search_query": query_text,
            "start": str(max(0, start)),
            "max_results": str(max(1, max_results)),
        }
    )
    return f"https://export.arxiv.org/api/query?{params}"


# OpenAlex polite pool: the API asks callers to pass a stable mailto contact so
# requests are served from the polite pool (10 req/s) instead of the common
# pool.  This placeholder identifies the Vibelution metadata-only collector and
# is not a secret.
_SOURCE_COLLECTION_OPENALEX_MAILTO = "challenge-cup-research@localhost"


def _openalex_search_url(query_text: str, *, per_page: int) -> str:
    params = urllib.parse.urlencode(
        {
            "search": query_text,
            "per-page": str(max(1, per_page)),
            "mailto": _SOURCE_COLLECTION_OPENALEX_MAILTO,
        }
    )
    return f"https://api.openalex.org/works?{params}"


# ---------------------------------------------------------------------------
# Qwen deep search (DashScope compatible-mode Responses API) — run-level
# source-collection supplement.
#
# Endpoint and shape verified live (2026-09-03, qwen3.8-flash + operator
# DASHSCOPE_API_KEY): the compatible-mode Responses endpoint
# (``POST /compatible-mode/v1/responses`` with ``tools=[{"type": "web_search"}]``)
# is the only usable web-search surface — the native multimodal-generation
# endpoint rejects the model (HTTP 400) and chat-completions ``enable_search``
# takes minutes without structured sources.  A non-streaming response carries
# an ``output`` array where every ``web_search_call`` item exposes
# ``action.sources`` (structured ``{type, url}`` lists, e.g. precise arXiv
# hits) and ``action.queries`` (the model's actual search phrases), and a
# ``message`` item holds the synthesis text; ``usage.x_tools.web_search.count``
# carries billing observability.  The bare ``qwen3.8`` id is rejected here
# ("Unsupported model"), ``qwen3.8-flash`` works.  Requests stay plain bounded
# urllib POSTs (no console, no subprocess, no streaming aggregation).
# ---------------------------------------------------------------------------

_DASHSCOPE_SEARCH_API_KEY_ENV = "DASHSCOPE_API_KEY"
_DASHSCOPE_SEARCH_MODEL_ENV = "VIBELUTION_SOURCE_COLLECTION_QWEN_SEARCH_MODEL"
_DASHSCOPE_SEARCH_MODEL_DEFAULT = "qwen3.8-flash"
_DASHSCOPE_RESPONSES_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS_DEFAULT = 4096
_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS_ENV = "VIBELUTION_SOURCE_COLLECTION_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS"
_QWEN_DEEP_SEARCH_TASK_MAX_CHARS = 4000
_QWEN_DEEP_SEARCH_TASK_DIRECTION_LIMIT = 12


def _dashscope_search_api_key() -> str:
    """Read the DashScope API key from the environment ("" = not configured)."""
    return str(os.environ.get(_DASHSCOPE_SEARCH_API_KEY_ENV) or "").strip()


def _dashscope_search_model() -> str:
    """Deep-search model id (env-overridable; ``qwen3.8`` bare id is rejected)."""
    raw = str(os.environ.get(_DASHSCOPE_SEARCH_MODEL_ENV) or "").strip()
    return raw or _DASHSCOPE_SEARCH_MODEL_DEFAULT


def _qwen_deep_search_max_output_tokens() -> int:
    """Output-token ceiling for the deep-search call (cost/latency bound)."""
    s = _service()
    raw = str(os.environ.get(_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS_ENV) or "").strip()
    return s._normalize_int(raw, default=_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS_DEFAULT, minimum=512, maximum=16384)


def _qwen_deep_search_question_en(run: dict[str, Any]) -> str:
    """Resolve the challenge question's English text from the run scope.

    Deep-search tasks are phrased in English because the primary literature is
    English; the run scope pins only ``questionId``, so the official catalog is
    the authority for the question text.  Any resolution failure degrades to
    the goal/topic task lines (fail-open — never blocks collection).
    """
    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    question_id = s._trim_text(scope.get("questionId"), max_length=64)
    if not question_id:
        return ""
    try:
        from core.research.competition.resources import load_science_question_catalog

        catalog = load_science_question_catalog()
    except Exception:  # noqa: BLE001 - catalog problems must not block search
        return ""
    for item in catalog.get("questions") if isinstance(catalog.get("questions"), list) else []:
        if isinstance(item, dict) and s._trim_text(item.get("id"), max_length=64) == question_id:
            return s._trim_text(item.get("question_en"), max_length=600)
    return ""


def _qwen_deep_search_task(run: dict[str, Any], assignments: list[dict[str, Any]]) -> str:
    """Compose the one natural-language task for the run-level deep search.

    The task merges the question's English text (catalog-resolved), the
    collection goal/topic, envelope keywords, and the currently assigned
    search directions into a single paragraph so the model searches the same
    research question the per-query providers are sweeping with keywords.
    """
    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    question_en = _qwen_deep_search_question_en(run)
    goal = s._trim_text(scope.get("goal"), max_length=600)
    topic = s._trim_text(scope.get("topic"), max_length=300)
    envelope = scope.get("searchEnvelope") if isinstance(scope.get("searchEnvelope"), dict) else {}
    keywords = [item for item in list(envelope.get("keywords") or [])[:8] if s._trim_text(item, max_length=200)]
    directions: list[str] = []
    for assignment in assignments if isinstance(assignments, list) else []:
        if not isinstance(assignment, dict):
            continue
        assignment_scope = assignment.get("scope") if isinstance(assignment.get("scope"), dict) else {}
        for query in list(assignment_scope.get("assignedQueries") or []):
            if not isinstance(query, dict):
                continue
            text = s._trim_text(query.get("query"), max_length=200)
            if text and text not in directions:
                directions.append(text)
            if len(directions) >= _QWEN_DEEP_SEARCH_TASK_DIRECTION_LIMIT:
                break
        if len(directions) >= _QWEN_DEEP_SEARCH_TASK_DIRECTION_LIMIT:
            break
    if not (question_en or goal or topic or keywords or directions):
        # Nothing to search for: the caller records an empty-task skip instead
        # of sending an instruction-only prompt to the model.
        return ""
    lines = ["Literature search task for a research evidence collection run."]
    if question_en:
        lines.append(f"Research question: {question_en}")
    if goal:
        lines.append(f"Collection goal: {goal}")
    if topic:
        lines.append(f"Topic: {topic}")
    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")
    if directions:
        lines.append("Current search directions:")
        lines.extend(f"- {text}" for text in directions)
    lines.append(
        "Search the open web for the most authoritative primary sources that answer this "
        "research question: peer-reviewed journal articles, official publisher pages, and "
        "preprint servers such as arXiv. Prefer primary literature over blogs, news, or "
        "course materials, and include the canonical abstract URL for every source you rely on."
    )
    return s._trim_text("\n".join(lines), max_length=_QWEN_DEEP_SEARCH_TASK_MAX_CHARS)


def _qwen_deep_search_request_payload(task_text: str) -> dict[str, Any]:
    """Build one non-streaming Responses API web_search request body."""
    return {
        "model": _dashscope_search_model(),
        "input": task_text,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": _qwen_deep_search_max_output_tokens(),
    }


def _current_research_stage(phases: list[dict[str, Any]], workflow: dict[str, Any]) -> str:
    s = _service()
    for phase in phases:
        if phase.get("activeRoundId"):
            return str(phase.get("stageType") or "")
    state_machine = workflow.get("stateMachine") if isinstance(workflow.get("stateMachine"), dict) else {}
    return str(state_machine.get("currentStage") or "knowledge_collection")


def _decode_local_workspace_sample(sample_bytes: bytes) -> str:
    s = _service()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return sample_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return sample_bytes.decode("utf-8", errors="ignore")


def _dedupe_text_values(values: list[Any]) -> list[str]:
    s = _service()
    result: list[str] = []
    for value in values:
        text = s._trim_text(value, max_length=500)
        if text and text not in result:
            result.append(text)
    return result


def _ensure_project_child(path: Path) -> Path:
    s = _service()
    resolved = path.resolve()
    project_root = s._project_root().resolve()
    workspace_root = s.resolve_workspace_home().resolve()
    for allowed_root in (project_root, workspace_root):
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    raise s.TeamWorkflowOrchestrationError("Source collection storage path must stay inside the Vibelution project or workspace data root.")


def _filtered_candidates(
    candidate_store: dict[str, Any],
    *,
    candidate_type: str,
    current_state: str,
    quality_status: str,
) -> list[dict[str, Any]]:
    s = _service()
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate_type and str(candidate.get("candidateType") or "") != candidate_type:
            continue
        if current_state and str(candidate.get("currentState") or "") != current_state:
            continue
        if quality_status and str(candidate.get("qualityStatus") or "") != quality_status:
            continue
        filtered.append(candidate)
    return filtered


def _find_candidate_by_id(candidate_store: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    s = _service()
    for candidate in [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]:
        if str(candidate.get("candidateId") or "") == candidate_id:
            return candidate
    return None


def _find_candidate_imported_from_data_record(candidate_store: dict[str, Any], run_id: str, record_id: str) -> dict[str, Any] | None:
    s = _service()
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id and str(imported_from.get("recordId") or "") == record_id:
            return candidate
    return None


def _first_non_empty_text(*values: Any) -> str:
    s = _service()
    for value in values:
        text = s._trim_text(value, max_length=1200)
        if text:
            return text
    return ""


def _has_any_list_value(value: Any) -> bool:
    s = _service()
    return isinstance(value, list) and any(s._has_value(item) for item in value)


def _has_citation_anchor(value: dict[str, Any]) -> bool:
    s = _service()
    source_ref = s._trim_text(value.get("sourceRef") or value.get("sourceRefId") or value.get("sourceId"), max_length=240)
    page = s._trim_text(value.get("page") or value.get("pageAnchor") or value.get("pageRange"), max_length=120)
    citation = s._trim_text(value.get("citation") or value.get("citationAnchor"), max_length=240)
    evidence_ref = s._trim_text(value.get("evidenceRef") or value.get("evidenceRefId"), max_length=240)
    return bool(source_ref and (page or citation or evidence_ref))


def _has_neuro_term_or_unknown(value: Any) -> bool:
    s = _service()
    if isinstance(value, list):
        return any(s._has_value(item) for item in value)
    text = s._trim_text(value, max_length=160).lower()
    return bool(text)


def _has_value(value: Any) -> bool:
    s = _service()
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _is_over_analogy_risky(value: Any) -> bool:
    s = _service()
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        level = s._trim_text(value.get("level") or value.get("severity") or value.get("riskLevel"), max_length=80).lower()
        status = s._trim_text(value.get("status"), max_length=80).lower()
        return level in {"high", "critical", "severe", "高", "严重"} or status in {"unresolved", "open", "未解决"}
    if isinstance(value, list):
        return any(s._is_over_analogy_risky(item) for item in value)
    text = s._trim_text(value, max_length=400).lower()
    return text in {"high", "critical", "severe", "高", "严重"} or "over" in text or "过度" in text or "unsupported" in text or "unresolved" in text


def _load_data_processing_record(run_id: str, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    s = _service()
    try:
        run = s.data_processing_service.get_processing_run(run_id)
        records = s.data_processing_service.list_records(run_id).get("records", [])
    except s.data_processing_service.DataProcessingNotFoundError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    record = next((item for item in records if isinstance(item, dict) and str(item.get("recordId") or "") == record_id), None)
    if record is None:
        raise s.TeamWorkflowOrchestrationError(f"Data processing record not found: {record_id}")
    return run, record


def _looks_like_url(value: str) -> bool:
    s = _service()
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _metadata_text_values(value: Any) -> list[str]:
    s = _service()
    if isinstance(value, str):
        return [s._trim_text(value, max_length=220)] if s._trim_text(value, max_length=220) else []
    if isinstance(value, list):
        results: list[str] = []
        for item in value[:24]:
            results.extend(s._metadata_text_values(item))
        return results
    if isinstance(value, dict):
        results: list[str] = []
        for item in value.values():
            results.extend(s._metadata_text_values(item))
        return results
    return []


def _normalize_candidate_type(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80) or "source_manifest"
    if normalized not in s.CANDIDATE_TYPES:
        raise s.TeamWorkflowOrchestrationError("Candidate type is invalid.")
    return normalized


def _normalize_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    s = _service()
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _normalize_metadata(value: Any) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    return {
        s._trim_text(key, max_length=80): s._normalize_metadata_value(item)
        for key, item in value.items()
        if s._trim_text(key, max_length=80)
    }


def _normalize_metadata_list(value: Any, *, max_items: int) -> list[dict[str, Any]]:
    s = _service()
    if not isinstance(value, list):
        return []
    return [s._normalize_metadata(item) for item in value[:max_items] if isinstance(item, dict)]


def _normalize_metadata_value(value: Any) -> Any:
    s = _service()
    if isinstance(value, str):
        return s._trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [s._normalize_metadata_value(item) for item in value[:24]]
    if isinstance(value, dict):
        return s._normalize_metadata(value)
    return s._trim_text(value, max_length=1000)


def _normalize_rating_enum(value: Any, allowed: set[str], *, default: str) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "reviewable": "medium",
        "needs_review": "elevated",
        "pending_review": "elevated",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def _normalize_ref_list(value: Any, *, max_items: int) -> list[dict[str, str]]:
    s = _service()
    if not isinstance(value, list):
        return []
    refs: list[dict[str, str]] = []
    for item in value[:max_items]:
        if isinstance(item, dict):
            ref_type = s._trim_text(item.get("type"), max_length=80)
            ref_id = s._trim_text(item.get("id"), max_length=240)
            label = s._trim_text(item.get("label"), max_length=240)
            if ref_type or ref_id or label:
                refs.append({"type": ref_type, "id": ref_id, "label": label})
        else:
            label = s._trim_text(item, max_length=240)
            if label:
                refs.append({"type": "text", "id": "", "label": label})
    return refs


def _normalize_required_id(value: Any, message: str) -> str:
    s = _service()
    normalized = s._safe_token(value, default="", max_length=128)
    if not normalized:
        raise s.TeamWorkflowOrchestrationError(message)
    return normalized


def _normalize_stage_start_mode(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80)
    return "new_round" if normalized in {"new_round", "new", "restart"} else "continue_or_start"


def _normalize_stage_type(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80)
    if normalized not in s.RESEARCH_STAGE_TYPES:
        raise s.TeamWorkflowOrchestrationError("Unsupported research stage type.")
    return normalized


def _normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    s = _service()
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:max_items]:
        text = s._trim_text(item, max_length=max_length)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_workflow_kind(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80) or s.WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH
    if normalized not in s.ALLOWED_WORKFLOW_KINDS:
        raise s.TeamWorkflowOrchestrationError("Workflow kind is not enabled.")
    return normalized


def _open_local_path(path: Path) -> None:
    s = _service()
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _page_numbers_from_scope(page_scope: str, *, total_pages: int, max_pages: int) -> list[int]:
    s = _service()
    if total_pages <= 0 or max_pages <= 0:
        return []
    normalized_scope = s._trim_text(page_scope, max_length=160)
    if not normalized_scope:
        return list(range(1, min(total_pages, max_pages) + 1))
    page_numbers: list[int] = []
    for part in re.split(r"[,;，；\s]+", normalized_scope):
        token = part.strip()
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", token)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                start, end = end, start
            page_numbers.extend(range(start, end + 1))
        elif token.isdigit():
            page_numbers.append(int(token))
    normalized: list[int] = []
    for number in page_numbers:
        if 1 <= number <= total_pages and number not in normalized:
            normalized.append(number)
        if len(normalized) >= max_pages:
            break
    return normalized or list(range(1, min(total_pages, max_pages) + 1))


def _parse_first_json_object(text: Any) -> dict[str, Any] | None:
    s = _service()
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(raw)
    sliced = s._slice_first_json_object(raw)
    if sliced and sliced not in candidates:
        candidates.append(sliced)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _payload_score(payload: dict[str, Any], key: str, default: int) -> int:
    s = _service()
    if key not in payload or payload.get(key) is None:
        return s._clamp_score(default)
    return s._clamp_score(s._normalize_int(payload.get(key), default=default, minimum=0, maximum=100))


def _project_root() -> Path:
    s = _service()
    root = Path(s.PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    s = _service()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _relative_path(path: Path) -> str:
    s = _service()
    try:
        return str(path.resolve().relative_to(s._project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _repair_workflow(payload: dict[str, Any], team_id: str) -> dict[str, Any]:
    s = _service()
    base = s._default_workflow(
        team_id,
        workflow_kind=s._normalize_workflow_kind(payload.get("workflowKind") or s.WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH),
        owner_agent_id=s._trim_text(payload.get("ownerAgentId"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID,
    )
    for key in (
        "workflowId",
        "status",
        "stateMachine",
        "routingPolicy",
        "transferPolicy",
        "activeWorkflowItems",
        "createdAt",
        "updatedAt",
    ):
        if key in payload:
            base[key] = payload[key]
    base["schemaVersion"] = s.SCHEMA_VERSION
    base["teamId"] = team_id
    base["workflowId"] = s._trim_text(base.get("workflowId"), max_length=120) or s.DEFAULT_WORKFLOW_ID
    base["status"] = s._trim_text(base.get("status"), max_length=32) or "active"
    if not isinstance(base.get("activeWorkflowItems"), list):
        base["activeWorkflowItems"] = []
    base["routingPolicy"] = s._sync_owner_policy(base.get("routingPolicy"), str(base.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID))
    base["transferPolicy"] = s._sync_transfer_policy(base.get("transferPolicy"), str(base.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID))
    return base


def _requires_terminology_uncertain(output: dict[str, Any]) -> bool:
    s = _service()
    terms = [output.get("brainSystems"), output.get("cognitiveFunctions"), output.get("uncertainty")]
    for value in terms:
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = s._trim_text(item, max_length=400).lower()
            if text in {"unknown", "uncertain", "不确定", "未知"} or "terminology" in text or "术语" in text:
                return True
    return False


def _research_stage_boundaries() -> dict[str, bool]:
    s = _service()
    return {
        "externalSearchTriggered": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "autoTransitionsNextStage": False,
        "stageRecordsOnly": True,
    }


def _risk_flags_include(output: dict[str, Any], flag: str) -> bool:
    s = _service()
    risk_flags = output.get("riskFlags")
    return isinstance(risk_flags, list) and flag in {str(item) for item in risk_flags}


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return default
    text = s._SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _slice_first_json_object(text: str) -> str:
    s = _service()
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _source_extraction_anchor_id(candidate: dict[str, Any], anchor: dict[str, Any]) -> str:
    s = _service()
    page = int(anchor.get("page") or 0)
    source_token = s._safe_token(candidate.get("candidateId"), default="source", max_length=48)
    return s._trim_text(anchor.get("id"), max_length=240) or f"{source_token}-p{page}"


def _stage_agent_binding_warnings(assignments: list[dict[str, Any]]) -> list[dict[str, str]]:
    s = _service()
    warnings: list[dict[str, str]] = []
    for item in assignments:
        agent_role = str(item.get("agentRole") or "")
        agent_id = str(item.get("agentId") or "")
        if agent_role and agent_id == agent_role:
            warnings.append(
                {
                    "code": "agent_binding_missing",
                    "severity": "warning",
                    "message": f"{agent_role} has no concrete team agent binding.",
                }
            )
    return warnings


def _stage_default_goal(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    s = _service()
    if previous_round:
        inherited = s._trim_text(previous_round.get("goal"), max_length=1000)
        if inherited:
            return inherited
    if stage_type == "experiment":
        return "Plan experiments from accepted knowledge-collection candidates without executing them automatically."
    if stage_type == "iteration":
        return "Plan the next improvement round from experiment evidence and unresolved risks."
    return "Collect traceable research sources for neuroscience-inspired algorithm discovery."


def _stage_default_topic(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    s = _service()
    if previous_round:
        inherited = s._trim_text(previous_round.get("topic"), max_length=500)
        if inherited:
            return inherited
    return {
        "experiment": "challenge cup experiment planning",
        "iteration": "challenge cup iteration planning",
    }.get(stage_type, "challenge cup research")


def _stage_label(stage_type: str) -> str:
    s = _service()
    return {
        "knowledge_collection": "知识搜集",
        "experiment": "实验",
        "iteration": "迭代",
    }.get(stage_type, stage_type)


def _stage_memory_record(stage_round: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "recordId": s._new_record_id("stagemem"),
        "recordKind": "team_workflow_stage_record",
        "workflowId": workflow.get("workflowId", s.DEFAULT_WORKFLOW_ID),
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_round.get("stageType", ""),
        "roundNumber": stage_round.get("roundNumber", 0),
        "status": stage_round.get("status", ""),
        "topic": stage_round.get("topic", ""),
        "goal": stage_round.get("goal", ""),
        "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
        "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        "promptCachePolicyRef": s._source_collection_prompt_cache_policy_ref(stage_round.get("promptCachePolicy") if isinstance(stage_round.get("promptCachePolicy"), dict) else {}),
        "memoryContextId": str((stage_round.get("memoryContext") or {}).get("contextId") or ""),
        "boundary": "runtime_stage_record_only_not_formal_team_knowledge",
        "createdAt": s.utc_now_iso(),
    }


def _stage_next_actions(stage_type: str, *, reused: bool) -> list[str]:
    s = _service()
    if reused:
        return ["Continue the active stage round instead of creating a duplicate.", "Open the matching research workspace view."]
    if stage_type == "knowledge_collection":
        return [
            "Open Source collection to inspect query seeds, assignments, and writeback contract.",
            "Functional agents submit CollectionOutput records before candidate import.",
            "User decides whether to start experiment after screening.",
        ]
    if stage_type == "experiment":
        return ["Review upstream knowledge-collection evidence.", "Draft experiment plan; do not auto-run experiments."]
    return ["Review experiment evidence.", "Plan the next iteration round; do not auto-apply changes."]


def _stage_planning_contract(stage_type: str, stage_round: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    if stage_type == "experiment":
        expected_outputs = ["experiment_plan", "baseline_selection", "success_metrics", "risk_controls"]
    elif stage_type == "iteration":
        expected_outputs = ["iteration_goal", "change_list", "evidence_to_compare", "next_round_entry"]
    else:
        expected_outputs = ["source_manifest_candidates"]
    return {
        "contractKind": f"{stage_type}_planning_contract",
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "expectedOutputs": expected_outputs,
        "autoExecution": False,
        "requiresUserDecision": True,
    }


def _stage_query_seeds(payload: dict[str, Any], previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    s = _service()
    seeds = s._normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220)
    if seeds:
        return seeds
    suggested = s._suggest_stage_query_seeds(previous_round, topic=topic, goal=goal)
    if suggested:
        return suggested[:8]
    return [item for item in [topic, goal] if item][:2]


def _stage_readiness(
    team_id: str,
    stage_type: str,
    rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    if stage_type == "knowledge_collection":
        return {"ready": True, "reason": "知识搜集可随时多轮启动。"}
    if stage_type == "experiment":
        latest_collection = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return {
            "ready": bool(latest_collection),
            "reason": "已有知识搜集轮次，可由用户决定进入实验规划。" if latest_collection else "需要先启动至少一轮知识搜集。",
        }
    latest_experiment = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    if not latest_experiment:
        return {
            "ready": False,
            "code": "missing_experiment_stage_round",
            "reason": "需要先启动实验规划。",
        }
    from core.web.services.team_workflow.research_project_agent_tasks import (
        research_project_iteration_readiness,
    )

    research_project = s.resolve_research_project_identity(team_id, "")
    readiness = research_project_iteration_readiness(
        team_id,
        research_project["projectId"],
    )
    return {
        **readiness,
        "reason": readiness.get("reasonZh") or readiness["reason"],
    }


def _stage_upstream_round_ids(
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    stage_type: str,
    previous_round: dict[str, Any] | None,
) -> list[str]:
    s = _service()
    explicit = s._normalize_text_list(payload.get("upstreamRoundIds"), max_items=24, max_length=160)
    if explicit:
        return explicit
    if stage_type == "knowledge_collection":
        return [str(previous_round.get("stageRoundId"))] if previous_round and previous_round.get("stageRoundId") else []
    if stage_type == "experiment":
        latest_collection = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return [str(latest_collection.get("stageRoundId"))] if latest_collection and latest_collection.get("stageRoundId") else []
    latest_experiment = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    return [str(latest_experiment.get("stageRoundId"))] if latest_experiment and latest_experiment.get("stageRoundId") else []


def _strip_html(value: str) -> str:
    s = _service()
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _suggest_stage_query_seeds(previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    s = _service()
    seeds: list[str] = []
    if previous_round:
        for warning in list(previous_round.get("warnings") or []):
            if isinstance(warning, dict):
                s._append_source_collection_seed(seeds, warning.get("message"))
        for item in list(previous_round.get("suggestedQuerySeeds") or [])[:6]:
            s._append_source_collection_seed(seeds, item)
        for item in list(previous_round.get("querySeeds") or [])[:6]:
            s._append_source_collection_seed(seeds, f"{item} missing evidence")
    s._append_source_collection_seed(seeds, topic)
    if goal:
        s._append_source_collection_seed(seeds, goal)
    return seeds[:10]


def _sync_owner_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    s = _service()
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "coordinationAgentId": owner_agent_id,
        "functionalAgentsMayRequestTransfer": True,
        "finalStateWriter": owner_agent_id,
    }


def _sync_transfer_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    s = _service()
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "requiresUserConfirmation": False,
        "requestedBy": "functional_agent",
        "decidedBy": owner_agent_id,
        "recordDecidedByAgent": True,
    }


def _team_workflow_kernel_summary(kernel_result: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    event = kernel_result.get("event") if isinstance(kernel_result.get("event"), dict) else {}
    task = kernel_result.get("task") if isinstance(kernel_result.get("task"), dict) else {}
    execution = kernel_result.get("execution") if isinstance(kernel_result.get("execution"), dict) else {}
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    adapter = kernel_result.get("adapter") if isinstance(kernel_result.get("adapter"), dict) else {}
    return {
        "eventId": str(adapter.get("eventId") or event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome.get("status") or "").strip(),
        "adapterVersion": str(adapter.get("adapterVersion") or "").strip(),
        "reused": bool(kernel_result.get("reused", False)),
    }


def _trim_text(value: Any, *, max_length: int) -> str:
    s = _service()
    text = str(value or "").strip()
    return text[:max_length]


def _upsert_active_item(
    items: Any,
    *,
    candidate_id: str,
    current_node: str,
    status: str,
    transfer_id: str,
) -> list[dict[str, Any]]:
    s = _service()
    normalized_items = [item for item in list(items or []) if isinstance(item, dict)]
    now = s.utc_now_iso()
    next_item = {
        "candidateId": candidate_id,
        "currentNode": current_node,
        "status": status,
        "pendingTransferId": transfer_id,
        "updatedAt": now,
    }
    for index, item in enumerate(normalized_items):
        if str(item.get("candidateId") or "") == candidate_id:
            normalized_items[index] = {**item, **next_item}
            return normalized_items
    normalized_items.append(next_item)
    return normalized_items


def _workflow_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "workflow_orchestration.json"


def _workflow_timestamp_sort_key(value: Any) -> tuple[float, str]:
    s = _service()
    text = s._trim_text(value, max_length=120)
    if not text:
        return (0.0, "")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.timestamp(), text)
    except ValueError:
        return (0.0, text)


def _workflow_to_api(
    team_id: str,
    workflow: dict[str, Any],
    candidate_store: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    return {
        **workflow,
        "candidateStore": {
            "schemaVersion": s.SCHEMA_VERSION,
            "candidateCount": len(candidates),
            "candidateTypes": sorted({str(item.get("candidateType") or "") for item in candidates if item.get("candidateType")}),
            "updatedAt": str(candidate_store.get("updatedAt") or ""),
            "storagePath": s._relative_path(s._candidate_store_path(team_id)),
        },
        "transferRecordsPath": s._relative_path(s._transfer_records_path(team_id)),
        "storagePath": s._relative_path(s._workflow_path(team_id)),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # Keep the temporary leaf shorter than the target leaf: pytest-xdist and
    # Windows user profiles can otherwise push an otherwise valid target path
    # across the legacy 260-character limit before ``os.replace`` runs.
    fd, temp_name = tempfile.mkstemp(prefix=".tmp-", suffix="", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def utc_now_iso() -> str:
    s = _service()
    return datetime.now(timezone.utc).isoformat()
