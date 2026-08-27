"""R4.3 anomaly inbox: one sorted, fail-closed projection of anomaly signals.

The inbox is a *derived, read-only projection* (like the claim belief table):
it never writes, never reads the ledger and never executes commands.  It
unifies the blocking / risk / drift / needs-human signals that are otherwise
scattered across the hypothesis-first state v2 snapshot (phase problems,
``awaitingHumanCount``), the frozen retry taxonomy (human-required outcome
codes), the claim belief table (``disputed`` claims), review-independence
escalations (``flagged_only``) and audit-sampling drift sentinels into one
ranked list for the operations console and batch control consumers.

Closed kind set (``ANOMALY_KINDS``):

===================================  ==================================================
kind                                 signal source
===================================  ==================================================
``blocked_run``                      a run-level problem whose code the frozen retry
                                     taxonomy classifies ``human_required`` (e.g.
                                     ``collection_run_needs_continue``)
``heartbeat_stale``                  ``generation_heartbeat_stale`` /
                                     ``review_heartbeat_stale`` /
                                     ``review_dispatch_heartbeat_stale`` problems
``needs_human_gate``                 snapshot ``awaitingHumanCount > 0``
``claim_disputed``                   disputed claim count (five-state belief table)
``review_disagreement_escalation``   review-independence escalation marked
                                     ``flagged_only``
``drift_sentinel_hit``               audit-sampling drift sentinel hit (concept only;
                                     the manifest structure is not imported here)
``budget_exhausted``                 ``budget_exceeded`` problem code
``retry_budget_exhausted``           node whose charged business retries exhausted
                                     ``budgetPolicy.maxRetries``
===================================  ==================================================

Severity mapping (frozen table ``ANOMALY_KIND_SEVERITY``, single source of
truth; ``AnomalyInboxItem.create`` derives severity from the kind and
``from_dict`` rejects mismatches, so the rule below is machine-enforced):

- ``critical`` -- the run cannot advance by itself and only a human rebuild
  can unblock it: ``blocked_run`` (taxonomy human-required code) and
  ``budget_exhausted`` (no budget means no automatic path at all).
- ``high`` -- progress is stalled or a verdict is untrusted until a human
  decides: ``heartbeat_stale`` (executor presumed dead),
  ``needs_human_gate`` (workflow halted at a human gate),
  ``retry_budget_exhausted`` (automatic retries used up) and
  ``claim_disputed`` (support and counter evidence coexist, ranking cannot
  be trusted before adjudication).
- ``medium`` -- risk/audit signals that do not halt the run:
  ``review_disagreement_escalation`` (marked ``flagged_only``) and
  ``drift_sentinel_hit`` (sampling quality signal).

Ordering invariant (fail-closed on :meth:`AnomalyInbox.from_dict`, enforced
by construction on :meth:`AnomalyInbox.create`): items are sorted by

1. severity ascending rank (``critical`` before ``high`` before ``medium``),
2. ``lastSeenAt`` descending (newest activity first within one severity),
3. scope stable order (the canonical scope key ascending, so identical
   rankings are deterministic across reads),
4. kind ascending (final total-order tiebreak; two items sharing scope+kind
   are impossible because they are merged).

Dedup/merge rule: items with the same ``(scope key, kind)`` are merged into
one entry that keeps the *earliest* ``firstSeenAt``, the *latest*
``lastSeenAt``, the representative (earliest-seen) summary and recommended
action, and the sorted union of all evidence references.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ._validation import ContractValidationError, require_list, require_text
from .retry_taxonomy import HumanActionFamily

ANOMALY_INBOX_SCHEMA_VERSION = 1
ANOMALY_INBOX_RULE_ID = "anomaly_inbox_rule.v1"

AnomalyKind = str  # closed set: every value must appear in ANOMALY_KINDS

ANOMALY_KIND_BLOCKED_RUN = "blocked_run"
ANOMALY_KIND_HEARTBEAT_STALE = "heartbeat_stale"
ANOMALY_KIND_NEEDS_HUMAN_GATE = "needs_human_gate"
ANOMALY_KIND_CLAIM_DISPUTED = "claim_disputed"
ANOMALY_KIND_REVIEW_DISAGREEMENT_ESCALATION = "review_disagreement_escalation"
ANOMALY_KIND_DRIFT_SENTINEL_HIT = "drift_sentinel_hit"
ANOMALY_KIND_BUDGET_EXHAUSTED = "budget_exhausted"
ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"

ANOMALY_KINDS = frozenset(
    {
        ANOMALY_KIND_BLOCKED_RUN,
        ANOMALY_KIND_HEARTBEAT_STALE,
        ANOMALY_KIND_NEEDS_HUMAN_GATE,
        ANOMALY_KIND_CLAIM_DISPUTED,
        ANOMALY_KIND_REVIEW_DISAGREEMENT_ESCALATION,
        ANOMALY_KIND_DRIFT_SENTINEL_HIT,
        ANOMALY_KIND_BUDGET_EXHAUSTED,
        ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
    }
)

ANOMALY_SEVERITY_CRITICAL = "critical"
ANOMALY_SEVERITY_HIGH = "high"
ANOMALY_SEVERITY_MEDIUM = "medium"

ANOMALY_SEVERITIES = frozenset(
    {ANOMALY_SEVERITY_CRITICAL, ANOMALY_SEVERITY_HIGH, ANOMALY_SEVERITY_MEDIUM}
)

# Lower rank sorts first: critical items head the inbox.
ANOMALY_SEVERITY_RANK: dict[str, int] = {
    ANOMALY_SEVERITY_CRITICAL: 0,
    ANOMALY_SEVERITY_HIGH: 1,
    ANOMALY_SEVERITY_MEDIUM: 2,
}

# Frozen kind -> severity mapping (module docstring states the rule).  The
# import-time check below keeps the closed kind set and this table from
# drifting apart: adding a kind without a severity (or leaving an orphaned
# severity behind) fails at import, never at read time.
ANOMALY_KIND_SEVERITY: dict[AnomalyKind, str] = {
    ANOMALY_KIND_BLOCKED_RUN: ANOMALY_SEVERITY_CRITICAL,
    ANOMALY_KIND_BUDGET_EXHAUSTED: ANOMALY_SEVERITY_CRITICAL,
    ANOMALY_KIND_HEARTBEAT_STALE: ANOMALY_SEVERITY_HIGH,
    ANOMALY_KIND_NEEDS_HUMAN_GATE: ANOMALY_SEVERITY_HIGH,
    ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED: ANOMALY_SEVERITY_HIGH,
    ANOMALY_KIND_CLAIM_DISPUTED: ANOMALY_SEVERITY_HIGH,
    ANOMALY_KIND_REVIEW_DISAGREEMENT_ESCALATION: ANOMALY_SEVERITY_MEDIUM,
    ANOMALY_KIND_DRIFT_SENTINEL_HIT: ANOMALY_SEVERITY_MEDIUM,
}

if set(ANOMALY_KIND_SEVERITY) != set(ANOMALY_KINDS) or not all(
    severity in ANOMALY_SEVERITIES for severity in ANOMALY_KIND_SEVERITY.values()
):  # pragma: no cover - import-time self-consistency guard
    raise ContractValidationError(
        "ANOMALY_KIND_SEVERITY must cover exactly the closed ANOMALY_KINDS set "
        "with known severities"
    )

_RECOMMENDED_ACTION_VALUES = frozenset(
    member.value for member in HumanActionFamily
)

_SCOPE_FIELDS = ("teamId", "questionId", "runId", "nodeId", "meetingRoundId")

_SCOPE_KEY_SEPARATOR = "\x1f"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_inbox_timestamp(value: Any, field_name: str) -> datetime:
    """Parse one durable ISO-8601 timestamp (fail-closed on garbage)."""

    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(
            f"{field_name} must be a non-empty ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ContractValidationError(
            f"{field_name} must be an ISO-8601 timestamp, got {text!r}"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AnomalyInboxScope:
    """Where the anomaly lives; every field optional, at least one required.

    The identity fields are filled by availability (team/question always for
    state-derived signals; run/node for run-scoped problems; meetingRoundId
    for meeting-scoped heartbeat problems).  ``scope_key`` is the stable
    canonical identity used for dedup/merge and for the scope tiebreak of
    the ordering invariant.
    """

    teamId: str = ""
    questionId: str = ""
    runId: str = ""
    nodeId: str = ""
    meetingRoundId: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AnomalyInboxScope:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("scope must be an object")
        values = {
            field: str(payload.get(field) or "").strip() for field in _SCOPE_FIELDS
        }
        if not any(values.values()):
            raise ContractValidationError(
                "scope must carry at least one of: " + ", ".join(_SCOPE_FIELDS)
            )
        return cls(**values)

    def to_dict(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in _SCOPE_FIELDS}

    def scope_key(self) -> str:
        """Stable canonical identity; never rely on dict ordering."""

        return _SCOPE_KEY_SEPARATOR.join(
            getattr(self, field) for field in _SCOPE_FIELDS
        )


@dataclass(frozen=True, slots=True)
class AnomalyInboxItem:
    """One merged anomaly signal with its severity and evidence refs."""

    kind: str
    scope: AnomalyInboxScope
    severity: str
    firstSeenAt: str
    lastSeenAt: str
    summary: str
    recommendedAction: str | None = None
    evidence: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        scope: AnomalyInboxScope,
        first_seen_at: str,
        last_seen_at: str,
        summary: str,
        recommended_action: str | None = None,
        evidence: Iterable[str] = (),
    ) -> AnomalyInboxItem:
        """Build an item, deriving severity from the frozen kind mapping.

        Producers never pick a severity themselves: the frozen
        ``ANOMALY_KIND_SEVERITY`` table is the single source of the mapping.
        """

        if kind not in ANOMALY_KIND_SEVERITY:
            raise ContractValidationError(
                "kind must be one of: " + ", ".join(sorted(ANOMALY_KINDS))
            )
        return cls.from_dict(
            {
                "kind": kind,
                "scope": scope.to_dict() if isinstance(scope, AnomalyInboxScope) else scope,
                "severity": ANOMALY_KIND_SEVERITY[kind],
                "firstSeenAt": first_seen_at,
                "lastSeenAt": last_seen_at,
                "summary": summary,
                "recommendedAction": recommended_action,
                "evidence": list(evidence),
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AnomalyInboxItem:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("anomaly inbox item must be an object")
        kind = require_text(payload, "kind")
        if kind not in ANOMALY_KINDS:
            # Fail-closed: an unknown kind can never silently enter the inbox.
            raise ContractValidationError(
                "kind must be one of: " + ", ".join(sorted(ANOMALY_KINDS))
            )
        raw_severity = payload.get("severity")
        severity = str(raw_severity or "").strip()
        if not severity:
            # Fail-closed: a missing severity is a malformed item, not a default.
            raise ContractValidationError("severity must be a non-empty string")
        if severity not in ANOMALY_SEVERITIES:
            raise ContractValidationError(
                "severity must be one of: " + ", ".join(sorted(ANOMALY_SEVERITIES))
            )
        expected_severity = ANOMALY_KIND_SEVERITY[kind]
        if severity != expected_severity:
            raise ContractValidationError(
                f"severity '{severity}' does not match the frozen mapping for "
                f"kind '{kind}' (expected '{expected_severity}')"
            )
        scope_payload = payload.get("scope")
        scope = (
            scope_payload
            if isinstance(scope_payload, AnomalyInboxScope)
            else AnomalyInboxScope.from_dict(scope_payload or {})
        )
        first_seen = require_text(payload, "firstSeenAt")
        last_seen = require_text(payload, "lastSeenAt")
        first_seen_parsed = _parse_inbox_timestamp(first_seen, "firstSeenAt")
        last_seen_parsed = _parse_inbox_timestamp(last_seen, "lastSeenAt")
        if last_seen_parsed < first_seen_parsed:
            raise ContractValidationError(
                "lastSeenAt must not precede firstSeenAt"
            )
        summary = require_text(payload, "summary")
        raw_action = payload.get("recommendedAction")
        recommended_action = str(raw_action or "").strip() or None
        if recommended_action is not None and (
            recommended_action not in _RECOMMENDED_ACTION_VALUES
        ):
            raise ContractValidationError(
                "recommendedAction must be a HumanActionFamily value: "
                + ", ".join(sorted(_RECOMMENDED_ACTION_VALUES))
            )
        raw_evidence = payload.get("evidence")
        evidence_list = list(raw_evidence) if isinstance(raw_evidence, (list, tuple)) else []
        evidence: list[str] = []
        for index, item in enumerate(evidence_list):
            text = str(item or "").strip()
            if not text:
                raise ContractValidationError(
                    f"evidence entry at index {index} must be a non-empty string"
                )
            evidence.append(text)
        if not evidence:
            # Completeness: every item must cite at least one evidence ref
            # (the problem code itself counts).
            raise ContractValidationError(
                "evidence must carry at least one non-empty reference"
            )
        return cls(
            kind=kind,
            scope=scope,
            severity=severity,
            firstSeenAt=first_seen,
            lastSeenAt=last_seen,
            summary=summary,
            recommendedAction=recommended_action,
            evidence=tuple(sorted(set(evidence))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scope": self.scope.to_dict(),
            "severity": self.severity,
            "firstSeenAt": self.firstSeenAt,
            "lastSeenAt": self.lastSeenAt,
            "summary": self.summary,
            "recommendedAction": self.recommendedAction,
            "evidence": list(self.evidence),
        }

    def dedup_key(self) -> tuple[str, str]:
        """Identity for the same scope+kind merge rule."""

        return (self.scope.scope_key(), self.kind)

    def sort_key(self) -> tuple[int, datetime, str, str]:
        """The ordering invariant: severity asc, lastSeen desc, scope asc, kind asc."""

        return (
            ANOMALY_SEVERITY_RANK[self.severity],
            -_parse_inbox_timestamp(self.lastSeenAt, "lastSeenAt").timestamp(),
            self.scope.scope_key(),
            self.kind,
        )


def _merged_representative(items: list[AnomalyInboxItem]) -> AnomalyInboxItem:
    """Merge same scope+kind items, keeping the earliest firstSeen.

    The representative (earliest ``firstSeenAt``, tie: lexicographically
    smallest summary) contributes summary and recommended action so repeated
    reads of the same signals stay byte-stable; evidence refs are unioned and
    ``lastSeenAt`` advances to the latest observation.
    """

    representative = min(
        items,
        key=lambda item: (
            _parse_inbox_timestamp(item.firstSeenAt, "firstSeenAt"),
            item.summary,
        ),
    )
    last_seen = max(
        items,
        key=lambda item: (
            _parse_inbox_timestamp(item.lastSeenAt, "lastSeenAt"),
            item.lastSeenAt,
        ),
    ).lastSeenAt
    evidence: set[str] = set()
    for item in items:
        evidence.update(item.evidence)
    return AnomalyInboxItem(
        kind=representative.kind,
        scope=representative.scope,
        severity=representative.severity,
        firstSeenAt=representative.firstSeenAt,
        lastSeenAt=last_seen,
        summary=representative.summary,
        recommendedAction=representative.recommendedAction,
        evidence=tuple(sorted(evidence)),
    )


@dataclass(frozen=True, slots=True)
class AnomalyInbox:
    """Fail-closed container of the merged, sorted anomaly items."""

    schemaVersion: int
    ruleId: str
    generatedAt: str
    items: tuple[AnomalyInboxItem, ...]

    @classmethod
    def create(
        cls,
        items: Iterable[AnomalyInboxItem],
        *,
        generated_at: str | None = None,
    ) -> AnomalyInbox:
        """Merge same scope+kind items, sort by the invariant, seal."""

        normalized: list[AnomalyInboxItem] = []
        for item in items:
            if not isinstance(item, AnomalyInboxItem):
                raise ContractValidationError(
                    "anomaly inbox items must be AnomalyInboxItem instances"
                )
            normalized.append(item)
        merged: dict[tuple[str, str], AnomalyInboxItem] = {}
        for item in normalized:
            key = item.dedup_key()
            existing = merged.get(key)
            merged[key] = item if existing is None else _merged_representative(
                [existing, item]
            )
        sorted_items = tuple(sorted(merged.values(), key=lambda item: item.sort_key()))
        return cls(
            schemaVersion=ANOMALY_INBOX_SCHEMA_VERSION,
            ruleId=ANOMALY_INBOX_RULE_ID,
            generatedAt=(generated_at or "").strip() or _utc_now(),
            items=sorted_items,
        )

    @classmethod
    def empty(cls, *, generated_at: str | None = None) -> AnomalyInbox:
        """The legal no-signal state."""

        return cls.create((), generated_at=generated_at)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AnomalyInbox:
        schema_version = payload.get("schemaVersion")
        if schema_version != ANOMALY_INBOX_SCHEMA_VERSION:
            raise ContractValidationError(
                f"anomaly inbox schemaVersion must be {ANOMALY_INBOX_SCHEMA_VERSION}"
            )
        rule_id = require_text(payload, "ruleId")
        if rule_id != ANOMALY_INBOX_RULE_ID:
            raise ContractValidationError(
                f"anomaly inbox ruleId must be {ANOMALY_INBOX_RULE_ID}"
            )
        generated_at = require_text(payload, "generatedAt")
        _parse_inbox_timestamp(generated_at, "generatedAt")
        raw_items = require_list(payload, "items")
        items: list[AnomalyInboxItem] = []
        seen_keys: set[tuple[str, str]] = set()
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise ContractValidationError(
                    f"anomaly inbox item at index {index} must be an object"
                )
            item = AnomalyInboxItem.from_dict(raw_item)
            key = item.dedup_key()
            if key in seen_keys:
                # Fail-closed: persisted inboxes must already be merged.
                raise ContractValidationError(
                    "anomaly inbox contains unmerged duplicate scope+kind: "
                    f"kind '{item.kind}' scope '{key[0]}'"
                )
            seen_keys.add(key)
            items.append(item)
        ordered = sorted(items, key=lambda item: item.sort_key())
        if items != ordered:
            # Fail-closed: the sort invariant is part of the persisted shape.
            raise ContractValidationError(
                "anomaly inbox items violate the ordering invariant "
                "(severity asc -> lastSeenAt desc -> scope asc -> kind asc)"
            )
        return cls(
            schemaVersion=schema_version,
            ruleId=rule_id,
            generatedAt=generated_at,
            items=tuple(items),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "ruleId": self.ruleId,
            "generatedAt": self.generatedAt,
            "items": [item.to_dict() for item in self.items],
        }
