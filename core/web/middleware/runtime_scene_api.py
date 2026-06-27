"""Runtime-scene observation middleware for Web API requests."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qsl, urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from core.web.services.runtime_scene_service import record_backend_api_event


SENSITIVE_QUERY_KEYWORDS = (
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "bearer",
)
API_RUNTIME_SLOW_GET_THRESHOLD_MS = 800.0
API_RUNTIME_EXCLUDED_PATHS = frozenset(
    {
        "/api/health",
        "/api/control-token",
        "/api/runtime/browser-telemetry",
        "/api/runtime/events",
    }
)
API_RUNTIME_ALWAYS_RECORD_REFERER_PATHS = frozenset({"/teams", "/agents/teams"})


class RuntimeSceneApiEventMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = _api_runtime_perf_counter()
        should_record = should_record_api_runtime_event(request)
        try:
            response = await call_next(request)
        except Exception as exc:
            if should_record:
                record_api_runtime_event(
                    request,
                    status_code=500,
                    duration_ms=(_api_runtime_perf_counter() - start) * 1000,
                    exception=exc,
                )
            raise

        duration_ms = (_api_runtime_perf_counter() - start) * 1000
        if should_record and is_signal_api_response(request, response.status_code, duration_ms=duration_ms):
            record_api_runtime_event(
                request,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        return response


def should_record_api_runtime_event(request: Request) -> bool:
    path = str(request.url.path or "")
    if not path.startswith("/api/"):
        return False
    if path in API_RUNTIME_EXCLUDED_PATHS:
        return False
    return True


def is_signal_api_response(request: Request, status_code: int, *, duration_ms: float = 0.0) -> bool:
    method = request.method.upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if method == "GET" and _is_always_recorded_referer_probe(request):
        return True
    if method == "GET" and float(duration_ms or 0.0) >= API_RUNTIME_SLOW_GET_THRESHOLD_MS:
        return True
    return int(status_code or 0) >= 400


def record_api_runtime_event(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    exception: Exception | None = None,
) -> None:
    try:
        route = request.scope.get("route")
        request_path = str(request.url.path or "")
        path_template = _api_runtime_path_template(request_path, str(getattr(route, "path", "") or ""))
        client = request.client.host if request.client else ""
        query_diagnostics = _request_query_diagnostics(request)
        record_backend_api_event(
            {
                "method": request.method.upper(),
                "path": request_path,
                "path_template": path_template,
                "query": query_diagnostics["summary"],
                "query_keys": query_diagnostics["keys"],
                "query_param_count": query_diagnostics["param_count"],
                "query_length": query_diagnostics["length"],
                "sensitive_query_key_count": query_diagnostics["sensitive_key_count"],
                "status_code": int(status_code or 0),
                "duration_ms": duration_ms,
                "client": client,
                "referer_path": _safe_referer_path(request),
                "request_origin": _request_origin_summary(request),
                "user_agent_family": _user_agent_family(request),
                "exception_type": type(exception).__name__ if exception else "",
                "exception_message": str(exception or ""),
            }
        )
    except Exception:
        pass


def _api_runtime_perf_counter() -> float:
    return time.perf_counter()


def _is_always_recorded_referer_probe(request: Request) -> bool:
    return _safe_referer_path(request) in API_RUNTIME_ALWAYS_RECORD_REFERER_PATHS


def _api_runtime_path_template(request_path: str, route_path: str) -> str:
    normalized_request_path = str(request_path or "")
    normalized_route_path = str(route_path or "") or normalized_request_path
    if (
        normalized_request_path.startswith("/api/")
        and normalized_route_path.startswith("/")
        and not normalized_route_path.startswith("/api/")
    ):
        return f"/api{normalized_route_path}"
    return normalized_route_path


def _request_query_diagnostics(request: Request) -> dict[str, Any]:
    raw_query = str(request.url.query or "")
    if not raw_query:
        return {
            "summary": "",
            "keys": [],
            "param_count": 0,
            "length": 0,
            "sensitive_key_count": 0,
        }

    parsed_pairs = parse_qsl(raw_query, keep_blank_values=True)
    if not parsed_pairs:
        parsed_pairs = [(item.split("=", 1)[0], "") for item in raw_query.split("&") if item]
    safe_keys: list[str] = []
    sensitive_key_count = 0
    seen_keys: set[str] = set()
    for key, _ in parsed_pairs:
        key_text = str(key or "").strip()
        if not key_text:
            continue
        if _is_sensitive_query_key(key_text):
            sensitive_key_count += 1
            continue
        safe_key = _safe_query_key(key_text)
        if safe_key and safe_key not in seen_keys:
            safe_keys.append(safe_key)
            seen_keys.add(safe_key)
        if len(safe_keys) >= 12:
            break

    summary_parts = [
        f"params={len(parsed_pairs)}",
        f"length={len(raw_query)}",
    ]
    if safe_keys:
        summary_parts.append(f"keys={','.join(safe_keys)}")
    if sensitive_key_count:
        summary_parts.append(f"sensitiveKeys={sensitive_key_count}")
    return {
        "summary": ";".join(summary_parts),
        "keys": safe_keys,
        "param_count": len(parsed_pairs),
        "length": len(raw_query),
        "sensitive_key_count": sensitive_key_count,
    }


def _is_sensitive_query_key(value: str) -> bool:
    lowered = str(value or "").strip().lower().replace("-", "_")
    return any(keyword in lowered for keyword in SENSITIVE_QUERY_KEYWORDS)


def _safe_query_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:80]


def _safe_referer_path(request: Request) -> str:
    referer = str(request.headers.get("referer") or "").strip()
    if not referer:
        return ""
    parsed = urlparse(referer)
    if parsed.scheme and parsed.netloc:
        return (parsed.path or "/")[:240]
    if referer.startswith("/"):
        return referer.split("?", 1)[0].split("#", 1)[0][:240]
    return ""


def _request_origin_summary(request: Request) -> str:
    origin = str(request.headers.get("origin") or "").strip()
    if origin:
        parsed_origin = urlparse(origin)
        if parsed_origin.scheme and parsed_origin.netloc:
            return f"{parsed_origin.scheme}://{parsed_origin.netloc}"[:160]
        return origin[:80]

    referer = str(request.headers.get("referer") or "").strip()
    parsed_referer = urlparse(referer)
    if parsed_referer.scheme and parsed_referer.netloc:
        return f"{parsed_referer.scheme}://{parsed_referer.netloc}"[:160]
    return ""


def _user_agent_family(request: Request) -> str:
    user_agent = str(request.headers.get("user-agent") or "").lower()
    if not user_agent:
        return ""
    if "testclient" in user_agent:
        return "testclient"
    if "edg/" in user_agent or "edge/" in user_agent:
        return "edge"
    if "chrome/" in user_agent or "chromium/" in user_agent:
        return "chrome"
    if "firefox/" in user_agent:
        return "firefox"
    if "safari/" in user_agent:
        return "safari"
    if "python" in user_agent:
        return "python"
    if "curl/" in user_agent:
        return "curl"
    if "playwright" in user_agent:
        return "playwright"
    return "other"
