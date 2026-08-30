from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.agent_plugins.virtual_human_life.geography import (
    derive_environment_context,
    list_city_locations,
    resolve_city_location,
)
from core.agent_plugins.virtual_human_life.life_world_store import (
    LifeWorldConflictError,
    LifeWorldStore,
)
from core.agent_plugins.virtual_human_life.planning import build_deterministic_schedule
from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore


NOW = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)


def _world(tmp_path: Path) -> LifeWorldStore:
    plugin_store = VirtualHumanLifeStore(
        tmp_path,
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
    )
    return LifeWorldStore(plugin_store, now_provider=lambda: NOW)


def test_city_catalog_resolves_canonical_city_anchor_without_gps_or_address() -> None:
    catalog = list_city_locations()
    shanghai = resolve_city_location("CN-SHANGHAI")

    assert any(row["locationId"] == "CN-SHANGHAI" for row in catalog)
    assert shanghai == {
        "locationId": "CN-SHANGHAI",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "SH",
        "regionName": "上海",
        "cityCode": "SHA",
        "cityName": "上海",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 31.2304,
        "longitude": 121.4737,
        "precision": "city_center",
        "sourceKind": "builtin_city_catalog",
        "sourceVersion": "2026.08",
    }
    assert "gps" not in {str(key).lower() for key in shanghai}
    assert "address" not in {str(key).lower() for key in shanghai}

    context = derive_environment_context(shanghai, at=NOW)
    assert context["localDate"] == "2026-08-30"
    assert context["localTime"] == "10:00"
    assert context["season"] == "summer"
    assert context["dayPeriod"] == "morning"
    assert context["weather"] is None
    assert context["externalFactsStatus"] == "source_required"

    with pytest.raises(ValueError, match="Unsupported city location"):
        resolve_city_location("CN-UNKNOWN")


def test_life_world_draft_is_not_fact_until_confirmed_and_is_agent_scoped(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    shanghai = resolve_city_location("CN-SHANGHAI")

    draft = world.create_or_get_draft(
        "agent-a",
        home_location=shanghai,
        identity_kind="student",
        idempotency_key="draft-agent-a",
    )

    assert draft["status"] == "draft"
    assert draft["revision"] == 1
    assert draft["payload"]["identity"]["kind"] == "student"
    assert draft["payload"]["affiliations"][0]["organizationKind"] == "school"
    assert draft["payload"]["routines"]
    assert draft["payload"]["items"]
    assert draft["payload"]["accounts"]
    assert draft["payload"]["recurringRules"]

    before = world.projection("agent-a")
    assert before["setupState"] == "draft"
    assert before["draft"]["draftId"] == draft["draftId"]
    assert before["facts"] == {
        "identities": [],
        "affiliations": [],
        "routines": [],
        "items": [],
        "accounts": [],
        "recurringRules": [],
        "transactions": [],
    }
    assert world.projection("agent-b")["setupState"] == "missing"
    assert world.database_path("agent-a") != world.database_path("agent-b")

    updated = world.update_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=1,
        patch={
            "identity": {"roleTitle": "视觉设计专业学生"},
            "affiliations": [{"name": "栖光艺术学院"}],
        },
        idempotency_key="draft-agent-a-edit-1",
    )
    assert updated["revision"] == 2
    assert updated["payload"]["identity"]["roleTitle"] == "视觉设计专业学生"
    assert updated["payload"]["affiliations"][0]["name"] == "栖光艺术学院"

    confirmed = world.confirm_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=2,
        idempotency_key="confirm-agent-a",
    )
    replay = world.confirm_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=2,
        idempotency_key="confirm-agent-a",
    )
    after = world.projection("agent-a")

    assert confirmed == replay
    assert confirmed["status"] == "confirmed"
    assert confirmed["receiptId"]
    assert after["setupState"] == "ready"
    assert after["revision"] == 1
    assert after["facts"]["identities"][0]["kind"] == "student"
    assert after["facts"]["identities"][0]["roleTitle"] == "视觉设计专业学生"
    assert after["facts"]["affiliations"][0]["name"] == "栖光艺术学院"
    assert len(after["facts"]["transactions"]) == len(after["facts"]["accounts"])
    assert all(row["currency"] == "CNY" for row in after["facts"]["accounts"])


def test_unconfirmed_draft_reanchors_but_confirmed_world_requires_relocation(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    first = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-SHANGHAI"),
        identity_kind="student",
        idempotency_key="draft-shanghai-student",
    )

    replacement = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-BEIJING"),
        identity_kind="employee",
        idempotency_key="draft-beijing-employee",
    )

    assert replacement["draftId"] != first["draftId"]
    assert replacement["payload"]["homeLocation"]["locationId"] == "CN-BEIJING"
    assert replacement["payload"]["identity"]["kind"] == "employee"
    assert world.projection("agent-a")["draft"]["draftId"] == replacement["draftId"]

    world.confirm_draft(
        "agent-a",
        draft_id=replacement["draftId"],
        expected_revision=replacement["revision"],
        idempotency_key="confirm-beijing-employee",
    )

    with pytest.raises(LifeWorldConflictError, match="relocation"):
        world.create_or_get_draft(
            "agent-a",
            home_location=resolve_city_location("CN-SHANGHAI"),
            identity_kind="student",
            idempotency_key="draft-after-confirmation",
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"routines": [{"startTime": "99:00"}]},
        {"recurringRules": [{"frequency": "whenever"}]},
        {"recurringRules": [{"nextDueOn": "not-a-date"}]},
    ],
)
def test_life_world_draft_rejects_invalid_time_and_recurring_rules(
    tmp_path: Path,
    patch: dict,
) -> None:
    world = _world(tmp_path)
    draft = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-SHANGHAI"),
        identity_kind="employee",
        idempotency_key="draft-validation",
    )

    with pytest.raises(ValueError):
        world.update_draft(
            "agent-a",
            draft_id=draft["draftId"],
            expected_revision=draft["revision"],
            patch=patch,
            idempotency_key=f"invalid-draft-{next(iter(patch))}-{patch}",
        )

    assert world.projection("agent-a")["draft"]["revision"] == draft["revision"]


def test_life_world_transaction_is_integer_currency_safe_and_idempotent(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    draft = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-SHANGHAI"),
        identity_kind="employee",
        idempotency_key="draft-employee",
    )
    world.confirm_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=draft["revision"],
        idempotency_key="confirm-employee",
    )
    account = world.projection("agent-a")["facts"]["accounts"][0]
    before_balance = account["balanceMinor"]

    first = world.record_transaction(
        "agent-a",
        account_id=account["accountId"],
        amount_minor=-1250,
        currency="CNY",
        category="meal",
        description="午餐",
        occurred_at="2026-08-30T04:00:00+00:00",
        idempotency_key="meal-20260830",
    )
    replay = world.record_transaction(
        "agent-a",
        account_id=account["accountId"],
        amount_minor=-1250,
        currency="CNY",
        category="meal",
        description="午餐",
        occurred_at="2026-08-30T04:00:00+00:00",
        idempotency_key="meal-20260830",
    )

    assert first == replay
    assert first["balanceMinor"] == before_balance - 1250
    assert len(world.projection("agent-a")["facts"]["transactions"]) == 3

    with pytest.raises(LifeWorldConflictError, match="another operation"):
        world.record_transaction(
            "agent-a",
            account_id=account["accountId"],
            amount_minor=-1300,
            currency="CNY",
            category="meal",
            description="不同金额",
            occurred_at="2026-08-30T04:00:00+00:00",
            idempotency_key="meal-20260830",
        )
    with pytest.raises(ValueError, match="currency"):
        world.record_transaction(
            "agent-a",
            account_id=account["accountId"],
            amount_minor=-1250,
            currency="USD",
            category="meal",
            description="错误币种",
            occurred_at="2026-08-30T04:00:00+00:00",
            idempotency_key="meal-wrong-currency",
        )


def test_due_recurring_income_and_expense_apply_once_per_due_date(tmp_path: Path) -> None:
    world = _world(tmp_path)
    draft = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-SHANGHAI"),
        identity_kind="employee",
        idempotency_key="draft-recurring",
    )
    world.confirm_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=draft["revision"],
        idempotency_key="confirm-recurring",
    )
    before = world.projection("agent-a")
    bank_before = next(
        row["balanceMinor"]
        for row in before["facts"]["accounts"]
        if row["accountType"] == "bank"
    )
    net_monthly = sum(
        row["amountMinor"] for row in before["facts"]["recurringRules"]
    )

    first = world.apply_due_recurring_rules("agent-a", local_date=date(2026, 8, 30))
    replay = world.apply_due_recurring_rules("agent-a", local_date=date(2026, 8, 30))
    after = world.projection("agent-a")
    bank_after = next(
        row["balanceMinor"]
        for row in after["facts"]["accounts"]
        if row["accountType"] == "bank"
    )

    assert len(first["applied"]) == 2
    assert replay["applied"] == []
    assert bank_after == bank_before + net_monthly
    assert all(
        row["lastAppliedOn"] == "2026-08-01"
        and row["nextDueOn"] == "2026-09-01"
        for row in after["facts"]["recurringRules"]
    )
    recurring_transactions = [
        row
        for row in after["facts"]["transactions"]
        if row["category"].startswith("recurring_")
    ]
    assert len(recurring_transactions) == 2


@pytest.mark.parametrize(
    ("identity_kind", "expected_title"),
    [
        ("student", "上课"),
        ("employee", "上班"),
        ("freelancer", "自由职业项目"),
        ("unemployed", "求职与个人安排"),
        ("retired", "退休生活安排"),
    ],
)
def test_identity_profile_changes_deterministic_schedule(
    tmp_path: Path,
    identity_kind: str,
    expected_title: str,
) -> None:
    world = _world(tmp_path)
    draft = world.create_or_get_draft(
        "agent-a",
        home_location=resolve_city_location("CN-SHANGHAI"),
        identity_kind=identity_kind,
        idempotency_key=f"draft-{identity_kind}",
    )
    world.confirm_draft(
        "agent-a",
        draft_id=draft["draftId"],
        expected_revision=draft["revision"],
        idempotency_key=f"confirm-{identity_kind}",
    )
    schedule = build_deterministic_schedule(
        "agent-a",
        date(2026, 8, 31),
        timezone_name="Asia/Shanghai",
        zone=ZoneInfo("Asia/Shanghai"),
        now=NOW,
        life_world=world.projection("agent-a"),
    )

    assert any(expected_title in row["title"] for row in schedule["activities"])
    assert schedule["identityConstraint"]["kind"] == identity_kind
