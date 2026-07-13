from __future__ import annotations

import json
import tomllib
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
    assert patched.index("[custom]") < patched.index("[llm]") < patched.index("[llm.providers.ai-pixel]")
    assert (
        tomllib.loads(patched)["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"][
            "enabled"
        ]
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
    assert '# operator note' in patched
    assert 'label = "keep" # keep inline' in patched
    assert '[custom]\nunknown = "keep-me"' in patched
    parsed = tomllib.loads(patched)
    assert set(parsed["llm"]["providers"]) == {"keep_me"}


def test_remove_table_tree_rejects_missing_path() -> None:
    with pytest.raises(ValueError, match="not found"):
        remove_toml_table_tree("[llm]\nschema_version = 2\n", ("llm", "providers", "missing"))


@pytest.mark.parametrize(
    ("value_text", "expected"),
    [
        ('"old#value"', "old#value"),
        ("'old#value'", "old#value"),
        ('"old\\\"#value"', 'old"#value'),
    ],
)
def test_replace_scalar_preserves_quoted_hash_and_inline_comment(value_text: str, expected: str) -> None:
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
def test_replace_scalar_requires_exactly_one_direct_key(text: str, expected_error: str) -> None:
    with pytest.raises(ValueError, match=expected_error):
        replace_toml_scalar(text, ("table",), "value", 1, 2)


def test_replace_scalar_rejects_unexpected_current_value() -> None:
    with pytest.raises(ValueError, match="unexpected current value"):
        replace_toml_scalar("[table]\nvalue = 1\n", ("table",), "value", 2, 3)


def test_prepare_rejects_stale_hash_before_mutation_or_artifact_writes(tmp_path: Path) -> None:
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


def test_apply_writes_backups_and_manifest_before_config_and_holds_lock(tmp_path: Path, monkeypatch) -> None:
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

    monkeypatch.setattr(transaction_module, "_strict_atomic_write", recording_atomic_write)
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

    with pytest.raises(OperatorConfigTransactionError, match="participant failed") as caught:
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
