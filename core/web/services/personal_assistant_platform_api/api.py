"""Read-only loopback platform API access for the personal assistant.

The assistant manages the platform through the same HTTP surface the
workbench UI uses.  This pack exposes a GET-only gateway to that surface:

- The control token never crosses the model boundary: the executor calls
  ``core.web.control.get_control_token`` in-process and attaches the header
  itself.
- Only endpoints registered in the live OpenAPI spec are callable, method is
  fixed to GET, and the endpoint's tag must be in ``ALLOWED_TAGS``.
- Private-content sub-resources are denied by path token even inside allowed
  tags: message bodies, transcripts, exports, timelines, inboxes, events.
- Every response carries ``untrustedContent``; payloads are size-truncated
  with an explicit marker.

``path="index"`` navigates the allowlisted surface (per-tag endpoint lists),
``path="/api/..."`` executes one GET.  No mutations: write-side management
keeps going through ``personal_assistant_manage_tool`` and its approvals.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

# Read/status surfaces of the workbench API, by OpenAPI tag.  Deliberately
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
DENIED_STATIC_PATHS = frozenset(
    {"/api/chat-rooms", "/api/sessions", "/api/sessions/query", "/api/sessions/bootstrap",
     "/api/agents", "/api/agents/config-workspace"}
)


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
        "policy": "GET-only; control token stays in-process; private content paths are denied",
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
    if not any(_matches_path(template, normalized) for template in endpoints):
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
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            body = response.read(MAX_RESPONSE_CHARS + 1).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", "replace")
        return _envelope(
            {
                "httpStatus": int(exc.code),
                "message": _json_detail(detail) or "endpoint returned an HTTP error",
                "ok": False,
            },
            ok=False,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return _envelope(
            {
                "message": f"loopback API unreachable: {type(exc).__name__}",
                "ok": False,
            },
            ok=False,
        )
    truncated = len(body) > MAX_RESPONSE_CHARS
    if truncated:
        body = body[:MAX_RESPONSE_CHARS]
    data: Any
    try:
        data = json.loads(body)
    except ValueError:
        data = body
    return _envelope(
        {
            "httpStatus": status,
            "data": data,
            "truncated": truncated,
        }
    )


def _allowlisted_get_endpoints() -> dict[str, dict[str, Any]]:
    """Registered GET paths (OpenAPI) that pass the tag and path gates."""

    from core.web.app import app, ensure_web_routes_registered

    ensure_web_routes_registered(app)
    return _filter_get_endpoints(app.openapi().get("paths") or {})


def _filter_get_endpoints(paths: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply the tag allowlist and private-path denial to a raw OpenAPI paths map."""

    result: dict[str, dict[str, Any]] = {}
    for path, ops in paths.items():
        get_op = ops.get("get") if isinstance(ops, dict) else None
        if not isinstance(get_op, dict):
            continue
        tags = frozenset(str(item) for item in get_op.get("tags") or [])
        if not tags or not (tags & ALLOWED_TAGS):
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


def _json_detail(text: str) -> str:
    try:
        payload = json.loads(text)
    except ValueError:
        return str(text or "").strip()[:300]
    if isinstance(payload, dict):
        return str(payload.get("detail") or payload.get("message") or "")[:300]
    return str(payload)[:300]


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
