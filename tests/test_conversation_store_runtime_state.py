"""Runtime-state payload vs session directory repair contracts.

Covers the 2026-10-20 incident shape: a session whose runtime payload was
sealed by an archived Agent (archive_state.status=archived,
source=agent_archive) while the sessions directory row was rebound to a
different Agent. The store must re-seal and re-bind the row to the
payload-proven Agent at open, the bridge must repair only proven splits, and
the explicit CAS repair must refuse guarded rows.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store import database as store_database


def _safe_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_database.sqlite3, "sqlite_version_info", (3, 51, 3))


@pytest.fixture
def store(tmp_path, monkeypatch):
    _safe_sqlite(monkeypatch)
    value = ConversationStore(tmp_path / "conversations.sqlite3")
    value.open()
    for agent_id in ("old", "repaired"):
        revision = value.repository.create_agent(
            agent_id=agent_id, display_name=agent_id, kind="assistant", config={}, source="test",
        ).result(timeout=5)["configRevisionId"]
        if agent_id == "old":
            value.repository.create_session(
                session_id="history", agent_id=agent_id,
                agent_config_revision_id=revision, title="History",
            ).result(timeout=5)
    yield value
    value.close()


def archived_payload():
    return {
        "conversation_id": "history", "agent_id": "repaired", "title": "History",
        "archive_state": {"status": "archived", "source": "agent_archive", "agentId": "repaired"},
        "hidden_from_index": True, "read_only": True,
        "conversation_index_kind": "hidden", "conversation_index_visibility": "hidden",
    }


def directory_row(store):
    with sqlite3.connect(store.database.path) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM sessions WHERE session_id='history'").fetchone())


def test_startup_self_heal_rebinds_split_owner_to_payload_agent(tmp_path, monkeypatch):
    """Incident shape: payload sealed by Agent A, directory row bound to Agent B.

    One reopen re-seals the row and rebinds the owner to the payload-proven
    Agent; the second reopen rewrites nothing (idempotent).
    """

    _safe_sqlite(monkeypatch)
    db_path = tmp_path / "conversations.sqlite3"
    seed = ConversationStore(db_path)
    seed.open()
    try:
        for agent_id in ("old", "repaired"):
            seed.repository.create_agent(
                agent_id=agent_id, display_name=agent_id, kind="assistant",
                config={}, source="test",
            ).result(timeout=5)
        revision = seed.repository.get_agent("old")["currentConfigRevisionId"]
        seed.repository.create_session(
            session_id="history", agent_id="old",
            agent_config_revision_id=revision, title="History",
        ).result(timeout=5)
        seed.repository.upsert_session_runtime_state(
            "history", archived_payload(),
        ).result(timeout=5)
        assert directory_row(seed)["agent_id"] == "old"
    finally:
        seed.close()

    reopened = ConversationStore(db_path)
    reopened.open()
    try:
        row = directory_row(reopened)
        assert row["agent_id"] == "repaired"
        assert row["archived_at_ms"] is not None
        assert row["agent_config_revision_id"] == (
            reopened.repository.get_agent("repaired")["currentConfigRevisionId"]
        )
        visible = reopened.repository.get_session("history")
        assert visible is None  # sealed rows stay out of the live directory get()
        archived_view = reopened.repository.get_session("history", include_archived=True)
        assert archived_view is not None and archived_view["agentId"] == "repaired"
    finally:
        reopened.close()

    third = ConversationStore(db_path)
    third.open()
    try:
        after = directory_row(third)
        assert after["agent_id"] == "repaired"
        assert after["archived_at_ms"] == row["archived_at_ms"]
        assert after["updated_at_ms"] == row["updated_at_ms"]
    finally:
        third.close()


def test_startup_owner_rebind_keeps_guarded_rows_sealed_only(store, monkeypatch):
    db_path = store.database.path
    with sqlite3.connect(db_path) as connection:
        old_revision = connection.execute(
            "SELECT current_config_revision_id FROM agents WHERE agent_id='old'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO session_admissions (session_id, client_submission_id, turn_id, "
            "agent_id, agent_config_revision_id, state, created_at_ms, updated_at_ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("history", "submission", "turn", "old", old_revision, "reserved", 1, 1),
        )
    store.repository.upsert_session_runtime_state("history", archived_payload()).result(timeout=5)
    store.close()

    monkeypatch.setattr(store_database.sqlite3, "sqlite_version_info", (3, 51, 3))
    reopened = ConversationStore(db_path)
    reopened.open()
    try:
        row = directory_row(reopened)
        assert row["agent_id"] == "old"  # active admission blocks the rebind
        assert row["archived_at_ms"] is not None  # seal repair still applies
    finally:
        reopened.close()


def test_startup_owner_rebind_requires_canonical_seal_agent(tmp_path, monkeypatch):
    """A seal without a matching seal agentId proves visibility, not ownership."""

    _safe_sqlite(monkeypatch)
    db_path = tmp_path / "conversations.sqlite3"
    seed = ConversationStore(db_path)
    seed.open()
    try:
        for agent_id in ("old", "repaired"):
            seed.repository.create_agent(
                agent_id=agent_id, display_name=agent_id, kind="assistant",
                config={}, source="test",
            ).result(timeout=5)
        revision = seed.repository.get_agent("old")["currentConfigRevisionId"]
        seed.repository.create_session(
            session_id="history", agent_id="old",
            agent_config_revision_id=revision, title="History",
        ).result(timeout=5)
        payload = archived_payload()
        del payload["archive_state"]["agentId"]
        seed.repository.upsert_session_runtime_state("history", payload).result(timeout=5)
    finally:
        seed.close()

    reopened = ConversationStore(db_path)
    reopened.open()
    try:
        row = directory_row(reopened)
        assert row["agent_id"] == "old"
        assert row["archived_at_ms"] is not None
    finally:
        reopened.close()


def test_get_session_include_archived_reads_sealed_rows(store):
    store.repository.upsert_session_runtime_state("history", archived_payload()).result(timeout=5)
    revision = store.repository.get_agent("old")["currentConfigRevisionId"]
    store.repository.upsert_directory_session(
        session_id="history", agent_id="old", agent_config_revision_id=revision,
        title="History", hidden_from_index=True, archived=True,
    ).result(timeout=5)
    assert store.repository.get_session("history") is None
    sealed = store.repository.get_session("history", include_archived=True)
    assert sealed is not None and sealed["agentId"] == "old"


@pytest.mark.parametrize("provenance", [True, False])
def test_bridge_repairs_only_proven_legacy_owner_and_reports_failure(store, monkeypatch, provenance):
    from types import SimpleNamespace
    from core.web.services.session import directory_bridge, directory_runtime

    payload = archived_payload()
    store.repository.upsert_session_runtime_state("history", payload).result(timeout=5)
    revision = store.repository.get_agent("repaired")["currentConfigRevisionId"]
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: store)
    monkeypatch.setattr(directory_bridge, "_ensure_agent_revision", lambda *_: revision)
    agent = {"createdBy": "session_repair" if provenance else "user", "directSessionId": "history"}
    monkeypatch.setattr(directory_bridge, "_service", lambda: SimpleNamespace(get_agent=lambda *_args, **_kwargs: agent))
    events = []
    monkeypatch.setattr(directory_runtime, "_record", lambda event, **kwargs: events.append((event, kwargs)))
    directory_bridge.sync_conversation_record(payload, touch_recency=False)
    assert directory_row(store)["agent_id"] == ("repaired" if provenance else "old")
    assert events[0][0] == ("session_directory.owner.repaired" if provenance else "session_directory.sync.failed")
    if provenance:
        assert directory_row(store)["archived_at_ms"] is not None


def test_explicit_archived_owner_repair_checks_canonical_seal_and_expected_owner(store):
    store.repository.upsert_session_runtime_state("history", archived_payload()).result(timeout=5)
    revision = store.repository.get_agent("repaired")["currentConfigRevisionId"]
    result = store.repository.repair_archived_directory_owner(
        session_id="history", expected_agent_id="old", agent_id="repaired",
        agent_config_revision_id=revision,
    ).result(timeout=5)
    assert result["action"] == "repaired"
    assert directory_row(store)["agent_id"] == "repaired"
    assert directory_row(store)["archived_at_ms"] is not None
    with pytest.raises(ValueError, match="changed before repair"):
        store.repository.repair_archived_directory_owner(
            session_id="history", expected_agent_id="old", agent_id="repaired",
            agent_config_revision_id=revision,
        ).result(timeout=5)


def test_owner_repair_rejects_live_or_related_sessions(store):
    revision_old = store.repository.get_agent("old")["currentConfigRevisionId"]
    revision = store.repository.get_agent("repaired")["currentConfigRevisionId"]
    arguments = dict(session_id="history", expected_agent_id="old", agent_id="repaired",
                     agent_config_revision_id=revision)
    with pytest.raises(ValueError, match="current Agent archive seal"):
        store.repository.repair_archived_directory_owner(**arguments).result(timeout=5)
    store.repository.create_session(
        session_id="child", parent_session_id="history", agent_id="old",
        agent_config_revision_id=revision_old, title="Child",
    ).result(timeout=5)
    store.repository.upsert_session_runtime_state("history", archived_payload()).result(timeout=5)
    with pytest.raises(ValueError, match="session family"):
        store.repository.repair_archived_directory_owner(**arguments).result(timeout=5)
    assert directory_row(store)["agent_id"] == "old"


@pytest.mark.parametrize("state", ["reserved", "journaled", "projected"])
def test_owner_repair_preserves_historical_admission_identity_and_rejects_active_admissions(store, state):
    old_revision = store.repository.get_agent("old")["currentConfigRevisionId"]
    revision = store.repository.get_agent("repaired")["currentConfigRevisionId"]
    with sqlite3.connect(store.database.path) as connection:
        connection.execute(
            "INSERT INTO session_admissions (session_id, client_submission_id, turn_id, agent_id, "
            "agent_config_revision_id, state, created_at_ms, updated_at_ms) VALUES (?,?,?,?,?,?,?,?)",
            ("history", "submission", "turn", "old", old_revision, state, 1, 1),
        )
    store.repository.upsert_session_runtime_state("history", archived_payload()).result(timeout=5)
    future = store.repository.repair_archived_directory_owner(
        session_id="history", expected_agent_id="old", agent_id="repaired",
        agent_config_revision_id=revision,
    )
    if state == "projected":
        assert future.result(timeout=5)["action"] == "repaired"
    else:
        with pytest.raises(ValueError, match="active admission"):
            future.result(timeout=5)
    with sqlite3.connect(store.database.path) as connection:
        assert connection.execute(
            "SELECT agent_id, agent_config_revision_id, state FROM session_admissions"
        ).fetchone() == ("old", old_revision, state)
