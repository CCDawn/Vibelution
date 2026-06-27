"""Static frontend response helpers for the Web workbench."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse


FRONTEND_BUILD_HINT = (
    "Run `npm install` and `npm run build` in `web/`, or use `bun run bun:build` "
    "for local auxiliary builds after dependencies are ready, then restart the server."
)
INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def looks_like_static_asset_request(full_path: str) -> bool:
    normalized = str(full_path or "").strip().lstrip("/")
    if not normalized:
        return False
    path = Path(normalized)
    return normalized.startswith("assets/") or bool(path.suffix)


def web_index_response(web_dist: Path):
    if web_dist.exists():
        return FileResponse(web_dist / "index.html", headers=INDEX_CACHE_HEADERS)
    return _frontend_not_built_response()


def web_spa_fallback_response(full_path: str, web_dist: Path):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if web_dist.exists():
        candidate = (web_dist / full_path).resolve()
        dist_root = web_dist.resolve()
        try:
            candidate.relative_to(dist_root)
        except ValueError:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        if looks_like_static_asset_request(full_path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(web_dist / "index.html", headers=INDEX_CACHE_HEADERS)
    return _frontend_not_built_response()


def _frontend_not_built_response() -> JSONResponse:
    return JSONResponse(
        {
            "message": "Web frontend has not been built yet.",
            "next": FRONTEND_BUILD_HINT,
        },
        status_code=503,
    )
