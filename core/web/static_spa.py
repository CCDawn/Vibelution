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
# Hash-named build output never changes under the same URL, so it can be cached
# for a year. Anything outside ``assets/`` keeps default validators only.
ASSET_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
}


def is_immutable_asset_path(full_path: str) -> bool:
    """True when the request targets hash-named build output under ``assets/``."""
    return str(full_path or "").strip().lstrip("/").startswith("assets/")


def _static_file_response(path: Path, full_path: str) -> FileResponse:
    if is_immutable_asset_path(full_path):
        return FileResponse(path, headers=ASSET_CACHE_HEADERS)
    return FileResponse(path)


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
            return _static_file_response(candidate, full_path)
        if looks_like_static_asset_request(full_path):
            retained = _retained_release_asset(full_path, web_dist)
            if retained is not None:
                return _static_file_response(retained, full_path)
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(web_dist / "index.html", headers=INDEX_CACHE_HEADERS)
    return _frontend_not_built_response()


def _retained_release_asset(full_path: str, web_dist: Path) -> Path | None:
    # Open tabs keep loading hashed chunks from the build they started on. After
    # a restart pins a newer release, those exact files still exist in retained
    # sibling releases; serving them avoids a forced reload that aborts uploads.
    normalized = str(full_path or "").strip().lstrip("/")
    if not normalized.startswith("assets/"):
        return None
    releases_dir = web_dist.parent
    if not releases_dir.is_dir():
        return None
    releases_root = releases_dir.resolve()
    for release in releases_dir.iterdir():
        if not release.is_dir() or not release.name.startswith("release-"):
            continue
        release_root = release.resolve()
        try:
            release_root.relative_to(releases_root)
        except ValueError:
            continue
        candidate = (release_root / normalized).resolve()
        try:
            candidate.relative_to(release_root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _frontend_not_built_response() -> JSONResponse:
    return JSONResponse(
        {
            "message": "Web frontend has not been built yet.",
            "next": FRONTEND_BUILD_HINT,
        },
        status_code=503,
    )
