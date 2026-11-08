"""Native public-client OAuth for the Vibelution harness, independent of Codex.

The encrypted state file is the only credential authority. Login candidates
stay separate from the active account. Every refresh reads under the same
cross-process lock and saves replacements before any JWKS network request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .callback import CallbackListener
from .errors import ChatGPTSubscriptionError
from .identity import IdentityVerifier, trusted_auth_endpoint
from .storage import CredentialStorage, Encryption
from .transport import AuthHTTP

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPES = {"resource.invoke", "chatgpt.tokens.use.direct"}


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


class _LoginAttempt:
    def __init__(self, expires_at: float):
        self.id = secrets.token_urlsafe(24)
        self.state = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(64)
        self.expires_at = expires_at
        self.phase = "pending"
        self.cancelled = threading.Event()
        self.listener: CallbackListener | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {"attemptId": self.id, "state": self.phase, "expiresAt": _iso(self.expires_at)}


class ChatGPTSubscriptionAuth:
    def __init__(self, root: Path | None = None, *, http_client: httpx.Client | None = None,
                 encryption: Encryption | None = None, clock: Callable[[], float] = time.time,
                 login_ttl_seconds: float = 600.0):
        self.storage = CredentialStorage(root, encryption=encryption)
        self._owns_http = http_client is None
        self._client = http_client if http_client is not None else httpx.Client(trust_env=False)
        self._http = AuthHTTP(self._client)
        self._identity = IdentityVerifier(self._http.request)
        self._clock = clock
        self._ttl = min(max(float(login_ttl_seconds), 0.1), 600.0)
        self._attempt: _LoginAttempt | None = None
        self._guard = threading.Lock()
        self._lifecycle = threading.RLock()

    def status(self) -> dict[str, Any]:
        try:
            with self.storage.transaction() as state:
                credentials = state.get("credentials") or {}
                registration = state.get("registration") or {}
                error = state.get("lastError")
                # This reports verified local authorization, never plan tier or completed inference.
                connected = (bool(credentials.get("access_token")) and error != "reauth_required"
                             and REQUIRED_SCOPES.issubset(credentials.get("scopes", [])))
                result = {
                    "state": "connected" if connected else "signed_out",
                    "connected": connected,
                    "account": {"subject": registration.get("subject", ""), "email": registration.get("email", "")} if registration else None,
                    "expiresAt": _iso(credentials["expires_at"]) if connected else None,
                    "lastError": ChatGPTSubscriptionError(error).safe_dict() if error else None,
                    "login": None,
                }
                if not connected and error == "reauth_required":
                    result["state"] = "reauth_required"
            with self._guard:
                if self._attempt is not None:
                    result["login"] = self._attempt.safe_dict()
            return result
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"state": "unavailable", "connected": False, "account": None, "expiresAt": None,
                    "lastError": ChatGPTSubscriptionError("storage_corrupt").safe_dict(), "login": None}
        except ChatGPTSubscriptionError as exc:
            return {"state": "unavailable", "connected": False, "account": None, "expiresAt": None,
                    "lastError": exc.safe_dict(), "login": None}

    def start_login(self) -> dict[str, Any]:
        with self._lifecycle:
            return self._start_login()

    def _start_login(self) -> dict[str, Any]:
        self._cancel_current()
        attempt = _LoginAttempt(self._clock() + self._ttl)
        with self.storage.transaction() as state:
            registration = state.get("registration") or {}
            client_id = registration.get("clientId") or state.get("provisionalClientId") or "dynamic_agent_client"
            state["generation"] += 1
            generation = state["generation"]
            state["loginAttemptId"] = attempt.id
            state.pop("pendingLogin", None)
            if state.get("lastError") != "reauth_required":
                state.pop("lastError", None)
            host_id = state["hostId"]
            self.storage.save(state)
        with self._guard:
            self._attempt = attempt
        try:
            listener = CallbackListener(attempt.state, self._ttl,
                                        lambda values: self._receive_callback(attempt, generation, client_id, values),
                                        lambda: self._expire(attempt))
            attempt.listener = listener
        except ChatGPTSubscriptionError as exc:
            attempt.phase = "failed"
            self._record_error(exc)
            raise
        challenge = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        params = {"client_id": client_id, "ext_agent_host_id": host_id, "response_type": "code",
                  "redirect_uri": listener.redirect_uri, "scope": SCOPES, "resource": RESOURCE,
                  "state": attempt.state, "nonce": attempt.nonce, "code_challenge_method": "S256", "code_challenge": challenge}
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "Vibelution"
        # Deliberately omit ID-token/login hints: this URL is safe for the renderer to open.
        return {"attemptId": attempt.id, "authorizationUrl": f"{AUTHORIZE_URL}?{urlencode(params)}", "expiresAt": _iso(attempt.expires_at)}

    def cancel_login(self, attempt_id: str) -> dict[str, bool]:
        with self._lifecycle:
            return self._cancel_login(attempt_id)

    def _cancel_login(self, attempt_id: str, *, preserve_pending: bool = False) -> dict[str, bool]:
        with self._guard:
            attempt = self._attempt
        if attempt is None or attempt.id != attempt_id or attempt.phase not in {"pending", "exchanging"}:
            return {"cancelled": False}
        attempt.cancelled.set()
        attempt.phase = "cancelled"
        if attempt.listener is not None:
            attempt.listener.close()
        with self.storage.transaction() as state:
            if state.get("loginAttemptId") == attempt_id:
                state["generation"] += 1
                if not preserve_pending:
                    state.pop("pendingLogin", None)
                state.pop("loginAttemptId", None)
                self.storage.save(state)
        return {"cancelled": True}

    def _cancel_current(self):
        with self._guard:
            attempt = self._attempt
        if attempt is not None:
            self.cancel_login(attempt.id)

    def _expire(self, attempt: _LoginAttempt):
        if attempt.phase == "pending":
            attempt.cancelled.set()
            attempt.phase = "expired"
            self._record_error(ChatGPTSubscriptionError("login_expired"), attempt_id=attempt.id)

    def _assert_live(self, state: dict[str, Any], attempt: _LoginAttempt, generation: int):
        if (attempt.cancelled.is_set() or state["generation"] != generation
                or state.get("loginAttemptId") != attempt.id):
            raise ChatGPTSubscriptionError("login_cancelled")
        if self._clock() >= attempt.expires_at:
            raise ChatGPTSubscriptionError("login_expired")

    def _receive_callback(self, attempt: _LoginAttempt, generation: int, requested_client: str,
                          values: dict[str, str]) -> bool:
        try:
            if values.get("error"):
                raise ChatGPTSubscriptionError("login_declined")
            if not values.get("code"):
                raise ChatGPTSubscriptionError("invalid_response")
            issued_client = values.get("client_id") or requested_client
            if (re.fullmatch(r"oaiapp_[A-Za-z0-9_-]{1,500}", issued_client) is None
                    or (requested_client != "dynamic_agent_client" and issued_client != requested_client)):
                raise ChatGPTSubscriptionError("registration_incomplete")
            attempt.phase = "exchanging"
            with self.storage.transaction() as state:
                self._assert_live(state, attempt, generation)
                registration = state.get("registration") or {}
                # Persist issued ID BEFORE exchange, independently of the active account.
                if not registration:
                    state["provisionalClientId"] = issued_client
                    self.storage.save(state)
                assert attempt.listener is not None
                response = self._http.request("POST", TOKEN_URL, data={
                    "grant_type": "authorization_code", "client_id": issued_client, "code": values["code"],
                    "code_verifier": attempt.verifier, "redirect_uri": attempt.listener.redirect_uri, "resource": RESOURCE})
                tokens = self._tokens(response, nonce=attempt.nonce)
                state["pendingLogin"] = {"tokens": tokens, "clientId": issued_client,
                                         "expectedSubject": registration.get("subject"), "generation": generation,
                                         "attemptId": attempt.id}
                self.storage.save(state)
                self._assert_live(state, attempt, generation)
                self._finish_login(state, attempt=attempt)
                attempt.phase = "succeeded"
            return True
        except ChatGPTSubscriptionError as exc:
            if not attempt.cancelled.is_set():
                attempt.phase = "failed"
                self._record_error(exc, attempt_id=attempt.id)
            return False
        except Exception:  # noqa: BLE001 - OAuth callbacks must never emit upstream tracebacks.
            attempt.phase = "failed"
            self._record_error(ChatGPTSubscriptionError("invalid_response"), attempt_id=attempt.id)
            return False
        finally:
            # Keep only the safe attempt projection after callback consumption.
            attempt.verifier = ""
            attempt.state = ""
            attempt.nonce = ""

    def _tokens(self, payload: dict[str, Any], *, nonce: str | None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        previous = previous or {}
        result: dict[str, Any] = {}
        for field in ("access_token", "refresh_token"):
            value = payload.get(field)
            if (not isinstance(value, str) or not value or len(value) > 128 * 1024
                    or not value.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
                raise ChatGPTSubscriptionError("invalid_response")
            result[field] = value
        id_token = payload.get("id_token", previous.get("id_token"))
        if not isinstance(id_token, str) or not id_token or len(id_token) > 128 * 1024:
            raise ChatGPTSubscriptionError("invalid_response")
        duration = payload.get("expires_in")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 30 * 86400:
            raise ChatGPTSubscriptionError("invalid_response")
        if str(payload.get("token_type", "")).lower() != "bearer":
            raise ChatGPTSubscriptionError("invalid_response")
        scope = payload.get("scope")
        if scope is None and previous:
            scopes = previous["scopes"]
        elif isinstance(scope, str) and len(scope) <= 8192:
            scopes = scope.split()
        else:
            raise ChatGPTSubscriptionError("permission_missing")
        now = self._clock()
        earliest = payload.get("earliest_refresh_at", 0)
        if isinstance(earliest, bool) or not isinstance(earliest, (int, float)) or earliest < 0:
            earliest = 0
        result.update(id_token=id_token, nonce=nonce, scopes=scopes, token_type="Bearer", saved_at=now,
                      expires_at=now + duration, earliest_refresh_at=earliest)
        return result

    def _finish_login(self, state: dict[str, Any], *, attempt: _LoginAttempt | None = None):
        pending = state["pendingLogin"]
        tokens = pending["tokens"]
        if attempt is None:
            with self._guard:
                local_attempt = self._attempt
            if (local_attempt is not None and local_attempt.id == pending.get("attemptId")
                    and local_attempt.cancelled.is_set()):
                raise ChatGPTSubscriptionError("login_cancelled")
        if pending["generation"] != state["generation"]:
            state.pop("pendingLogin", None)
            self.storage.save(state)
            raise ChatGPTSubscriptionError("login_cancelled")
        try:
            identity = self._identity.verify(tokens["id_token"], pending["clientId"], nonce=tokens["nonce"],
                                             expected_subject=pending.get("expectedSubject"))
            if any(tokens[key] in value for key in ("access_token", "refresh_token", "id_token") for value in identity.values()):
                raise ChatGPTSubscriptionError("invalid_identity")
            if not REQUIRED_SCOPES.issubset(tokens["scopes"]):
                raise ChatGPTSubscriptionError("permission_missing")
        except ChatGPTSubscriptionError as exc:
            if exc.code in {"invalid_identity", "identity_mismatch", "permission_missing"}:
                state.pop("pendingLogin", None)
                self.storage.save(state)
            raise
        if attempt is not None:
            self._assert_live(state, attempt, pending["generation"])
        state["registration"] = {"clientId": pending["clientId"], **identity}
        state["credentials"] = tokens
        for key in ("pendingLogin", "pendingRefresh", "provisionalClientId", "lastError", "loginAttemptId"):
            state.pop(key, None)
        self.storage.save(state)

    def get_access_token(self) -> str:
        """Backend-only. Never serialize this return value into API DTOs or logs."""
        try:
            with self.storage.transaction() as state:
                if state.get("lastError") == "reauth_required" and not state.get("pendingLogin"):
                    raise ChatGPTSubscriptionError("reauth_required")
                if state.get("pendingLogin"):
                    try:
                        self._finish_login(state)
                    except ChatGPTSubscriptionError:
                        if not state.get("credentials"):
                            raise
                if state.get("lastError") == "reauth_required":
                    raise ChatGPTSubscriptionError("reauth_required")
                if state.get("pendingRefresh"):
                    self._finish_refresh(state)
                credentials = state.get("credentials")
                if not credentials:
                    raise ChatGPTSubscriptionError("reauth_required" if state.get("lastError") == "reauth_required" else "signed_out")
                now = self._clock()
                if credentials["expires_at"] > now + 60:
                    return credentials["access_token"]
                if credentials.get("earliest_refresh_at", 0) > now:
                    if credentials["expires_at"] > now:
                        return credentials["access_token"]
                    raise ChatGPTSubscriptionError("rate_limited")
                try:
                    response = self._http.request("POST", TOKEN_URL, data={
                        "grant_type": "refresh_token", "client_id": state["registration"]["clientId"],
                        "refresh_token": credentials["refresh_token"], "resource": RESOURCE})
                    tokens = self._tokens(response, nonce=credentials.get("nonce"), previous=credentials)
                    state["pendingRefresh"] = {"tokens": tokens, "verifyIdentity": "id_token" in response}
                    self.storage.save(state)
                    self._finish_refresh(state)
                except ChatGPTSubscriptionError as exc:
                    state["lastError"] = "reauth_required" if not state.get("credentials") else exc.code
                    if exc.code == "reauth_required":
                        state.pop("credentials", None)
                    self.storage.save(state)
                    raise
                return state["credentials"]["access_token"]
        except ChatGPTSubscriptionError:
            raise
        except Exception:  # noqa: BLE001 - Corrupt encrypted state must fail closed with a fixed public error.
            raise ChatGPTSubscriptionError("storage_corrupt") from None

    def mark_auth_rejected(self, expected_access_token: str) -> None:
        """Backend-only: a definite HTTP 401 may invalidate only its own token.

        Retain the renewable session for logout revocation. A delayed rejection
        of an older token cannot invalidate a newer login/refresh under this lock.
        """
        if not isinstance(expected_access_token, str) or not expected_access_token:
            return
        with self.storage.transaction() as state:
            current = (state.get("credentials") or {}).get("access_token")
            if (not isinstance(current, str)
                    or not hmac.compare_digest(current.encode("utf-8"), expected_access_token.encode("utf-8"))):
                return
            state["lastError"] = "reauth_required"
            self.storage.save(state)

    def _finish_refresh(self, state: dict[str, Any]):
        pending = state["pendingRefresh"]
        tokens = pending["tokens"]
        try:
            if pending["verifyIdentity"]:
                self._identity.verify(tokens["id_token"], state["registration"]["clientId"], nonce=tokens.get("nonce"),
                                      expected_subject=state["registration"]["subject"], require_nonce=False)
            if not REQUIRED_SCOPES.issubset(tokens["scopes"]):
                raise ChatGPTSubscriptionError("permission_missing")
        except ChatGPTSubscriptionError as exc:
            if exc.code in {"invalid_identity", "identity_mismatch", "permission_missing"}:
                state.pop("pendingRefresh", None)
                state.pop("credentials", None)
                state["lastError"] = "reauth_required"
                self.storage.save(state)
            raise
        state["credentials"] = tokens
        state.pop("pendingRefresh", None)
        state.pop("lastError", None)
        self.storage.save(state)

    def list_models(self) -> list[dict[str, Any]]:
        token = self.get_access_token()
        payload = self._http.request("GET", f"{RESOURCE}/models", headers={"Authorization": f"Bearer {token}"})
        models = payload.get("models")
        if not isinstance(models, list) or len(models) > 5000:
            raise ChatGPTSubscriptionError("invalid_response")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for model in models:
            if not isinstance(model, dict) or model.get("visibility") != "list":
                continue
            slug, name = model.get("slug"), model.get("display_name")
            if not isinstance(slug, str) or not slug or len(slug) > 512 or slug in seen:
                continue
            if not isinstance(name, str) or len(name) > 512:
                name = slug
            # Return only catalog fields used by a picker. Provider echoes never carry bearer credentials out.
            if token in slug or token in name:
                raise ChatGPTSubscriptionError("invalid_response")
            seen.add(slug)
            item: dict[str, Any] = {"slug": slug, "display_name": name, "visibility": "list"}
            if isinstance(model.get("supported_in_api"), bool):
                item["supported_in_api"] = model["supported_in_api"]
            window = model.get("context_window")
            if isinstance(window, int) and not isinstance(window, bool) and 0 < window <= 100_000_000:
                item["context_window"] = window
            if isinstance(model.get("input_modalities"), list):
                item["input_modalities"] = list(dict.fromkeys(
                    value for value in model["input_modalities"] if isinstance(value, str) and value in {"text", "image", "file"}))
            if isinstance(model.get("supported_reasoning_levels"), list):
                efforts = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
                item["supported_reasoning_levels"] = [{"effort": effort} for effort in dict.fromkeys(
                    level["effort"] for level in model["supported_reasoning_levels"]
                    if isinstance(level, dict) and isinstance(level.get("effort"), str) and level["effort"] in efforts)]
            result.append(item)
        return result

    def logout(self) -> dict[str, bool]:
        with self._lifecycle:
            return self._logout()

    def _logout(self) -> dict[str, bool]:
        with self._guard:
            attempt = self._attempt
        if attempt is not None:
            # Keep any tokens returned by an in-flight exchange long enough to revoke them.
            self._cancel_login(attempt.id, preserve_pending=True)
        confirmed = False
        with self.storage.transaction() as state:
            credentials = (state.get("pendingRefresh") or {}).get("tokens") or state.get("credentials") or {}
            registration = state.get("registration") or {}
            sessions = []
            if credentials.get("refresh_token") and registration.get("clientId"):
                sessions.append((credentials["refresh_token"], registration["clientId"]))
            candidate = state.get("pendingLogin") or {}
            if candidate.get("tokens", {}).get("refresh_token") and candidate.get("clientId"):
                sessions.append((candidate["tokens"]["refresh_token"], candidate["clientId"]))
            confirmations = []
            for refresh_token, client_id in dict.fromkeys(sessions):
                revoked = False
                for retry in range(2):
                    try:
                        endpoint = trusted_auth_endpoint(self._identity.metadata().get("revocation_endpoint"))
                        self._http.request("POST", endpoint, data={"token": refresh_token,
                                            "token_type_hint": "refresh_token", "client_id": client_id}, empty=True)
                        revoked = True
                        break
                    except ChatGPTSubscriptionError as exc:
                        if exc.code not in {"network", "timeout", "upstream_unavailable"} or retry:
                            break
                        time.sleep(0.2)
                confirmations.append(revoked)
            confirmed = bool(confirmations) and all(confirmations)
            state["generation"] += 1
            for key in ("credentials", "pendingRefresh", "pendingLogin", "loginAttemptId", "lastError", "provisionalClientId"):
                state.pop(key, None)
            self.storage.save(state)
        return {"revocationConfirmed": confirmed}

    def _record_error(self, error: ChatGPTSubscriptionError, *, attempt_id: str | None = None):
        try:
            with self.storage.transaction() as state:
                if attempt_id is not None and state.get("loginAttemptId") != attempt_id:
                    return
                if state.get("lastError") == "reauth_required":
                    # A cancelled/failed reauthorization must never unblock a definitively rejected token.
                    return
                state["lastError"] = error.code
                self.storage.save(state)
        except ChatGPTSubscriptionError:
            pass

    def close(self):
        self._cancel_current()
        with self._guard:
            attempt = self._attempt
        if attempt is not None and attempt.listener is not None:
            attempt.listener.close()
        if self._owns_http:
            self._client.close()
