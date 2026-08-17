"""ModelInvocationReceipt: bounded, evidence-carrying record of a model call.

Records provider/model/version, bounded request/response summary hashes,
timing, token/cost metadata, the complete scope, retry bookkeeping, a stable
status and an evidence locator. Construction and serialization scrub
credential-like fields and full prompt/raw response content; only bounded
excerpts and hashes survive.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._canonical import canonical_json
from ._validation import ContractValidationError


class ModelInvocationStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    TIMEOUT = "timeout"
    RETRIED = "retried"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    MODEL_IDENTITY_DRIFT = "model_identity_drift"


_MAX_EXCERPT_CHARS = 256
_REDACTED = "<redacted>"

_SENSITIVE_KEY_SUBSTRINGS = (
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "secret",
    "password",
    "credential",
    "bearer",
    "token",
)

_REDACT_PATTERN = re.compile(
    r"(?i)(api[_-]?key\s*[:=]?\s*\S+|authorization\s*[:=]?\s*\S+|"
    r"cookie\s*[:=]?\s*\S+|secret\s*[:=]?\s*\S+|password\s*[:=]?\s*\S+|"
    r"credential\s*[:=]?\s*\S+|bearer\s+\S+|access[_-]?token\s*[:=]?\s*\S+|"
    r"auth[_-]?token\s*[:=]?\s*\S+|sk-[a-z0-9]+|AKIA[0-9a-z]{16})"
)


def bound_excerpt(text: Any) -> str:
    """Bound and scrub a text excerpt; never returns full raw content."""
    value = _content_text(text)
    value = _REDACT_PATTERN.sub(_REDACTED, value)
    if len(value) > _MAX_EXCERPT_CHARS:
        value = value[:_MAX_EXCERPT_CHARS].rstrip() + "..."
    return value


def sanitize_metadata(value: Any) -> Any:
    """Recursively redact credential-like keys inside a free-form mapping."""
    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED
            if _is_sensitive_key(str(key))
            else sanitize_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_metadata(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_SUBSTRINGS)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, Mapping):
        return canonical_json(content)
    return str(content)


def _content_digest(content: Any) -> str:
    return hashlib.sha256(_content_text(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelInvocationReceipt:
    receipt_id: str
    run_id: str
    node_run_id: str
    scope: Mapping[str, str]
    provider: str
    model: str
    model_version: str
    requested_model: str
    status: ModelInvocationStatus
    request_summary_hash: str
    response_summary_hash: str
    request_excerpt: str
    response_excerpt: str
    started_at_ms: int
    finished_at_ms: int
    latency_ms: int
    attempt: int
    retry_count: int
    token_usage: Mapping[str, int]
    cost: Mapping[str, Any]
    metadata: Mapping[str, Any]
    evidence_locator: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.receipt_id.strip():
            raise ContractValidationError("receiptId must be a non-empty string")
        if not self.run_id.strip():
            raise ContractValidationError("runId must be a non-empty string")
        if not self.node_run_id.strip():
            raise ContractValidationError("nodeRunId must be a non-empty string")
        if not self.scope:
            raise ContractValidationError("scope must not be empty")
        if self.status is not ModelInvocationStatus.NOT_CONFIGURED and (
            not self.provider.strip() or not self.model.strip()
        ):
            raise ContractValidationError(
                "provider and model are required unless not_configured"
            )
        for name in ("request_summary_hash", "response_summary_hash"):
            digest = getattr(self, name)
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ContractValidationError(
                    f"{name} must be a lowercase sha256 hex digest"
                )
        if self.started_at_ms < 0 or self.finished_at_ms < 0:
            raise ContractValidationError("timestamps must be non-negative")
        if self.finished_at_ms < self.started_at_ms:
            raise ContractValidationError("finishedAtMs must not precede startedAtMs")
        if self.latency_ms != self.finished_at_ms - self.started_at_ms:
            raise ContractValidationError(
                "latencyMs must equal finishedAtMs - startedAtMs"
            )
        if self.attempt < 1:
            raise ContractValidationError("attempt must be >= 1")
        if self.retry_count < 0:
            raise ContractValidationError("retryCount must be >= 0")
        for key, value in self.token_usage.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(
                    f"tokenUsage.{key} must be an integer >= 0"
                )
        if (
            self.status is ModelInvocationStatus.RETRIED
            and self.retry_count < 1
        ):
            raise ContractValidationError("retried status requires retryCount >= 1")
        if self.status is ModelInvocationStatus.NOT_CONFIGURED:
            if self.retry_count != 0:
                raise ContractValidationError(
                    "not_configured requires retryCount == 0"
                )
            if self.latency_ms != 0:
                raise ContractValidationError("not_configured requires zero latency")

        actual = self.model.strip()
        requested = self.requested_model.strip()
        if actual and requested and actual != requested:
            if self.status is not ModelInvocationStatus.MODEL_IDENTITY_DRIFT:
                raise ContractValidationError(
                    "model_identity_drift: model identity mismatch must be "
                    "reported explicitly, silent degradation is not allowed"
                )
        if self.status is ModelInvocationStatus.MODEL_IDENTITY_DRIFT:
            if not actual or not requested or actual == requested:
                raise ContractValidationError(
                    "model_identity_drift requires distinct requested and "
                    "actual models"
                )
            if not self.evidence_locator:
                raise ContractValidationError(
                    "model_identity_drift requires evidence_locator"
                )

    @classmethod
    def from_invocation(
        cls,
        *,
        receipt_id: str,
        run_id: str,
        node_run_id: str,
        scope: Mapping[str, str],
        provider: str,
        model: str,
        model_version: str = "",
        requested_model: str = "",
        status: ModelInvocationStatus = ModelInvocationStatus.SUCCEEDED,
        request_content: Any = None,
        response_content: Any = None,
        started_at_ms: int = 0,
        finished_at_ms: int = 0,
        attempt: int = 1,
        retry_count: int = 0,
        token_usage: Mapping[str, int] | None = None,
        cost: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        evidence_locator: Mapping[str, Any] | None = None,
    ) -> ModelInvocationReceipt:
        return cls(
            receipt_id=receipt_id,
            run_id=run_id,
            node_run_id=node_run_id,
            scope=dict(scope),
            provider=provider,
            model=model,
            model_version=model_version,
            requested_model=requested_model,
            status=status,
            request_summary_hash=_content_digest(request_content),
            response_summary_hash=_content_digest(response_content),
            request_excerpt=bound_excerpt(request_content),
            response_excerpt=bound_excerpt(response_content),
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
            latency_ms=max(0, finished_at_ms - started_at_ms),
            attempt=attempt,
            retry_count=retry_count,
            token_usage=dict(token_usage or {}),
            cost=sanitize_metadata(dict(cost or {})),
            metadata=sanitize_metadata(dict(metadata or {})),
            evidence_locator=sanitize_metadata(dict(evidence_locator or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiptId": self.receipt_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "scope": dict(self.scope),
            "provider": self.provider,
            "model": self.model,
            "modelVersion": self.model_version,
            "requestedModel": self.requested_model,
            "status": self.status.value,
            "requestSummaryHash": self.request_summary_hash,
            "responseSummaryHash": self.response_summary_hash,
            "requestExcerpt": bound_excerpt(self.request_excerpt),
            "responseExcerpt": bound_excerpt(self.response_excerpt),
            "startedAtMs": self.started_at_ms,
            "finishedAtMs": self.finished_at_ms,
            "latencyMs": self.latency_ms,
            "attempt": self.attempt,
            "retryCount": self.retry_count,
            "tokenUsage": dict(self.token_usage),
            "cost": sanitize_metadata(dict(self.cost)),
            "metadata": sanitize_metadata(dict(self.metadata)),
            "evidenceLocator": sanitize_metadata(dict(self.evidence_locator)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelInvocationReceipt:
        status_raw = str(payload.get("status") or "")
        try:
            status = ModelInvocationStatus(status_raw)
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported model invocation status: {status_raw}"
            ) from exc
        return cls(
            receipt_id=str(payload.get("receiptId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            scope=dict(payload.get("scope") or {}),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            model_version=str(payload.get("modelVersion") or ""),
            requested_model=str(payload.get("requestedModel") or ""),
            status=status,
            request_summary_hash=str(payload.get("requestSummaryHash") or ""),
            response_summary_hash=str(payload.get("responseSummaryHash") or ""),
            request_excerpt=bound_excerpt(str(payload.get("requestExcerpt") or "")),
            response_excerpt=bound_excerpt(str(payload.get("responseExcerpt") or "")),
            started_at_ms=int(payload.get("startedAtMs") or 0),
            finished_at_ms=int(payload.get("finishedAtMs") or 0),
            latency_ms=int(payload.get("latencyMs") or 0),
            attempt=int(payload.get("attempt") or 1),
            retry_count=int(payload.get("retryCount") or 0),
            token_usage=dict(payload.get("tokenUsage") or {}),
            cost=sanitize_metadata(dict(payload.get("cost") or {})),
            metadata=sanitize_metadata(dict(payload.get("metadata") or {})),
            evidence_locator=sanitize_metadata(dict(payload.get("evidenceLocator") or {})),
        )