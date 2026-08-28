"""Server-signed command-offer authorization envelope (snapshot read layer).

Enforcement of ``_OPERATOR_ONLY_COMMANDS`` stays in
``WorkflowCommandService.submit`` (the single write entry).  This module gives
the canonical offer DTO the facts the UI needs to render an operator-only
action as disabled-with-reason BEFORE the user discovers the 403, plus a
server HMAC signature so a stale snapshot cannot be replayed as authority.

Signature scheme (deliberately minimal):
  HMAC-SHA256 over ``runId``/``idempotencyKey``/``command``/``nodeId``/
  ``expectedRunVersion``/``signedAtMs``/``expiresAtMs``, keyed by the existing
  web control-plane secret (``core.web.control.get_control_token`` — env
  ``VIBELUTION_WEB_CONTROL_TOKEN`` or a per-process generated secret; never
  committed).  ``authorizationStatus`` is ``authorized`` only when the server
  signed the exact (scope, run version) pair and the window has not expired.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping, Sequence
from typing import Any

OPERATOR_PERMISSION_REASON = "operator_permission_required"
AUTHORIZED_REASON = "ok"

AUTHORIZATION_STATUS_AUTHORIZED = "authorized"
AUTHORIZATION_STATUS_OPERATOR_REQUIRED = "operator_required"

# A snapshot is a read model refreshed within seconds; the signature window
# only needs to outlive short pauses, not sessions.
DEFAULT_AUTHORIZATION_TTL_MS = 10 * 60 * 1000


def operator_only_command_ids() -> frozenset[str]:
    """Command kinds reserved for operator identities (read-only derivation).

    Derived from the command service's own enforcement set so the projection
    can never drift from the write-side gate.
    """
    from .command_service import _OPERATOR_ONLY_COMMANDS  # noqa: PLC2701 - single enforcement source

    return frozenset(
        str(getattr(kind, "value", kind)) for kind in _OPERATOR_ONLY_COMMANDS
    )


def server_signing_key() -> str:
    """Existing control-plane secret; never a new committed key."""
    from core.web.control import get_control_token

    return str(get_control_token() or "")


def _canonical_signature_payload(
    *,
    run_id: str,
    idempotency_key: str,
    command: str,
    node_id: str | None,
    expected_run_version: int,
    signed_at_ms: int,
    expires_at_ms: int,
) -> str:
    return "\x1f".join(
        [
            "research-workflow-offer-auth/v1",
            str(run_id or ""),
            str(idempotency_key or ""),
            str(command or ""),
            str(node_id or ""),
            str(int(expected_run_version)),
            str(int(signed_at_ms)),
            str(int(expires_at_ms)),
        ]
    )


def sign_offer_authorization(
    *,
    key: str,
    run_id: str,
    idempotency_key: str,
    command: str,
    node_id: str | None,
    expected_run_version: int,
    signed_at_ms: int,
    expires_at_ms: int,
) -> str:
    payload = _canonical_signature_payload(
        run_id=run_id,
        idempotency_key=idempotency_key,
        command=command,
        node_id=node_id,
        expected_run_version=expected_run_version,
        signed_at_ms=signed_at_ms,
        expires_at_ms=expires_at_ms,
    )
    return hmac.new(
        key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_offer_authorization(
    payload: Any,
    *,
    key: str,
    run_id: str,
    now_ms: int | None = None,
) -> tuple[bool, str]:
    """Recompute and compare one authorization payload; returns (ok, reason)."""
    if not isinstance(payload, Mapping):
        try:
            payload = dict(payload)
        except (TypeError, ValueError):
            return False, "authorization_payload_invalid"
    required = (
        "idempotencyKey",
        "command",
        "signedAt",
        "expiresAt",
        "expectedRunVersion",
        "signature",
    )
    missing = [name for name in required if payload.get(name) in (None, "")]
    if missing:
        return False, "authorization_payload_incomplete"
    expected = sign_offer_authorization(
        key=key,
        run_id=run_id,
        idempotency_key=str(payload["idempotencyKey"]),
        command=str(payload["command"]),
        node_id=payload.get("nodeId") or None,
        expected_run_version=int(payload["expectedRunVersion"]),
        signed_at_ms=int(payload["signedAt"]),
        expires_at_ms=int(payload["expiresAt"]),
    )
    if not hmac.compare_digest(expected, str(payload["signature"])):
        return False, "authorization_signature_invalid"
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if current_ms >= int(payload["expiresAt"]):
        return False, "authorization_expired"
    return True, AUTHORIZED_REASON


def build_offer_authorizations(
    *,
    run_id: str,
    run_version: int,
    offers: Sequence[Any],
    now_ms: int | None = None,
    ttl_ms: int = DEFAULT_AUTHORIZATION_TTL_MS,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """One authorization envelope per offer, in offer order.

    ``requiresOperator`` is derived from the command service's enforcement set;
    everything else is server-signed scope binding.  ``key=None`` resolves the
    server control secret; tests may pass an explicit key.
    """
    resolved_key = key if key is not None else server_signing_key()
    if not resolved_key:
        return []
    signed_at = int(now_ms if now_ms is not None else time.time() * 1000)
    expires_at = signed_at + int(ttl_ms)
    operator_only = operator_only_command_ids()
    authorizations: list[dict[str, Any]] = []
    for offer in offers:
        raw_command = getattr(offer, "command", None)
        command_value = str(
            getattr(raw_command, "value", raw_command) or ""
        ).strip()
        node_id = getattr(offer, "node_id", None)
        idempotency_key = str(getattr(offer, "idempotency_key", "") or "")
        if not idempotency_key or not command_value:
            continue
        requires_operator = command_value in operator_only
        signature = sign_offer_authorization(
            key=resolved_key,
            run_id=run_id,
            idempotency_key=idempotency_key,
            command=command_value,
            node_id=node_id,
            expected_run_version=int(run_version),
            signed_at_ms=signed_at,
            expires_at_ms=expires_at,
        )
        authorizations.append(
            {
                "idempotencyKey": idempotency_key,
                "command": command_value,
                "nodeId": node_id,
                "requiresOperator": requires_operator,
                "authorizationStatus": (
                    AUTHORIZATION_STATUS_OPERATOR_REQUIRED
                    if requires_operator
                    else AUTHORIZATION_STATUS_AUTHORIZED
                ),
                "authorizationReason": (
                    OPERATOR_PERMISSION_REASON
                    if requires_operator
                    else AUTHORIZED_REASON
                ),
                "signedAt": signed_at,
                "expiresAt": expires_at,
                "expectedRunVersion": int(run_version),
                "signature": signature,
            }
        )
    return authorizations


__all__ = [
    "AUTHORIZED_REASON",
    "AUTHORIZATION_STATUS_AUTHORIZED",
    "AUTHORIZATION_STATUS_OPERATOR_REQUIRED",
    "DEFAULT_AUTHORIZATION_TTL_MS",
    "OPERATOR_PERMISSION_REASON",
    "build_offer_authorizations",
    "operator_only_command_ids",
    "server_signing_key",
    "sign_offer_authorization",
    "verify_offer_authorization",
]
