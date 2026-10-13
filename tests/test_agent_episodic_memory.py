from contextlib import contextmanager
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from threading import Event, Thread

import pytest

from core.web.services import agent_directory_service
from core.web.services.agent_directory import episodic_memory as episodic_memory_mod


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)


def _make_agent():
    return agent_directory_service.create_agent_instance(display_name="Episode Agent")


def _policy_path(agent_id: str, key: str) -> Path:
    policy = agent_directory_service.resolve_memory_policy_for_agent(agent_id)
    return agent_directory_service._resolve_project_path(str(policy.get(key) or ""))


def _jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_from_child_process(
    project_root: str,
    agent_id: str,
    lock_attempted,
    finished,
    errors,
) -> None:
    import os

    os.environ["VIBELUTION_DATA_HOME"] = project_root
    agent_directory_service.PROJECT_ROOT = Path(project_root)
    original_lock = episodic_memory_mod.cross_process_file_lock

    @contextmanager
    def signal_lock_attempt(*args, **kwargs):
        lock_attempted.set()
        with original_lock(*args, **kwargs):
            yield

    episodic_memory_mod.cross_process_file_lock = signal_lock_attempt
    try:
        agent_directory_service.append_episodic_event(
            agent_id, kind="note", text="child process append"
        )
    except Exception as exc:  # pragma: no cover - reported to parent process
        errors.put(repr(exc))
    finally:
        finished.set()


def test_append_writes_policy_path_and_not_derived_or_public_stores(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]

    event = agent_directory_service.append_episodic_event(
        agent_id,
        kind="preference",
        text="Prefer focused pytest over full suite.",
        refs=[{"type": "session", "id": "session-demo"}],
    )

    episode_path = _policy_path(agent_id, "episodicEventsPath")
    assert episode_path.exists()
    assert event["episodeId"]
    assert event["kind"] == "preference"
    assert event["validUntil"] == ""
    assert event["refs"] == [{"type": "session", "id": "session-demo"}]
    assert len(_jsonl_lines(episode_path)) == 1

    summaries_path = _policy_path(agent_id, "summariesPath")
    proposals_path = _policy_path(agent_id, "projectMemoryUpdatesPath")
    assert not summaries_path.exists()
    assert not proposals_path.exists()
    assert not (tmp_path / "workspace" / "knowledge" / "public").exists()


def test_supersede_keeps_jsonl_line_and_drops_from_current_list(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    first = agent_directory_service.append_episodic_event(
        agent_id,
        kind="session_fact",
        text="Old fact",
        occurred_at="2026-08-15T01:00:00+00:00",
    )
    second = agent_directory_service.append_episodic_event(
        agent_id,
        kind="note",
        text="Replacement note",
        occurred_at="2026-08-15T02:00:00+00:00",
    )

    superseded = agent_directory_service.supersede_episodic_event(
        agent_id,
        first["episodeId"],
        successor_episode_id=second["episodeId"],
    )

    episode_path = _policy_path(agent_id, "episodicEventsPath")
    assert len(_jsonl_lines(episode_path)) == 2
    assert superseded["validUntil"]
    assert superseded["supersededByEpisodeId"] == second["episodeId"]

    current = agent_directory_service.list_current_episodic_events(agent_id)
    assert [item["episodeId"] for item in current] == [second["episodeId"]]
    assert current[0]["text"] == "Replacement note"


def test_transaction_lists_full_history_and_commits_replacement_as_one_change(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    first = agent_directory_service.append_episodic_event(agent_id, text="old preference")

    with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
        assert [item["episodeId"] for item in transaction.events] == [first["episodeId"]]
        replacement = transaction.append(
            kind="preference", text="replacement preference", refs=[]
        )
        superseded = transaction.supersede(
            first["episodeId"], successor_episode_id=replacement["episodeId"]
        )

    assert superseded["supersededByEpisodeId"] == replacement["episodeId"]
    assert [item["episodeId"] for item in episodic_memory_mod.list_episodic_events(agent_id)] == [
        replacement["episodeId"]
    ]
    history = episodic_memory_mod.list_episodic_events(
        agent_id, include_superseded=True
    )
    assert {item["episodeId"] for item in history} == {
        first["episodeId"],
        replacement["episodeId"],
    }


def test_transaction_serializes_competing_threads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    holder_inside = Event()
    release_holder = Event()
    contender_attempted = Event()
    contender_inside = Event()
    errors: list[BaseException] = []

    def hold_transaction():
        try:
            with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
                transaction.append(kind="note", text="held thread append")
                holder_inside.set()
                if not release_holder.wait(10):
                    raise TimeoutError("holder release timed out")
        except BaseException as exc:  # surfaced in the test thread
            errors.append(exc)

    def append_contender():
        try:
            contender_attempted.set()
            with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
                contender_inside.set()
                transaction.append(kind="note", text="contending thread append")
        except BaseException as exc:  # surfaced in the test thread
            errors.append(exc)

    holder = Thread(target=hold_transaction)
    contender = None
    holder.start()
    try:
        assert holder_inside.wait(5)
        contender = Thread(target=append_contender)
        contender.start()
        assert contender_attempted.wait(5)
        assert not contender_inside.wait(0.1)
    finally:
        release_holder.set()
    holder.join(10)
    if contender is not None:
        contender.join(10)

    assert not holder.is_alive()
    assert contender is not None and not contender.is_alive()
    assert errors == []
    assert {item["text"] for item in agent_directory_service.list_current_episodic_events(agent_id)} == {
        "held thread append",
        "contending thread append",
    }


def test_transaction_serializes_a_cross_process_append(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    process_context = get_context("spawn")
    lock_attempted = process_context.Event()
    finished = process_context.Event()
    errors = process_context.Queue()
    child = process_context.Process(
        target=_append_from_child_process,
        args=(str(tmp_path), agent_id, lock_attempted, finished, errors),
    )

    child_started = False
    try:
        with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
            transaction.append(kind="note", text="parent transaction append")
            child.start()
            child_started = True
            assert lock_attempted.wait(10)
            assert not finished.wait(0.1)
    finally:
        if child_started:
            child.join(15)
            if child.is_alive():
                child.terminate()
                child.join(5)

    assert not child.is_alive()
    assert child.exitcode == 0
    assert finished.is_set()
    try:
        error = errors.get(timeout=1)
    except Empty:
        error = None
    finally:
        errors.close()
        errors.join_thread()
    assert error is None
    assert {item["text"] for item in agent_directory_service.list_current_episodic_events(agent_id)} == {
        "parent transaction append",
        "child process append",
    }


def test_failed_atomic_replacement_rolls_back_append_and_supersede(
    tmp_path, monkeypatch
):
    from core.infrastructure import atomic_io

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    original = agent_directory_service.append_episodic_event(
        agent_id, kind="preference", text="original remains current"
    )
    episode_path = _policy_path(agent_id, "episodicEventsPath")
    before = episode_path.read_bytes()

    def fail_replace(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_io, "_replace_with_retry", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
            replacement = transaction.append(
                kind="preference", text="must not become an orphan"
            )
            transaction.supersede(
                original["episodeId"], successor_episode_id=replacement["episodeId"]
            )

    assert episode_path.read_bytes() == before
    current = agent_directory_service.list_current_episodic_events(agent_id)
    assert [item["episodeId"] for item in current] == [original["episodeId"]]
    assert current[0]["text"] == "original remains current"


def test_transaction_refuses_to_rewrite_unreadable_jsonl(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    original = agent_directory_service.append_episodic_event(
        agent_id, text="preserve valid row"
    )
    path = _policy_path(agent_id, "episodicEventsPath")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{malformed row that must be preserved\n")
    before = path.read_bytes()

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="invalid JSON"):
        with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
            transaction.append(kind="note", text="must not overwrite unreadable history")

    assert path.read_bytes() == before
    assert original["episodeId"] in before.decode("utf-8")


def test_transaction_rechecks_memory_policy_before_commit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    original = agent_directory_service.append_episodic_event(agent_id, text="keep existing")
    original_gate = episodic_memory_mod._require_memory_policy_enabled
    gate_calls = 0

    def disable_on_commit(current_agent):
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            agent_directory_service.update_agent_instance(
                agent_id, memory_policy={"enabled": False}
            )
        return original_gate(current_agent)

    monkeypatch.setattr(episodic_memory_mod, "_require_memory_policy_enabled", disable_on_commit)
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="memoryPolicy.enabled"):
        with episodic_memory_mod.episodic_transaction(agent_id) as transaction:
            transaction.append(kind="note", text="must not commit after disable")

    assert gate_calls == 2
    assert agent_directory_service.list_current_episodic_events(agent_id) == [original]


def test_explicit_transaction_can_supersede_after_memory_is_disabled(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    original = agent_directory_service.append_episodic_event(agent_id, text="remove explicitly")
    agent_directory_service.update_agent_instance(agent_id, memory_policy={"enabled": False})

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="memoryPolicy.enabled"):
        with episodic_memory_mod.episodic_transaction(agent_id):
            pass

    with episodic_memory_mod.episodic_transaction(
        agent_id, require_enabled=False
    ) as transaction:
        transaction.supersede(original["episodeId"])

    assert episodic_memory_mod.list_episodic_events(agent_id) == []
    history = episodic_memory_mod.list_episodic_events(
        agent_id, include_superseded=True
    )
    assert history[0]["episodeId"] == original["episodeId"]
    assert history[0]["validUntil"]


def test_list_current_is_newest_first(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    older = agent_directory_service.append_episodic_event(
        agent_id,
        kind="private_note",
        text="Earlier",
        occurred_at="2026-08-14T10:00:00+00:00",
    )
    newer = agent_directory_service.append_episodic_event(
        agent_id,
        kind="private_note",
        text="Later",
        occurred_at="2026-08-15T10:00:00+00:00",
    )

    current = agent_directory_service.list_current_episodic_events(agent_id, limit=10)
    assert [item["episodeId"] for item in current] == [newer["episodeId"], older["episodeId"]]


def test_unknown_agent_and_missing_episode_raise(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    with pytest.raises(agent_directory_service.AgentNotFoundError):
        agent_directory_service.append_episodic_event("agent-missing", text="nope")

    agent = _make_agent()
    with pytest.raises(agent_directory_service.AgentEpisodicEventNotFoundError):
        agent_directory_service.supersede_episodic_event(agent["agentId"], "episode-missing")


def test_hot_path_module_does_not_import_llm():
    source = Path(episodic_memory_mod.__file__).read_text(encoding="utf-8")
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    assert import_lines
    assert all("llm" not in line.lower() for line in import_lines)


def test_append_and_supersede_rejected_when_memory_policy_disabled(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    existing = agent_directory_service.append_episodic_event(agent_id, text="Before switch off")

    agent_directory_service.update_agent_instance(agent_id, memory_policy={"enabled": False})

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="memoryPolicy.enabled"):
        agent_directory_service.append_episodic_event(agent_id, text="After switch off")
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="memoryPolicy.enabled"):
        agent_directory_service.supersede_episodic_event(agent_id, existing["episodeId"])

    episode_path = _policy_path(agent_id, "episodicEventsPath")
    assert len(_jsonl_lines(episode_path)) == 1
