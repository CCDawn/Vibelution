from __future__ import annotations

import json
import os
import threading
import tomllib
import traceback
from pathlib import Path

import pytest

import config.operator_config_transaction as transaction_module
from config.operator_config_transaction import (
    OperatorConfigTransactionError,
    TransactionParticipant,
    append_toml_table,
    apply_operator_config_transaction,
    prepare_operator_config_transaction,
    remove_toml_table_tree,
    replace_toml_scalar,
)
from config.paths import resolve_config_lock_path
from config.public_config import public_config_hash


def _valid_v2_text(*, newline: str = "\n") -> str:
    text = """# operator note: TOP_SECRET_VALUE
[custom]
unknown = "keep-me" # inline note

[llm]
schema_version = 2

[llm.providers.pixel_relay]
label = "Local Pixel Runtime"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.pixel_relay.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.pixel_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
label = "GPT-5.6 Luna"
enabled = true

[llm.profiles.primary]
model_ref = "pixel_relay/gpt-5.6-luna"

[llm.profiles.primary.overrides]
temperature = 0.4
"""
    return text.replace("\n", newline)


def _write_config(tmp_path: Path, *, newline: str = "\n") -> tuple[Path, bytes]:
    config_path = tmp_path / "config.toml"
    before = _valid_v2_text(newline=newline).encode("utf-8")
    config_path.write_bytes(before)
    return config_path, before


def _prepare_label_change(config_path: Path, before: bytes):
    return prepare_operator_config_transaction(
        operation_kind="test",
        expected_base_hash=public_config_hash(tomllib.loads(before.decode("utf-8"))),
        mutate_text=lambda text: replace_toml_scalar(
            text,
            ("llm", "providers", "pixel_relay", "models", "gpt-5.6-luna"),
            "label",
            "GPT-5.6 Luna",
            "Luna",
        ),
        config_path=config_path,
    )


def test_append_model_preserves_comments_unknown_fields_and_order() -> None:
    original = """# operator note
[custom]
unknown = "keep-me" # inline note

[llm]
schema_version = 2

[llm.providers.ai-pixel]
base_url = "https://relay.example/v1"
"""

    patched = append_toml_table(
        original,
        ("llm", "providers", "ai-pixel", "models", "gpt-5.6-luna"),
        {"upstream_id": "gpt-5.6-luna", "label": "Luna", "enabled": True},
    )

    assert patched.startswith(original)
    assert "# operator note" in patched
    assert 'unknown = "keep-me" # inline note' in patched
    assert (
        patched.index("[custom]")
        < patched.index("[llm]")
        < patched.index("[llm.providers.ai-pixel]")
    )
    assert (
        tomllib.loads(patched)["llm"]["providers"]["ai-pixel"]["models"][
            "gpt-5.6-luna"
        ]["enabled"]
        is True
    )


def test_append_table_rejects_existing_quoted_path() -> None:
    text = '[llm.providers."ai-pixel".models."gpt-5.6-luna"]\nenabled = true\n'

    with pytest.raises(ValueError, match="already exists"):
        append_toml_table(
            text,
            ("llm", "providers", "ai-pixel", "models", "gpt-5.6-luna"),
            {"enabled": True},
        )


def test_append_table_uses_existing_crlf_style_for_suffix_and_fragment() -> None:
    original = "[llm]\r\nschema_version = 2\r\n"

    patched = append_toml_table(
        original,
        ("llm", "providers", "local", "models", "model"),
        {"upstream_id": "model", "enabled": True},
    )

    expected_fragment = (
        "\r\n[llm.providers.local.models.model]\r\n"
        'upstream_id = "model"\r\n'
        "enabled = true\r\n"
    )
    assert patched == original + expected_fragment
    assert "\n" not in patched.replace("\r\n", "")
    assert (
        tomllib.loads(patched)["llm"]["providers"]["local"]["models"]["model"][
            "enabled"
        ]
        is True
    )


def test_remove_table_tree_preserves_unrelated_tables_and_comments() -> None:
    original = """# operator note
[llm.providers.remove_me]
label = "remove"

[llm.providers.remove_me.models.first]
enabled = true

[llm.providers.keep_me]
label = "keep" # keep inline

[custom]
unknown = "keep-me"
"""

    patched = remove_toml_table_tree(original, ("llm", "providers", "remove_me"))

    assert "remove_me" not in patched
    assert "# operator note" in patched
    assert 'label = "keep" # keep inline' in patched
    assert '[custom]\nunknown = "keep-me"' in patched
    parsed = tomllib.loads(patched)
    assert set(parsed["llm"]["providers"]) == {"keep_me"}


def test_remove_table_tree_preserves_following_unrelated_array_tables() -> None:
    original = """[target]
value = "remove"

[[kept_items]]
name = "first"

[[kept_items]]
name = "second"

[next]
enabled = true
"""
    kept = """[[kept_items]]
name = "first"

[[kept_items]]
name = "second"
"""

    patched = remove_toml_table_tree(original, ("target",))

    assert kept in patched
    assert tomllib.loads(patched)["kept_items"] == [
        {"name": "first"},
        {"name": "second"},
    ]


@pytest.mark.parametrize("delimiter", ['"""', "'''"])
def test_remove_table_tree_ignores_fake_headers_inside_multiline_strings(
    delimiter: str,
) -> None:
    multiline = f"payload = {delimiter}\n[target.child]\n[[fake]]\n{delimiter}\n"
    original = (
        "[target]\nvalue = 1\n\n[keep]\n"
        + multiline
        + "kept = true\n\n[next]\nvalue = 2\n"
    )

    patched = remove_toml_table_tree(original, ("target",))

    assert multiline in patched
    assert tomllib.loads(patched)["keep"]["payload"] == "[target.child]\n[[fake]]\n"


@pytest.mark.parametrize("delimiter", ['"""', "'''"])
def test_replace_scalar_ignores_fake_headers_inside_multiline_strings(
    delimiter: str,
) -> None:
    multiline = f"payload = {delimiter}\n[fake.table]\n[[fake]]\n{delimiter}\n"
    original = (
        "[target]\n" + multiline + "value = 1 # keep inline\n\n[next]\nvalue = 2\n"
    )

    patched = replace_toml_scalar(original, ("target",), "value", 1, 3)

    assert multiline in patched
    assert "value = 3 # keep inline\n" in patched
    assert tomllib.loads(patched)["target"]["payload"] == "[fake.table]\n[[fake]]\n"


@pytest.mark.parametrize("delimiter", ['"""', "'''"])
def test_replace_scalar_ignores_assignments_inside_multiline_strings(
    delimiter: str,
) -> None:
    multiline = f"payload = {delimiter}\nvalue = 1\n{delimiter}\n"
    original = "[target]\n" + multiline + "value = 2 # real scalar\n"

    patched = replace_toml_scalar(original, ("target",), "value", 2, 3)

    assert multiline in patched
    assert "value = 3 # real scalar\n" in patched
    assert tomllib.loads(patched)["target"]["payload"] == "value = 1\n"


def test_replace_scalar_preserves_multiline_array_structure() -> None:
    multiline_array = """choices = [
  "first",
  "[not.a.table]",
  ["nested", "values"],
]
"""
    original = (
        "[target]\n" + multiline_array + 'value = 1\n\n[[kept.items]]\nname = "item"\n'
    )

    patched = replace_toml_scalar(original, ("target",), "value", 1, 2)

    assert multiline_array in patched
    assert '[[kept.items]]\nname = "item"\n' in patched
    assert tomllib.loads(patched)["target"]["choices"][2] == ["nested", "values"]


def test_remove_quoted_table_tree_preserves_unrelated_array_table() -> None:
    original = """[llm.providers."ai.pixel"]
label = "remove"

[llm.providers."ai.pixel".models."gpt-5.6"]
enabled = true

[[llm.providers.keep.models]]
name = "kept"
"""
    kept = '[[llm.providers.keep.models]]\nname = "kept"\n'

    patched = remove_toml_table_tree(original, ("llm", "providers", "ai.pixel"))

    assert kept in patched
    assert "ai.pixel" not in patched
    assert tomllib.loads(patched)["llm"]["providers"]["keep"]["models"] == [
        {"name": "kept"}
    ]


def test_remove_table_tree_preserves_trailing_comments_and_blank_trivia() -> None:
    original = """[target]
value = "remove"
# keep transition note


[keep]
value = "keep"
"""

    patched = remove_toml_table_tree(original, ("target",))

    assert patched.startswith("# keep transition note\n\n\n[keep]\n")
    assert tomllib.loads(patched)["keep"]["value"] == "keep"


def test_remove_table_tree_rejects_missing_path() -> None:
    with pytest.raises(ValueError, match="not found"):
        remove_toml_table_tree(
            "[llm]\nschema_version = 2\n", ("llm", "providers", "missing")
        )


@pytest.mark.parametrize(
    ("value_text", "expected"),
    [
        ('"old#value"', "old#value"),
        ("'old#value'", "old#value"),
        ('"old\\"#value"', 'old"#value'),
    ],
)
def test_replace_scalar_preserves_quoted_hash_and_inline_comment(
    value_text: str, expected: str
) -> None:
    original = f"[table]\nvalue = {value_text} # operator note\n[next]\nkept = true\n"

    patched = replace_toml_scalar(original, ("table",), "value", expected, "new#value")

    assert 'value = "new#value" # operator note\n' in patched
    assert "[next]\nkept = true\n" in patched
    assert tomllib.loads(patched)["table"]["value"] == "new#value"


def test_replace_scalar_preserves_crlf_spacing_and_inline_comment() -> None:
    original = "[llm]\r\nschema_version  =  2  # keep\r\n[next]\r\nvalue = true\r\n"

    patched = replace_toml_scalar(original, ("llm",), "schema_version", 2, 3)

    assert "schema_version  =  3  # keep\r\n" in patched
    assert "\n" not in patched.replace("\r\n", "")
    assert tomllib.loads(patched)["llm"]["schema_version"] == 3


@pytest.mark.parametrize(
    ("text", "expected_error"),
    [
        ("[table]\nother = 1\n", "found 0"),
        ("[table]\nvalue = 1\nvalue = 1\n", "found 2"),
    ],
)
def test_replace_scalar_requires_exactly_one_direct_key(
    text: str, expected_error: str
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        replace_toml_scalar(text, ("table",), "value", 1, 2)


def test_replace_scalar_rejects_unexpected_current_value() -> None:
    with pytest.raises(ValueError, match="unexpected current value"):
        replace_toml_scalar("[table]\nvalue = 1\n", ("table",), "value", 2, 3)


def test_prepare_rejects_stale_hash_before_mutation_or_artifact_writes(
    tmp_path: Path,
) -> None:
    config_path, before = _write_config(tmp_path)
    called = False

    def mutate(text: str) -> str:
        nonlocal called
        called = True
        return text

    with pytest.raises(ValueError, match="stale config hash"):
        prepare_operator_config_transaction(
            operation_kind="test",
            expected_base_hash="stale",
            mutate_text=mutate,
            config_path=config_path,
        )

    assert called is False
    assert config_path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_apply_rejects_byte_drift_after_prepare_without_writes(tmp_path: Path) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    config_path.write_bytes(before.replace(b"# operator note", b"# changed note"))

    with pytest.raises(ValueError, match="changed after transaction preparation"):
        apply_operator_config_transaction(prepared)

    assert not prepared.manifest_path.exists()


def test_apply_writes_backups_and_manifest_before_config_and_holds_lock(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    writes: list[Path] = []
    original_atomic_write = transaction_module._strict_atomic_write

    def recording_atomic_write(path: Path, payload: bytes) -> None:
        resolved = Path(path).resolve()
        writes.append(resolved)
        if resolved == config_path.resolve():
            assert resolve_config_lock_path(config_path).exists()
        original_atomic_write(path, payload)

    monkeypatch.setattr(
        transaction_module, "_strict_atomic_write", recording_atomic_write
    )
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())

    result = apply_operator_config_transaction(prepared)

    assert result == {
        "status": "completed",
        "operationId": prepared.operation_id,
        "hash": prepared.candidate_hash,
        "manifestPath": str(prepared.manifest_path),
    }
    assert config_path.read_bytes() == prepared.after_bytes
    assert writes[0].name.endswith(".before.bin")
    assert writes[1].name.endswith(".after.bin")
    assert writes[2] == prepared.manifest_path
    assert writes[3] == config_path.resolve()
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert Path(manifest["beforeBackup"]).read_bytes() == before
    assert Path(manifest["afterBackup"]).read_bytes() == prepared.after_bytes
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "TOP_SECRET_VALUE" not in serialized
    assert "127.0.0.1" not in serialized
    assert "credential_ref" not in serialized


def test_participant_failure_restores_exact_config_bytes_and_compensates_in_reverse(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path, newline="\r\n")
    prepared = _prepare_label_change(config_path, before)
    events: list[str] = []

    first = TransactionParticipant(
        name="first",
        apply=lambda: events.append("first.apply"),
        verify=lambda: events.append("first.verify"),
        rollback=lambda: events.append("first.rollback"),
    )

    def fail_apply() -> None:
        events.append("second.apply")
        raise RuntimeError("participant failed: TOP_SECRET_VALUE")

    second = TransactionParticipant(
        name="second",
        apply=fail_apply,
        verify=lambda: events.append("second.verify"),
        rollback=lambda: events.append("second.rollback"),
    )
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())

    with pytest.raises(
        OperatorConfigTransactionError, match="participant failed"
    ) as caught:
        apply_operator_config_transaction(prepared, participants=[first, second])

    assert caught.value.status == "rolled_back"
    assert config_path.read_bytes() == before
    assert events == [
        "first.apply",
        "first.verify",
        "second.apply",
        "second.rollback",
        "first.rollback",
    ]
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "rolled_back"
    assert manifest["errorType"] == "RuntimeError"
    assert "TOP_SECRET_VALUE" not in json.dumps(manifest, ensure_ascii=False)


def test_participant_rollback_failure_is_recorded_without_skipping_config_restore(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)

    def fail_apply() -> None:
        raise RuntimeError("participant failed")

    def fail_rollback() -> None:
        raise RuntimeError("rollback failed")

    participant = TransactionParticipant(
        name="failing-participant",
        apply=fail_apply,
        verify=lambda: None,
        rollback=fail_rollback,
    )
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())

    with pytest.raises(OperatorConfigTransactionError) as caught:
        apply_operator_config_transaction(prepared, participants=[participant])

    assert caught.value.status == "rollback_failed"
    assert config_path.read_bytes() == before
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rollbackErrors"] == ["failing-participant:RuntimeError"]


@pytest.mark.parametrize("failure_source", ["participant", "reload"])
def test_transaction_error_severs_sensitive_exception_chain(
    failure_source: str, tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    sentinel = "RAW_EXCEPTION_SECRET_SENTINEL"
    reload_calls = 0

    def reload_with_optional_failure(path: str) -> object:
        nonlocal reload_calls
        reload_calls += 1
        if failure_source == "reload" and reload_calls == 1:
            raise RuntimeError(sentinel)
        return object()

    def participant_failure() -> None:
        raise RuntimeError(sentinel)

    participants = (
        [
            TransactionParticipant(
                name="sensitive-failure",
                apply=participant_failure,
                verify=lambda: None,
                rollback=lambda: None,
            )
        ]
        if failure_source == "participant"
        else []
    )
    monkeypatch.setattr(
        transaction_module, "reload_config", reload_with_optional_failure
    )

    with pytest.raises(OperatorConfigTransactionError) as caught:
        apply_operator_config_transaction(prepared, participants=participants)

    rendered = "".join(traceback.format_exception(caught.value))
    assert config_path.read_bytes() == before
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in repr(caught.value)
    assert sentinel not in rendered


@pytest.mark.parametrize(
    ("failed_write", "expected_phase"),
    [(5, "manifest_reloaded"), (6, "manifest_completed")],
)
def test_manifest_progress_write_failure_records_precise_phase_and_rolls_back(
    failed_write: int, expected_phase: str, tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    original_atomic_write = transaction_module._strict_atomic_write
    write_count = 0

    def fail_nth_write(path: Path, payload: bytes) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == failed_write:
            raise OSError("MANIFEST_PROGRESS_SECRET")
        original_atomic_write(path, payload)

    monkeypatch.setattr(transaction_module, "_strict_atomic_write", fail_nth_write)
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())

    with pytest.raises(OperatorConfigTransactionError) as caught:
        apply_operator_config_transaction(prepared)

    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert caught.value.status == "rolled_back"
    assert config_path.read_bytes() == before
    assert manifest["status"] == "rolled_back"
    assert manifest["failurePhase"] == expected_phase
    assert manifest["errorType"] == "OSError"


def test_secondary_rollback_manifest_failure_keeps_bounded_error_and_restored_config(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    original_atomic_write = transaction_module._strict_atomic_write
    write_count = 0
    failed_writes = {6, 8}
    sentinel = "SECONDARY_MANIFEST_SECRET"

    def fail_selected_writes(path: Path, payload: bytes) -> None:
        nonlocal write_count
        write_count += 1
        if write_count in failed_writes:
            raise OSError(sentinel)
        original_atomic_write(path, payload)

    monkeypatch.setattr(
        transaction_module, "_strict_atomic_write", fail_selected_writes
    )
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())

    with pytest.raises(OperatorConfigTransactionError) as caught:
        apply_operator_config_transaction(prepared)

    rendered = "".join(traceback.format_exception(caught.value))
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert config_path.read_bytes() == before
    assert caught.value.status == "rollback_failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in repr(caught.value)
    assert sentinel not in rendered
    assert manifest["status"] == "reloaded"


def test_candidate_atomic_write_preflight_failure_skips_redundant_restore_and_reload(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    original_atomic_write = transaction_module._strict_atomic_write
    config_write_attempts = 0
    reload_calls = 0

    def fail_config_writes(path: Path, payload: bytes) -> None:
        nonlocal config_write_attempts
        if Path(path).resolve() == config_path.resolve():
            config_write_attempts += 1
            raise PermissionError("CANDIDATE_WRITE_SECRET")
        original_atomic_write(path, payload)

    def record_reload(path: str) -> object:
        nonlocal reload_calls
        reload_calls += 1
        return object()

    monkeypatch.setattr(transaction_module, "_strict_atomic_write", fail_config_writes)
    monkeypatch.setattr(transaction_module, "reload_config", record_reload)

    with pytest.raises(OperatorConfigTransactionError) as caught:
        apply_operator_config_transaction(prepared)

    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert caught.value.status == "rolled_back"
    assert config_path.read_bytes() == before
    assert config_write_attempts == 1
    assert reload_calls == 0
    assert manifest["status"] == "rolled_back"
    assert manifest["failurePhase"] == "write_config"
    assert manifest["errorType"] == "PermissionError"


def test_transaction_lock_heartbeat_refreshes_owned_token_during_participant(
    tmp_path: Path, monkeypatch
) -> None:
    config_path, before = _write_config(tmp_path)
    prepared = _prepare_label_change(config_path, before)
    lock_path = resolve_config_lock_path(config_path)
    probe_ready = threading.Event()
    heartbeat_seen = threading.Event()
    original_touch = transaction_module._touch_lock_if_owned

    def recording_touch(path: Path, token: str) -> bool:
        touched = original_touch(path, token)
        if touched and probe_ready.is_set():
            heartbeat_seen.set()
        return touched

    def wait_for_heartbeat() -> None:
        owned_token = lock_path.read_text(encoding="utf-8").strip()
        old_ns = 1_000_000_000
        os.utime(lock_path, ns=(old_ns, old_ns))
        probe_ready.set()
        assert heartbeat_seen.wait(timeout=2.0), (
            "heartbeat did not refresh the active lock"
        )
        assert lock_path.read_text(encoding="utf-8").strip() == owned_token
        assert lock_path.stat().st_mtime_ns > old_ns

    monkeypatch.setattr(transaction_module, "_LOCK_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(transaction_module, "_touch_lock_if_owned", recording_touch)
    monkeypatch.setattr(transaction_module, "reload_config", lambda path: object())
    participant = TransactionParticipant(
        name="heartbeat-probe",
        apply=wait_for_heartbeat,
        verify=lambda: None,
        rollback=lambda: None,
    )

    result = apply_operator_config_transaction(prepared, participants=[participant])

    assert result["status"] == "completed"
    assert not lock_path.exists()


def test_lock_heartbeat_does_not_touch_replaced_owner_token(tmp_path: Path) -> None:
    lock_path = tmp_path / "config-edit.lock"
    lock_path.write_text("owner-a\n", encoding="utf-8")
    assert transaction_module._touch_lock_if_owned(lock_path, "owner-a") is True

    lock_path.write_text("owner-b\n", encoding="utf-8")
    old_ns = 1_000_000_000
    os.utime(lock_path, ns=(old_ns, old_ns))
    replaced_mtime = lock_path.stat().st_mtime_ns

    assert transaction_module._touch_lock_if_owned(lock_path, "owner-a") is False
    assert lock_path.read_text(encoding="utf-8") == "owner-b\n"
    assert lock_path.stat().st_mtime_ns == replaced_mtime
