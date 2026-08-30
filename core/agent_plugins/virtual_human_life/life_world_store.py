"""Agent-scoped SQLite store for structured fictional life-world facts.

This store never accepts free-form SQL.  Every mutation is a bounded method
with optimistic revisions, idempotency receipts, foreign keys, and one SQLite
transaction per operation.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .life_world import (
    ITEM_STATUSES,
    build_default_life_draft,
    merge_life_draft_patch,
    validate_life_draft,
)
from .storage import VirtualHumanLifeStore


LIFE_WORLD_SCHEMA_VERSION = 1


class LifeWorldError(RuntimeError):
    """Base error for structured life-world operations."""


class LifeWorldConflictError(LifeWorldError):
    """Raised for optimistic-version or idempotency conflicts."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(operation: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        _json({"operation": operation, "payload": payload}).encode("utf-8")
    ).hexdigest()


class LifeWorldStore:
    def __init__(
        self,
        plugin_store: VirtualHumanLifeStore,
        *,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.plugin_store = plugin_store
        self.now_provider = now_provider

    def database_path(self, agent_id: str) -> Path:
        return self.plugin_store.plugin_root(agent_id) / "life_world.sqlite3"

    def create_or_get_draft(
        self,
        agent_id: str,
        *,
        home_location: dict[str, Any],
        identity_kind: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_key = self._idempotency_key(idempotency_key)
        operation_payload = {
            "homeLocation": deepcopy(home_location),
            "identityKind": str(identity_kind or "").strip().lower(),
        }
        fingerprint = _fingerprint("create_draft", operation_payload)
        with self._transaction(agent_id, create=True) as connection:
            replay = self._receipt_replay(connection, normalized_key, fingerprint)
            if replay is not None:
                return replay
            existing = connection.execute(
                "SELECT draft_id, revision, status, payload_json, created_at, updated_at, confirmed_at "
                "FROM drafts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if existing is not None:
                response = self._draft_row(existing)
                payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
                payload_location = (
                    payload.get("homeLocation")
                    if isinstance(payload.get("homeLocation"), dict)
                    else {}
                )
                payload_identity = (
                    payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
                )
                same_anchor = (
                    str(payload_location.get("locationId") or "").strip()
                    == str(home_location.get("locationId") or "").strip()
                    and str(payload_identity.get("kind") or "").strip().lower()
                    == operation_payload["identityKind"]
                )
                if response["status"] == "confirmed" and not same_anchor:
                    raise LifeWorldConflictError(
                        "Confirmed life-world anchors require an explicit relocation operation."
                    )
                if response["status"] in {"draft", "confirmed"} and same_anchor:
                    self._store_receipt(
                        connection,
                        idempotency_key=normalized_key,
                        fingerprint=fingerprint,
                        operation="create_draft",
                        response=response,
                    )
                    return response
                if response["status"] == "draft":
                    connection.execute(
                        "UPDATE drafts SET status = 'superseded', updated_at = ? WHERE draft_id = ?",
                        (_iso(self._now()), response["draftId"]),
                    )
            draft_id = f"life-draft-{uuid.uuid4().hex[:16]}"
            local_date = self._now().astimezone(
                self._zone(str(home_location.get("timezone") or "UTC"))
            ).date()
            payload = build_default_life_draft(
                draft_id=draft_id,
                home_location=home_location,
                identity_kind=str(identity_kind or ""),
                local_date=local_date,
            )
            validate_life_draft(payload)
            now_text = _iso(self._now())
            connection.execute(
                "INSERT INTO drafts (draft_id, revision, status, payload_json, created_at, updated_at, confirmed_at) "
                "VALUES (?, 1, 'draft', ?, ?, ?, '')",
                (draft_id, _json(payload), now_text, now_text),
            )
            response = {
                "draftId": draft_id,
                "revision": 1,
                "status": "draft",
                "payload": deepcopy(payload),
                "createdAt": now_text,
                "updatedAt": now_text,
                "confirmedAt": "",
            }
            self._store_receipt(
                connection,
                idempotency_key=normalized_key,
                fingerprint=fingerprint,
                operation="create_draft",
                response=response,
            )
            return response

    def update_draft(
        self,
        agent_id: str,
        *,
        draft_id: str,
        expected_revision: int,
        patch: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_key = self._idempotency_key(idempotency_key)
        normalized_draft_id = str(draft_id or "").strip()
        if not normalized_draft_id:
            raise ValueError("Life draft id is required.")
        if not isinstance(patch, dict):
            raise ValueError("Life draft patch must be an object.")
        operation_payload = {
            "draftId": normalized_draft_id,
            "expectedRevision": int(expected_revision),
            "patch": deepcopy(patch),
        }
        fingerprint = _fingerprint("update_draft", operation_payload)
        with self._transaction(agent_id, create=False) as connection:
            replay = self._receipt_replay(connection, normalized_key, fingerprint)
            if replay is not None:
                return replay
            row = connection.execute(
                "SELECT draft_id, revision, status, payload_json, created_at, updated_at, confirmed_at "
                "FROM drafts WHERE draft_id = ?",
                (normalized_draft_id,),
            ).fetchone()
            if row is None:
                raise LifeWorldError("Life draft not found.")
            current = self._draft_row(row)
            if current["status"] != "draft":
                raise LifeWorldConflictError("Confirmed life draft cannot be edited.")
            if int(expected_revision) != int(current["revision"]):
                raise LifeWorldConflictError(
                    f"Life draft revision changed: expected {expected_revision}, current {current['revision']}."
                )
            payload = merge_life_draft_patch(current["payload"], patch)
            next_revision = int(current["revision"]) + 1
            now_text = _iso(self._now())
            connection.execute(
                "UPDATE drafts SET revision = ?, payload_json = ?, updated_at = ? WHERE draft_id = ?",
                (next_revision, _json(payload), now_text, normalized_draft_id),
            )
            response = {
                **current,
                "revision": next_revision,
                "payload": payload,
                "updatedAt": now_text,
            }
            self._store_receipt(
                connection,
                idempotency_key=normalized_key,
                fingerprint=fingerprint,
                operation="update_draft",
                response=response,
            )
            return response

    def confirm_draft(
        self,
        agent_id: str,
        *,
        draft_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_key = self._idempotency_key(idempotency_key)
        normalized_draft_id = str(draft_id or "").strip()
        operation_payload = {
            "draftId": normalized_draft_id,
            "expectedRevision": int(expected_revision),
        }
        fingerprint = _fingerprint("confirm_draft", operation_payload)
        with self._transaction(agent_id, create=False) as connection:
            replay = self._receipt_replay(connection, normalized_key, fingerprint)
            if replay is not None:
                return replay
            row = connection.execute(
                "SELECT draft_id, revision, status, payload_json, created_at, updated_at, confirmed_at "
                "FROM drafts WHERE draft_id = ?",
                (normalized_draft_id,),
            ).fetchone()
            if row is None:
                raise LifeWorldError("Life draft not found.")
            draft = self._draft_row(row)
            if draft["status"] != "draft":
                raise LifeWorldConflictError("Life draft is already confirmed.")
            if int(expected_revision) != int(draft["revision"]):
                raise LifeWorldConflictError(
                    f"Life draft revision changed: expected {expected_revision}, current {draft['revision']}."
                )
            world_revision = self._world_revision(connection)
            if world_revision > 0:
                raise LifeWorldConflictError("Life world already contains confirmed facts.")
            payload = draft["payload"]
            validate_life_draft(payload)
            now_text = _iso(self._now())
            receipt_id = f"life-world-confirm-{uuid.uuid4().hex[:16]}"
            self._insert_confirmed_facts(
                connection,
                payload=payload,
                opening_receipt_id=receipt_id,
                now_text=now_text,
            )
            connection.execute(
                "UPDATE drafts SET status = 'confirmed', confirmed_at = ?, updated_at = ? WHERE draft_id = ?",
                (now_text, now_text, normalized_draft_id),
            )
            connection.execute(
                "UPDATE world_meta SET value = '1' WHERE key = 'revision'"
            )
            connection.execute(
                "UPDATE world_meta SET value = ? WHERE key = 'updated_at'",
                (now_text,),
            )
            response = {
                "status": "confirmed",
                "draftId": normalized_draft_id,
                "draftRevision": int(draft["revision"]),
                "worldRevision": 1,
                "receiptId": receipt_id,
                "confirmedAt": now_text,
            }
            self._store_receipt(
                connection,
                idempotency_key=normalized_key,
                fingerprint=fingerprint,
                operation="confirm_draft",
                response=response,
                receipt_id=receipt_id,
            )
            return response

    def record_transaction(
        self,
        agent_id: str,
        *,
        account_id: str,
        amount_minor: int,
        currency: str,
        category: str,
        description: str,
        occurred_at: str,
        idempotency_key: str,
        expected_world_revision: int | None = None,
    ) -> dict[str, Any]:
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
            raise ValueError("amount_minor must use integer minor currency units.")
        normalized_key = self._idempotency_key(idempotency_key)
        normalized_account_id = str(account_id or "").strip()
        normalized_currency = str(currency or "").strip().upper()
        operation_payload = {
            "accountId": normalized_account_id,
            "amountMinor": amount_minor,
            "currency": normalized_currency,
            "category": str(category or "").strip(),
            "description": str(description or "").strip(),
            "occurredAt": str(occurred_at or "").strip(),
            "expectedWorldRevision": expected_world_revision,
        }
        fingerprint = _fingerprint("record_transaction", operation_payload)
        with self._transaction(agent_id, create=False) as connection:
            replay = self._receipt_replay(connection, normalized_key, fingerprint)
            if replay is not None:
                return replay
            current_world_revision = self._world_revision(connection)
            if current_world_revision <= 0:
                raise LifeWorldError("Life world facts are not confirmed.")
            if (
                expected_world_revision is not None
                and int(expected_world_revision) != current_world_revision
            ):
                raise LifeWorldConflictError(
                    "Life-world revision changed before recording the transaction."
                )
            account = connection.execute(
                "SELECT account_id, currency, balance_minor FROM accounts WHERE account_id = ? AND status = 'active'",
                (normalized_account_id,),
            ).fetchone()
            if account is None:
                raise LifeWorldError("Life world account not found.")
            if str(account["currency"]) != normalized_currency:
                raise ValueError("Transaction currency must match the target account currency.")
            before_balance = int(account["balance_minor"])
            after_balance = before_balance + amount_minor
            transaction_id = f"life-txn-{uuid.uuid4().hex[:16]}"
            receipt_id = f"life-world-receipt-{uuid.uuid4().hex[:16]}"
            now_text = _iso(self._now())
            occurred_text = str(occurred_at or "").strip() or now_text
            connection.execute(
                "INSERT INTO transactions (transaction_id, account_id, amount_minor, currency, category, description, occurred_at, receipt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    normalized_account_id,
                    amount_minor,
                    normalized_currency,
                    str(category or "").strip()[:80],
                    str(description or "").strip()[:240],
                    occurred_text,
                    receipt_id,
                    now_text,
                ),
            )
            connection.execute(
                "UPDATE accounts SET balance_minor = ?, updated_at = ? WHERE account_id = ?",
                (after_balance, now_text, normalized_account_id),
            )
            connection.execute(
                "UPDATE world_meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'revision'"
            )
            connection.execute(
                "UPDATE world_meta SET value = ? WHERE key = 'updated_at'",
                (now_text,),
            )
            response = {
                "status": "recorded",
                "transactionId": transaction_id,
                "receiptId": receipt_id,
                "accountId": normalized_account_id,
                "amountMinor": amount_minor,
                "currency": normalized_currency,
                "balanceMinor": after_balance,
                "occurredAt": occurred_text,
                "worldRevision": current_world_revision + 1,
            }
            self._store_receipt(
                connection,
                idempotency_key=normalized_key,
                fingerprint=fingerprint,
                operation="record_transaction",
                response=response,
                receipt_id=receipt_id,
            )
            return response

    def upsert_item(
        self,
        agent_id: str,
        *,
        item_id: str,
        category: str,
        name: str,
        brand: str,
        model: str,
        status: str,
        current_location: str,
        acquired_at: str,
        idempotency_key: str,
        expected_world_revision: int,
    ) -> dict[str, Any]:
        normalized_key = self._idempotency_key(idempotency_key)
        normalized_item_id = str(item_id or "").strip()[:160]
        normalized_name = str(name or "").strip()[:160]
        normalized_status = str(status or "active").strip().lower()
        if not normalized_item_id or not normalized_name:
            raise ValueError("Life-world item id and name are required.")
        if normalized_status not in ITEM_STATUSES:
            raise ValueError("Life-world item status is invalid.")
        operation_payload = {
            "itemId": normalized_item_id,
            "category": str(category or "personal").strip()[:80] or "personal",
            "name": normalized_name,
            "brand": str(brand or "").strip()[:120],
            "model": str(model or "").strip()[:120],
            "status": normalized_status,
            "currentLocation": str(current_location or "").strip()[:160],
            "acquiredAt": str(acquired_at or "").strip()[:40],
            "expectedWorldRevision": int(expected_world_revision),
        }
        fingerprint = _fingerprint("upsert_item", operation_payload)
        with self._transaction(agent_id, create=False) as connection:
            replay = self._receipt_replay(connection, normalized_key, fingerprint)
            if replay is not None:
                return replay
            current_world_revision = self._world_revision(connection)
            if current_world_revision <= 0:
                raise LifeWorldError("Life world facts are not confirmed.")
            if int(expected_world_revision) != current_world_revision:
                raise LifeWorldConflictError(
                    "Life-world revision changed before updating the item."
                )
            existing = connection.execute(
                "SELECT item_id, disposed_at FROM items WHERE item_id = ?",
                (normalized_item_id,),
            ).fetchone()
            now_text = _iso(self._now())
            disposed_at = (
                now_text
                if normalized_status == "disposed"
                else ""
            )
            if existing is None:
                connection.execute(
                    "INSERT INTO items (item_id, category, name, brand, model, status, current_location, acquired_at, disposed_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized_item_id,
                        operation_payload["category"],
                        normalized_name,
                        operation_payload["brand"],
                        operation_payload["model"],
                        normalized_status,
                        operation_payload["currentLocation"],
                        operation_payload["acquiredAt"],
                        disposed_at,
                        now_text,
                    ),
                )
                operation = "created"
            else:
                connection.execute(
                    "UPDATE items SET category = ?, name = ?, brand = ?, model = ?, status = ?, current_location = ?, acquired_at = ?, disposed_at = ?, updated_at = ? WHERE item_id = ?",
                    (
                        operation_payload["category"],
                        normalized_name,
                        operation_payload["brand"],
                        operation_payload["model"],
                        normalized_status,
                        operation_payload["currentLocation"],
                        operation_payload["acquiredAt"],
                        disposed_at,
                        now_text,
                        normalized_item_id,
                    ),
                )
                operation = "updated"
            connection.execute(
                "UPDATE world_meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'revision'"
            )
            connection.execute(
                "UPDATE world_meta SET value = ? WHERE key = 'updated_at'",
                (now_text,),
            )
            response = {
                "status": operation,
                "worldRevision": current_world_revision + 1,
                "item": {
                    "itemId": normalized_item_id,
                    "category": operation_payload["category"],
                    "name": normalized_name,
                    "brand": operation_payload["brand"],
                    "model": operation_payload["model"],
                    "status": normalized_status,
                    "currentLocation": operation_payload["currentLocation"],
                    "acquiredAt": operation_payload["acquiredAt"],
                    "disposedAt": disposed_at,
                },
            }
            self._store_receipt(
                connection,
                idempotency_key=normalized_key,
                fingerprint=fingerprint,
                operation="upsert_item",
                response=response,
            )
            return response

    def apply_due_recurring_rules(
        self,
        agent_id: str,
        *,
        local_date: date,
    ) -> dict[str, Any]:
        """Apply each due rule once and advance its durable next-due cursor."""

        if not isinstance(local_date, date):
            raise ValueError("Recurring-rule projection requires a local date.")
        with self._transaction(agent_id, create=False) as connection:
            current_world_revision = self._world_revision(connection)
            if current_world_revision <= 0:
                raise LifeWorldError("Life world facts are not confirmed.")
            rows = connection.execute(
                "SELECT rule_id, kind, account_id, title, amount_minor, currency, frequency, next_due_on, last_applied_on "
                "FROM recurring_rules WHERE status = 'active' AND next_due_on <= ? ORDER BY next_due_on, rule_id",
                (local_date.isoformat(),),
            ).fetchall()
            applied: list[dict[str, Any]] = []
            now_text = _iso(self._now())
            for row in rows:
                try:
                    due_on = date.fromisoformat(str(row["next_due_on"]))
                except ValueError as exc:
                    raise LifeWorldError("Recurring life-world rule has an invalid due date.") from exc
                last_applied_on = str(row["last_applied_on"] or "")
                iterations = 0
                while due_on <= local_date and iterations < 24:
                    iterations += 1
                    due_text = due_on.isoformat()
                    receipt_id = f"life-recurring:{row['rule_id']}:{due_text}"
                    existing = connection.execute(
                        "SELECT transaction_id FROM transactions WHERE receipt_id = ?",
                        (receipt_id,),
                    ).fetchone()
                    account = connection.execute(
                        "SELECT currency, balance_minor FROM accounts WHERE account_id = ? AND status = 'active'",
                        (str(row["account_id"]),),
                    ).fetchone()
                    if account is None:
                        raise LifeWorldError("Recurring life-world account is unavailable.")
                    if str(account["currency"]) != str(row["currency"]):
                        raise LifeWorldError("Recurring rule currency does not match its account.")
                    if existing is None:
                        amount_minor = int(row["amount_minor"])
                        balance_minor = int(account["balance_minor"]) + amount_minor
                        transaction_id = "life-recurring-" + hashlib.sha256(
                            receipt_id.encode("utf-8")
                        ).hexdigest()[:20]
                        connection.execute(
                            "INSERT INTO transactions (transaction_id, account_id, amount_minor, currency, category, description, occurred_at, receipt_id, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                transaction_id,
                                str(row["account_id"]),
                                amount_minor,
                                str(row["currency"]),
                                f"recurring_{str(row['kind']).strip()[:40]}",
                                str(row["title"] or "")[:240],
                                due_text,
                                receipt_id,
                                now_text,
                            ),
                        )
                        connection.execute(
                            "UPDATE accounts SET balance_minor = ?, updated_at = ? WHERE account_id = ?",
                            (balance_minor, now_text, str(row["account_id"])),
                        )
                        applied.append(
                            {
                                "ruleId": str(row["rule_id"]),
                                "transactionId": transaction_id,
                                "accountId": str(row["account_id"]),
                                "amountMinor": amount_minor,
                                "currency": str(row["currency"]),
                                "dueOn": due_text,
                                "balanceMinor": balance_minor,
                            }
                        )
                    last_applied_on = due_text
                    due_on = self._next_recurring_due_date(
                        due_on,
                        str(row["frequency"] or "").strip().lower(),
                    )
                connection.execute(
                    "UPDATE recurring_rules SET next_due_on = ?, last_applied_on = ? WHERE rule_id = ?",
                    (due_on.isoformat(), last_applied_on, str(row["rule_id"])),
                )
            if applied:
                connection.execute(
                    "UPDATE world_meta SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) WHERE key = 'revision'",
                    (len(applied),),
                )
                connection.execute(
                    "UPDATE world_meta SET value = ? WHERE key = 'updated_at'",
                    (now_text,),
                )
            return {
                "localDate": local_date.isoformat(),
                "applied": applied,
                "worldRevision": current_world_revision + len(applied),
            }

    @staticmethod
    def _next_recurring_due_date(current: date, frequency: str) -> date:
        if frequency == "daily":
            return current + timedelta(days=1)
        if frequency == "weekly":
            return current + timedelta(days=7)
        if frequency != "monthly":
            raise LifeWorldError("Recurring life-world frequency is unsupported.")
        month_index = current.month
        year = current.year + month_index // 12
        month = month_index % 12 + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def rollback_confirmation(
        self,
        agent_id: str,
        *,
        draft_id: str,
        confirmation_idempotency_key: str,
        receipt_id: str,
    ) -> None:
        """Compensate a just-confirmed draft when paired provisioning fails."""

        normalized_key = self._idempotency_key(confirmation_idempotency_key)
        with self._transaction(agent_id, create=False) as connection:
            receipt = connection.execute(
                "SELECT receipt_id, operation FROM operation_receipts WHERE idempotency_key = ?",
                (normalized_key,),
            ).fetchone()
            if (
                receipt is None
                or str(receipt["operation"]) != "confirm_draft"
                or str(receipt["receipt_id"]) != str(receipt_id or "").strip()
            ):
                raise LifeWorldConflictError("Life-world confirmation receipt no longer matches rollback.")
            if self._world_revision(connection) != 1:
                raise LifeWorldConflictError("Life-world changed after confirmation and cannot be rolled back.")
            non_opening = connection.execute(
                "SELECT COUNT(*) AS count FROM transactions WHERE category != 'opening_balance'"
            ).fetchone()
            if int(non_opening["count"] if non_opening else 0) != 0:
                raise LifeWorldConflictError("Life-world has later transactions and cannot be rolled back.")
            for table in (
                "recurring_rules",
                "transactions",
                "accounts",
                "items",
                "routines",
                "affiliations",
                "identities",
            ):
                connection.execute(f"DELETE FROM {table}")
            now_text = _iso(self._now())
            connection.execute(
                "UPDATE drafts SET status = 'draft', confirmed_at = '', updated_at = ? WHERE draft_id = ?",
                (now_text, str(draft_id or "").strip()),
            )
            connection.execute("UPDATE world_meta SET value = '0' WHERE key = 'revision'")
            connection.execute(
                "UPDATE world_meta SET value = ? WHERE key = 'updated_at'",
                (now_text,),
            )
            connection.execute(
                "DELETE FROM operation_receipts WHERE idempotency_key = ?",
                (normalized_key,),
            )

    def projection(self, agent_id: str) -> dict[str, Any]:
        path = self.database_path(agent_id)
        if not path.is_file():
            return {
                "schemaVersion": LIFE_WORLD_SCHEMA_VERSION,
                "setupState": "missing",
                "revision": 0,
                "draft": None,
                "facts": self._empty_facts(),
                "updatedAt": "",
            }
        connection = self._connect(agent_id, create=False)
        try:
            revision = self._world_revision(connection)
            draft_row = connection.execute(
                "SELECT draft_id, revision, status, payload_json, created_at, updated_at, confirmed_at "
                "FROM drafts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            draft = self._draft_row(draft_row) if draft_row is not None else None
            setup_state = "ready" if revision > 0 else "draft" if draft else "missing"
            updated_row = connection.execute(
                "SELECT value FROM world_meta WHERE key = 'updated_at'"
            ).fetchone()
            facts = self._facts_projection(connection) if revision > 0 else self._empty_facts()
            return {
                "schemaVersion": LIFE_WORLD_SCHEMA_VERSION,
                "setupState": setup_state,
                "revision": revision,
                "draft": draft,
                "facts": facts,
                "updatedAt": str(updated_row["value"] if updated_row else ""),
            }
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, agent_id: str, *, create: bool) -> Iterator[sqlite3.Connection]:
        connection = self._connect(agent_id, create=create)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self, agent_id: str, *, create: bool) -> sqlite3.Connection:
        path = self.database_path(agent_id)
        if not path.is_file() and not create:
            raise LifeWorldError("Life world database is not initialized.")
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if create:
            self._ensure_schema(connection)
        else:
            self._assert_schema(connection)
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS world_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO world_meta(key, value) VALUES ('schema_version', '1');
            INSERT OR IGNORE INTO world_meta(key, value) VALUES ('revision', '0');
            INSERT OR IGNORE INTO world_meta(key, value) VALUES ('updated_at', '');

            CREATE TABLE IF NOT EXISTS drafts (
                draft_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                status TEXT NOT NULL CHECK (status IN ('draft', 'confirmed', 'superseded')),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS identities (
                identity_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                role_title TEXT NOT NULL,
                stage TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                effective_to TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS affiliations (
                affiliation_id TEXT PRIMARY KEY,
                organization_kind TEXT NOT NULL,
                name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                city_location_id TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                effective_to TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routines (
                routine_id TEXT PRIMARY KEY,
                day_type TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                title TEXT NOT NULL,
                activity_kind TEXT NOT NULL,
                affiliation_id TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                current_location TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                disposed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL,
                currency TEXT NOT NULL CHECK (length(currency) = 3),
                balance_minor INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recurring_rules (
                rule_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                account_id TEXT NOT NULL REFERENCES accounts(account_id),
                title TEXT NOT NULL,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                frequency TEXT NOT NULL,
                next_due_on TEXT NOT NULL,
                status TEXT NOT NULL,
                last_applied_on TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(account_id),
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                receipt_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operation_receipts (
                idempotency_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_account_time
                ON transactions(account_id, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_routines_day_time
                ON routines(day_type, start_time);
            """
        )
        LifeWorldStore._assert_schema(connection)

    @staticmethod
    def _assert_schema(connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute(
                "SELECT value FROM world_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise LifeWorldError("Life world database schema is unavailable.") from exc
        if row is None or int(row["value"]) != LIFE_WORLD_SCHEMA_VERSION:
            raise LifeWorldError("Unsupported life world database schema version.")

    @staticmethod
    def _world_revision(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM world_meta WHERE key = 'revision'"
        ).fetchone()
        return max(0, int(row["value"] if row else 0))

    def _insert_confirmed_facts(
        self,
        connection: sqlite3.Connection,
        *,
        payload: dict[str, Any],
        opening_receipt_id: str,
        now_text: str,
    ) -> None:
        identity = dict(payload["identity"])
        connection.execute(
            "INSERT INTO identities (identity_id, kind, role_title, stage, effective_from, effective_to, source_kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identity["identityId"],
                identity["kind"],
                identity["roleTitle"],
                identity["stage"],
                identity["effectiveFrom"],
                identity.get("effectiveTo", ""),
                identity["sourceKind"],
            ),
        )
        for row in list(payload.get("affiliations") or []):
            connection.execute(
                "INSERT INTO affiliations (affiliation_id, organization_kind, name, department, role, city_location_id, effective_from, effective_to, source_kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["affiliationId"],
                    row["organizationKind"],
                    row["name"],
                    row.get("department", ""),
                    row.get("role", ""),
                    row["cityLocationId"],
                    row["effectiveFrom"],
                    row.get("effectiveTo", ""),
                    row["sourceKind"],
                ),
            )
        for row in list(payload.get("routines") or []):
            connection.execute(
                "INSERT INTO routines (routine_id, day_type, start_time, end_time, title, activity_kind, affiliation_id, timezone) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["routineId"],
                    row["dayType"],
                    row["startTime"],
                    row["endTime"],
                    row["title"],
                    row["activityKind"],
                    row.get("affiliationId", ""),
                    row["timezone"],
                ),
            )
        for row in list(payload.get("items") or []):
            connection.execute(
                "INSERT INTO items (item_id, category, name, brand, model, status, current_location, acquired_at, disposed_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
                (
                    row["itemId"],
                    row["category"],
                    row["name"],
                    row.get("brand", ""),
                    row.get("model", ""),
                    row["status"],
                    row["currentLocation"],
                    row["acquiredAt"],
                    now_text,
                ),
            )
        for row in list(payload.get("accounts") or []):
            connection.execute(
                "INSERT INTO accounts (account_id, name, account_type, currency, balance_minor, status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (
                    row["accountId"],
                    row["name"],
                    row["accountType"],
                    row["currency"],
                    int(row["balanceMinor"]),
                    now_text,
                ),
            )
            transaction_id = f"life-opening-{uuid.uuid4().hex[:16]}"
            connection.execute(
                "INSERT INTO transactions (transaction_id, account_id, amount_minor, currency, category, description, occurred_at, receipt_id, created_at) "
                "VALUES (?, ?, ?, ?, 'opening_balance', '用户确认的虚构初始余额', ?, ?, ?)",
                (
                    transaction_id,
                    row["accountId"],
                    int(row["balanceMinor"]),
                    row["currency"],
                    now_text,
                    f"{opening_receipt_id}:{row['accountId']}",
                    now_text,
                ),
            )
        for row in list(payload.get("recurringRules") or []):
            connection.execute(
                "INSERT INTO recurring_rules (rule_id, kind, account_id, title, amount_minor, currency, frequency, next_due_on, status, last_applied_on) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
                (
                    row["ruleId"],
                    row["kind"],
                    row["accountId"],
                    row["title"],
                    int(row["amountMinor"]),
                    row["currency"],
                    row["frequency"],
                    row["nextDueOn"],
                    row["status"],
                ),
            )

    @staticmethod
    def _draft_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "draftId": str(row["draft_id"]),
            "revision": int(row["revision"]),
            "status": str(row["status"]),
            "payload": json.loads(str(row["payload_json"])),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "confirmedAt": str(row["confirmed_at"]),
        }

    @staticmethod
    def _empty_facts() -> dict[str, list[dict[str, Any]]]:
        return {
            "identities": [],
            "affiliations": [],
            "routines": [],
            "items": [],
            "accounts": [],
            "recurringRules": [],
            "transactions": [],
        }

    @staticmethod
    def _facts_projection(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        return {
            "identities": [
                {
                    "identityId": row["identity_id"],
                    "kind": row["kind"],
                    "roleTitle": row["role_title"],
                    "stage": row["stage"],
                    "effectiveFrom": row["effective_from"],
                    "effectiveTo": row["effective_to"],
                    "sourceKind": row["source_kind"],
                }
                for row in connection.execute("SELECT * FROM identities ORDER BY effective_from, identity_id")
            ],
            "affiliations": [
                {
                    "affiliationId": row["affiliation_id"],
                    "organizationKind": row["organization_kind"],
                    "name": row["name"],
                    "department": row["department"],
                    "role": row["role"],
                    "cityLocationId": row["city_location_id"],
                    "effectiveFrom": row["effective_from"],
                    "effectiveTo": row["effective_to"],
                    "sourceKind": row["source_kind"],
                }
                for row in connection.execute("SELECT * FROM affiliations ORDER BY effective_from, affiliation_id")
            ],
            "routines": [
                {
                    "routineId": row["routine_id"],
                    "dayType": row["day_type"],
                    "startTime": row["start_time"],
                    "endTime": row["end_time"],
                    "title": row["title"],
                    "activityKind": row["activity_kind"],
                    "affiliationId": row["affiliation_id"],
                    "timezone": row["timezone"],
                }
                for row in connection.execute("SELECT * FROM routines ORDER BY day_type, start_time, routine_id")
            ],
            "items": [
                {
                    "itemId": row["item_id"],
                    "category": row["category"],
                    "name": row["name"],
                    "brand": row["brand"],
                    "model": row["model"],
                    "status": row["status"],
                    "currentLocation": row["current_location"],
                    "acquiredAt": row["acquired_at"],
                    "disposedAt": row["disposed_at"],
                }
                for row in connection.execute("SELECT * FROM items ORDER BY category, item_id")
            ],
            "accounts": [
                {
                    "accountId": row["account_id"],
                    "name": row["name"],
                    "accountType": row["account_type"],
                    "currency": row["currency"],
                    "balanceMinor": int(row["balance_minor"]),
                    "status": row["status"],
                }
                for row in connection.execute("SELECT * FROM accounts ORDER BY account_type, account_id")
            ],
            "recurringRules": [
                {
                    "ruleId": row["rule_id"],
                    "kind": row["kind"],
                    "accountId": row["account_id"],
                    "title": row["title"],
                    "amountMinor": int(row["amount_minor"]),
                    "currency": row["currency"],
                    "frequency": row["frequency"],
                    "nextDueOn": row["next_due_on"],
                    "status": row["status"],
                    "lastAppliedOn": row["last_applied_on"],
                }
                for row in connection.execute("SELECT * FROM recurring_rules ORDER BY kind, rule_id")
            ],
            "transactions": [
                {
                    "transactionId": row["transaction_id"],
                    "accountId": row["account_id"],
                    "amountMinor": int(row["amount_minor"]),
                    "currency": row["currency"],
                    "category": row["category"],
                    "description": row["description"],
                    "occurredAt": row["occurred_at"],
                    "receiptId": row["receipt_id"],
                }
                for row in connection.execute("SELECT * FROM transactions ORDER BY occurred_at, transaction_id")
            ],
        }

    @staticmethod
    def _idempotency_key(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("A bounded life-world idempotency key is required.")
        return normalized

    @staticmethod
    def _receipt_replay(
        connection: sqlite3.Connection,
        idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT fingerprint, response_json FROM operation_receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if str(row["fingerprint"]) != fingerprint:
            raise LifeWorldConflictError(
                "Life-world idempotency key was already used for another operation."
            )
        return json.loads(str(row["response_json"]))

    def _store_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        fingerprint: str,
        operation: str,
        response: dict[str, Any],
        receipt_id: str = "",
    ) -> None:
        connection.execute(
            "INSERT INTO operation_receipts (idempotency_key, fingerprint, receipt_id, operation, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                idempotency_key,
                fingerprint,
                receipt_id or f"life-world-receipt-{uuid.uuid4().hex[:16]}",
                operation,
                _json(response),
                _iso(self._now()),
            ),
        )

    def _now(self) -> datetime:
        value = self.now_provider()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _zone(name: str):
        from zoneinfo import ZoneInfo

        return ZoneInfo(str(name or "UTC"))


__all__ = [
    "LIFE_WORLD_SCHEMA_VERSION",
    "LifeWorldConflictError",
    "LifeWorldError",
    "LifeWorldStore",
]
