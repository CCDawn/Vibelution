"""Static asset delivery: immutable caching for hashed output, assets-only gzip."""
from __future__ import annotations

from pathlib import Path

from starlette.middleware.gzip import GZipMiddleware

from core.web.middleware.asset_compression import (
    ASSET_GZIP_COMPRESS_LEVEL,
    ASSET_GZIP_MINIMUM_SIZE,
    AssetOnlyGZipMiddleware,
    is_asset_request_path,
)
from core.web.static_spa import (
    ASSET_CACHE_HEADERS,
    is_immutable_asset_path,
    web_index_response,
    web_spa_fallback_response,
)

PAYLOAD = "console.log('boot');" * 400


def _build_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text(PAYLOAD, encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"ico")
    return dist


def test_asset_request_path_helper():
    assert is_asset_request_path("/assets/app-abc123.js")
    assert is_asset_request_path("/assets/nested/chunk.css")
    assert not is_asset_request_path("/api/health")
    assert not is_asset_request_path("/")
    assert not is_asset_request_path("assets/app.js")
    assert is_immutable_asset_path("assets/app.js")
    assert not is_immutable_asset_path("/api/health")
    assert not is_immutable_asset_path("favicon.ico")


def test_gzip_wrapper_only_wraps_asset_requests():
    marker = object()
    middleware = AssetOnlyGZipMiddleware(marker)

    assert middleware.app is marker
    assert isinstance(middleware._gzip_app, GZipMiddleware)


def test_gzip_wrapper_forwards_compression_settings():
    middleware = AssetOnlyGZipMiddleware(object(), minimum_size=2048, compresslevel=5)

    assert middleware._gzip_app.minimum_size == 2048
    assert middleware._gzip_app.compresslevel == 5
    assert ASSET_GZIP_MINIMUM_SIZE >= 1024
    assert 1 <= ASSET_GZIP_COMPRESS_LEVEL <= 9


def test_hashed_asset_is_immutably_cached(tmp_path):
    response = web_spa_fallback_response("assets/app-abc123.js", _build_dist(tmp_path))

    assert response.headers["cache-control"] == ASSET_CACHE_HEADERS["Cache-Control"]
    assert "immutable" in response.headers["cache-control"]


def test_index_stays_no_store(tmp_path):
    response = web_index_response(_build_dist(tmp_path))

    assert "no-store" in response.headers["cache-control"]


def test_non_asset_static_file_gets_no_immutable_cache(tmp_path):
    response = web_spa_fallback_response("favicon.ico", _build_dist(tmp_path))

    assert "immutable" not in response.headers.get("cache-control", "")


def test_missing_asset_stays_404(tmp_path):
    response = web_spa_fallback_response("assets/missing-zzz.js", _build_dist(tmp_path))

    assert response.status_code == 404
