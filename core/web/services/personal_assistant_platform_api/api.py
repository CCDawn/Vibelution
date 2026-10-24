"""Read-only loopback platform API access for the personal assistant.

The assistant manages the platform through the same HTTP surface the
workbench UI uses.  This pack exposes a GET-only gateway to that surface:

- The control token never crosses the model boundary: the executor calls
  ``core.web.control.get_control_token`` in-process and attaches the header
  itself.
- Only explicitly audited (GET, path) pairs that remain registered in the
  live OpenAPI spec are callable. Tags organize the index, never grant access.
- Private-content sub-resources are denied by path token even inside allowed
  tags: message bodies, transcripts, exports, timelines, inboxes, events.
- Every response carries ``untrustedContent``; payloads are size-truncated
  with an explicit marker.
- Redirects are never followed and HTTP error bodies never leave the process.
- Application catalogs and financial workspaces use closed field projections;
  invalid or oversized projected responses fail closed without a raw fallback.

``path="index"`` navigates the allowlisted surface (per-tag endpoint lists),
``path="/api/..."`` executes one GET.  No mutations: write-side management
keeps going through ``personal_assistant_manage_tool`` and its approvals.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Any

# Index categories, not an authorization policy. Deliberately
# excluded: ``memory`` (agent-private memories), ``external-agent`` (MCP
# protocol surface), ``user-content``/``files`` (raw user documents),
# ``logs`` (untrusted raw logs; use the project-query pack), ``config``
# (provider credentials until masking is proven), ``computer-use`` (screen
# data goes through the consented computer tools) and untagged endpoints.
ALLOWED_TAGS = frozenset(
    {
        "runtime",
        "launcher",
        "runtime-tasks",
        "cli-agents",
        "diagnostics",
        "usage",
        "agents",
        "agent-plugins",
        "agent-kernel",
        "sessions",
        "session-archive",
        "chat-rooms",
        "teams",
        "team-templates",
        "team-workflows",
        "knowledge",
        "skills",
        "tools",
        "research",
        "research-evidence",
        "research-loop",
        "git",
        "evolution",
        "data-processing",
        "virtual-human-life",
        "personal-assistant",
        "financial-assistant",
        "financial-team",
        "financial-jobs",
        "financial-reports",
        "financial-backtests",
        "financial-portfolio",
        "financial-research",
        "financial-paper",
        "financial-preferences",
    }
)

# Path words that mark private content even under an allowed tag.  Matched as
# whole words per path segment (``-``/``_`` split), so ``member-messages`` is
# denied while a compound like ``messagesdigest`` is not treated as a hit.
DENIED_PATH_TOKENS = frozenset(
    {"messages", "transcript", "export", "timeline", "inbox", "events"}
)

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_CHARS = 48_000
INDEX_ENDPOINTS_CAP = 80

# Dynamic GETs were previously unreachable with concrete IDs. Enable only
# audited metadata projections, rather than opening every tagged detail route.
# Session detail defaults to transcriptScope=all; queued turns, artifacts and
# room detail/list projections also expose conversation content. Session
# catalogs/child catalogs carry lastPreview and journal searchSnippets too.
PUBLIC_DYNAMIC_PATHS = frozenset(
    {
        "/api/sessions/{session_id}/llm-options",
        "/api/sessions/{session_id}/budget-parameters",
    }
)
# Closed native GET surface, audited against route/service return values.
# Catalogs contain avatar filenames and fixed chat-room choices; settings and
# freshness contain configuration selectors and process/build identity; usage
# contains numeric rollups. No tag, name pattern or response size grants access.
# In particular runtime/summary and diagnostics/health derive session titles,
# taskSummary/latestSignal, while archive/plugin catalogs contain private state.
# They need a separate identity-aware public projection, not this raw gateway.
PUBLIC_GET_OPERATIONS = frozenset(
    {
        ("GET", "/api/agents/avatar-options"),
        ("GET", "/api/chat-rooms/modes"),
        ("GET", "/api/chat-rooms/purposes"),
        ("GET", "/api/runtime/code-freshness"),
        ("GET", "/api/launcher/freshness"),
        ("GET", "/api/launcher/current-instance"),
        ("GET", "/api/launcher/settings/workbench-window"),
        ("GET", "/api/launcher/settings/startup"),
        ("GET", "/api/launcher/developer-mode"),
        ("GET", "/api/usage/summary"),
        *(("GET", path) for path in PUBLIC_DYNAMIC_PATHS),
    }
)
DENIED_STATIC_PATHS = frozenset(
    {"/api/chat-rooms", "/api/sessions", "/api/sessions/query", "/api/sessions/bootstrap",
     "/api/sessions/active", "/api/session-archive", "/api/agents", "/api/agents/config-workspace",
     "/api/agent-plugins/virtual-human-life/companions",
     "/api/agent-plugins/virtual-human-life/companion-bindings",
     "/api/agent-plugins/virtual-human-life/companion-activity"}
)

# Closed projections are intentionally independent of OpenAPI's permissive
# `extra=allow` DTOs. Tuple schemas mean (item schema, maximum list length).
# Evidence: financial_assistant.py / financial_research.py return typed market
# DTOs; financial_preferences.py's workspace also contains reviewCases and
# instructions; financial_jobs.py batches also contain turnRefs/terminalReason.
# None of those conversational fields is part of the projections below.
_STOCK_ID = {key: str for key in ("symbol", "ticker", "name", "market", "marketCode", "currency", "marketTimeZone")}
_QUOTE = {
    **_STOCK_ID,
    **{key: float for key in (
        "price", "previousClose", "open", "high", "low", "change", "changePercent", "volume",
        "volumeLots", "turnover", "turnoverYuan", "peRatio", "pbRatio", "marketCap", "totalMarketCapYuan",
    )},
    **{key: str for key in ("priceUnit", "volumeUnit", "timestamp", "timeOfDay")},
}
_EXECUTION = {key: str for key in ("kind", "timezone", "scheduledAt", "timeOfDay")}
_KNOWLEDGE_BASE = {
    **{key: str for key in (
        "knowledgeBaseId", "scopedKnowledgeBaseId", "ownerType", "ownerId", "teamId",
        "teamName", "name", "status", "createdAt", "updatedAt",
    )},
    "stats": {key: int for key in ("itemCount", "sourceArtifactCount", "pendingProposalCount", "proposalCount", "batchCount")},
}
_KNOWLEDGE_CATALOG = {
    "schemaVersion": int, "updatedAt": str,
    "knowledgeBases": (_KNOWLEDGE_BASE, 80),
    "summary": {key: int for key in ("knowledgeBaseCount", "itemCount", "sourceArtifactCount", "pendingProposalCount")},
}
_PORTFOLIO = {
    **{key: str for key in ("accountId", "generatedAt", "source", "sourceUrl", "adjustment", "period")},
    "simulationOnly": bool,
    "summary": {
        **{key: str for key in ("equityYuan", "cashYuan", "marketValueYuan", "cashWeightPercent", "maxPositionWeightPercent", "topThreeWeightPercent")},
        **{key: int for key in ("positionCount", "valuedPositionCount", "correlationPairCount", "highCorrelationPairCount", "insufficientCorrelationPairCount", "unavailableCorrelationPairCount")},
        "valuationComplete": bool,
    },
    "positions": ({
        **{key: str for key in (
            "symbol", "ticker", "name", "market", "markPriceYuan", "marketValueYuan", "unrealizedPnlYuan",
            "weightPercent", "valuationStatus", "quoteTimestamp", "quoteFetchedAt", "source", "sourceUrl", "returnSeriesStatus",
        )},
        "quantity": int,
    }, 50),
    "correlations": ({
        **{key: str for key in ("firstSymbol", "firstName", "secondSymbol", "secondName", "startDate", "endDate")},
        "correlation": float, "observations": int,
    }, 60),
    "coverage": {
        **{key: int for key in (
            "eligiblePositionCount", "selectedPositionCount", "candleLoadedPositionCount", "candleUnavailablePositionCount",
            "budgetSkippedPositionCount", "capacitySkippedPositionCount", "deadlineSkippedPositionCount", "unvaluedPositionCount",
            "maxAnalyzedPositions", "maxConcurrentFetches", "minimumCorrelationObservations",
        )},
        "deadlineSeconds": float,
        **{key: (str, 50) for key in ("analyzedSymbols", "budgetSkippedSymbols", "unavailableSymbols")},
    },
}
PUBLIC_RESPONSE_PROJECTIONS: dict[str, Any] = {
    "/api/financial-assistants": ({
        **{key: str for key in (
            "agentId", "agentCode", "displayName", "status", "setupStatus", "knowledgeBaseId", "modelStatus",
            "reportStatus", "marketDataStatus", "marketToolStatus", "newsDelegationStatus", "privateLedgerStatus",
        )},
        "knowledgeReadable": bool, "tradingEnabled": bool,
    }, 40),
    "/api/financial-market/search": (_STOCK_ID, 50),
    "/api/financial-market/quotes": {
        "source": str, "sourceUrl": str, "fetchedAt": str,
        "items": ({"symbol": str, "quote": _QUOTE}, 50),
    },
    "/api/financial-market/screen": {
        **{key: str for key in ("source", "sourceUrl", "fetchedAt", "dataDate", "dataTime", "resultScope", "sortBy", "direction")},
        "page": int, "pageSize": int, "cacheSeconds": int,
        "coverage": {
            **{key: int for key in ("providerTotal", "loaded", "invalidRows", "duplicateRows", "totalFiltered")},
            "complete": bool, "failedPages": (int, 100),
        },
        "items": (_QUOTE, 100),
    },
    "/api/financial-preferences/{agent_id}/workspace": {
        "schemaVersion": int, "revision": int, "updatedAt": str,
        "selectedStock": _STOCK_ID,
        "watchlist": ({**_STOCK_ID, "tags": (str, 10)}, 50),
        "manualPositions": ({"id": str, "stock": _STOCK_ID, "quantity": float, "costPrice": float, "currency": str}, 50),
        "investmentProfile": {
            **{key: float for key in ("budgetCny", "availableCashCny", "maxLossCny", "cashReserveCny", "maxPositionPct")},
            "horizonMonths": int, "flexibleHorizon": bool, "market": str, "holdingsStatus": str,
        },
        "profiles": ({"id": str, "name": str, "scope": str, "depth": str, "period": str, "isDefault": bool}, 20),
        "investmentPlans": ({
            **{key: str for key in ("id", "status", "createdAt", "updatedAt", "reviewAfter")},
            "needsReview": bool,
            "orders": ({"symbol": str, "side": str, "quantity": int}, 20),
        }, 20),
    },
    "/api/financial-portfolios/{agentId}/research": _PORTFOLIO,
    "/api/financial-jobs/{assistant_agent_id}/schedules": {
        "schedules": ({
            **{key: str for key in (
                "scheduleId", "depth", "researchDate", "createdAt", "updatedAt", "nextRunAt", "lastBatchId",
                "lastTriggeredAt", "calendarStatus", "lastScheduledAt", "lastTriggerReason",
            )},
            "periodDays": int, "enabled": bool, "lastSkippedOccurrenceCount": int,
            "symbols": (str, 10), "execution": _EXECUTION,
        }, 60),
    },
    "/api/financial-jobs/{assistant_agent_id}/batches": {
        "batches": ({
            **{key: str for key in ("batchId", "scheduleId", "status", "triggeredAt", "scheduledAt", "triggerReason", "updatedAt", "researchDate", "depth")},
            "skippedOccurrenceCount": int, "periodDays": int, "symbols": (str, 10),
            "items": ({"symbol": str, "status": str, "runId": str, "startedAt": str, "completedAt": str}, 10),
        }, 60),
    },
    # team_knowledge_service._knowledge_base_to_api also includes description,
    # ACL and per-actor permissions; overview adds pending proposal bodies.
    # Only team-owned directory metadata is exposed, never Agent memory bases.
    "/api/knowledge/overview": _KNOWLEDGE_CATALOG,
    "/api/knowledge/team-catalog": _KNOWLEDGE_CATALOG,
    # ResearchKnowledgeBase.payload includes claims/evidence/gaps, agentContext,
    # per-entry summaries, queries and session provenance. Its tags are derived
    # from openGoal/preferences (_tags_for_source), so omit those as well.
    "/api/research/knowledge-base": {
        "schemaVersion": int, "updatedAt": str,
        "entries": ({
            **{key: str for key in ("knowledgeId", "kind", "title", "url", "reliability", "firstSeenAt", "lastSeenAt", "firstRetrievedAt", "lastRetrievedAt")},
            "categories": (str, 20), "hitCount": int,
        }, 100),
        "summary": {key: int for key in (
            "entryCount", "visibleCount", "claimCount", "visibleClaimCount", "evidenceCount", "visibleEvidenceCount", "gapCount", "visibleGapCount",
        )},
    },
    "/api/research/theme-discovery/sessions": {
        "sessions": ({
            **{key: str for key in ("sessionId", "status", "createdAt", "updatedAt", "selectedThemeId")},
            "candidateCount": int,
            "summary": {key: int for key in ("searchRunCount", "sourceCount", "evidenceCount", "candidateThemeCount", "staleThemeCount", "themeCardCount", "approvedThemeCardCount")},
        }, 60),
        "summary": {"sessionCount": int, "selectedCount": int},
    },
}
PUBLIC_GET_OPERATIONS |= frozenset(("GET", path) for path in PUBLIC_RESPONSE_PROJECTIONS)
PUBLIC_DYNAMIC_PATHS |= frozenset(path for path in PUBLIC_RESPONSE_PROJECTIONS if "{" in path)
MAX_PROJECTION_BYTES = 1_000_000
MAX_PROJECTED_STRING_CHARS = 512


def platform_api_index(*, tag: str = "") -> dict[str, Any]:
    """Navigate the allowlisted GET surface of the live API."""

    wanted = str(tag or "").strip().lower()
    if wanted and wanted not in ALLOWED_TAGS:
        return _blocked(f"tag {wanted or '(empty)'} is not in the allowlist")
    endpoints = _allowlisted_get_endpoints()
    by_tag: dict[str, list[dict[str, str]]] = {}
    for path, entry in sorted(endpoints.items()):
        for endpoint_tag in sorted(entry["tags"]):
            by_tag.setdefault(endpoint_tag, []).append(
                {"path": path, "summary": entry["summary"]}
            )
    if wanted:
        listing = by_tag.get(wanted, [])[:INDEX_ENDPOINTS_CAP]
        return _envelope(
            {
                "mode": "tag",
                "tag": wanted,
                "endpoints": listing,
                "endpointCount": len(by_tag.get(wanted, [])),
                "truncated": len(by_tag.get(wanted, [])) > len(listing),
            }
        )
    overview = {
        "mode": "overview",
        "policy": "audited GET paths only; control token stays in-process; redirects and private content paths are denied",
        "tags": {
            name: {"endpointCount": len(items)}
            for name, items in sorted(by_tag.items())
        },
        "hint": "call again with tag=<name> to list that tag's endpoints, then GET a path directly",
    }
    return _envelope(overview)


def platform_api_get(path: str, query: str = "") -> dict[str, Any]:
    """Execute one allowlisted GET against the loopback workbench API."""

    normalized = str(path or "")
    if not _is_concrete_api_path(normalized) or _has_denied_path_word(normalized):
        return _blocked("path must be a concrete /api/ path without URL, query, fragment or encoding")
    endpoints = _allowlisted_get_endpoints()
    matched_path = next((template for template in endpoints if _matches_path(template, normalized)), "")
    if not matched_path:
        return _blocked(
            "path is not a registered public GET endpoint; call index or personal_assistant_query_tool"
        )
    suffix = str(query or "").strip()
    url = f"http://127.0.0.1:{_workbench_port()}{normalized}"
    if suffix:
        url = f"{url}?{suffix}"
    request = urllib.request.Request(url, method="GET")
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    request.add_header(CONTROL_TOKEN_HEADER, get_control_token())
    request.add_header("Accept", "application/json")
    projected = matched_path in PUBLIC_RESPONSE_PROJECTIONS
    response_limit = MAX_PROJECTION_BYTES if projected else MAX_RESPONSE_CHARS
    try:
        with _open_get(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            if not 200 <= status < 300:
                return _http_error(status)
            raw_body = response.read(response_limit + 1)
    except urllib.error.HTTPError as exc:
        # Error bodies and reasons may echo a request, prompt or credential.
        # Do not read them, including when a redirect is rejected below.
        exc.close()
        return _http_error(int(exc.code))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return _envelope(
            {
                "message": f"loopback API unreachable: {type(exc).__name__}",
                "ok": False,
            },
            ok=False,
        )
    if projected and len(raw_body) > response_limit:
        return _envelope({"httpStatus": status, "message": "public response exceeds the projection limit", "truncated": True}, ok=False)
    body = raw_body.decode("utf-8", "replace")
    truncated = len(body) > MAX_RESPONSE_CHARS
    if truncated and not projected:
        body = body[:MAX_RESPONSE_CHARS]
    data: Any
    try:
        data = json.loads(body)
    except ValueError:
        if projected:
            return _blocked("public response is not valid JSON")
        data = body
    if projected:
        try:
            data, truncated = _project_public_response(matched_path, data)
        except _PublicProjectionError:
            return _blocked("public response does not match the audited metadata shape")
        if len(json.dumps(data, ensure_ascii=False)) > MAX_RESPONSE_CHARS:
            return _envelope({"httpStatus": status, "message": "public projection is too large; narrow the query", "truncated": True}, ok=False)
    return _envelope(
        {
            "httpStatus": status,
            "data": data,
            "truncated": truncated,
        }
    )


class _PublicProjectionError(ValueError):
    pass


def _project_public_response(path: str, data: Any) -> tuple[Any, bool]:
    if data is None:
        raise _PublicProjectionError()
    clipped = [False]
    if path in {"/api/knowledge/overview", "/api/knowledge/team-catalog"}:
        if not isinstance(data, dict) or not isinstance(data.get("knowledgeBases"), list):
            raise _PublicProjectionError()
        # A caller-supplied agentId must not reveal Agent-owned memory metadata
        # or its aggregate counts through the otherwise public team directory.
        data = {
            key: value for key, value in data.items() if key != "summary"
        } | {"knowledgeBases": [
            base for base in data["knowledgeBases"]
            if isinstance(base, dict) and base.get("ownerType") == "team"
        ]}
    result = _project_fields(data, PUBLIC_RESPONSE_PROJECTIONS[path], clipped)
    if path in {"/api/knowledge/overview", "/api/knowledge/team-catalog"}:
        bases = result["knowledgeBases"]
        result["summary"] = {
            "knowledgeBaseCount": len(bases),
            **{key: sum((base.get("stats") or {}).get(key) or 0 for base in bases)
               for key in ("itemCount", "sourceArtifactCount", "pendingProposalCount")},
        }
    return result, clipped[0]


def _project_fields(value: Any, schema: Any, clipped: list[bool]) -> Any:
    """Select only explicit nested fields; never stringify an unexpected value."""

    if value is None:
        return None
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise _PublicProjectionError()
        return {key: _project_fields(value[key], child, clipped)
                for key, child in schema.items() if key in value}
    if isinstance(schema, tuple):
        if not isinstance(value, list):
            raise _PublicProjectionError()
        child, limit = schema
        clipped[0] |= len(value) > limit
        return [_project_fields(item, child, clipped) for item in value[:limit]]
    if schema is str and isinstance(value, str):
        clipped[0] |= len(value) > MAX_PROJECTED_STRING_CHARS
        return value[:MAX_PROJECTED_STRING_CHARS]
    if type(value) is schema or (schema is float and type(value) is int):
        try:
            finite = schema is not float or math.isfinite(value)
        except OverflowError:
            finite = False
        if finite:
            return value
    raise _PublicProjectionError()


def _allowlisted_get_endpoints() -> dict[str, dict[str, Any]]:
    """Audited GET paths that are still registered in OpenAPI."""

    from core.web.app import app, ensure_web_routes_registered

    ensure_web_routes_registered(app)
    return _filter_get_endpoints(app.openapi().get("paths") or {})


def _filter_get_endpoints(paths: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Intersect registration with the closed policy; tags only group entries."""

    result: dict[str, dict[str, Any]] = {}
    for path, ops in paths.items():
        if ("GET", str(path)) not in PUBLIC_GET_OPERATIONS:
            continue
        get_op = ops.get("get") if isinstance(ops, dict) else None
        if not isinstance(get_op, dict):
            continue
        tags = frozenset(str(item) for item in get_op.get("tags") or []) & ALLOWED_TAGS
        if not tags:
            continue
        if _has_denied_path_word(str(path)):
            continue
        if str(path) in DENIED_STATIC_PATHS:
            continue
        if "{" in str(path) and str(path) not in PUBLIC_DYNAMIC_PATHS:
            continue
        result[str(path)] = {
            "tags": tags,
            "summary": str(get_op.get("summary") or "")[:120],
        }
    return result


def _is_concrete_api_path(path: str) -> bool:
    """Accept one unencoded path, never URL syntax or routing normalization.

    IDs on the audited routes are plain identifiers. Reject encoded input
    altogether so ASGI/proxy decoding cannot turn an ID into another path.
    Query values keep their separate, existing passthrough semantics.
    """

    return (
        path.startswith("/api/")
        and not any(character in path for character in "\\?#{}%")
        and all(32 < ord(character) < 127 for character in path)
        and all(segment not in {"", ".", ".."} for segment in path.split("/")[1:])
    )


def _matches_path(template: str, path: str) -> bool:
    """Match complete path segments; a parameter consumes exactly one ID."""

    expected, actual = template.split("/"), path.split("/")
    return len(expected) == len(actual) and all(
        item == value or (item.startswith("{") and item.endswith("}"))
        for item, value in zip(expected, actual)
    )


def _has_denied_path_word(path: str) -> bool:
    lowered = str(path).lower()
    words = {
        word
        for segment in lowered.split("/")
        for word in segment.replace("-", "_").split("_")
        if word
    }
    return bool(words & DENIED_PATH_TOKENS)


def _workbench_port() -> int:
    raw = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_get(request: urllib.request.Request, *, timeout: float):
    # Do not consult process-global openers or proxy environment variables.
    # The credential is valid only for this single fixed loopback request.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirects())
    return opener.open(request, timeout=timeout)


def _http_error(status: int) -> dict[str, Any]:
    return _envelope(
        {
            "httpStatus": status,
            "message": "endpoint redirect rejected" if 300 <= status < 400 else "endpoint returned an HTTP error",
        },
        ok=False,
    )


def _envelope(payload: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": "ok" if ok else "error",
        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "loopback-workbench-api",
        "untrustedContent": True,
        **payload,
    }


def _blocked(message: str) -> dict[str, Any]:
    return _envelope({"message": message, "ok": False}, ok=False)


__all__ = ["ALLOWED_TAGS", "DENIED_PATH_TOKENS", "platform_api_get", "platform_api_index"]
