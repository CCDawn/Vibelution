"""Compress only hash-named frontend assets.

API JSON and SSE stay uncompressed on purpose: an event stream must reach the
browser chunk by chunk, and per-response deflate cost is wasted on the small
polling payloads the workbench sends every few seconds. Static assets are the
one place where compression is a pure win, so this wrapper narrows Starlette's
``GZipMiddleware`` to ``/assets/*`` instead of installing it app-wide.
"""
from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

ASSET_PATH_PREFIX = "/assets/"

# 1 KiB keeps tiny source maps and icons out of the compressor.
ASSET_GZIP_MINIMUM_SIZE = 1024
# 6 is the usual speed/ratio knee; assets are already minified.
ASSET_GZIP_COMPRESS_LEVEL = 6


def is_asset_request_path(path: object) -> bool:
    """True when the ASGI scope path targets the hash-named build output."""
    return str(path or "").startswith(ASSET_PATH_PREFIX)


class AssetOnlyGZipMiddleware:
    """Run Starlette's gzip middleware for ``/assets/*`` responses only."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = ASSET_GZIP_MINIMUM_SIZE,
        compresslevel: int = ASSET_GZIP_COMPRESS_LEVEL,
    ) -> None:
        self.app = app
        self._gzip_app = GZipMiddleware(
            app,
            minimum_size=minimum_size,
            compresslevel=compresslevel,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_asset_request_path(scope.get("path")):
            await self._gzip_app(scope, receive, send)
            return
        await self.app(scope, receive, send)
