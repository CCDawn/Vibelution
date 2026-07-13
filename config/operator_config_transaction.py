"""Source-preserving patches and fail-closed operator config transactions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import tomllib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from config.llm_security import validate_llm_public_config
from config.paths import resolve_config_backup_dir, resolve_config_lock_path
from config.public_config import (
    CONFIG_PATH,
    _config_edit_lock,
    build_effective_config,
    load_public_config,
    public_config_hash,
)
from config.settings import reload_config
from config.toml_writer import dumps_toml_table, format_toml_scalar


_SCALAR_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<separator>\s*=\s*)(?P<payload>.*)$"
)
_LOCK_HEARTBEAT_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class _TableSpan:
    path: tuple[str, ...]
    start: int
    end: int


@dataclass
class _TomlLexicalState:
    multiline_quote: str = ""
    square_depth: int = 0
    curly_depth: int = 0


@dataclass(frozen=True)
class TransactionParticipant:
    name: str
    apply: Callable[[], None]
    verify: Callable[[], None]
    rollback: Callable[[], None]


@dataclass(frozen=True)
class PreparedOperatorConfigTransaction:
    operation_id: str
    operation_kind: str
    config_path: Path
    before_bytes: bytes = field(repr=False)
    after_bytes: bytes = field(repr=False)
    base_hash: str
    candidate_hash: str
    manifest_path: Path


@dataclass
class _TransactionArtifacts:
    manifest_path: Path
    manifest: dict[str, Any]


def _touch_lock_if_owned(lock_path: Path, token: str) -> bool:
    """Refresh a config lock only while its owner token still matches."""

    try:
        if lock_path.read_text(encoding="utf-8").strip() != token:
            return False
        os.utime(lock_path, None)
        return lock_path.read_text(encoding="utf-8").strip() == token
    except (OSError, UnicodeError):
        return False


@dataclass
class _ConfigLockHeartbeat:
    lock_path: Path
    token: str = field(repr=False)
    interval_seconds: float
    _stop: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _ownership_lost: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="operator-config-lock-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        interval = max(float(self.interval_seconds), 0.001)
        while not self._stop.wait(interval):
            if not _touch_lock_if_owned(self.lock_path, self.token):
                self._ownership_lost.set()
                return

    def assert_owned(self) -> None:
        if self._ownership_lost.is_set() or not _touch_lock_if_owned(
            self.lock_path, self.token
        ):
            self._ownership_lost.set()
            raise RuntimeError("operator config edit lock ownership lost")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


@contextmanager
def _active_config_edit_lock(config_path: Path):
    with _config_edit_lock(config_path):
        lock_path = resolve_config_lock_path(config_path)
        try:
            token = lock_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise RuntimeError(
                "operator config edit lock token is unavailable"
            ) from None
        if not token:
            raise RuntimeError("operator config edit lock token is unavailable")
        heartbeat = _ConfigLockHeartbeat(
            lock_path=lock_path,
            token=token,
            interval_seconds=_LOCK_HEARTBEAT_INTERVAL_SECONDS,
        )
        heartbeat.start()
        try:
            heartbeat.assert_owned()
            yield heartbeat
        finally:
            heartbeat.stop()


class OperatorConfigTransactionError(RuntimeError):
    """Raised after a failed transaction has attempted every compensation."""

    def __init__(self, *, status: str, operation_id: str, manifest_path: Path) -> None:
        self.status = status
        self.operation_id = operation_id
        self.manifest_path = manifest_path
        super().__init__(
            "operator config participant failed or reload failed; "
            f"status={status}; operationId={operation_id}"
        )


def _normalized_table_path(table_path: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(part) for part in table_path)
    if not normalized:
        raise ValueError("table_path is required")
    return normalized


def _table_path_from_line(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    marker = "__vibelution_table_marker__"
    try:
        payload = tomllib.loads(f"{line.rstrip(chr(13) + chr(10))}\n{marker} = true\n")
    except tomllib.TOMLDecodeError:
        return None

    def find(node: Any, prefix: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(node, dict):
            if node.get(marker) is True:
                return prefix
            for key, value in node.items():
                found = find(value, (*prefix, str(key)))
                if found:
                    return found
        elif isinstance(node, list):
            for value in reversed(node):
                found = find(value, prefix)
                if found:
                    return found
        return ()

    resolved = find(payload, ())
    return resolved or None


def _is_unescaped_quote_run(line: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and line[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 0


def _advance_lexical_state(line: str, state: _TomlLexicalState) -> None:
    index = 0
    local_quote = ""
    escaped = False
    while index < len(line):
        if state.multiline_quote:
            delimiter = state.multiline_quote * 3
            if line.startswith(delimiter, index):
                if state.multiline_quote == "'" or _is_unescaped_quote_run(line, index):
                    run_end = index
                    while (
                        run_end < len(line) and line[run_end] == state.multiline_quote
                    ):
                        run_end += 1
                    state.multiline_quote = ""
                    index = run_end
                    continue
            index += 1
            continue
        if local_quote == '"':
            if escaped:
                escaped = False
            elif line[index] == "\\":
                escaped = True
            elif line[index] == '"':
                local_quote = ""
            index += 1
            continue
        if local_quote == "'":
            if line[index] == "'":
                local_quote = ""
            index += 1
            continue
        if line[index] == "#":
            break
        if line.startswith('"""', index):
            state.multiline_quote = '"'
            index += 3
            continue
        if line.startswith("'''", index):
            state.multiline_quote = "'"
            index += 3
            continue
        if line[index] == '"':
            local_quote = '"'
        elif line[index] == "'":
            local_quote = "'"
        elif line[index] == "[":
            state.square_depth += 1
        elif line[index] == "]":
            state.square_depth -= 1
            if state.square_depth < 0:
                raise ValueError("uncertain TOML bracket structure")
        elif line[index] == "{":
            state.curly_depth += 1
        elif line[index] == "}":
            state.curly_depth -= 1
            if state.curly_depth < 0:
                raise ValueError("uncertain TOML brace structure")
        index += 1
    if local_quote:
        raise ValueError("uncertain TOML string structure")


def _table_spans(lines: Sequence[str]) -> list[_TableSpan]:
    headers: list[tuple[int, tuple[str, ...]]] = []
    state = _TomlLexicalState()
    for index, line in enumerate(lines):
        if (
            not state.multiline_quote
            and state.square_depth == 0
            and state.curly_depth == 0
        ):
            path = _table_path_from_line(line)
            if path is not None:
                headers.append((index, path))
                continue
        _advance_lexical_state(line, state)
    if state.multiline_quote or state.square_depth or state.curly_depth:
        raise ValueError("uncertain TOML multiline structure")
    return [
        _TableSpan(
            path=path,
            start=start,
            end=headers[index + 1][0] if index + 1 < len(headers) else len(lines),
        )
        for index, (start, path) in enumerate(headers)
    ]


def _table_paths(text: str) -> set[tuple[str, ...]]:
    return {span.path for span in _table_spans(text.splitlines(keepends=True))}


def _newline_style(text: str) -> str:
    first_lf = text.find("\n")
    if first_lf > 0 and text[first_lf - 1] == "\r":
        return "\r\n"
    return "\n"


def append_toml_table(
    text: str,
    table_path: tuple[str, ...],
    values: dict[str, Any],
) -> str:
    path = _normalized_table_path(table_path)
    tomllib.loads(text)
    if path in _table_paths(text):
        raise ValueError("TOML table already exists")
    newline = _newline_style(text)
    suffix = (
        ""
        if not text or text.endswith(newline * 2)
        else newline
        if text.endswith(newline)
        else newline * 2
    )
    fragment = dumps_toml_table(path, values).replace("\n", newline)
    candidate = text + suffix + fragment
    tomllib.loads(candidate)
    return candidate


def remove_toml_table_tree(text: str, table_path: tuple[str, ...]) -> str:
    path = _normalized_table_path(table_path)
    tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    spans = _table_spans(lines)
    removed = [span for span in spans if span.path[: len(path)] == path]
    if not removed:
        raise ValueError("TOML table tree not found")
    indexes: set[int] = set()
    for span in removed:
        content_end = span.end
        while content_end > span.start + 1:
            stripped = lines[content_end - 1].strip()
            if stripped and not stripped.startswith("#"):
                break
            content_end -= 1
        indexes.update(range(span.start, content_end))
    candidate = "".join(
        line for index, line in enumerate(lines) if index not in indexes
    )
    tomllib.loads(candidate)
    return candidate


def _split_toml_value_suffix(payload: str) -> tuple[str, str]:
    quote = ""
    escaped = False
    for index, char in enumerate(payload):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif quote == "'":
            if char == quote:
                quote = ""
        elif char in {'"', "'"}:
            quote = char
        elif char == "#":
            value = payload[:index].rstrip()
            return value, payload[len(value) :]
    value = payload.rstrip()
    return value, payload[len(value) :]


def replace_toml_scalar(
    text: str,
    table_path: tuple[str, ...],
    key: str,
    expected: Any,
    replacement: Any,
) -> str:
    path = _normalized_table_path(table_path)
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str], str, str]] = []
    for span in _table_spans(lines):
        if span.path != path:
            continue
        state = _TomlLexicalState()
        for index in range(span.start + 1, span.end):
            if (
                not state.multiline_quote
                and state.square_depth == 0
                and state.curly_depth == 0
            ):
                newline = (
                    "\r\n"
                    if lines[index].endswith("\r\n")
                    else "\n"
                    if lines[index].endswith("\n")
                    else ""
                )
                body = lines[index][: -len(newline)] if newline else lines[index]
                match = _SCALAR_ASSIGNMENT.fullmatch(body)
                if match and match.group("key") == key:
                    value_text, suffix = _split_toml_value_suffix(
                        match.group("payload")
                    )
                    matches.append((index, match, value_text, suffix + newline))
            _advance_lexical_state(lines[index], state)
    if len(matches) != 1:
        dotted_key = ".".join((*path, key))
        raise ValueError(f"expected one scalar {dotted_key}, found {len(matches)}")
    tomllib.loads(text)
    index, match, value_text, suffix = matches[0]
    current = tomllib.loads(f"value = {value_text}\n")["value"]
    if current != expected:
        raise ValueError(f"unexpected current value for {'.'.join((*path, key))}")
    lines[index] = (
        match.group("indent")
        + match.group("key")
        + match.group("separator")
        + format_toml_scalar(replacement)
        + suffix
    )
    candidate = "".join(lines)
    tomllib.loads(candidate)
    return candidate


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_atomic_write(path: Path, payload: bytes) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _strict_atomic_write(path, payload)


def _prepared_transaction(
    operation_kind: str,
    config_path: Path,
    before_bytes: bytes,
    after_bytes: bytes,
    base_hash: str,
    candidate_hash: str,
) -> PreparedOperatorConfigTransaction:
    kind = str(operation_kind or "").strip()
    if not kind:
        raise ValueError("operation_kind is required")
    operation_id = "operator-config-" + uuid.uuid4().hex
    manifest_path = (
        resolve_config_backup_dir(config_path)
        / f"operator-config-transaction-{operation_id}.json"
    ).resolve()
    return PreparedOperatorConfigTransaction(
        operation_id=operation_id,
        operation_kind=kind,
        config_path=config_path,
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        base_hash=base_hash,
        candidate_hash=candidate_hash,
        manifest_path=manifest_path,
    )


def prepare_operator_config_transaction(
    *,
    operation_kind: str,
    expected_base_hash: str,
    mutate_text: Callable[[str], str],
    config_path: Path | str = CONFIG_PATH,
) -> PreparedOperatorConfigTransaction:
    path = Path(config_path).expanduser().resolve()
    before = path.read_bytes()
    before_text = before.decode("utf-8")
    current = tomllib.loads(before_text)
    base_hash = public_config_hash(current)
    if base_hash != str(expected_base_hash):
        raise ValueError("stale config hash")
    after_text = mutate_text(before_text)
    if not isinstance(after_text, str):
        raise TypeError("mutate_text must return str")
    after = after_text.encode("utf-8")
    candidate = tomllib.loads(after_text)
    validate_llm_public_config(candidate)
    build_effective_config(candidate)
    candidate_hash = public_config_hash(candidate)
    return _prepared_transaction(
        operation_kind,
        path,
        before,
        after,
        base_hash,
        candidate_hash,
    )


def _write_transaction_artifacts(
    prepared: PreparedOperatorConfigTransaction,
    *,
    status: str,
    participant_names: Sequence[str],
) -> _TransactionArtifacts:
    backup_dir = prepared.manifest_path.parent
    before_path = (
        backup_dir / f"operator-config-transaction-{prepared.operation_id}.before.bin"
    ).resolve()
    after_path = (
        backup_dir / f"operator-config-transaction-{prepared.operation_id}.after.bin"
    ).resolve()
    _strict_atomic_write(before_path, prepared.before_bytes)
    _strict_atomic_write(after_path, prepared.after_bytes)
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "operationId": prepared.operation_id,
        "operationKind": prepared.operation_kind,
        "status": status,
        "phase": status,
        "configPath": str(prepared.config_path),
        "baseHash": prepared.base_hash,
        "candidateHash": prepared.candidate_hash,
        "beforeBackup": str(before_path),
        "afterBackup": str(after_path),
        "beforeSha256": _sha256(prepared.before_bytes),
        "afterSha256": _sha256(prepared.after_bytes),
        "participants": list(participant_names),
    }
    _write_manifest(prepared.manifest_path, manifest)
    return _TransactionArtifacts(
        manifest_path=prepared.manifest_path, manifest=manifest
    )


def _update_transaction_manifest(
    artifacts: _TransactionArtifacts,
    *,
    status: str,
    failure_phase: str = "",
    error_type: str = "",
    rollback_errors: Sequence[str] = (),
) -> None:
    artifacts.manifest["status"] = status
    artifacts.manifest["phase"] = status
    if failure_phase:
        artifacts.manifest["failurePhase"] = failure_phase
    if error_type:
        artifacts.manifest["errorType"] = error_type
    if rollback_errors:
        artifacts.manifest["rollbackErrors"] = list(rollback_errors)
    _write_manifest(artifacts.manifest_path, artifacts.manifest)


def _validate_participants(
    participants: Sequence[TransactionParticipant],
) -> tuple[TransactionParticipant, ...]:
    validated = tuple(participants)
    for participant in validated:
        if not isinstance(participant, TransactionParticipant):
            raise TypeError("participants must be TransactionParticipant instances")
        if not str(participant.name).strip():
            raise ValueError("participant name is required")
    return validated


def apply_operator_config_transaction(
    prepared: PreparedOperatorConfigTransaction,
    *,
    participants: Sequence[TransactionParticipant] = (),
) -> dict[str, Any]:
    participant_list = _validate_participants(participants)
    applied: list[TransactionParticipant] = []
    rollback_errors: list[str] = []
    failure_phase = "write_config"
    bounded_error: OperatorConfigTransactionError | None = None
    config_state = "before"
    runtime_reloaded = False
    with _active_config_edit_lock(prepared.config_path) as lock_heartbeat:
        current_bytes = prepared.config_path.read_bytes()
        current_public = tomllib.loads(current_bytes.decode("utf-8"))
        if (
            current_bytes != prepared.before_bytes
            or public_config_hash(current_public) != prepared.base_hash
        ):
            raise ValueError("operator config changed after transaction preparation")
        artifacts = _write_transaction_artifacts(
            prepared,
            status="prepared",
            participant_names=[participant.name for participant in participant_list],
        )
        try:
            lock_heartbeat.assert_owned()
            _strict_atomic_write(prepared.config_path, prepared.after_bytes)
            config_state = "candidate"
            failure_phase = "validate_persisted_config"
            persisted = load_public_config(prepared.config_path)
            validate_llm_public_config(persisted)
            build_effective_config(persisted)
            persisted_hash = public_config_hash(persisted)
            if persisted_hash != prepared.candidate_hash:
                raise ValueError("persisted public config hash mismatch")
            failure_phase = "reload_config"
            reload_config(str(prepared.config_path))
            runtime_reloaded = True
            failure_phase = "manifest_reloaded"
            _update_transaction_manifest(artifacts, status="reloaded")
            for participant in participant_list:
                applied.append(participant)
                failure_phase = "participant_apply"
                lock_heartbeat.assert_owned()
                participant.apply()
                failure_phase = "participant_verify"
                participant.verify()
                lock_heartbeat.assert_owned()
            failure_phase = "manifest_completed"
            lock_heartbeat.assert_owned()
            _update_transaction_manifest(artifacts, status="completed")
            return {
                "status": "completed",
                "operationId": prepared.operation_id,
                "hash": persisted_hash,
                "manifestPath": str(prepared.manifest_path),
            }
        except Exception as exc:
            for participant in reversed(applied):
                try:
                    participant.rollback()
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"{participant.name}:{type(rollback_exc).__name__}"
                    )
            try:
                observed_bytes = prepared.config_path.read_bytes()
                if observed_bytes == prepared.before_bytes:
                    config_state = "before"
                elif observed_bytes == prepared.after_bytes:
                    config_state = "candidate"
                else:
                    config_state = "drift"
            except Exception as readback_exc:
                config_state = "unknown"
                rollback_errors.append(
                    f"operator_config_readback:{type(readback_exc).__name__}"
                )
            config_needs_restore = config_state != "before"
            config_restored = not config_needs_restore
            try:
                if config_needs_restore:
                    _strict_atomic_write(prepared.config_path, prepared.before_bytes)
                    if prepared.config_path.read_bytes() != prepared.before_bytes:
                        raise RuntimeError("operator config byte restoration mismatch")
                    config_restored = True
            except Exception as rollback_exc:
                config_restored = False
                rollback_errors.append(f"operator_config:{type(rollback_exc).__name__}")
            if config_restored and (config_needs_restore or runtime_reloaded):
                try:
                    reload_config(str(prepared.config_path))
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"operator_config_reload:{type(rollback_exc).__name__}"
                    )
            status = "rollback_failed" if rollback_errors else "rolled_back"
            try:
                _update_transaction_manifest(
                    artifacts,
                    status=status,
                    failure_phase=failure_phase,
                    error_type=type(exc).__name__,
                    rollback_errors=rollback_errors,
                )
            except Exception as manifest_exc:
                rollback_errors.append(f"manifest:{type(manifest_exc).__name__}")
                status = "rollback_failed"
            bounded_error = OperatorConfigTransactionError(
                status=status,
                operation_id=prepared.operation_id,
                manifest_path=prepared.manifest_path,
            )
    if bounded_error is not None:
        raise bounded_error
    raise RuntimeError("operator config transaction ended without a result")


__all__ = [
    "OperatorConfigTransactionError",
    "PreparedOperatorConfigTransaction",
    "TransactionParticipant",
    "append_toml_table",
    "apply_operator_config_transaction",
    "prepare_operator_config_transaction",
    "remove_toml_table_tree",
    "replace_toml_scalar",
]
