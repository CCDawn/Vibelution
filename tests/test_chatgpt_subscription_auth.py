from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from core.llm.chatgpt_subscription import (
    ChatGPTSubscriptionAuth,
    ChatGPTSubscriptionError,
)
from core.llm.chatgpt_subscription.auth import SCOPES, TOKEN_URL
from core.llm.chatgpt_subscription.identity import (
    DISCOVERY_URL,
    ISSUER,
    IdentityVerifier,
)
from tests.test_chatgpt_subscription_storage import TestEncryption


@pytest.fixture(scope="module")
def signing_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="synthetic-key", alg="RS256", use="sig")
    return private, public


class OpenAISyntheticServer:
    def __init__(self, signing_key):
        self.key, self.jwk = signing_key
        self.nonce = ""
        self.subject = "synthetic-account"
        self.client_id = "oaiapp_synthetic"
        self.scopes = SCOPES
        self.jwks_offline = False
        self.token_error = None
        self.revocation_status = 200
        self.refresh_count = 0
        self.refresh_id_token = False
        self.calls = []
        self.models = []
        self.storage = None
        self.issued_id_was_saved = False

    def id_token(self, **overrides):
        now = int(time.time())
        payload = {"iss": ISSUER, "aud": self.client_id, "sub": self.subject,
                   "iat": now, "exp": now + 3600, "nonce": self.nonce, "email": "synthetic@example.test"}
        payload.update(overrides)
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": "synthetic-key"})

    def __call__(self, request):
        data = {key: values[0] for key, values in parse_qs(request.content.decode()).items()} if request.content else {}
        self.calls.append((request.method, str(request.url), data))
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks", "revocation_endpoint": f"{ISSUER}/revoke"})
        if request.url.path == "/jwks":
            return httpx.Response(503, text="synthetic-secret upstream") if self.jwks_offline else httpx.Response(200, json={"keys": [self.jwk]})
        if request.url.path == "/revoke":
            return httpx.Response(self.revocation_status, text="" if self.revocation_status == 200 else "synthetic-secret")
        if str(request.url) == TOKEN_URL:
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error, "error_description": "synthetic-secret"})
            refresh = data.get("grant_type") == "refresh_token"
            if refresh:
                self.refresh_count += 1
                assert "scope" not in data
            elif self.storage is not None:
                with self.storage.transaction() as state:
                    self.issued_id_was_saved = state.get("provisionalClientId") == self.client_id
            payload = {"access_token": "synthetic-access-2" if refresh else "synthetic-access-1",
                       "refresh_token": "synthetic-refresh-2" if refresh else "synthetic-refresh-1",
                       "token_type": "Bearer", "expires_in": 3600, "scope": self.scopes}
            if not refresh or self.refresh_id_token:
                payload["id_token"] = self.id_token()
            return httpx.Response(200, json=payload)
        if request.url.path == "/v1/models":
            assert request.headers["Authorization"].startswith("Bearer synthetic-access-")
            return httpx.Response(200, json={"models": self.models})
        raise AssertionError("Unexpected synthetic endpoint")


@pytest.fixture
def auth_harness(tmp_path, signing_key):
    server = OpenAISyntheticServer(signing_key)
    encryption = TestEncryption()
    client = httpx.Client(transport=httpx.MockTransport(server))
    auth = ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=encryption)
    server.storage = auth.storage
    yield auth, server, client, encryption
    auth.close()
    client.close()


def begin(auth, server):
    result = auth.start_login()
    params = {key: values[0] for key, values in parse_qs(urlsplit(result["authorizationUrl"]).query).items()}
    server.nonce = params["nonce"]
    return result, params


def callback(params, **overrides):
    values = {"code": "synthetic-code", "state": params["state"], "client_id": "oaiapp_synthetic"}
    values.update(overrides)
    with httpx.Client(trust_env=False) as client:
        return client.get(params["redirect_uri"], params=values)


def connect(auth, server):
    _, params = begin(auth, server)
    assert callback(params).status_code == 200
    assert auth.status()["connected"] is True


def expire_access(auth):
    with auth.storage.transaction() as state:
        state["credentials"]["expires_at"] = 0
        auth.storage.save(state)


def test_signed_out_status_contains_no_credentials_and_does_not_call_network(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("network")))) as client:
        auth = ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=TestEncryption())
        assert auth.status()["state"] == "signed_out"
        assert auth.status()["connected"] is False
        auth.close()


def test_pkce_and_host_identity_are_stable_and_urls_contain_no_token_hints(auth_harness):
    auth, server, _, _ = auth_harness
    first, params = begin(auth, server)
    assert params["client_id"] == "dynamic_agent_client"
    assert params["agent_name_hint"] == "Vibelution"
    assert params["scope"] == SCOPES
    assert params["resource"] == "https://api.openai.com/v1"
    assert params["code_challenge_method"] == "S256"
    assert urlsplit(params["redirect_uri"]).hostname == "127.0.0.1"
    assert urlsplit(params["redirect_uri"]).path == "/auth/callback"
    verifier = auth._attempt.verifier
    assert params["code_challenge"] == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert "id_token_hint" not in params and "login_hint" not in params
    second, later = begin(auth, server)
    assert later["ext_agent_host_id"] == params["ext_agent_host_id"]
    assert first["attemptId"] != second["attemptId"]
    assert later["state"] != params["state"] and later["nonce"] != params["nonce"]


def test_loopback_rejects_wrong_host_path_state_and_duplicates_without_consuming_attempt(auth_harness):
    auth, server, _, _ = auth_harness
    _, params = begin(auth, server)
    with httpx.Client(trust_env=False) as client:
        assert client.get(params["redirect_uri"], headers={"Host": "attacker.test"}).status_code == 400
        assert client.get(params["redirect_uri"].replace("/auth/callback", "/callback")).status_code == 404
        assert client.get(params["redirect_uri"], params={"state": "wrong"}).status_code == 400
        assert client.get(params["redirect_uri"], params={"state": "非ASCII"}).status_code == 400
        assert client.get(params["redirect_uri"] + "?" + urlencode({"state": params["state"]}) + "&state=other").status_code == 400
    assert not server.calls
    assert callback(params).status_code == 200
    assert server.issued_id_was_saved
    assert auth.get_access_token() == "synthetic-access-1"
    projected = json.dumps(auth.status())
    assert "synthetic-access" not in projected and "synthetic-refresh" not in projected and "id_token" not in projected
    exchange = next(data for _, url, data in server.calls if url == TOKEN_URL)
    assert exchange["redirect_uri"] == params["redirect_uri"]
    assert exchange["client_id"] == "oaiapp_synthetic"


@pytest.mark.parametrize("overrides", [
    {"iss": "https://attacker.test"}, {"aud": "oaiapp_other"}, {"exp": 1}, {"nonce": "wrong"},
    {"sub": ""}, {"sub": None}, {"azp": "oaiapp_other"},
    {"aud": ["oaiapp_synthetic", "oaiapp_other"]},
])
def test_identity_checks_all_required_claims(signing_key, overrides):
    server = OpenAISyntheticServer(signing_key)
    server.nonce = "nonce"
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        auth = ChatGPTSubscriptionAuth(http_client=client, encryption=TestEncryption())
        verifier = IdentityVerifier(auth._http.request)
        with pytest.raises(ChatGPTSubscriptionError) as raised:
            verifier.verify(server.id_token(**overrides), server.client_id, nonce="nonce")
    assert raised.value.code == "invalid_identity"


def test_identity_rejects_bad_signature_and_unsigned_algorithm(signing_key):
    server = OpenAISyntheticServer(signing_key)
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        auth = ChatGPTSubscriptionAuth(http_client=client, encryption=TestEncryption())
        token = server.id_token()
        head, payload, signature = token.split(".")
        changed = ("A" if signature[0] != "A" else "B") + signature[1:]
        for invalid in (f"{head}.{payload}.{changed}", jwt.encode({"sub": "x"}, key="", algorithm="none")):
            with pytest.raises(ChatGPTSubscriptionError, match="无法验证"):
                auth._identity.verify(invalid, server.client_id, nonce="nonce")


def test_reauthorization_requires_same_subject_and_preserves_active_credentials(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    server.subject = "different-account"
    _, params = begin(auth, server)
    assert params["client_id"] == "oaiapp_synthetic" and "agent_name_hint" not in params
    assert callback(params).status_code == 400
    assert auth.status()["lastError"]["code"] == "identity_mismatch"
    assert auth.status()["account"]["subject"] == "synthetic-account"
    assert auth.get_access_token() == "synthetic-access-1"


def test_missing_issued_client_id_does_not_exchange(auth_harness):
    auth, server, _, _ = auth_harness
    _, params = begin(auth, server)
    assert callback(params, client_id="").status_code == 400
    assert not server.calls
    assert auth.status()["lastError"]["code"] == "registration_incomplete"


def test_invalid_grant_retains_issued_client_for_next_attempt(auth_harness):
    auth, server, _, _ = auth_harness
    server.token_error = "invalid_grant"
    _, params = begin(auth, server)
    assert callback(params).status_code == 400
    assert "synthetic-secret" not in json.dumps(auth.status())
    _, retry = begin(auth, server)
    assert retry["client_id"] == "oaiapp_synthetic"


def test_declined_login_and_missing_plan_scope_never_connect(auth_harness):
    auth, server, _, _ = auth_harness
    _, params = begin(auth, server)
    assert callback(params, error="access_denied", error_description="synthetic-secret").status_code == 400
    assert not server.calls
    assert auth.status()["lastError"]["code"] == "login_declined"
    server.scopes = "openid profile email"
    _, params = begin(auth, server)
    assert callback(params).status_code == 400
    assert not auth.status()["connected"]
    assert auth.status()["lastError"]["code"] == "permission_missing"


def test_cancel_and_ttl_close_real_listener(auth_harness, tmp_path):
    auth, server, client, encryption = auth_harness
    attempt, params = begin(auth, server)
    assert auth.cancel_login("not-the-attempt") == {"cancelled": False}
    assert auth.cancel_login(attempt["attemptId"]) == {"cancelled": True}
    assert auth.status()["login"]["state"] == "cancelled"
    with pytest.raises(httpx.ConnectError):
        callback(params)
    short = ChatGPTSubscriptionAuth(tmp_path / "ttl", http_client=client, encryption=encryption, login_ttl_seconds=0.1)
    try:
        short.start_login()
        time.sleep(0.25)
        assert short.status()["login"]["state"] == "expired"
        assert short.status()["lastError"]["code"] == "login_expired"
    finally:
        short.close()


def test_logout_during_exchange_revokes_received_candidate_and_never_reactivates(auth_harness):
    auth, server, client, _ = auth_harness
    connect(auth, server)
    entered, release = threading.Event(), threading.Event()

    def blocked_exchange(request):
        if str(request.url) == TOKEN_URL:
            entered.set()
            assert release.wait(timeout=5)
            response = server(request)
            payload = response.json()
            payload.update(access_token="synthetic-pending-access", refresh_token="synthetic-pending-refresh")
            return httpx.Response(200, json=payload)
        return server(request)

    client._transport = httpx.MockTransport(blocked_exchange)
    _, params = begin(auth, server)
    with ThreadPoolExecutor(max_workers=2) as executor:
        received = executor.submit(callback, params)
        assert entered.wait(timeout=5)
        logged_out = executor.submit(auth.logout)
        # Cancellation is observable before logout waits on the credential lock.
        assert auth._attempt.cancelled.wait(timeout=5)
        release.set()
        assert received.result(timeout=5).status_code == 400
        assert logged_out.result(timeout=5) == {"revocationConfirmed": True}
    assert auth.status()["connected"] is False
    revoked = {data["token"] for _, url, data in server.calls if url.endswith("/revoke")}
    assert revoked == {"synthetic-refresh-1", "synthetic-pending-refresh"}
    with auth.storage.transaction() as state:
        assert "credentials" not in state and "pendingLogin" not in state


def test_logout_revokes_unverified_candidate_after_jwks_outage(auth_harness):
    auth, server, _, _ = auth_harness
    server.jwks_offline = True
    _, params = begin(auth, server)
    assert callback(params).status_code == 400
    assert auth.logout() == {"revocationConfirmed": True}
    revoked = [data["token"] for _, url, data in server.calls if url.endswith("/revoke")]
    assert revoked == ["synthetic-refresh-1"]


def test_unknown_jwks_kid_refreshes_keys_and_rejects_untrusted_discovery(signing_key):
    server = OpenAISyntheticServer(signing_key)
    server.nonce = "nonce"
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        verifier = IdentityVerifier(ChatGPTSubscriptionAuth(http_client=client)._http.request)
        verifier._keys = [{**server.jwk, "kid": "old-key"}]
        verifier._keys_at = time.monotonic()
        assert verifier.verify(server.id_token(), server.client_id, nonce="nonce")["subject"] == server.subject
        assert any(url.endswith("/jwks") for _, url, _ in server.calls)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        "issuer": ISSUER, "jwks_uri": "https://attacker.test/jwks"}))) as client:
        verifier = IdentityVerifier(ChatGPTSubscriptionAuth(http_client=client)._http.request)
        with pytest.raises(ChatGPTSubscriptionError) as raised:
            verifier.verify(server.id_token(), server.client_id, nonce="nonce")
        assert raised.value.code == "invalid_response"


def test_token_endpoint_redirect_is_not_followed_or_exposed(auth_harness):
    auth, server, client, _ = auth_harness
    calls = []

    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://attacker.test/synthetic-secret"}, text="synthetic-secret")

    client._transport = httpx.MockTransport(redirect)
    _, params = begin(auth, server)
    assert callback(params).status_code == 400
    assert calls == [TOKEN_URL]
    assert "synthetic-secret" not in json.dumps(auth.status())


def test_refresh_is_serialized_across_independent_managers(auth_harness, tmp_path):
    auth, server, client, encryption = auth_harness
    connect(auth, server)
    expire_access(auth)
    managers = [ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=encryption) for _ in range(5)]
    barrier = threading.Barrier(5)

    def get_token(manager):
        barrier.wait(timeout=5)
        return manager.get_access_token()

    with ThreadPoolExecutor(max_workers=5) as executor:
        assert list(executor.map(get_token, managers)) == ["synthetic-access-2"] * 5
    assert server.refresh_count == 1
    with auth.storage.transaction() as state:
        assert state["credentials"]["refresh_token"] == "synthetic-refresh-2"
        assert "pendingRefresh" not in state


def test_rotated_refresh_survives_jwks_outage_and_manager_restart(auth_harness, tmp_path):
    auth, server, client, encryption = auth_harness
    connect(auth, server)
    expire_access(auth)
    server.refresh_id_token = True
    server.jwks_offline = True
    # A new process starts with no cached keys.
    restarted = ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=encryption)
    with pytest.raises(ChatGPTSubscriptionError) as raised:
        restarted.get_access_token()
    assert raised.value.code == "upstream_unavailable"
    with auth.storage.transaction() as state:
        assert state["pendingRefresh"]["tokens"]["refresh_token"] == "synthetic-refresh-2"
    assert "synthetic-refresh-2" not in auth.storage.path.read_text()
    server.jwks_offline = False
    recovered = ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=encryption)
    assert recovered.get_access_token() == "synthetic-access-2"
    assert server.refresh_count == 1


def test_initial_tokens_survive_jwks_outage_without_overwriting_account(auth_harness, tmp_path):
    auth, server, client, encryption = auth_harness
    server.jwks_offline = True
    _, params = begin(auth, server)
    assert callback(params).status_code == 400
    assert auth.status()["connected"] is False
    with auth.storage.transaction() as state:
        assert state["pendingLogin"]["tokens"]["refresh_token"] == "synthetic-refresh-1"
        assert not state.get("registration")
    server.jwks_offline = False
    recovered = ChatGPTSubscriptionAuth(tmp_path, http_client=client, encryption=encryption)
    assert recovered.get_access_token() == "synthetic-access-1"


def test_invalid_refresh_grant_requires_reauth_without_upstream_body(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    expire_access(auth)
    server.token_error = "invalid_grant"
    with pytest.raises(ChatGPTSubscriptionError) as raised:
        auth.get_access_token()
    assert raised.value.code == "reauth_required"
    assert "synthetic-secret" not in str(raised.value)
    assert auth.status()["state"] == "reauth_required"


def test_definite_401_marks_current_token_invalid_without_network_or_losing_refresh(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    token = auth.get_access_token()
    calls = len(server.calls)
    auth.mark_auth_rejected(token)
    assert len(server.calls) == calls
    assert auth.status()["state"] == "reauth_required"
    assert auth.status()["connected"] is False
    with pytest.raises(ChatGPTSubscriptionError) as raised:
        auth.get_access_token()
    assert raised.value.code == "reauth_required"
    assert len(server.calls) == calls
    with auth.storage.transaction() as state:
        assert state["credentials"]["refresh_token"] == "synthetic-refresh-1"
    assert auth.logout() == {"revocationConfirmed": True}


def test_late_401_from_old_access_token_cannot_invalidate_refreshed_session(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    old_token = auth.get_access_token()
    expire_access(auth)
    assert auth.get_access_token() == "synthetic-access-2"
    calls = len(server.calls)
    auth.mark_auth_rejected(old_token)
    assert auth.status()["state"] == "connected"
    assert auth.get_access_token() == "synthetic-access-2"
    assert len(server.calls) == calls


def test_rejected_token_stays_blocked_until_new_login_is_verified(auth_harness):
    auth, server, client, _ = auth_harness
    connect(auth, server)
    old_token = auth.get_access_token()
    auth.mark_auth_rejected(old_token)
    _, params = begin(auth, server)
    calls = len(server.calls)
    assert auth.status()["state"] == "reauth_required"
    with pytest.raises(ChatGPTSubscriptionError) as raised:
        auth.get_access_token()
    assert raised.value.code == "reauth_required"
    assert len(server.calls) == calls

    def new_session(request):
        response = server(request)
        if str(request.url) == TOKEN_URL:
            payload = response.json()
            payload.update(access_token="synthetic-new-login-access", refresh_token="synthetic-new-login-refresh")
            return httpx.Response(200, json=payload)
        return response

    client._transport = httpx.MockTransport(new_session)
    assert callback(params).status_code == 200
    auth.mark_auth_rejected(old_token)
    assert auth.get_access_token() == "synthetic-new-login-access"
    assert auth.status()["connected"] is True


def test_declined_reauthorization_cannot_unblock_a_rejected_access_token(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    auth.mark_auth_rejected(auth.get_access_token())
    _, params = begin(auth, server)
    assert callback(params, error="access_denied").status_code == 400
    assert auth.status()["state"] == "reauth_required"
    assert auth.status()["connected"] is False
    calls = len(server.calls)
    with pytest.raises(ChatGPTSubscriptionError) as raised:
        auth.get_access_token()
    assert raised.value.code == "reauth_required"
    assert len(server.calls) == calls


@pytest.mark.parametrize("status_code,confirmed", [(200, True), (503, False)])
def test_logout_revokes_then_clears_tokens_and_keeps_registration(auth_harness, status_code, confirmed):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    server.revocation_status = status_code
    with auth.storage.transaction() as state:
        host_id = state["hostId"]
    assert auth.logout() == {"revocationConfirmed": confirmed}
    with auth.storage.transaction() as state:
        assert state["hostId"] == host_id
        assert state["registration"]["clientId"] == "oaiapp_synthetic"
        assert not any(key in state for key in ("credentials", "pendingLogin", "pendingRefresh"))
    assert auth.status()["connected"] is False
    revocations = [data for _, url, data in server.calls if url.endswith("/revoke")]
    assert len(revocations) == (1 if confirmed else 2)
    assert revocations[0]["token_type_hint"] == "refresh_token"


def test_model_catalog_is_live_ordered_and_whitelisted(auth_harness):
    auth, server, _, _ = auth_harness
    connect(auth, server)
    server.models = [
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
        {"slug": "second", "display_name": "Second", "visibility": "list", "supported_in_api": True,
         "context_window": 1234, "input_modalities": ["image", "text", "unsafe"],
         "supported_reasoning_levels": [{"effort": "high"}, {"effort": "unsafe"}], "token": "synthetic-secret"},
        {"slug": "first", "display_name": "First", "visibility": "list", "context_window": True},
        {"slug": "second", "display_name": "Duplicate", "visibility": "list"},
    ]
    catalog = auth.list_models()
    assert [model["slug"] for model in catalog] == ["second", "first"]
    assert catalog[0]["input_modalities"] == ["image", "text"]
    assert catalog[0]["supported_reasoning_levels"] == [{"effort": "high"}]
    assert "context_window" not in catalog[1]
    assert "synthetic-secret" not in json.dumps(catalog)
    server.models = [{"slug": "new", "display_name": "New", "visibility": "list"}]
    assert auth.list_models()[0]["slug"] == "new"
