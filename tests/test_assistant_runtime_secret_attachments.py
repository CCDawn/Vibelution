"""Privacy attachment staging: pop-on-read store, TTL, and value-free probes.

The store is pure process memory; these tests run in-process against the
module singleton and isolate its dict between cases.
"""

from __future__ import annotations

import threading

import pytest

from core.assistant_runtime import secret_attachments


@pytest.fixture(autouse=True)
def _isolated_store():
    secret_attachments._STORE.clear()
    yield
    secret_attachments._STORE.clear()


def test_issue_returns_sec_token_and_resolve_pops_once() -> None:
    token = secret_attachments.issue_secret_attachment("sk-live-key-123", "api_key")
    assert token.startswith("sec_")
    assert token != secret_attachments.SECRET_ATTACHMENT_ID_PREFIX
    assert secret_attachments.peek_secret_attachment(token) == "api_key"
    assert secret_attachments.resolve_secret_attachment(token) == ("sk-live-key-123", "api_key")
    # Pop-on-read: the second consume and the probe both miss afterwards.
    assert secret_attachments.resolve_secret_attachment(token) is None
    assert secret_attachments.peek_secret_attachment(token) is None


def test_issue_tokens_are_unique() -> None:
    first = secret_attachments.issue_secret_attachment("value-a", "secret")
    second = secret_attachments.issue_secret_attachment("value-a", "secret")
    assert first != second


def test_consume_secret_credential_returns_value_then_invalid_reference() -> None:
    token = secret_attachments.issue_secret_attachment("sk-consume-1", "api_key")
    assert secret_attachments.consume_secret_credential(token) == "sk-consume-1"
    # Pop-on-read: the second consume fails with the stable invalid prefix.
    with pytest.raises(secret_attachments.SecretCredentialError) as second:
        secret_attachments.consume_secret_credential(token)
    assert str(second.value).startswith("invalid_secret_reference")
    assert second.value.prefix == "invalid_secret_reference"


def test_consume_secret_credential_rejects_unknown_token() -> None:
    with pytest.raises(secret_attachments.SecretCredentialError) as raised:
        secret_attachments.consume_secret_credential("sec_unknown_or_expired")
    assert str(raised.value).startswith("invalid_secret_reference")


def test_consume_secret_credential_expected_kind_match_passes() -> None:
    token = secret_attachments.issue_secret_attachment("match-value", "token")
    assert secret_attachments.consume_secret_credential(token, expected_kind="token") == "match-value"


def test_consume_secret_credential_expected_kind_mismatch_consumes_entry() -> None:
    token = secret_attachments.issue_secret_attachment("not-an-api-key", "password")
    with pytest.raises(secret_attachments.SecretCredentialError) as raised:
        secret_attachments.consume_secret_credential(token, expected_kind="api_key")
    assert str(raised.value).startswith("kind_mismatch")
    assert raised.value.prefix == "kind_mismatch"
    # The pop already happened; retrying fails as an invalid reference.
    with pytest.raises(secret_attachments.SecretCredentialError) as second:
        secret_attachments.consume_secret_credential(token)
    assert str(second.value).startswith("invalid_secret_reference")


def test_consume_secret_credential_expired_token_is_invalid(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(secret_attachments.time, "monotonic", lambda: clock["now"])
    token = secret_attachments.issue_secret_attachment("soon-dead", "secret")
    clock["now"] += secret_attachments.SECRET_ATTACHMENT_TTL_SECONDS + 1
    with pytest.raises(secret_attachments.SecretCredentialError) as raised:
        secret_attachments.consume_secret_credential(token)
    assert str(raised.value).startswith("invalid_secret_reference")
    assert secret_attachments._STORE == {}


def test_peek_reports_kind_without_popping_or_returning_value() -> None:
    token = secret_attachments.issue_secret_attachment("peeked-value", "password", label="邮箱密码")
    for _ in range(3):
        assert secret_attachments.peek_secret_attachment(token) == "password"
    assert secret_attachments.resolve_secret_attachment(token) == ("peeked-value", "password")


def test_issue_rejects_unknown_kind_and_invalid_value() -> None:
    for kind in ("certificate", "", "API_KEYS"):
        with pytest.raises(ValueError):
            secret_attachments.issue_secret_attachment("value", kind)
    for value in ("", "   ", None):
        with pytest.raises(ValueError):
            secret_attachments.issue_secret_attachment(value, "api_key")
    with pytest.raises(ValueError):
        secret_attachments.issue_secret_attachment(
            "x" * (secret_attachments.SECRET_MAX_VALUE_CHARS + 1), "api_key",
        )


def test_issue_normalizes_kind_case() -> None:
    token = secret_attachments.issue_secret_attachment("case-value", "API_KEY")
    assert secret_attachments.peek_secret_attachment(token) == "api_key"


def test_ttl_expiry_lazily_drops_entries(monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(secret_attachments.time, "monotonic", lambda: clock["now"])
    token = secret_attachments.issue_secret_attachment("value-1", "token")
    clock["now"] += secret_attachments.SECRET_ATTACHMENT_TTL_SECONDS - 1
    assert secret_attachments.peek_secret_attachment(token) == "token"
    assert secret_attachments.resolve_secret_attachment(token) == ("value-1", "token")
    # Issued inside the live window, then read after expiry.
    token2 = secret_attachments.issue_secret_attachment("value-2", "password")
    clock["now"] += secret_attachments.SECRET_ATTACHMENT_TTL_SECONDS
    assert secret_attachments.peek_secret_attachment(token2) is None
    assert secret_attachments.resolve_secret_attachment(token2) is None
    assert secret_attachments._STORE == {}


def test_purge_expired_returns_count_and_keeps_live_entries(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(secret_attachments.time, "monotonic", lambda: clock["now"])
    dead_one = secret_attachments.issue_secret_attachment("dead-1", "secret")
    clock["now"] = 100.0
    dead_two = secret_attachments.issue_secret_attachment("dead-2", "api_key")
    clock["now"] = 200.0
    live = secret_attachments.issue_secret_attachment("live", "token")
    # Purge at 700: dead_one (age 700) and dead_two (age 600) are expired;
    # live (age 500) stays. Nothing was issued past an expiry boundary, so
    # the lazy sweeps inside issue never consumed these.
    clock["now"] = 700.0
    assert secret_attachments.purge_expired_secret_attachments() == 2
    assert secret_attachments.purge_expired_secret_attachments() == 0
    assert secret_attachments.peek_secret_attachment(live) == "token"
    assert secret_attachments.peek_secret_attachment(dead_one) is None
    assert secret_attachments.resolve_secret_attachment(dead_two) is None


def test_metadata_row_is_value_free() -> None:
    token = secret_attachments.issue_secret_attachment("super-secret", "api_key", label="Provider Key")
    row = secret_attachments.secret_attachment_metadata(token)
    assert row == {"attachmentId": token, "kind": "user_secret", "label": "Provider Key"}
    assert "super-secret" not in str(row)
    assert secret_attachments.secret_attachment_metadata("sec_missing") is None
    # Without a label the row omits the key entirely (contract shape).
    bare = secret_attachments.issue_secret_attachment("bare", "token")
    assert secret_attachments.secret_attachment_metadata(bare) == {
        "attachmentId": bare, "kind": "user_secret",
    }


def test_metadata_row_disappears_after_expiry(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(secret_attachments.time, "monotonic", lambda: clock["now"])
    token = secret_attachments.issue_secret_attachment("soon-dead", "secret")
    clock["now"] += secret_attachments.SECRET_ATTACHMENT_TTL_SECONDS + 1
    assert secret_attachments.secret_attachment_metadata(token) is None
    # Expired entries never resolve either.
    assert secret_attachments.resolve_secret_attachment(token) is None


def test_is_secret_attachment_id_shape() -> None:
    assert secret_attachments.is_secret_attachment_id("sec_abc123")
    assert secret_attachments.is_secret_attachment_id("  sec_abc123  ")
    assert not secret_attachments.is_secret_attachment_id("artifact-123")
    assert not secret_attachments.is_secret_attachment_id("sec")
    assert not secret_attachments.is_secret_attachment_id("")
    assert not secret_attachments.is_secret_attachment_id(None)


def test_concurrent_issue_and_resolve() -> None:
    lock = threading.Lock()
    tokens: list[str] = []

    def issuer(index: int) -> None:
        token = secret_attachments.issue_secret_attachment(f"value-{index}", "token")
        with lock:
            tokens.append(token)

    issuers = [threading.Thread(target=issuer, args=(index,)) for index in range(16)]
    for thread in issuers:
        thread.start()
    for thread in issuers:
        thread.join()
    assert len(tokens) == 16
    assert len(set(tokens)) == 16

    resolved: list[tuple[str, str] | None] = []

    def resolver(token: str) -> None:
        result = secret_attachments.resolve_secret_attachment(token)
        with lock:
            resolved.append(result)

    resolvers = [threading.Thread(target=resolver, args=(token,)) for token in tokens]
    for thread in resolvers:
        thread.start()
    for thread in resolvers:
        thread.join()
    values = {value for value, _kind in resolved if value is not None}
    assert len(values) == 16
    # Every token popped exactly once across threads.
    assert all(secret_attachments.resolve_secret_attachment(token) is None for token in tokens)
