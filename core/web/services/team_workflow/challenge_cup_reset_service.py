"""Governed Challenge Cup reset contract and orchestration core.

This module deliberately does not discover or mutate the live application
stores by itself.  A reset is a cross-store destructive operation, so the
owner is split into two explicit ports:

* ``ChallengeCupInventoryReader`` is read-only and supplies a bounded object
  inventory, active-work authority, and the other-team protection snapshot.
* ``ChallengeCupDestructiveAdapter`` owns the already-governed lifecycle
  operations (fence, staging, row-level deletion, verification and bootstrap).

The service can therefore produce a deterministic preview with a fake reader,
while an unbound or partial destructive adapter can never pretend to have
completed a purge.  In particular, this file never calls ``unlink``,
``rmtree``, Session lifecycle APIs, or a raw SQLite delete.

The manifest shape is intentionally small.  Object records may contain full
private data in a reader, but only stable identifiers and hashes are returned
from preview; prompts, transcripts and experiment payloads are never copied
into the plan.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


SCHEMA_VERSION = 1
RESET_OPERATION = "challenge_cup_reset"
RESEARCH_TEAM_ID = "research-team"
GOLDEN_SAMPLE_QUESTION_ID = "SCI-096"
GOLDEN_SAMPLE_PROJECT_ID = "challenge-sci-096"
GOLDEN_SAMPLE_BOOTSTRAP_ID = "challenge-cup-golden-sample-sci-096-v1"
CONFIRMATION_PHRASE = "RESET research-team KEEP SCI-096"

# These are role keys, not display names or mutable Agent ids.  The retained
# Agent ids are resolved from the current inventory and must be present before
# a plan may become executable.
RETAINED_AGENT_ROLE_KEYS: tuple[str, ...] = (
    "challenge_cup_search",
    "extractor",
    "knowledge_manager",
    "execution_steward",
    "experiment_revision",
    "evaluator",
)

RETAIN_ALLOWLIST: dict[str, Any] = {
    "teamId": RESEARCH_TEAM_ID,
    "agentRoleKeys": list(RETAINED_AGENT_ROLE_KEYS),
    "catalog": "science_125_questions",
    "program": "competition_program_core",
    "policy": "full_catalog_execution_core",
    "goldenSampleQuestionId": GOLDEN_SAMPLE_QUESTION_ID,
    "goldenSampleProjectId": GOLDEN_SAMPLE_PROJECT_ID,
    "bootstrapId": GOLDEN_SAMPLE_BOOTSTRAP_ID,
}

# A family is considered runtime state unless it is explicitly immutable.  We
# keep this list broad on purpose: an unrecognised team-owned family must enter
# the delete set, rather than being silently forgotten by a new store.
IMMUTABLE_FAMILIES = frozenset(
    {
        "catalog",
        "catalogs",
        "program",
        "programs",
        "policy",
        "policies",
        "immutable_seed",
        "immutable_seeds",
        "seed",
        "seeds",
    }
)
TEAM_FAMILIES = frozenset({"team", "teams"})
AGENT_FAMILIES = frozenset({"agent", "agents"})
SESSION_FAMILIES = frozenset(
    {
        "session",
        "sessions",
        "session_binding",
        "session_bindings",
        "child_session",
        "child_sessions",
        "conversation",
        "conversations",
        "compression_checkpoint",
        "compression_checkpoints",
    }
)
ACTIVE_WORK_STATUSES = frozenset(
    {
        "queued",
        "starting",
        "dispatching",
        "running",
        "stopping",
        "paused",
        "waiting_human",
        "summarizing",
        "awaiting_approval",
        "collecting",
    }
)


class ChallengeCupResetError(RuntimeError):
    """Base error for the governed reset contract."""

    code = "challenge_cup_reset_error"


class ResetInventoryError(ChallengeCupResetError):
    code = "inventory_unavailable"


class ResetValidationError(ChallengeCupResetError):
    code = "invalid_reset_request"


class ResetConfirmationError(ChallengeCupResetError):
    code = "confirmation_required"


class ResetPlanStaleError(ChallengeCupResetError):
    code = "purge_plan_stale"


class ResetBlockedError(ChallengeCupResetError):
    code = "reset_blocked"


class ResetCapabilityError(ChallengeCupResetError):
    code = "destructive_adapter_unbound"


class ResetExecutionError(ChallengeCupResetError):
    code = "reset_execution_failed"


@runtime_checkable
class ChallengeCupInventoryReader(Protocol):
    """Read-only source for a reset preview.

    ``read_inventory`` must return object families under ``objects`` (or the
    family mapping itself), plus ``activeWork`` and
    ``otherTeamProtection``.  Implementations may expose the latter two via
    separate methods instead; the service accepts both forms to ease gradual
    adoption of existing stores.
    """

    def read_inventory(self, team_id: str) -> Mapping[str, Any]: ...


@runtime_checkable
class ChallengeCupDestructiveAdapter(Protocol):
    """Explicit port for the irreversible stages.

    The implementation is expected to reuse existing governed room/session
    reset and row-level storage owners.  The service only invokes methods by
    these names and never supplies arbitrary filesystem paths.
    """

    def lookup_completed(self, purge_plan_id: str) -> Mapping[str, Any] | None: ...

    def fence(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def drain_check(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def stage(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def commit(
        self,
        team_id: str,
        plan: Mapping[str, Any],
        stage: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def verify_zero(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def rebootstrap(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def destroy_staging(
        self,
        team_id: str,
        plan: Mapping[str, Any],
        stage: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ChallengeCupResetInventory:
    """Typed convenience wrapper around the JSON-safe inventory/preview."""

    payload: dict[str, Any]

    @property
    def purge_plan_id(self) -> str:
        return str(self.payload.get("purgePlanId") or "")

    @property
    def inventory_hash(self) -> str:
        return str(self.payload.get("inventoryHash") or "")

    @property
    def safe_to_confirm(self) -> bool:
        return bool(self.payload.get("safeToConfirm"))

    def to_dict(self) -> dict[str, Any]:
        return _clone_json(self.payload)


@dataclass(frozen=True)
class ResetPreview(ChallengeCupResetInventory):
    """Named preview view kept separate from the inventory contract."""


def _clone_json(value: Any) -> Any:
    """Return a JSON-safe detached value for adapter/test boundaries."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, *, upper: bool = False) -> str:
    normalized = str(value or "").strip()
    return normalized.upper() if upper else normalized


def _positive_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).lower() not in {"", "0", "false", "no", "off", "none", "null"}


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return ""


def _family_name(value: Any) -> str:
    raw = _text(value).replace("-", "_").replace(" ", "_")
    raw = re.sub(r"(?<!^)(?=[A-Z])", "_", raw)
    return raw.lower() or "unknown"


def _object_id(family: str, item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, Mapping):
        return ""
    singular = family.rstrip("s")
    return _text(
        _first(
            item,
            "id",
            f"{family}Id",
            f"{singular}Id",
            "objectId",
            "recordId",
            "roomId",
            "projectId",
            "planId",
            "runId",
            "workflowRunId",
            "checkpointId",
            "artifactId",
            "receiptId",
            "sessionId",
            "agentId",
            "teamId",
        )
    )


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Read a small identity field from a record or its scope/config."""

    direct = _first(mapping, *keys)
    if direct:
        return direct
    for container_key in ("scope", "config", "metadata", "binding", "experimentBinding"):
        nested = mapping.get(container_key)
        if isinstance(nested, Mapping):
            value = _first(nested, *keys)
            if value:
                return value
    return ""


def _owner_team_id(item: Any) -> str:
    if not isinstance(item, Mapping):
        return ""
    return _text(
        _nested(
            item,
            "teamId",
            "team_id",
            "ownerTeamId",
            "owner_team_id",
            "researchTeamId",
        )
    )


def _role_key(item: Any) -> str:
    if not isinstance(item, Mapping):
        return ""
    return _text(_nested(item, "roleKey", "role_key", "agentRoleKey", "role"))


def _is_legacy_challenge_item(family: str, item: Any) -> bool:
    if not isinstance(item, Mapping):
        return False
    explicit = _first(
        item,
        "legacyChallenge",
        "legacyChallengeData",
        "challengeCup",
        "challengeCupData",
        "isChallengeCup",
    )
    if _truthy(explicit):
        return True
    source = _text(_nested(item, "source", "sourceKind", "ownerKind", "workflowKind")).lower()
    if any(token in source for token in ("challenge", "hypothesis", "research_workflow")):
        return True
    # The old direct sessions were intentionally attached to the six product
    # roles.  Treating those unscoped rows as legacy challenge data is safe only
    # for the session families and never for arbitrary team-owned records.
    return family in SESSION_FAMILIES and _role_key(item) in RETAINED_AGENT_ROLE_KEYS


def _raw_family_mapping(raw_inventory: Mapping[str, Any]) -> dict[str, list[Any]]:
    raw_objects = raw_inventory.get("objects")
    if raw_objects is None:
        raw_objects = raw_inventory.get("objectFamilies")
    if raw_objects is None:
        # A manifest may use top-level family keys.  Keep control fields out.
        raw_objects = {
            key: value
            for key, value in raw_inventory.items()
            if key not in {"schemaVersion", "activeWork", "otherTeamProtection", "otherTeams"}
        }
    if not isinstance(raw_objects, Mapping):
        raise ResetInventoryError("Reset inventory must contain an object-family mapping.")
    families: dict[str, list[Any]] = {}
    for raw_family, raw_items in raw_objects.items():
        family = _family_name(raw_family)
        if isinstance(raw_items, Mapping):
            # A family can be represented as id -> row in JSON fixtures.
            items = [
                dict(item) if isinstance(item, Mapping) else {"id": key, "value": item}
                for key, item in raw_items.items()
            ]
        elif isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes, bytearray)):
            items = list(raw_items)
        elif raw_items in (None, ""):
            items = []
        else:
            items = [raw_items]
        families.setdefault(family, []).extend(items)
    return families


def _normalize_active_work(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"authorityPresent": False, "activeCount": 0, "items": [], "statuses": {}}
    if isinstance(raw, Mapping):
        payload = dict(raw)
        authority_present = _truthy(payload.get("authorityPresent", True))
        items = payload.get("items") or payload.get("active") or payload.get("runs") or []
        statuses = payload.get("statuses") if isinstance(payload.get("statuses"), Mapping) else {}
        active_count = _positive_count(
            _first(payload, "activeCount", "count", "activeWorkCount")
        )
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        authority_present, items, statuses, active_count = True, list(raw), {}, 0
    else:
        authority_present, items, statuses, active_count = True, [], {}, _positive_count(raw)

    normalized_items: list[dict[str, Any]] = []
    for item in items if isinstance(items, Iterable) and not isinstance(items, (str, bytes, bytearray, Mapping)) else []:
        if isinstance(item, Mapping):
            normalized_items.append(
                {
                    "id": _object_id("work", item),
                    "kind": _text(_first(item, "kind", "family", "type")),
                    "status": _text(_first(item, "status", "state")).lower(),
                }
            )
        else:
            normalized_items.append({"id": _text(item), "kind": "", "status": ""})
    status_counts: dict[str, int] = {}
    for raw_status, raw_count in statuses.items():
        status = _text(raw_status).lower()
        if status:
            status_counts[status] = _positive_count(raw_count)
    active_from_items = sum(1 for item in normalized_items if item["status"] in ACTIVE_WORK_STATUSES)
    active_from_statuses = sum(
        count for status, count in status_counts.items() if status in ACTIVE_WORK_STATUSES
    )
    return {
        "authorityPresent": authority_present,
        "activeCount": max(active_count, active_from_items, active_from_statuses),
        "items": sorted(normalized_items, key=lambda item: (item["kind"], item["id"], item["status"])),
        "statuses": dict(sorted(status_counts.items())),
    }


def _summary_for_protection(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"authorityPresent": False, "snapshot": {}}
    if isinstance(raw, Mapping):
        payload = dict(raw)
        supplied_hash = _text(_first(payload, "hash", "protectionHash", "snapshotHash"))
        snapshot = payload.get("snapshot")
        if snapshot is None:
            snapshot = {
                key: value
                for key, value in payload.items()
                if key not in {"hash", "protectionHash", "snapshotHash", "authorityPresent"}
            }
        authority_present = _truthy(payload.get("authorityPresent", True))
    else:
        supplied_hash, snapshot, authority_present = "", raw, True
    # The supplied hash is accepted as an external authority only when it is a
    # non-empty hex digest.  Otherwise derive a deterministic digest from the
    # bounded reader snapshot.
    if supplied_hash and len(supplied_hash) == 64 and all(c in "0123456789abcdefABCDEF" for c in supplied_hash):
        protection_hash = supplied_hash.lower()
    else:
        protection_hash = _stable_hash(snapshot)
    return {
        "authorityPresent": authority_present,
        "snapshotHash": protection_hash,
        "snapshot": _clone_json(snapshot),
    }


def _adapter_method(adapter: Any, name: str):
    method = getattr(adapter, name, None)
    if not callable(method):
        raise ResetCapabilityError(f"Destructive adapter is missing required method: {name}.")
    return method


def _compact_record(family: str, item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        compact = {
            "id": _object_id(family, item),
            "teamId": _owner_team_id(item),
            "roleKey": _role_key(item),
            "questionId": _text(_nested(item, "questionId", "question_id"), upper=True),
            "projectId": _text(_nested(item, "projectId", "researchProjectId")),
            "immutable": _truthy(_first(item, "immutable", "isImmutable")),
            "recordHash": _stable_hash(item),
        }
    else:
        compact = {
            "id": _object_id(family, item),
            "teamId": "",
            "roleKey": "",
            "questionId": "",
            "projectId": "",
            "immutable": False,
            "recordHash": _stable_hash(item),
        }
    return compact


def _inventory_payload(
    *,
    team_id: str,
    raw_inventory: Mapping[str, Any],
    active_work: Any,
    other_team_protection: Any,
) -> dict[str, Any]:
    families = _raw_family_mapping(raw_inventory)
    normalized_families: dict[str, list[dict[str, Any]]] = {}
    delete_set: dict[str, list[str]] = {}
    retained: dict[str, Any] = {
        "teamId": team_id,
        "agentRoleKeys": list(RETAINED_AGENT_ROLE_KEYS),
        "agents": [],
        "catalog": [],
        "program": [],
        "policy": [],
        "goldenSample": {
            "questionId": GOLDEN_SAMPLE_QUESTION_ID,
            "projectId": GOLDEN_SAMPLE_PROJECT_ID,
            "bootstrapId": GOLDEN_SAMPLE_BOOTSTRAP_ID,
            "status": "initialized",
        },
    }
    blockers: list[dict[str, Any]] = []
    retained_role_keys: set[str] = set()

    for family in sorted(families):
        compact_records: list[dict[str, Any]] = []
        delete_ids: list[str] = []
        for item in families[family]:
            compact = _compact_record(family, item)
            compact_records.append(compact)
            object_id = compact["id"]
            owner = compact["teamId"]
            role_key = compact["roleKey"]
            if not object_id:
                blockers.append({"code": "object_id_missing", "family": family})
                continue

            if family in IMMUTABLE_FAMILIES:
                # Immutable catalog/program/policy/seed definitions are never
                # part of the delete set, regardless of their physical path.
                bucket = "catalog" if "catalog" in family else "program" if "program" in family else "policy"
                retained[bucket].append({"id": object_id, "recordHash": compact["recordHash"]})
                continue
            if family in TEAM_FAMILIES:
                if object_id == team_id or owner == team_id:
                    retained["teamId"] = team_id
                elif owner == team_id:
                    delete_ids.append(object_id)
                continue
            if family in AGENT_FAMILIES:
                if owner == team_id and role_key in RETAINED_AGENT_ROLE_KEYS:
                    retained["agents"].append(
                        {"agentId": object_id, "roleKey": role_key, "recordHash": compact["recordHash"]}
                    )
                    retained_role_keys.add(role_key)
                elif owner == team_id:
                    blockers.append(
                        {
                            "code": "unexpected_team_agent",
                            "family": family,
                            "id": object_id,
                            "roleKey": role_key,
                        }
                    )
                continue

            challenge_owned = owner == team_id or (not owner and _is_legacy_challenge_item(family, item))
            if challenge_owned:
                delete_ids.append(object_id)
            elif not owner and family not in IMMUTABLE_FAMILIES:
                blockers.append(
                    {
                        "code": "unowned_or_unscoped_runtime_object",
                        "family": family,
                        "id": object_id,
                    }
                )
            # Objects owned by another team are intentionally ignored; their
            # count/hash is protected separately and never enters delete_set.

        normalized_families[family] = sorted(
            compact_records,
            key=lambda item: (item["id"], item["recordHash"]),
        )
        if delete_ids:
            delete_set[family] = sorted(set(delete_ids))

    retained["agents"] = sorted(retained["agents"], key=lambda item: (item["roleKey"], item["agentId"]))
    for bucket in ("catalog", "program", "policy"):
        retained[bucket] = sorted(retained[bucket], key=lambda item: item["id"])
    missing_roles = [role for role in RETAINED_AGENT_ROLE_KEYS if role not in retained_role_keys]
    if missing_roles:
        blockers.append({"code": "retained_agent_roles_missing", "roles": missing_roles})
    if not retained["catalog"]:
        blockers.append({"code": "immutable_catalog_missing"})
    if not retained["program"]:
        blockers.append({"code": "immutable_program_or_policy_missing"})

    normalized_active_work = _normalize_active_work(active_work)
    protection = _summary_for_protection(other_team_protection)
    if not normalized_active_work["authorityPresent"]:
        blockers.append({"code": "active_work_authority_missing"})
    if normalized_active_work["activeCount"]:
        blockers.append(
            {
                "code": "active_work_present",
                "activeCount": normalized_active_work["activeCount"],
                "items": normalized_active_work["items"],
            }
        )
    if not protection["authorityPresent"]:
        blockers.append({"code": "other_team_protection_missing"})

    # Inventory hash intentionally includes record hashes and the classified
    # delete/retain sets, but not prompts/transcripts themselves.
    canonical_inventory = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "families": normalized_families,
        "deleteSet": delete_set,
        "retained": retained,
        "activeWork": normalized_active_work,
        "otherTeamProtectionHash": protection["snapshotHash"],
        "blockers": blockers,
    }
    inventory_hash = _stable_hash(canonical_inventory)
    purge_plan_id = _stable_hash(
        {
            "teamId": team_id,
            "allowlist": RETAIN_ALLOWLIST,
            "inventoryHash": inventory_hash,
        }
    )
    impact = {
        "familyCounts": {family: len(ids) for family, ids in sorted(delete_set.items())},
        "deleteObjectCount": sum(len(ids) for ids in delete_set.values()),
        "deleteObjectIds": {family: list(ids) for family, ids in sorted(delete_set.items())},
        "retainedAgentCount": len(retained["agents"]),
        "retainedAgentIds": [item["agentId"] for item in retained["agents"]],
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "operation": RESET_OPERATION,
        "teamId": team_id,
        "retainAllowlist": _clone_json(RETAIN_ALLOWLIST),
        "retained": retained,
        "deleteSet": {family: list(ids) for family, ids in sorted(delete_set.items())},
        "impact": impact,
        "inventoryHash": inventory_hash,
        "purgePlanId": purge_plan_id,
        "activeWork": normalized_active_work,
        "otherTeamProtectionHash": protection["snapshotHash"],
        "otherTeamProtection": {
            "authorityPresent": protection["authorityPresent"],
            "snapshotHash": protection["snapshotHash"],
        },
        "blockers": blockers,
        "safeToConfirm": not blockers,
        "canReset": not blockers,
        "status": "preview_ready" if not blockers else "blocked",
        "destructiveSequence": [
            "PREVIEW",
            "CONFIRM",
            "FENCE",
            "DRAIN",
            "STAGE",
            "COMMIT",
            "VERIFY_ZERO",
            "REBOOTSTRAP",
            "DESTROY_STAGING",
        ],
    }


def _read_inventory_parts(reader: Any, team_id: str) -> tuple[Mapping[str, Any], Any, Any]:
    method = getattr(reader, "read_inventory", None)
    if not callable(method):
        raise ResetInventoryError("Inventory reader is not bound to a read_inventory method.")
    raw_inventory = method(team_id)
    if not isinstance(raw_inventory, Mapping):
        raise ResetInventoryError("Inventory reader returned a non-mapping payload.")
    active_work = raw_inventory.get("activeWork")
    if active_work is None:
        separate = getattr(reader, "read_active_work", None)
        if callable(separate):
            active_work = separate(team_id)
    other_protection = raw_inventory.get("otherTeamProtection")
    if other_protection is None:
        other_protection = raw_inventory.get("otherTeams")
    if other_protection is None:
        separate = getattr(reader, "read_other_team_protection", None)
        if callable(separate):
            other_protection = separate(team_id)
    return raw_inventory, active_work, other_protection


def _validate_team_id(team_id: str) -> str:
    normalized = _text(team_id)
    if normalized != RESEARCH_TEAM_ID:
        raise ResetValidationError(
            f"Challenge Cup reset is restricted to {RESEARCH_TEAM_ID!r}; refusing {normalized!r}."
        )
    return normalized


def _assert_confirmation(confirmation_phrase: str) -> None:
    if str(confirmation_phrase or "") != CONFIRMATION_PHRASE:
        raise ResetConfirmationError(
            f"Exact confirmation phrase required: {CONFIRMATION_PHRASE}"
        )


class ChallengeCupResetService:
    """Preview, confirm and (when explicitly bound) execute a reset plan."""

    def __init__(
        self,
        *,
        inventory_reader: ChallengeCupInventoryReader | Any,
        destructive_adapter: ChallengeCupDestructiveAdapter | Any | None = None,
        code_version: str = "",
    ) -> None:
        self._inventory_reader = inventory_reader
        self._destructive_adapter = destructive_adapter
        self._code_version = _text(code_version)

    def preview(self, team_id: str = RESEARCH_TEAM_ID) -> ResetPreview:
        normalized_team_id = _validate_team_id(team_id)
        raw_inventory, active_work, other_protection = _read_inventory_parts(
            self._inventory_reader, normalized_team_id
        )
        payload = _inventory_payload(
            team_id=normalized_team_id,
            raw_inventory=raw_inventory,
            active_work=active_work,
            other_team_protection=other_protection,
        )
        payload["codeVersion"] = self._code_version
        return ResetPreview(payload)

    def confirm(
        self,
        *,
        purge_plan_id: str,
        confirmation_phrase: str,
        team_id: str = RESEARCH_TEAM_ID,
    ) -> dict[str, Any]:
        """Re-preview and confirm without fencing or changing any state."""

        _assert_confirmation(confirmation_phrase)
        preview = self.preview(team_id)
        expected_plan_id = preview.purge_plan_id
        if _text(purge_plan_id) != expected_plan_id:
            raise ResetPlanStaleError(
                "Inventory changed or purgePlanId does not belong to this preview."
            )
        if not preview.safe_to_confirm:
            raise ResetBlockedError(
                "Reset preview is blocked; resolve all blockers and preview again."
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "operation": RESET_OPERATION,
            "status": "confirmed",
            "teamId": preview.payload["teamId"],
            "purgePlanId": expected_plan_id,
            "inventoryHash": preview.inventory_hash,
            "confirmationPhraseAccepted": True,
            "destructiveStarted": False,
        }

    def execute(
        self,
        *,
        purge_plan_id: str,
        confirmation_phrase: str,
        team_id: str = RESEARCH_TEAM_ID,
    ) -> dict[str, Any]:
        """Run the governed state machine through an explicit adapter.

        The method is intentionally impossible to use with the default
        ``None`` adapter.  It also refuses a changed inventory before fencing,
        checks active work after fencing, and keeps the fence in place when a
        destructive stage fails.
        """

        _assert_confirmation(confirmation_phrase)
        normalized_team_id = _validate_team_id(team_id)
        plan_id = _text(purge_plan_id)
        if not plan_id:
            raise ResetValidationError("purgePlanId is required.")
        adapter = self._destructive_adapter
        if adapter is None:
            raise ResetCapabilityError(
                "No destructive adapter is bound; preview/confirm are available, purge is fail-closed."
            )

        lookup_completed = getattr(adapter, "lookup_completed", None)
        if callable(lookup_completed):
            completed = lookup_completed(plan_id)
            if isinstance(completed, Mapping) and completed:
                result = _clone_json(completed)
                result.setdefault("status", "already_completed")
                result.setdefault("purgePlanId", plan_id)
                return result

        preview = self.preview(normalized_team_id)
        if preview.purge_plan_id != plan_id:
            raise ResetPlanStaleError(
                "Inventory changed since PREVIEW; the old purgePlanId is invalid."
            )
        if not preview.safe_to_confirm:
            raise ResetBlockedError("Reset is blocked by inventory or active-work guards.")
        plan = preview.payload
        steps: list[dict[str, Any]] = [
            {"step": "PREVIEW", "status": "succeeded", "inventoryHash": preview.inventory_hash},
            {"step": "CONFIRM", "status": "succeeded"},
        ]
        fence_result: Mapping[str, Any] | None = None
        stage_result: Mapping[str, Any] | None = None
        try:
            fence_result = _adapter_method(adapter, "fence")(normalized_team_id, plan)
            steps.append({"step": "FENCE", "status": "succeeded", "result": _clone_json(fence_result)})

            drain_result = _adapter_method(adapter, "drain_check")(normalized_team_id, plan)
            normalized_drain = _normalize_active_work(drain_result)
            if not normalized_drain["authorityPresent"] or normalized_drain["activeCount"]:
                steps.append(
                    {
                        "step": "DRAIN",
                        "status": "blocked",
                        "result": _clone_json(normalized_drain),
                    }
                )
                raise ResetBlockedError(
                    "Active Challenge Cup work remains after the maintenance fence; no data was deleted."
                )
            steps.append({"step": "DRAIN", "status": "succeeded", "result": _clone_json(normalized_drain)})

            stage_result = _adapter_method(adapter, "stage")(normalized_team_id, plan)
            steps.append({"step": "STAGE", "status": "succeeded", "result": _clone_json(stage_result)})
            commit_result = _adapter_method(adapter, "commit")(
                normalized_team_id, plan, stage_result
            )
            steps.append({"step": "COMMIT", "status": "succeeded", "result": _clone_json(commit_result)})

            verify_result = _adapter_method(adapter, "verify_zero")(normalized_team_id, plan)
            if not _verify_zero_result(verify_result):
                steps.append({"step": "VERIFY_ZERO", "status": "blocked", "result": _clone_json(verify_result)})
                raise ResetExecutionError("VERIFY_ZERO did not prove that the delete set is empty.")
            steps.append({"step": "VERIFY_ZERO", "status": "succeeded", "result": _clone_json(verify_result)})

            bootstrap_result = _adapter_method(adapter, "rebootstrap")(normalized_team_id, plan)
            if not _verify_bootstrap_result(bootstrap_result):
                steps.append(
                    {"step": "REBOOTSTRAP", "status": "blocked", "result": _clone_json(bootstrap_result)}
                )
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "operation": RESET_OPERATION,
                    "status": "needs_rebootstrap",
                    "teamId": normalized_team_id,
                    "purgePlanId": plan_id,
                    "inventoryHash": preview.inventory_hash,
                    "steps": steps,
                    "stagingDestroyed": False,
                    "irreversible": True,
                }
            steps.append(
                {"step": "REBOOTSTRAP", "status": "succeeded", "result": _clone_json(bootstrap_result)}
            )

            destroy_result = _adapter_method(adapter, "destroy_staging")(
                normalized_team_id, plan, stage_result
            )
            steps.append(
                {"step": "DESTROY_STAGING", "status": "succeeded", "result": _clone_json(destroy_result)}
            )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "operation": RESET_OPERATION,
                "status": "succeeded",
                "teamId": normalized_team_id,
                "purgePlanId": plan_id,
                "inventoryHash": preview.inventory_hash,
                "otherTeamProtectionHash": plan["otherTeamProtectionHash"],
                "steps": steps,
                "stagingDestroyed": True,
                "irreversible": True,
                "audit": {
                    "purgePlanId": plan_id,
                    "inventoryHash": preview.inventory_hash,
                    "deleteObjectCount": plan["impact"]["deleteObjectCount"],
                    "allowlist": _clone_json(RETAIN_ALLOWLIST),
                    "codeVersion": self._code_version,
                },
            }
        except ResetCapabilityError:
            # A partially bound adapter is never converted into a generic
            # success/failure payload: the operator must bind the missing
            # governed port before retrying, while the fence (if any) stays
            # active.
            raise
        except ResetBlockedError:
            # A fence may be intentionally retained so the operator can drain
            # work and preview again.  Do not attempt rollback or unfence here.
            raise
        except Exception as exc:
            if stage_result is not None:
                restore = getattr(adapter, "restore", None)
                if not callable(restore):
                    raise ResetCapabilityError(
                        "Destructive adapter failed after staging and has no restore port; fence remains active."
                    ) from exc
                try:
                    restore_result = restore(normalized_team_id, plan, stage_result)
                    steps.append(
                        {
                            "step": "RESTORE",
                            "status": "succeeded",
                            "result": _clone_json(restore_result),
                        }
                    )
                except Exception as restore_exc:
                    raise ResetExecutionError(
                        "Reset failed and staging restore also failed; fence remains active."
                    ) from restore_exc
            raise ResetExecutionError(
                f"Reset execution failed at {steps[-1].get('step') if steps else 'unknown'}; fence remains active."
            ) from exc


def _verify_zero_result(value: Any) -> bool:
    if value is True:
        return True
    if not isinstance(value, Mapping):
        return False
    if value.get("verified") is False or value.get("zero") is False:
        return False
    if "remainingCount" in value and _positive_count(value.get("remainingCount")) != 0:
        return False
    if "remaining" in value:
        remaining = value.get("remaining")
        if isinstance(remaining, Mapping):
            if any(_positive_count(count) for count in remaining.values()):
                return False
        elif isinstance(remaining, Sequence) and not isinstance(remaining, (str, bytes, bytearray)):
            if remaining:
                return False
    return bool(value.get("verified") or value.get("zero") or value.get("status") in {"verified", "zero"})


def _verify_bootstrap_result(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    project = value.get("project") if isinstance(value.get("project"), Mapping) else value
    project_id = _text(_first(project, "projectId", "id"))
    question_id = _text(_first(project, "questionId", "challengeQuestionId"), upper=True)
    status = _text(_first(project, "status", "state")).lower()
    bootstrap_id = _text(_first(project, "bootstrapId"))
    if project_id != GOLDEN_SAMPLE_PROJECT_ID or question_id != GOLDEN_SAMPLE_QUESTION_ID:
        return False
    if status != "initialized":
        return False
    if bootstrap_id != GOLDEN_SAMPLE_BOOTSTRAP_ID:
        return False
    forbidden_counts = value.get("counts") if isinstance(value.get("counts"), Mapping) else None
    if forbidden_counts is None:
        return False
    forbidden = {
        "plans",
        "runs",
        "results",
        "rooms",
        "checkpoints",
        "artifacts",
        "receipts",
        "candidates",
        "selections",
        "meetings",
        "rounds",
        "legacyParticipantBindings",
    }
    return all(key in forbidden_counts and _positive_count(forbidden_counts.get(key)) == 0 for key in forbidden)


class ManifestInventoryReader:
    """Read a JSON inventory manifest without mutating the project.

    This is useful for temporary fixture roots and for the future canonical
    project-data-home adapter.  It intentionally accepts an explicit path and
    never walks or deletes a live directory implicitly.
    """

    def __init__(self, manifest_path: Path | str) -> None:
        self.manifest_path = Path(manifest_path)

    def read_inventory(self, team_id: str) -> Mapping[str, Any]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResetInventoryError(f"Unable to read reset inventory manifest: {self.manifest_path}") from exc
        if not isinstance(payload, Mapping):
            raise ResetInventoryError("Reset inventory manifest must contain a JSON object.")
        declared_team_id = _text(payload.get("teamId"))
        if declared_team_id and declared_team_id != team_id:
            raise ResetInventoryError("Inventory manifest belongs to another team.")
        return payload


def preview_challenge_cup_reset(
    inventory_reader: ChallengeCupInventoryReader | Any,
    *,
    team_id: str = RESEARCH_TEAM_ID,
    code_version: str = "",
) -> dict[str, Any]:
    """Functional preview entry point for route/service integration."""

    return ChallengeCupResetService(
        inventory_reader=inventory_reader,
        code_version=code_version,
    ).preview(team_id).to_dict()


def confirm_challenge_cup_reset(
    inventory_reader: ChallengeCupInventoryReader | Any,
    *,
    purge_plan_id: str,
    confirmation_phrase: str,
    team_id: str = RESEARCH_TEAM_ID,
    code_version: str = "",
) -> dict[str, Any]:
    """Functional confirmation entry point; this remains non-destructive."""

    return ChallengeCupResetService(
        inventory_reader=inventory_reader,
        code_version=code_version,
    ).confirm(
        purge_plan_id=purge_plan_id,
        confirmation_phrase=confirmation_phrase,
        team_id=team_id,
    )


def execute_challenge_cup_reset(
    inventory_reader: ChallengeCupInventoryReader | Any,
    destructive_adapter: ChallengeCupDestructiveAdapter | Any | None,
    *,
    purge_plan_id: str,
    confirmation_phrase: str,
    team_id: str = RESEARCH_TEAM_ID,
    code_version: str = "",
) -> dict[str, Any]:
    """Functional execute entry point; no adapter means fail-closed."""

    return ChallengeCupResetService(
        inventory_reader=inventory_reader,
        destructive_adapter=destructive_adapter,
        code_version=code_version,
    ).execute(
        purge_plan_id=purge_plan_id,
        confirmation_phrase=confirmation_phrase,
        team_id=team_id,
    )


__all__ = [
    "ChallengeCupDestructiveAdapter",
    "ChallengeCupInventoryReader",
    "ChallengeCupResetInventory",
    "ChallengeCupResetError",
    "ChallengeCupResetService",
    "CONFIRMATION_PHRASE",
    "GOLDEN_SAMPLE_BOOTSTRAP_ID",
    "GOLDEN_SAMPLE_PROJECT_ID",
    "GOLDEN_SAMPLE_QUESTION_ID",
    "ManifestInventoryReader",
    "RESEARCH_TEAM_ID",
    "RETAINED_AGENT_ROLE_KEYS",
    "RETAIN_ALLOWLIST",
    "ResetBlockedError",
    "ResetCapabilityError",
    "ResetConfirmationError",
    "ResetExecutionError",
    "ResetInventoryError",
    "ResetPlanStaleError",
    "ResetPreview",
    "ResetValidationError",
    "confirm_challenge_cup_reset",
    "execute_challenge_cup_reset",
    "preview_challenge_cup_reset",
]
