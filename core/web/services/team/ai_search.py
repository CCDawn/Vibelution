"""Team AI search source-scope runs and page ranking helpers.

Claim scope: AI search run start/list, source-scope file IO, query card execution,
and page-fallback parsing. Pure ranking stays in ai_search_ranking; system team
materialize stays in system_teams.
Late-binds ``team_service`` for constants, paths, and ensure_ai_search_system_team.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx

from core.chat.chat_task_types import trim_lines
from core.web.services.team.ai_search_ranking import _clean_ai_search_source_text


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def list_ai_search_source_scope_runs(team_id: str, *, limit: int = 6) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    if normalized_team_id != s.AI_SEARCH_TEAM_ID:
        raise s.TeamServiceError("AI search runs are only available for the AI search scope Team.")
    s.ensure_ai_search_system_team()
    index = s._load_ai_search_runs_index()
    runs = [
        item for item in list(index.get("runs") or [])
        if isinstance(item, dict)
    ]
    runs.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
    limited_runs = runs[: max(1, min(int(limit or 6), 20))]
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": s.AI_SEARCH_TEAM_ID,
        "runs": limited_runs,
        "summary": {
            "runCount": len(runs),
            "visibleRunCount": len(limited_runs),
        },
        "storage": {
            "runsPath": s._relative_path(s._ai_search_runs_index_path()),
            "runsRoot": s._relative_path(s._ai_search_runs_root()),
        },
        "updatedAt": str(index.get("updatedAt") or ""),
    }


def start_ai_search_source_scope_run(
    team_id: str,
    *,
    topic: str = "",
    source_limit: int = 8,
    max_results_per_query: int = 3,
    include_signals: bool = False,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    if normalized_team_id != s.AI_SEARCH_TEAM_ID:
        raise s.TeamServiceError("AI search runs can only be started from the AI search scope Team.")
    s.ensure_ai_search_system_team()
    scope = s._load_ai_search_source_scope()
    query_topic = trim_lines(topic or "AI 最新动态", max_lines=1).strip() or "AI 最新动态"
    bounded_source_limit = max(1, min(int(source_limit or 8), 12))
    bounded_max_results = max(1, min(int(max_results_per_query or 3), 10))
    selected_sources = s._select_ai_search_sources(scope, source_limit=bounded_source_limit, include_signals=include_signals)
    if not selected_sources:
        raise s.TeamServiceError("AI search source scope has no enabled sources to search.")
    now = s.utc_now_iso()
    run_id = s._new_ai_search_run_id()
    queries = [
        s._ai_search_query_for_source(source, topic=query_topic, run_id=run_id, index=index)
        for index, source in enumerate(selected_sources, start=1)
    ]
    run = {
        "schemaVersion": s.SCHEMA_VERSION,
        "runId": run_id,
        "teamId": s.AI_SEARCH_TEAM_ID,
        "title": f"{query_topic} 一键搜索",
        "topic": query_topic,
        "status": "running",
        "createdAt": now,
        "updatedAt": now,
        "sourceScope": {
            "scopeId": str(scope.get("scopeId") or ""),
            "sourceScopePath": s._relative_path(s._ai_search_source_scope_path()),
            "defaultEnabledTiers": list((scope.get("policy") or {}).get("defaultEnabledTiers") or []),
            "requiresPrimaryEvidenceForConclusion": bool((scope.get("policy") or {}).get("requiresPrimaryEvidenceForConclusion")),
        },
        "queryPlan": {
            "queryCount": len(queries),
            "sourceLimit": bounded_source_limit,
            "maxResultsPerQuery": bounded_max_results,
            "includeSignals": bool(include_signals),
            "queries": queries,
        },
        "cards": [],
        "errors": [],
        "summary": {
            "cardCount": 0,
            "succeededCount": 0,
            "failedCount": 0,
            "degradedCount": 0,
            "referenceCount": 0,
        },
        "storage": {
            "runPath": s._relative_path(s._ai_search_run_path(run_id)),
            "runsPath": s._relative_path(s._ai_search_runs_index_path()),
        },
    }
    s._record_team_event(
        "team.ai_search_run.started",
        {"teamId": s.AI_SEARCH_TEAM_ID, "name": s.AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
        fields={
            "runId": run_id,
            "topic": query_topic,
            "queryCount": len(queries),
            "sourceLimit": bounded_source_limit,
            "includeSignals": bool(include_signals),
        },
    )
    cards: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for query in queries:
        card = s._execute_ai_search_query_card(query, max_results=bounded_max_results)
        cards.append(card)
        if card["status"] == "failed":
            errors.append({"queryId": query["queryId"], "sourceId": query["sourceId"], "message": card["summary"]})
    succeeded_count = sum(1 for card in cards if card.get("status") == "succeeded")
    failed_count = len(cards) - succeeded_count
    degraded_count = sum(1 for card in cards if bool(card.get("degraded")))
    reference_count = sum(len(list(card.get("references") or [])) for card in cards)
    status = "failed" if failed_count == len(cards) else "partial" if failed_count else "completed"
    run.update(
        {
            "status": status,
            "updatedAt": s.utc_now_iso(),
            "cards": cards,
            "errors": errors,
            "summary": {
                "cardCount": len(cards),
                "succeededCount": succeeded_count,
                "failedCount": failed_count,
                "degradedCount": degraded_count,
                "referenceCount": reference_count,
            },
        }
    )
    s._write_json(s._ai_search_run_path(run_id), run)
    s._upsert_ai_search_run_summary(run)
    if degraded_count:
        s._record_team_event(
            "team.ai_search_run.fallback_used",
            {"teamId": s.AI_SEARCH_TEAM_ID, "name": s.AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
            fields={
                "runId": run_id,
                "topic": query_topic,
                "degradedCount": degraded_count,
                "searchModes": sorted({str(card.get("searchMode") or "").strip() for card in cards if bool(card.get("degraded"))}),
                "sourceIds": [str(card.get("sourceId") or "").strip() for card in cards if bool(card.get("degraded"))],
            },
        )
    s._record_team_event(
        "team.ai_search_run.completed",
        {"teamId": s.AI_SEARCH_TEAM_ID, "name": s.AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
        fields={
            "runId": run_id,
            "topic": query_topic,
            "status": status,
            "queryCount": len(queries),
            "succeededCount": succeeded_count,
            "failedCount": failed_count,
            "degradedCount": degraded_count,
            "referenceCount": reference_count,
            "runPath": s._relative_path(s._ai_search_run_path(run_id)),
        },
    )
    return run


def _default_ai_search_source_scope() -> dict[str, Any]:
    s = _service()
    groups = [dict(group) for group in s.AI_SEARCH_SOURCE_SCOPE_GROUPS]
    normalized_groups: list[dict[str, Any]] = []
    for group in groups:
        sources = []
        for source in list(group.get("sources") or []):
            source_payload = dict(source)
            source_payload["tier"] = str(source_payload.get("tier") or group.get("tier") or "").strip()
            source_payload["evidenceRole"] = str(source_payload.get("evidenceRole") or group.get("evidenceRole") or "").strip()
            source_payload["enabledByDefault"] = bool(group.get("enabledByDefault"))
            source_payload["ownerRole"] = str(group.get("ownerRole") or "").strip()
            source_payload["tags"] = list(source_payload.get("tags") or [])
            sources.append(source_payload)
        normalized_groups.append(
            {
                **group,
                "sources": sources,
                "sourceCount": len(sources),
            }
        )
    source_count = sum(int(group.get("sourceCount") or 0) for group in normalized_groups)
    enabled_count = sum(
        1
        for group in normalized_groups
        for source in list(group.get("sources") or [])
        if bool(source.get("enabledByDefault"))
    )
    return {
        "schemaVersion": s.AI_SEARCH_SOURCE_SCOPE_SCHEMA_VERSION,
        "scopeId": "ai-latest-news-source-scope-v1",
        "teamId": s.AI_SEARCH_TEAM_ID,
        "title": "AI 最新动态搜索范围白名单",
        "description": "一键搜索 AI 最新动态时优先使用的来源范围；Tier3 只作线索，结论必须回链一手证据。",
        "curatedAt": s.AI_SEARCH_SOURCE_SCOPE_CURATED_AT,
        "policy": {
            "defaultEnabledTiers": ["tier1", "tier2"],
            "signalTiers": ["tier3"],
            "requiresPrimaryEvidenceForConclusion": True,
            "dedupeBy": ["canonicalUrl", "sourceId", "title"],
            "writesFormalKnowledge": False,
        },
        "summary": {
            "groupCount": len(normalized_groups),
            "sourceCount": source_count,
            "enabledByDefaultCount": enabled_count,
            "signalOnlyCount": source_count - enabled_count,
        },
        "groups": normalized_groups,
        "storage": {
            "path": s._relative_path(s._ai_search_source_scope_path()),
        },
    }


def _ai_search_source_scope_needs_sync(path: Path) -> bool:
    s = _service()
    if not path.exists():
        return True
    try:
        scope = s._read_json(path)
    except Exception:
        return True
    if int(scope.get("schemaVersion") or 0) != s.AI_SEARCH_SOURCE_SCOPE_SCHEMA_VERSION:
        return True
    if str(scope.get("teamId") or "").strip() != s.AI_SEARCH_TEAM_ID:
        return True
    groups = scope.get("groups") if isinstance(scope.get("groups"), list) else []
    if not groups:
        return True
    group_ids = {
        str(group.get("groupId") or "").strip()
        for group in groups
        if isinstance(group, dict)
    }
    expected_group_ids = {
        str(group.get("groupId") or "").strip()
        for group in s.AI_SEARCH_SOURCE_SCOPE_GROUPS
    }
    return not expected_group_ids.issubset(group_ids)


def _ensure_ai_search_source_scope_file() -> bool:
    s = _service()
    path = s._ai_search_source_scope_path()
    if not s._ai_search_source_scope_needs_sync(path):
        return False
    s._write_json(path, s._default_ai_search_source_scope())
    return True


def _load_ai_search_source_scope() -> dict[str, Any]:
    s = _service()
    path = s._ai_search_source_scope_path()
    if s._ai_search_source_scope_needs_sync(path):
        return s._default_ai_search_source_scope()
    try:
        scope = s._read_json(path)
    except Exception:
        return s._default_ai_search_source_scope()
    scope["storage"] = {
        **dict(scope.get("storage") or {}),
        "path": s._relative_path(path),
    }
    return scope


def _ai_search_source_scope_api_fields(team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    if s._infer_team_kind(team) != "ai_search":
        return {}
    return {
        "sourceScopePath": s._relative_path(s._ai_search_source_scope_path()),
        "sourceScope": s._load_ai_search_source_scope(),
    }


def _select_ai_search_sources(scope: dict[str, Any], *, source_limit: int, include_signals: bool) -> list[dict[str, Any]]:
    s = _service()
    groups = [
        group for group in list(scope.get("groups") or [])
        if isinstance(group, dict)
        and (bool(group.get("enabledByDefault")) or include_signals)
    ]
    selected: list[dict[str, Any]] = []
    group_sources: list[list[dict[str, Any]]] = []
    for group in groups:
        sources = [
            {
                **source,
                "groupId": str(group.get("groupId") or "").strip(),
                "groupLabel": str(group.get("label") or "").strip(),
                "groupTier": str(group.get("tier") or "").strip(),
                "groupEvidenceRole": str(group.get("evidenceRole") or "").strip(),
            }
            for source in list(group.get("sources") or [])
            if isinstance(source, dict)
            and (bool(source.get("enabledByDefault")) or include_signals)
        ]
        if sources:
            group_sources.append(sources)
    cursor = 0
    while len(selected) < source_limit and group_sources:
        next_group_sources: list[list[dict[str, Any]]] = []
        for sources in group_sources:
            if cursor < len(sources) and len(selected) < source_limit:
                selected.append(sources[cursor])
            if cursor + 1 < len(sources):
                next_group_sources.append(sources)
        cursor += 1
        group_sources = next_group_sources
    return selected


def _ai_search_query_for_source(source: dict[str, Any], *, topic: str, run_id: str, index: int) -> dict[str, Any]:
    s = _service()
    url = str(source.get("url") or "").strip()
    domain = urlparse(url).netloc or urlparse(f"https://{url}").netloc
    query_parts = [
        topic,
        str(source.get("name") or "").strip(),
        "latest AI model product research update",
    ]
    if domain:
        query_parts.append(f"site:{domain}")
    query = " ".join(part for part in query_parts if part).strip()
    return {
        "queryId": f"{run_id}-q{index:02d}",
        "query": query,
        "sourceId": str(source.get("sourceId") or "").strip(),
        "sourceName": str(source.get("name") or "").strip(),
        "sourceUrl": url,
        "sourceType": str(source.get("sourceType") or "").strip(),
        "groupId": str(source.get("groupId") or "").strip(),
        "groupLabel": str(source.get("groupLabel") or "").strip(),
        "tier": str(source.get("tier") or source.get("groupTier") or "").strip(),
        "evidenceRole": str(source.get("evidenceRole") or source.get("groupEvidenceRole") or "").strip(),
        "enabledByDefault": bool(source.get("enabledByDefault")),
    }


def _execute_ai_search_query_card(query: dict[str, Any], *, max_results: int) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    query_text = str(query.get("query") or "").strip()
    search_mode = "web_search"
    degraded = False
    fallback_reason = ""
    try:
        result_text = s._run_ai_web_search(query_text, max_results=max_results)
    except Exception as exc:
        result_text = f"[错误] 搜索执行异常: {type(exc).__name__}: {exc}"
    failed = s._ai_search_result_is_error(result_text)
    if failed:
        fallback_reason = s._web_search_summary_text(result_text) or str(result_text or "").strip()
        fallback_text = s._run_ai_source_page_fallback(query, max_results=max_results, primary_error=fallback_reason)
        fallback_failed = s._ai_search_result_is_error(fallback_text)
        if fallback_failed:
            result_text = f"{result_text}\n\n{fallback_text}".strip()
        else:
            result_text = fallback_text
            failed = False
            degraded = True
            search_mode = "source_page_fallback"
    references = [] if failed else s._references_from_web_search_result(result_text)
    return {
        "cardId": f"{query.get('queryId')}-card",
        "queryId": str(query.get("queryId") or "").strip(),
        "sourceId": str(query.get("sourceId") or "").strip(),
        "sourceName": str(query.get("sourceName") or "").strip(),
        "sourceUrl": str(query.get("sourceUrl") or "").strip(),
        "sourceType": str(query.get("sourceType") or "").strip(),
        "groupId": str(query.get("groupId") or "").strip(),
        "groupLabel": str(query.get("groupLabel") or "").strip(),
        "tier": str(query.get("tier") or "").strip(),
        "evidenceRole": str(query.get("evidenceRole") or "").strip(),
        "query": query_text,
        "status": "failed" if failed else "succeeded",
        "searchMode": search_mode,
        "degraded": degraded,
        "fallbackReason": fallback_reason,
        "summary": s._web_search_summary_text(result_text),
        "resultText": result_text,
        "references": references,
        "createdAt": now,
        "updatedAt": now,
    }


def _run_ai_web_search(query: str, *, max_results: int) -> str:
    s = _service()
    from tools.web_search_tool import web_search

    return web_search(query=query, max_results=max_results)


def _run_ai_source_page_fallback(query: dict[str, Any], *, max_results: int, primary_error: str) -> str:
    s = _service()
    source_url = str(query.get("sourceUrl") or "").strip()
    if not source_url:
        return "[错误] 主搜索工具失败，且该来源没有可扫描的官方页面 URL。"
    source_name = str(query.get("sourceName") or query.get("sourceId") or source_url).strip()
    try:
        page = s._fetch_ai_search_source_page(source_url)
    except Exception as exc:
        return f"[错误] 主搜索工具失败，官方源页面扫描也失败: {type(exc).__name__}: {exc}"
    final_url = str(page.get("url") or source_url).strip()
    references = s._rank_ai_search_source_page_references(
        list(page.get("links") or []),
        topic=str(query.get("query") or ""),
        source_name=source_name,
        base_url=final_url,
        max_results=max_results,
    )
    if not references:
        page_title = _clean_ai_search_source_text(str(page.get("title") or source_name or final_url), max_length=160)
        references = [{"title": page_title or final_url, "url": final_url}]
    title = _clean_ai_search_source_text(str(page.get("title") or source_name), max_length=180)
    description = _clean_ai_search_source_text(str(page.get("description") or ""), max_length=360)
    summary_lines = [
        "[降级] 主搜索工具不可用，已改用官方源页面扫描。",
        f"来源: {source_name}",
        f"页面: {title or final_url}",
    ]
    if description:
        summary_lines.append(f"摘要: {description}")
    summary_lines.append(f"主搜索失败原因: {trim_lines(primary_error, max_lines=2)[:260]}")
    summary_lines.append("候选动态:")
    for reference in references[:max_results]:
        summary_lines.append(f"- {reference['title']} ({reference['url']})")
    reference_lines = ["", "**参考来源：**"]
    for index, reference in enumerate(references[:max_results], start=1):
        reference_lines.append(f"{index}. [{reference['title']}]({reference['url']})")
    return "\n".join(summary_lines + reference_lines)


def _fetch_ai_search_source_page(source_url: str) -> dict[str, Any]:
    s = _service()
    normalized_url = str(source_url or "").strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("source URL must use http or https")
    headers = {"User-Agent": s.AI_SEARCH_SOURCE_PAGE_USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=s.AI_SEARCH_SOURCE_PAGE_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.get(normalized_url)
        response.raise_for_status()
    content = response.content[:s.AI_SEARCH_SOURCE_PAGE_MAX_BYTES]
    encoding = response.encoding or "utf-8"
    html = content.decode(encoding, errors="replace")
    parsed_page = s._parse_ai_search_source_page(html, str(response.url))
    parsed_page["url"] = str(response.url)
    return parsed_page


def _parse_ai_search_source_page(html: str, base_url: str) -> dict[str, Any]:
    s = _service()
    parser = s._AiSearchSourcePageParser(base_url=base_url)
    parser.feed(str(html or ""))
    parser.close()
    return {
        "title": _clean_ai_search_source_text(parser.title_text(), max_length=180),
        "description": _clean_ai_search_source_text(parser.description, max_length=360),
        "links": parser.normalized_links(),
    }


class _AiSearchSourcePageParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._in_title = False
        self._title_parts: list[str] = []
        self._current_href = ""
        self._current_anchor_parts: list[str] = []
        self.description = ""
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if normalized_tag == "title":
            self._in_title = True
            return
        if normalized_tag == "meta" and not self.description:
            name = attr_map.get("name") or attr_map.get("property")
            if name.lower() in {"description", "og:description", "twitter:description"}:
                self.description = attr_map.get("content", "")
            return
        if normalized_tag == "a":
            self._current_href = attr_map.get("href", "").strip()
            self._current_anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = False
            return
        if normalized_tag == "a" and self._current_href:
            title = _clean_ai_search_source_text(" ".join(self._current_anchor_parts), max_length=180)
            self.links.append({"title": title or self._current_href, "url": urljoin(self.base_url, self._current_href)})
            self._current_href = ""
            self._current_anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._current_href:
            self._current_anchor_parts.append(data)

    def title_text(self) -> str:
        return " ".join(self._title_parts)

    def normalized_links(self) -> list[dict[str, str]]:
        seen: set[str] = set()
        links: list[dict[str, str]] = []
        for link in self.links:
            url = str(link.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"title": str(link.get("title") or url).strip(), "url": url})
        return links


def _ai_search_result_is_error(result_text: str) -> bool:
    s = _service()
    normalized = str(result_text or "").strip()
    return normalized.startswith("[错误]") or "dependency unavailable" in normalized.lower() or "依赖不可用" in normalized


def _web_search_summary_text(result_text: str) -> str:
    s = _service()
    text = str(result_text or "").strip()
    if not text:
        return ""
    marker = "\n\n**参考来源：**"
    summary = text.split(marker, 1)[0].strip()
    return trim_lines(summary, max_lines=6)[:1200]


def _references_from_web_search_result(result_text: str) -> list[dict[str, str]]:
    s = _service()
    references: list[dict[str, str]] = []
    for match in re.finditer(r"^\s*\d+\.\s+\[([^\]]+)\]\(([^)]+)\)", str(result_text or ""), flags=re.MULTILINE):
        title = match.group(1).strip()
        url = match.group(2).strip()
        if title or url:
            references.append({"title": title, "url": url})
    return references[:10]


def _new_ai_search_run_id() -> str:
    s = _service()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"ai-search-run-{stamp}-{uuid4().hex[:8]}"


def _load_ai_search_runs_index() -> dict[str, Any]:
    s = _service()
    path = s._ai_search_runs_index_path()
    if not path.exists():
        return {"schemaVersion": s.SCHEMA_VERSION, "teamId": s.AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": s.SCHEMA_VERSION, "teamId": s.AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    if not isinstance(data, dict):
        return {"schemaVersion": s.SCHEMA_VERSION, "teamId": s.AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    if not isinstance(data.get("runs"), list):
        data["runs"] = []
    return data


def _upsert_ai_search_run_summary(run: dict[str, Any]) -> None:
    s = _service()
    index = s._load_ai_search_runs_index()
    run_id = str(run.get("runId") or "").strip()
    summary = {
        "runId": run_id,
        "teamId": s.AI_SEARCH_TEAM_ID,
        "title": str(run.get("title") or "").strip(),
        "topic": str(run.get("topic") or "").strip(),
        "status": str(run.get("status") or "").strip(),
        "createdAt": str(run.get("createdAt") or "").strip(),
        "updatedAt": str(run.get("updatedAt") or "").strip(),
        "queryCount": int((run.get("queryPlan") or {}).get("queryCount") or 0),
        "cardCount": int((run.get("summary") or {}).get("cardCount") or 0),
        "succeededCount": int((run.get("summary") or {}).get("succeededCount") or 0),
        "failedCount": int((run.get("summary") or {}).get("failedCount") or 0),
        "degradedCount": int((run.get("summary") or {}).get("degradedCount") or 0),
        "referenceCount": int((run.get("summary") or {}).get("referenceCount") or 0),
        "runPath": s._relative_path(s._ai_search_run_path(run_id)) if run_id else "",
        "cards": list(run.get("cards") or [])[:12],
    }
    runs = [
        item for item in list(index.get("runs") or [])
        if isinstance(item, dict) and str(item.get("runId") or "").strip() != run_id
    ]
    runs.insert(0, summary)
    index.update(
        {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": s.AI_SEARCH_TEAM_ID,
            "updatedAt": str(run.get("updatedAt") or s.utc_now_iso()),
            "runs": runs[:50],
        }
    )
    s._write_json(s._ai_search_runs_index_path(), index)


def _ai_search_source_scope_path() -> Path:
    s = _service()
    return s._teams_root() / s.AI_SEARCH_TEAM_ID / "source_scope.json"


def _ai_search_runs_root() -> Path:
    s = _service()
    return s._teams_root() / s.AI_SEARCH_TEAM_ID / "search_runs"


def _ai_search_runs_index_path() -> Path:
    s = _service()
    return s._ai_search_runs_root() / "index.json"


def _ai_search_run_path(run_id: str) -> Path:
    s = _service()
    return s._ai_search_runs_root() / f"{s._safe_token(run_id, default='run', max_length=96)}.json"
