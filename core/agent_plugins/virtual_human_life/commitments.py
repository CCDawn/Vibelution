"""Pure commitment lifecycle operations for the Companion calendar ledger.

Commitments share the append-only ``calendar/events.jsonl`` ledger with the
long-lived calendar.  A proposal is deliberately represented by an operation
that :mod:`calendar` does not materialize; only an explicit later confirmation
becomes a normal calendar ``upsert``.  This module owns no storage and does not
write Life Events, relationship events, transcripts, or messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .calendar import normalize_calendar_change

UTC = timezone.utc
_ACTIONS = frozenset({"propose", "confirm", "reject", "cancel", "complete"})
_PROPOSAL_OPERATION = "commitment_proposed"
_TERMINAL_STATES = frozenset({"rejected", "cancelled", "completed", "expired"})
_MANAGED_STATES = frozenset({"pending", "confirmed", *_TERMINAL_STATES})
_MAX_RECENT_TERMINAL = 8
_MAX_PROJECTION_ITEMS = 8


def _text(value: object, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _required(value: object, name: str, limit: int = 160) -> str:
    normalized = _text(value, limit)
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _aware_now(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    raw = _text(value, 80)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _operation(row: Mapping[str, Any]) -> str:
    return _text(row.get("operation"), 40).lower()


def _state(row: Mapping[str, Any]) -> str:
    return _text(row.get("commitmentState"), 40).lower()


def _commitment_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("commitmentId") or row.get("eventId"), 160)


def _row_session(row: Mapping[str, Any]) -> str:
    return _text(row.get("sourceSessionId"), 160)


def _row_agent(row: Mapping[str, Any]) -> str:
    return _text(row.get("agentId"), 160)


def _is_managed_row(row: object) -> bool:
    """Recognize only rows carrying the explicit commitment marker.

    A regular calendar event can use ``kind=commitment`` as a caller-defined
    label, so the state marker is required as well.  This keeps old or
    operator-owned rows outside this lifecycle.
    """

    if not isinstance(row, Mapping):
        return False
    state = _state(row)
    if state not in _MANAGED_STATES or not _commitment_id(row):
        return False
    operation = _operation(row)
    kind = _text(row.get("kind"), 40).lower()
    return (
        operation == _PROPOSAL_OPERATION
        or operation == "cancel"
        or kind == "commitment"
    )


def _copy_rows(ledger: object) -> list[dict[str, Any]]:
    if not isinstance(ledger, list):
        raise TypeError("ledger must be a list")
    return [deepcopy(dict(row)) for row in ledger if isinstance(row, Mapping)]


def _managed_rows(
    rows: list[dict[str, Any]], commitment_id: str
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, row)
        for index, row in enumerate(rows)
        if _is_managed_row(row) and _commitment_id(row) == commitment_id
    ]


def _same_event_id_rows(
    rows: list[dict[str, Any]], commitment_id: str
) -> list[dict[str, Any]]:
    return [row for row in rows if _text(row.get("eventId"), 160) == commitment_id]


def _validate_identity(
    rows: list[dict[str, Any]],
    *,
    commitment_id: str,
    agent_id: str,
    session_id: str,
) -> list[tuple[int, dict[str, Any]]]:
    managed = _managed_rows(rows, commitment_id)
    for _, row in managed:
        stored_agent = _row_agent(row)
        stored_session = _row_session(row)
        if stored_agent and stored_agent != agent_id:
            raise ValueError("commitment agent identity mismatch")
        if stored_session and stored_session != session_id:
            raise ValueError("commitment session identity mismatch")
        if not stored_agent or not stored_session:
            raise ValueError("stored commitment identity is incomplete")
    return managed


def _ensure_no_ordinary_takeover(
    rows: list[dict[str, Any]],
    *,
    commitment_id: str,
    action: str,
) -> None:
    if action not in {"confirm", "cancel", "complete"}:
        return
    ordinary = [
        row
        for row in _same_event_id_rows(rows, commitment_id)
        if not _is_managed_row(row)
    ]
    if ordinary:
        raise ValueError("ordinary calendar event cannot be taken over as a commitment")


def _candidate_and_active(
    managed: list[tuple[int, dict[str, Any]]],
) -> tuple[tuple[int, dict[str, Any]] | None, tuple[int, dict[str, Any]] | None]:
    """Resolve the latest pending candidate and the latest active upsert.

    Rejection does not touch an earlier confirmed event.  A cancellation or
    completion, however, is an ordinary calendar cancellation and therefore
    terminates whichever confirmed event preceded it.
    """

    candidate: tuple[int, dict[str, Any]] | None = None
    active: tuple[int, dict[str, Any]] | None = None
    for index, row in managed:
        operation = _operation(row)
        state = _state(row)
        if operation == _PROPOSAL_OPERATION:
            if state == "pending":
                candidate = (index, row)
            elif state in _TERMINAL_STATES:
                candidate = None
        elif operation == "upsert" and state == "confirmed":
            active = (index, row)
            candidate = None
        elif operation == "cancel" and state in {"cancelled", "completed"}:
            active = None
            candidate = None
    return candidate, active


def _window_tuple(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(row.get("title"), 160),
        _text(row.get("startAt"), 80),
        _text(row.get("endAt"), 80),
        _text(row.get("timezone"), 80),
    )


def _normalize_window(
    *,
    commitment_id: str,
    agent_id: str,
    source_turn_id: str,
    title: str,
    start_at: str,
    end_at: str,
    timezone_name: str,
    now: datetime,
) -> dict[str, Any]:
    """Delegate all title/window/timezone checks to the existing calendar API."""

    return normalize_calendar_change(
        {
            "operation": "upsert",
            "eventId": commitment_id,
            "agentId": agent_id,
            "title": title,
            "kind": "commitment",
            "startAt": start_at,
            "endAt": end_at,
            "timezone": timezone_name,
            "source": {"kind": "companion_commitment", "ref": source_turn_id},
        },
        agent_id=agent_id,
        now=now,
    )


def _decorate(
    row: Mapping[str, Any],
    *,
    action: str,
    state: str,
    commitment_id: str,
    agent_id: str,
    session_id: str,
    source_turn_id: str,
    operation_id: str,
    now: datetime,
    operation_payload: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = deepcopy(dict(row))
    result.update(
        {
            "commitmentId": commitment_id,
            "commitmentState": state,
            "commitmentAction": action,
            "agentId": agent_id,
            "sourceSessionId": session_id,
            "sourceTurnId": source_turn_id,
            "operationId": operation_id,
            "operationPayload": deepcopy(dict(operation_payload)),
        }
    )
    result["changedAt"] = _iso(now)
    result["source"] = {
        "kind": "companion_commitment",
        "ref": source_turn_id,
    }
    if state == "pending":
        result["expiresAt"] = _text(result.get("startAt"), 80)
    elif previous is not None:
        proposal_session = _row_session(previous)
        proposal_turn = _text(previous.get("sourceTurnId"), 160)
        if proposal_session:
            result["proposalSourceSessionId"] = proposal_session
        if proposal_turn:
            result["proposalSourceTurnId"] = proposal_turn
        if _text(previous.get("expiresAt"), 80):
            result["expiresAt"] = _text(previous.get("expiresAt"), 80)
    if action == "confirm":
        result["confirmedAt"] = _iso(now)
        result["confirmationSourceSessionId"] = session_id
        result["confirmationSourceTurnId"] = source_turn_id
    if action in {"cancel", "complete", "reject"} and previous is not None:
        result["previousCommitmentState"] = _state(previous) or "pending"
    return result


def _cancel_row(
    *,
    commitment_id: str,
    agent_id: str,
    session_id: str,
    source_turn_id: str,
    operation_id: str,
    state: str,
    action: str,
    now: datetime,
    reason: str,
    target: Mapping[str, Any],
    operation_payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_calendar_change(
        {
            "operation": "cancel",
            "eventId": commitment_id,
            "agentId": agent_id,
            "reason": reason,
        },
        agent_id=agent_id,
        now=now,
    )
    # Keep enough event shape for a terminal projection while preserving the
    # ordinary calendar cancellation operation used by the shared fold.
    for key in ("title", "kind", "startAt", "endAt", "timezone", "recurrence"):
        if key in target:
            normalized[key] = deepcopy(target[key])
    return _decorate(
        normalized,
        action=action,
        state=state,
        commitment_id=commitment_id,
        agent_id=agent_id,
        session_id=session_id,
        source_turn_id=source_turn_id,
        operation_id=operation_id,
        now=now,
        operation_payload=operation_payload,
        previous=target,
    )


def _payload(
    *,
    action: str,
    commitment_id: str,
    agent_id: str,
    session_id: str,
    source_turn_id: str,
    title: str = "",
    start_at: str = "",
    end_at: str = "",
    timezone_name: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "action": action,
        "commitmentId": commitment_id,
        "agentId": agent_id,
        "sessionId": session_id,
        "sourceTurnId": source_turn_id,
        "title": title,
        "startAt": start_at,
        "endAt": end_at,
        "timezone": timezone_name,
        "reason": reason,
    }


def _find_duplicate_operation(
    rows: list[dict[str, Any]],
    *,
    operation_id: str,
    operation_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    duplicate: dict[str, Any] | None = None
    for row in rows:
        if _text(row.get("operationId"), 160) != operation_id:
            continue
        stored = row.get("operationPayload")
        if not isinstance(stored, Mapping) or dict(stored) != dict(operation_payload):
            raise ValueError("operationId was already used with a different payload")
        duplicate = row
    return duplicate


def _find_duplicate_request(
    rows: list[dict[str, Any]],
    *,
    operation_id: str,
    action: str,
    commitment_id: str,
    agent_id: str,
    session_id: str,
    source_turn_id: str,
    title: str,
    start_at: str,
    end_at: str,
    timezone_name: str,
    reason: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Check replay identity before resolving mutable lifecycle state.

    Confirmation and rejection may be retried after the pending candidate has
    been consumed, so their canonical window is recovered from the recorded
    operation payload.  Blank scheduling arguments mean "use the recorded
    candidate" for those two actions; a supplied value must still normalize to
    the same window.
    """

    duplicate: dict[str, Any] | None = None
    for row in rows:
        if _text(row.get("operationId"), 160) != operation_id:
            continue
        stored = row.get("operationPayload")
        if not isinstance(stored, Mapping):
            raise TypeError("operationId was already used without a commitment payload")
        static_expected = {
            "action": action,
            "commitmentId": commitment_id,
            "agentId": agent_id,
            "sessionId": session_id,
            "sourceTurnId": source_turn_id,
            "reason": reason,
        }
        for key, expected in static_expected.items():
            if stored.get(key) != expected:
                raise ValueError(
                    "operationId was already used with a different payload"
                )

        if action == "propose":
            # Proposals are normalized by the caller before this helper and
            # therefore compare exactly through the regular helper.
            duplicate = row
            continue

        stored_title = _text(stored.get("title"), 160)
        stored_start = _text(stored.get("startAt"), 80)
        stored_end = _text(stored.get("endAt"), 80)
        stored_zone = _text(stored.get("timezone"), 80)
        supplied_title = _text(title, 160)
        supplied_start = _text(start_at, 80)
        supplied_end = _text(end_at, 80)
        supplied_zone = _text(timezone_name, 80)
        if (
            action in {"confirm", "reject"}
            and supplied_zone
            and supplied_zone != "Asia/Shanghai"
            and supplied_zone != stored_zone
        ):
            raise ValueError("operationId was already used with a different payload")
        if action in {"confirm", "reject"} and (
            supplied_title or supplied_start or supplied_end
        ):
            trial_zone = stored_zone or supplied_zone or "Asia/Shanghai"
            # ``Asia/Shanghai`` is the public default and cannot distinguish
            # omission from an explicit value on this API.
            if supplied_zone and supplied_zone != "Asia/Shanghai":
                trial_zone = supplied_zone
            try:
                trial = _normalize_window(
                    commitment_id=commitment_id,
                    agent_id=agent_id,
                    source_turn_id=source_turn_id,
                    title=supplied_title or stored_title,
                    start_at=supplied_start or stored_start,
                    end_at=supplied_end or stored_end,
                    timezone_name=trial_zone,
                    now=now,
                )
            except (TypeError, ValueError):
                raise ValueError(
                    "operationId was already used with a different payload"
                ) from None
            if (
                _text(trial.get("title"), 160) != stored_title
                or _text(trial.get("startAt"), 80) != stored_start
                or _text(trial.get("endAt"), 80) != stored_end
                or _text(trial.get("timezone"), 80) != stored_zone
            ):
                raise ValueError(
                    "operationId was already used with a different payload"
                )
        elif action in {"cancel", "complete"} and (
            supplied_title or supplied_start or supplied_end
        ):
            raise ValueError("operationId was already used with a different payload")
        # For confirm/reject with no window arguments, and terminal actions,
        # the recorded canonical payload is the complete request identity.
        duplicate = row
    return duplicate


def _result_from_row(
    row: Mapping[str, Any], *, changed: bool, idempotent: bool = False
) -> dict[str, Any]:
    event = deepcopy(dict(row))
    return {
        "accepted": True,
        "changed": changed,
        "idempotent": idempotent,
        "action": _text(event.get("commitmentAction"), 40),
        "commitmentId": _commitment_id(event),
        "commitmentState": _state(event),
        "operationId": _text(event.get("operationId"), 160),
        "sourceSessionId": _row_session(event),
        "sourceTurnId": _text(event.get("sourceTurnId"), 160),
        "event": event,
        "row": deepcopy(event),
    }


def _projection_item(
    row: Mapping[str, Any], *, state: str | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "commitmentId": _commitment_id(row),
        "eventId": _text(row.get("eventId"), 160),
        "title": _text(row.get("title") or "日历安排", 160),
        "kind": "commitment",
        "startAt": _text(row.get("startAt"), 80),
        "endAt": _text(row.get("endAt"), 80),
        "timezone": _text(row.get("timezone") or "Asia/Shanghai", 80),
        "commitmentState": state or _state(row),
        "sourceSessionId": _row_session(row),
        "sourceTurnId": _text(row.get("sourceTurnId"), 160),
        "operationId": _text(row.get("operationId"), 160),
        "changedAt": _text(row.get("changedAt"), 80),
        "sourceEventId": _text(row.get("sourceEventId"), 200),
    }
    if _text(row.get("expiresAt"), 80):
        item["expiresAt"] = _text(row.get("expiresAt"), 80)
    if _text(row.get("reason"), 300):
        item["reason"] = _text(row.get("reason"), 300)
    if _text(row.get("confirmedAt"), 80):
        item["confirmedAt"] = _text(row.get("confirmedAt"), 80)
    return item


def apply_commitment_action(
    ledger: list[dict[str, Any]],
    *,
    action: str,
    commitment_id: str,
    operation_id: str,
    agent_id: str,
    session_id: str,
    source_turn_id: str,
    now: datetime,
    title: str = "",
    start_at: str = "",
    end_at: str = "",
    timezone_name: str = "Asia/Shanghai",
    reason: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply one commitment transition without performing I/O.

    The returned ledger is a fresh list that preserves all input rows.  Reusing an ``operation_id``
    with the same payload is a no-op; reusing it with any changed payload is a
    hard error so a replay cannot silently alter a commitment.
    """

    rows = _copy_rows(ledger)
    normalized_action = _required(action, "action", 40).lower()
    if normalized_action not in _ACTIONS:
        raise ValueError("unsupported commitment action")
    normalized_id = _required(commitment_id, "commitment_id")
    normalized_operation_id = _required(operation_id, "operation_id")
    normalized_agent_id = _required(agent_id, "agent_id")
    normalized_session_id = _required(session_id, "session_id")
    normalized_turn_id = _required(source_turn_id, "source_turn_id")
    current = _aware_now(now)
    normalized_reason = _text(reason, 300)

    managed = _validate_identity(
        rows,
        commitment_id=normalized_id,
        agent_id=normalized_agent_id,
        session_id=normalized_session_id,
    )

    prepared_proposal: dict[str, Any] | None = None
    prepared_payload: dict[str, Any] | None = None
    if normalized_action == "propose":
        prepared_proposal = _normalize_window(
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            source_turn_id=normalized_turn_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            timezone_name=timezone_name,
            now=current,
        )
        prepared_payload = _payload(
            action=normalized_action,
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            source_turn_id=normalized_turn_id,
            title=_text(prepared_proposal.get("title"), 160),
            start_at=_text(prepared_proposal.get("startAt"), 80),
            end_at=_text(prepared_proposal.get("endAt"), 80),
            timezone_name=_text(prepared_proposal.get("timezone"), 80),
            reason=normalized_reason,
        )
        duplicate = _find_duplicate_operation(
            rows,
            operation_id=normalized_operation_id,
            operation_payload=prepared_payload,
        )
    else:
        duplicate = _find_duplicate_request(
            rows,
            operation_id=normalized_operation_id,
            action=normalized_action,
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            source_turn_id=normalized_turn_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            timezone_name=timezone_name,
            reason=normalized_reason,
            now=current,
        )
    if duplicate is not None:
        return rows, _result_from_row(duplicate, changed=False, idempotent=True)

    _ensure_no_ordinary_takeover(
        rows,
        commitment_id=normalized_id,
        action=normalized_action,
    )
    candidate, active = _candidate_and_active(managed)

    target: Mapping[str, Any] | None = None
    if normalized_action == "propose":
        # The proposal and payload were normalized before lifecycle checks so
        # a replay is idempotent even after another action consumed it.
        normalized = prepared_proposal
        operation_payload = prepared_payload
        assert normalized is not None and operation_payload is not None
        normalized["operation"] = _PROPOSAL_OPERATION
        saved = _decorate(
            normalized,
            action=normalized_action,
            state="pending",
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            source_turn_id=normalized_turn_id,
            operation_id=normalized_operation_id,
            now=current,
            operation_payload=operation_payload,
        )
    elif normalized_action in {"confirm", "reject"}:
        if candidate is None:
            raise ValueError("no pending commitment candidate")
        _, candidate_row = candidate
        if (
            _row_session(candidate_row) != normalized_session_id
            or _row_agent(candidate_row) != normalized_agent_id
        ):
            raise ValueError("commitment identity mismatch")
        if normalized_action == "confirm":
            proposal_turn = _text(candidate_row.get("sourceTurnId"), 160)
            if proposal_turn and proposal_turn == normalized_turn_id:
                raise ValueError("commitment confirmation requires a later source turn")
            expires_at = _parse_datetime(
                candidate_row.get("expiresAt") or candidate_row.get("startAt")
            )
            if expires_at is None or _utc(expires_at) <= _utc(current):
                raise ValueError("commitment candidate has expired")
            candidate_window = _window_tuple(candidate_row)
            # Confirmation normally carries no scheduling fields.  If callers
            # repeat them, validate them against the candidate rather than
            # silently creating a second interpretation of the commitment.
            has_window_input = bool(
                _text(title)
                or _text(start_at)
                or _text(end_at)
                or (_text(timezone_name, 80) not in {"", "Asia/Shanghai"})
            )
            if has_window_input:
                confirmation_zone = _text(timezone_name, 80) or candidate_window[3]
                normalized_check = _normalize_window(
                    commitment_id=normalized_id,
                    agent_id=normalized_agent_id,
                    source_turn_id=normalized_turn_id,
                    title=title or candidate_window[0],
                    start_at=start_at or candidate_window[1],
                    end_at=end_at or candidate_window[2],
                    timezone_name=confirmation_zone,
                    now=current,
                )
                if _window_tuple(normalized_check) != candidate_window:
                    raise ValueError("confirmation payload differs from candidate")
            operation_payload = _payload(
                action=normalized_action,
                commitment_id=normalized_id,
                agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                source_turn_id=normalized_turn_id,
                title=candidate_window[0],
                start_at=candidate_window[1],
                end_at=candidate_window[2],
                timezone_name=candidate_window[3],
                reason=normalized_reason,
            )
            duplicate = _find_duplicate_operation(
                rows,
                operation_id=normalized_operation_id,
                operation_payload=operation_payload,
            )
            if duplicate is not None:
                return rows, _result_from_row(duplicate, changed=False, idempotent=True)
            normalized = deepcopy(dict(candidate_row))
            normalized["operation"] = "upsert"
            normalized["source"] = {
                "kind": "companion_commitment",
                "ref": normalized_turn_id,
            }
            saved = _decorate(
                normalized,
                action=normalized_action,
                state="confirmed",
                commitment_id=normalized_id,
                agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                source_turn_id=normalized_turn_id,
                operation_id=normalized_operation_id,
                now=current,
                operation_payload=operation_payload,
                previous=candidate_row,
            )
        else:
            candidate_window = _window_tuple(candidate_row)
            operation_payload = _payload(
                action=normalized_action,
                commitment_id=normalized_id,
                agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                source_turn_id=normalized_turn_id,
                title=candidate_window[0],
                start_at=candidate_window[1],
                end_at=candidate_window[2],
                timezone_name=candidate_window[3],
                reason=normalized_reason,
            )
            duplicate = _find_duplicate_operation(
                rows,
                operation_id=normalized_operation_id,
                operation_payload=operation_payload,
            )
            if duplicate is not None:
                return rows, _result_from_row(duplicate, changed=False, idempotent=True)
            normalized = deepcopy(dict(candidate_row))
            normalized["operation"] = _PROPOSAL_OPERATION
            normalized["source"] = {
                "kind": "companion_commitment",
                "ref": normalized_turn_id,
            }
            if normalized_reason:
                normalized["reason"] = normalized_reason
            saved = _decorate(
                normalized,
                action=normalized_action,
                state="rejected",
                commitment_id=normalized_id,
                agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                source_turn_id=normalized_turn_id,
                operation_id=normalized_operation_id,
                now=current,
                operation_payload=operation_payload,
                previous=candidate_row,
            )
    else:
        if normalized_action == "complete" and candidate is not None:
            raise ValueError("unconfirmed commitment cannot be completed")
        target = (
            active[1]
            if active is not None
            else (candidate[1] if candidate is not None else None)
        )
        if target is None:
            raise ValueError("no active commitment")
        if normalized_action == "complete" and active is None:
            raise ValueError("unconfirmed commitment cannot be completed")
        operation_payload = _payload(
            action=normalized_action,
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            source_turn_id=normalized_turn_id,
            reason=normalized_reason,
        )
        duplicate = _find_duplicate_operation(
            rows,
            operation_id=normalized_operation_id,
            operation_payload=operation_payload,
        )
        if duplicate is not None:
            return rows, _result_from_row(duplicate, changed=False, idempotent=True)
        saved = _cancel_row(
            commitment_id=normalized_id,
            agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            source_turn_id=normalized_turn_id,
            operation_id=normalized_operation_id,
            state="completed" if normalized_action == "complete" else "cancelled",
            action=normalized_action,
            now=current,
            reason=normalized_reason,
            target=target,
            operation_payload=operation_payload,
        )

    # Do not trim here: this function shares the calendar ledger with ordinary
    # long-lived events, and a Companion transition must never delete unrelated
    # calendar facts.  Storage owners may apply their own retention policy
    # only when it is proven safe for the complete ledger.
    rows.append(saved)
    return rows, _result_from_row(saved, changed=True)


def project_commitments(
    ledger: list[Mapping[str, Any]],
    *,
    session_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Project only this session's commitment state without exposing messages."""

    normalized_session_id = _required(session_id, "session_id")
    current = _aware_now(now)
    rows = _copy_rows(list(ledger) if isinstance(ledger, list) else ledger)
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(rows):
        if not _is_managed_row(row):
            continue
        if _row_session(row) != normalized_session_id:
            continue
        commitment_id = _commitment_id(row)
        grouped.setdefault(commitment_id, []).append((index, row))

    pending_items: list[tuple[int, dict[str, Any]]] = []
    confirmed_items: list[tuple[int, dict[str, Any]]] = []
    awaiting_items: list[tuple[int, dict[str, Any]]] = []
    terminal_items: list[tuple[int, dict[str, Any]]] = []
    current_utc = _utc(current)

    for managed in grouped.values():
        candidate, active = _candidate_and_active(managed)
        if candidate is not None:
            candidate_index, candidate_row = candidate
            expires_at = _parse_datetime(
                candidate_row.get("expiresAt") or candidate_row.get("startAt")
            )
            if expires_at is not None and _utc(expires_at) <= current_utc:
                terminal_items.append(
                    (
                        candidate_index,
                        _projection_item(candidate_row, state="expired"),
                    )
                )
            else:
                pending_items.append(
                    (candidate_index, _projection_item(candidate_row, state="pending"))
                )
        if active is not None:
            active_index, active_row = active
            end_at = _parse_datetime(active_row.get("endAt"))
            if end_at is not None and _utc(end_at) <= current_utc:
                awaiting_items.append(
                    (
                        active_index,
                        _projection_item(active_row, state="awaiting_outcome"),
                    )
                )
            else:
                confirmed_items.append(
                    (active_index, _projection_item(active_row, state="confirmed"))
                )

        for index, row in managed:
            if _operation(row) == _PROPOSAL_OPERATION and _state(row) == "rejected":
                terminal_items.append((index, _projection_item(row, state="rejected")))
            elif _operation(row) == "cancel" and _state(row) in {
                "cancelled",
                "completed",
            }:
                terminal_items.append((index, _projection_item(row)))

    def _ordered(
        items: list[tuple[int, dict[str, Any]]], limit: int
    ) -> list[dict[str, Any]]:
        # Newest lifecycle decisions are most useful to the Companion.  The
        # stable index tie-breaker keeps projections deterministic for equal
        # timestamps.
        items.sort(
            key=lambda pair: (str(pair[1].get("changedAt") or ""), pair[0]),
            reverse=True,
        )
        return [item for _, item in items[:limit]]

    return {
        "sessionId": normalized_session_id,
        "asOf": _iso(current),
        "pending": _ordered(pending_items, _MAX_PROJECTION_ITEMS),
        "confirmed": _ordered(confirmed_items, _MAX_PROJECTION_ITEMS),
        "awaitingOutcome": _ordered(awaiting_items, _MAX_PROJECTION_ITEMS),
        "recentTerminal": _ordered(terminal_items, _MAX_RECENT_TERMINAL),
    }


__all__ = ["apply_commitment_action", "project_commitments"]
