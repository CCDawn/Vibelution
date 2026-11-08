"""OpenAI OIDC verification. Access tokens remain opaque bearer credentials."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import jwt

from .errors import ChatGPTSubscriptionError

ISSUER = "https://auth.openai.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


def trusted_auth_endpoint(value: Any) -> str:
    if not isinstance(value, str):
        raise ChatGPTSubscriptionError("invalid_response")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname == "auth.openai.com"
                 and parsed.port in {None, 443} and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and parsed.path.startswith("/"))
    except ValueError:
        valid = False
    if not valid:
        raise ChatGPTSubscriptionError("invalid_response")
    return value


class IdentityVerifier:
    def __init__(self, fetch_json: Callable[..., dict[str, Any]]):
        self.fetch_json = fetch_json
        self._metadata: dict[str, Any] | None = None
        self._keys: list[dict[str, Any]] = []
        self._keys_at = 0.0

    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            metadata = self.fetch_json("GET", DISCOVERY_URL)
            if metadata.get("issuer") != ISSUER:
                raise ChatGPTSubscriptionError("invalid_response")
            trusted_auth_endpoint(metadata.get("jwks_uri"))
            self._metadata = metadata
        return self._metadata

    def verify(self, token: str, client_id: str, *, nonce: str | None,
               expected_subject: str | None = None, require_nonce: bool = True) -> dict[str, str]:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError("header")
            kid = header["kid"]
            candidates = [key for key in self._keys if key.get("kid") == kid]
            if not candidates or time.monotonic() - self._keys_at >= 300:
                payload = self.fetch_json("GET", trusted_auth_endpoint(self.metadata().get("jwks_uri")))
                if not isinstance(payload.get("keys"), list) or len(payload["keys"]) > 100:
                    raise ValueError("jwks")
                self._keys = payload["keys"]
                self._keys_at = time.monotonic()
                candidates = [key for key in self._keys if isinstance(key, dict) and key.get("kid") == kid]
            if len(candidates) != 1:
                raise ValueError("key")
            jwk = candidates[0]
            if jwk.get("kty") != "RSA" or jwk.get("use", "sig") != "sig" or jwk.get("alg", "RS256") != "RS256":
                raise ValueError("key type")
            if "key_ops" in jwk and (not isinstance(jwk["key_ops"], list) or "verify" not in jwk["key_ops"]):
                raise ValueError("key operation")
            claims = jwt.decode(token, jwt.PyJWK.from_dict(jwk, algorithm="RS256").key,
                                algorithms=["RS256"], issuer=ISSUER, audience=client_id,
                                leeway=5, options={"require": ["iss", "aud", "exp", "iat", "sub"]})
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject or len(subject) > 1024:
                raise ValueError("subject")
            if require_nonce or "nonce" in claims:
                actual_nonce = claims.get("nonce")
                if not isinstance(nonce, str) or not isinstance(actual_nonce, str) or not hmac.compare_digest(actual_nonce, nonce):
                    raise ValueError("nonce")
            if claims.get("azp", client_id) != client_id:
                raise ValueError("authorized party")
            if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
                raise ValueError("multiple audiences")
            if expected_subject and not hmac.compare_digest(subject, expected_subject):
                raise ChatGPTSubscriptionError("identity_mismatch")
            email = claims.get("email", "")
            return {"subject": subject, "email": email[:320] if isinstance(email, str) else ""}
        except ChatGPTSubscriptionError:
            raise
        except Exception:  # noqa: BLE001 - JWT parsers/crypto errors are mapped to one non-sensitive rejection.
            raise ChatGPTSubscriptionError("invalid_identity") from None
