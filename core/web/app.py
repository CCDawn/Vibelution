"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from core.version import get_product_version
from .control import WebControlGuardMiddleware, control_token_payload, ensure_control_source, trusted_control_origins
from .routes.config import router as config_router
from .routes.agents import router as agents_router
from .routes.chat_rooms import router as chat_rooms_router
from .routes.cli_agents import router as cli_agents_router
from .routes.computer_use import router as computer_use_router
from .routes.conversations import router as conversations_router
from .routes.data_processing import router as data_processing_router
from .routes.diagnostics import router as diagnostics_router
from .routes.evolution import router as evolution_router
from .routes.files import router as files_router
from .routes.git import router as git_router
from .routes.knowledge import router as knowledge_router
from .routes.kernel import router as kernel_router
from .routes.launcher import router as launcher_router
from .routes.logs import router as logs_router
from .routes.memory import router as memory_router
from .routes.pet import router as pet_router
from .routes.project_agent_bus import router as project_agent_bus_router
from .routes.research import router as research_router
from .routes.research_loop import router as research_loop_router
from .routes.reset import router as reset_router
from .routes.runtime import router as runtime_router
from .routes.sessions import router as sessions_router
from .routes.skills import router as skills_router
from .routes.team_templates import router as team_templates_router
from .routes.team_workflows import router as team_workflows_router
from .routes.teams import router as teams_router
from .routes.tools import router as tools_router
from .services.runtime_scene_service import record_backend_api_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = PROJECT_ROOT / "web" / "dist"
FRONTEND_BUILD_HINT = (
    "Run `npm install` and `npm run build` in `web/`, or use `bun run bun:build` "
    "for local auxiliary builds after dependencies are ready, then restart the server."
)
INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
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
API_RUNTIME_TEAM_WORKBENCH_REFERER_PATHS = frozenset({"/teams", "/agents/teams"})


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def _looks_like_static_asset_request(full_path: str) -> bool:
    normalized = str(full_path or "").strip().lstrip("/")
    if not normalized:
        return False
    path = Path(normalized)
    return normalized.startswith("assets/") or bool(path.suffix)


def _default_workbench_port() -> int:
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


def _is_windows_proactor_disconnect_noise(context: dict[str, Any]) -> bool:
    if os.name != "nt":
        return False
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False
    fragments = [
        str(context.get("message") or ""),
        repr(context.get("handle")),
        repr(context.get("transport")),
        repr(context.get("protocol")),
    ]
    haystack = " ".join(fragment for fragment in fragments if fragment).lower()
    return "proactorbasepipetransport._call_connection_lost" in haystack


def _api_runtime_perf_counter() -> float:
    return time.perf_counter()


class RuntimeSceneApiEventMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = _api_runtime_perf_counter()
        should_record = _should_record_api_runtime_event(request)
        try:
            response = await call_next(request)
        except Exception as exc:
            if should_record:
                _record_api_runtime_event(
                    request,
                    status_code=500,
                    duration_ms=(_api_runtime_perf_counter() - start) * 1000,
                    exception=exc,
                )
            raise

        duration_ms = (_api_runtime_perf_counter() - start) * 1000
        if should_record and _is_signal_api_response(request, response.status_code, duration_ms=duration_ms):
            _record_api_runtime_event(
                request,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        return response


def _should_record_api_runtime_event(request: Request) -> bool:
    path = str(request.url.path or "")
    if not path.startswith("/api/"):
        return False
    if path in {"/api/health", "/api/control-token", "/api/runtime/browser-telemetry", "/api/runtime/events"}:
        return False
    return True


def _is_signal_api_response(request: Request, status_code: int, *, duration_ms: float = 0.0) -> bool:
    method = request.method.upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if method == "GET" and _is_team_workbench_api_probe_request(request):
        return True
    if method == "GET" and float(duration_ms or 0.0) >= API_RUNTIME_SLOW_GET_THRESHOLD_MS:
        return True
    return int(status_code or 0) >= 400


def _is_team_workbench_api_probe_request(request: Request) -> bool:
    return _safe_referer_path(request) in API_RUNTIME_TEAM_WORKBENCH_REFERER_PATHS


def _record_api_runtime_event(
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


@asynccontextmanager
async def _lifespan(_: FastAPI):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_loop_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if _is_windows_proactor_disconnect_noise(context):
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    from .services.cli_agent_terminal_service import reconcile_cli_agent_terminal_states_on_startup

    await asyncio.to_thread(reconcile_cli_agent_terminal_states_on_startup, reason="backend_startup")
    startup_cache_prewarm_task = asyncio.create_task(_prewarm_ui_caches_on_startup())

    def consume_startup_cache_prewarm_result(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            loop.call_exception_handler(
                {
                    "message": "UI cache prewarm failed during startup.",
                    "exception": exc,
                }
            )

    startup_cache_prewarm_task.add_done_callback(consume_startup_cache_prewarm_result)
    try:
        yield
    finally:
        if not startup_cache_prewarm_task.done():
            startup_cache_prewarm_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_cache_prewarm_task
        from .services.cli_agent_terminal_service import shutdown_cli_agent_terminal_sessions

        await asyncio.to_thread(shutdown_cli_agent_terminal_sessions)
        loop.set_exception_handler(previous_handler)


async def _prewarm_ui_caches_on_startup() -> None:
    from .services import chat_room_service, memory_service, session_service

    await asyncio.to_thread(session_service.prewarm_session_list_cache, reason="startup")
    await asyncio.to_thread(chat_room_service.prewarm_chat_room_participant_indexes, reason="startup")
    await asyncio.to_thread(memory_service.prewarm_memory_overview_cache, reason="startup")


def create_app() -> FastAPI:
    """Create the local web workbench app."""

    app = FastAPI(
        title="Vibelution Web Workbench",
        version=get_product_version(),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
        default_response_class=UTF8JSONResponse,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(trusted_control_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Vibelution-Control-Token"],
    )
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/control-token")
    def control_token(request: Request) -> dict[str, str]:
        ensure_control_source(request)
        return control_token_payload()

    app.include_router(runtime_router, prefix="/api")
    app.include_router(launcher_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(chat_rooms_router, prefix="/api")
    app.include_router(cli_agents_router, prefix="/api")
    app.include_router(project_agent_bus_router, prefix="/api")
    app.include_router(kernel_router, prefix="/api")
    app.include_router(team_templates_router, prefix="/api")
    app.include_router(teams_router, prefix="/api")
    app.include_router(team_workflows_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(tools_router, prefix="/api")
    app.include_router(computer_use_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(git_router, prefix="/api")
    app.include_router(data_processing_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(research_router, prefix="/api")
    app.include_router(research_loop_router, prefix="/api")
    app.include_router(diagnostics_router, prefix="/api")
    app.include_router(evolution_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(reset_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        ensure_control_source(request)
        if WEB_DIST.exists():
            return FileResponse(WEB_DIST / "index.html", headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Web frontend has not been built yet.",
                "next": FRONTEND_BUILD_HINT,
            },
            status_code=503,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str, request: Request):
        ensure_control_source(request)
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if WEB_DIST.exists():
            candidate = (WEB_DIST / full_path).resolve()
            dist_root = WEB_DIST.resolve()
            try:
                candidate.relative_to(dist_root)
            except ValueError:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            if _looks_like_static_asset_request(full_path):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(WEB_DIST / "index.html", headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Web frontend has not been built yet.",
                "next": FRONTEND_BUILD_HINT,
            },
            status_code=503,
        )

    return app


app = create_app()
