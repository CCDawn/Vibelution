"""Bounded HTTP with fixed errors, no redirects, and no response-body leakage."""

from __future__ import annotations

import json
from typing import Any

import httpx

from .errors import ChatGPTSubscriptionError


class AuthHTTP:
    def __init__(self, client: httpx.Client):
        self.client = client

    def request(self, method: str, url: str, *, data: dict[str, str] | None = None,
                headers: dict[str, str] | None = None, empty: bool = False) -> dict[str, Any]:
        try:
            with self.client.stream(method, url, data=data, headers=headers,
                                    timeout=httpx.Timeout(15.0, connect=10.0), follow_redirects=False) as response:
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ChatGPTSubscriptionError("invalid_response")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if response.status_code != 200:
                    error_code = ""
                    try:
                        error = json.loads(body)
                        if isinstance(error, dict):
                            error_code = error.get("error")
                    except (ValueError, UnicodeError):
                        pass
                    if error_code in ("invalid_grant", "invalid_token") or response.status_code in {401, 403}:
                        raise ChatGPTSubscriptionError("reauth_required")
                    if response.status_code == 429:
                        raise ChatGPTSubscriptionError("rate_limited")
                    if response.status_code >= 500:
                        raise ChatGPTSubscriptionError("upstream_unavailable")
                    raise ChatGPTSubscriptionError("invalid_response")
                if empty:
                    return {}
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ChatGPTSubscriptionError("invalid_response")
                return payload
        except ChatGPTSubscriptionError:
            raise
        except httpx.TimeoutException:
            raise ChatGPTSubscriptionError("timeout") from None
        except httpx.HTTPError:
            raise ChatGPTSubscriptionError("network") from None
        except (ValueError, UnicodeError):
            raise ChatGPTSubscriptionError("invalid_response") from None
