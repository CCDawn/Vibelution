"""Verified, object-only translation across a deliberately repaired Git history.

This module is also copied into the standalone hooks snapshot: keep it stdlib-only.
The caller owns refs and the active pointer; none of these APIs update Git refs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


class HistoryBridgeError(RuntimeError):
    """History or its recovery evidence does not satisfy the repair contract."""


@dataclass(frozen=True)
class MappingReceipt:
    oldmain: str
    newmain: str
    mapping: Mapping[str, str]
    digest: str
    backup_refs: Mapping[str, str]
    backup_zip: Path
    zip_sha256: str
    author_fixes: Mapping[str, bytes]
    receipt_path: Path


@dataclass(frozen=True)
class TranslationResult:
    head: str
    mapping: Mapping[str, str]


_BOT_EMAILS = (b"cursoragent@cursor.com", b"noreply@commandcode.ai")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IDENTITY = re.compile(rb"(.+ <([^<>\n]+)>)( -?\d+ [+-]\d{4})\Z")
_LOCAL_GIT_ENV = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_DIR",
    "GIT_GRAFT_FILE", "GIT_IMPLICIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_INTERNAL_SUPER_PREFIX", "GIT_NO_REPLACE_OBJECTS", "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_WORK_TREE",
}


def _process_options(repo: Path) -> dict:
    return {
        "cwd": repo,
        "env": {key: value for key, value in os.environ.items() if key not in _LOCAL_GIT_ENV},
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    }


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", *args], input=data, capture_output=True,
        **_process_options(repo),
    )
    if result.returncode:
        raise HistoryBridgeError(result.stderr.decode("utf-8", "replace").strip() or "git failed")
    return result.stdout


def _oid(value: str) -> str:
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise HistoryBridgeError("expected a full lowercase object ID")
    return value


def _resolve(repo: Path, value: str) -> str:
    return _oid(_git(repo, "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}").decode().strip())


def _is_ancestor(repo: Path, ancestor: str, head: str) -> bool:
    result = subprocess.run(
        ["git", "--no-replace-objects", "merge-base", "--is-ancestor", ancestor, head],
        capture_output=True, **_process_options(repo),
    )
    if result.returncode not in (0, 1):
        raise HistoryBridgeError(result.stderr.decode("utf-8", "replace").strip() or "ancestry check failed")
    return result.returncode == 0


class _RawCommits:
    """One native cat-file process; no replace refs or mailmap interpretation."""

    def __init__(self, repo: Path):
        self.process = subprocess.Popen(
            ["git", "--no-replace-objects", "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **_process_options(repo),
        )
        self.cache: dict[str, bytes] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()
        self.process.wait(timeout=10)

    def get(self, oid: str) -> bytes:
        _oid(oid)
        if oid not in self.cache:
            self.process.stdin.write(oid.encode() + b"\n")
            self.process.stdin.flush()
            fields = self.process.stdout.readline().split()
            if len(fields) != 3 or fields[0] != oid.encode() or fields[1] != b"commit":
                raise HistoryBridgeError(f"missing or invalid raw commit: {oid}")
            raw = self.process.stdout.read(int(fields[2]))
            if len(raw) != int(fields[2]) or self.process.stdout.read(1) != b"\n":
                raise HistoryBridgeError(f"truncated raw commit: {oid}")
            self.cache[oid] = raw
        return self.cache[oid]


def _parts(raw: bytes) -> tuple[list[list[bytes]], bytes]:
    if b"\n\n" not in raw:
        raise HistoryBridgeError("invalid commit headers")
    header, message = raw.split(b"\n\n", 1)
    records: list[list[bytes]] = []
    for line in header.split(b"\n"):
        if line.startswith(b" "):
            if not records:
                raise HistoryBridgeError("orphan commit header continuation")
            records[-1].append(line)
        else:
            records.append([line])
    for key in (b"tree", b"author", b"committer"):
        matching = [record for record in records if record[0].startswith(key + b" ")]
        if len(matching) != 1 or len(matching[0]) != 1:
            raise HistoryBridgeError(f"invalid {key.decode()} header")
    return records, message


def _parents(raw: bytes) -> list[str]:
    records, _ = _parts(raw)
    return [_oid(record[0][7:].decode("ascii")) for record in records if record[0].startswith(b"parent ")]


def _transform(oid: str, raw: bytes, mapping: Mapping[str, str], fixes: Mapping[str, bytes]) -> bytes:
    records, message = _parts(raw)
    identities = {}
    for role in (b"author", b"committer"):
        value = next(record[0][len(role) + 1:] for record in records if record[0].startswith(role + b" "))
        match = _IDENTITY.fullmatch(value)
        if match is None:
            raise HistoryBridgeError(f"invalid {role.decode()} identity: {oid}")
        identities[role] = match
        if match[2].lower() in _BOT_EMAILS and not (role == b"author" and oid in fixes):
            raise HistoryBridgeError(f"unknown bot {role.decode()}: {oid}")
    for line in message.splitlines():
        if line.lstrip().lower().startswith(b"co-authored-by:") and any(email in line.lower() for email in _BOT_EMAILS):
            raise HistoryBridgeError(f"unknown bot coauthor: {oid}")
    if oid in fixes:
        if (identities[b"author"][2].lower() not in _BOT_EMAILS
                or fixes[oid] != identities[b"committer"][1]):
            raise HistoryBridgeError(f"author fix must use the human committer identity: {oid}")
    changed = False
    updated = []
    for record in records:
        first = record[0]
        replacement = first
        if first.startswith(b"parent "):
            parent = _oid(first[7:].decode("ascii"))
            replacement = b"parent " + mapping.get(parent, parent).encode("ascii")
        elif first.startswith(b"author ") and oid in fixes:
            replacement = b"author " + fixes[oid] + identities[b"author"][3]
        changed |= replacement != first
        updated.append([replacement, *record[1:]])
    if changed:
        updated = [record for record in updated if record[0].split(b" ", 1)[0] not in (b"gpgsig", b"gpgsig-sha256")]
    return b"\n".join(line for record in updated for line in record) + b"\n\n" + message


def _hash(raw: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload(receipt: MappingReceipt) -> dict:
    return {
        "version": 1, "oldmain": receipt.oldmain, "newmain": receipt.newmain,
        "mapping": dict(receipt.mapping), "backup_refs": dict(receipt.backup_refs),
        "backup_zip": str(receipt.backup_zip), "zip_sha256": receipt.zip_sha256,
        "author_fixes": {oid: base64.b64encode(value).decode("ascii") for oid, value in receipt.author_fixes.items()},
    }


def _check_backups(repo: Path, refs: Mapping[str, str], oldmain: str) -> None:
    if not refs or oldmain not in refs.values():
        raise HistoryBridgeError("a backup ref must retain oldmain")
    for ref, expected in refs.items():
        if not isinstance(ref, str) or not ref.startswith("refs/"):
            raise HistoryBridgeError("backup ref must be fully qualified")
        _oid(expected)
        actual = _git(repo, "show-ref", "--verify", "--hash", ref).decode().strip()
        if actual != expected:
            raise HistoryBridgeError(f"backup ref moved: {ref}")


def _validate_pairs(reader: _RawCommits, mapping: Mapping[str, str], fixes: Mapping[str, bytes]) -> None:
    for old, new in mapping.items():
        _oid(old)
        _oid(new)
        expected = _transform(old, reader.get(old), mapping, fixes)
        if expected != reader.get(new):
            raise HistoryBridgeError(f"raw commit transformation mismatch: {old}")
    _check_unmapped_ancestry(reader, mapping)


def _check_unmapped_ancestry(reader: _RawCommits, mapping: Mapping[str, str]) -> None:
    # A valid pair is not sufficient to make it a stopping boundary: a partial
    # seed could otherwise hide a missing object or bot behind a human node.
    # Unlisted human ancestors are allowed, but inspect their complete raw DAG.
    checked = set(mapping) | set(mapping.values())
    pending = [parent for old in mapping for parent in _parents(reader.get(old)) if parent not in checked]
    while pending:
        oid = pending.pop()
        if oid in checked:
            continue
        raw = reader.get(oid)
        _transform(oid, raw, {}, {})
        checked.add(oid)
        pending.extend(parent for parent in _parents(raw) if parent not in checked)


def _write_objects(repo: Path, objects: Mapping[str, bytes]) -> None:
    if not objects:
        return
    with tempfile.TemporaryDirectory(prefix="history-bridge-") as directory:
        paths = []
        for oid, raw in objects.items():
            path = Path(directory) / oid
            path.write_bytes(raw)
            quoted = path.as_posix().encode("utf-8").replace(b"\\", b"\\\\").replace(b'"', b'\\"')
            paths.append(b'"' + quoted + b'"\n')
        result = _git(repo, "hash-object", "-w", "-t", "commit", "--stdin-paths", data=b"".join(paths))
        if result.decode().splitlines() != list(objects):
            raise HistoryBridgeError("native object IDs disagree with the candidate mapping")


def rewrite_commit_dag(
    repo: Path, oldmain: str, *, author_fixes: dict[str, bytes], backup_zip: Path,
    receipt_path: Path, backup_refs: dict[str, str], seed_map: dict[str, str] | None = None,
) -> MappingReceipt:
    """Back up raw commits, then construct a candidate DAG without changing refs."""
    repo, backup_zip, receipt_path = Path(repo), Path(backup_zip).resolve(), Path(receipt_path).resolve()
    oldmain = _resolve(repo, oldmain)
    _check_backups(repo, backup_refs, oldmain)
    if backup_zip == receipt_path or backup_zip.exists() or receipt_path.exists():
        raise HistoryBridgeError("backup and receipt paths must be distinct new files")
    algorithm = _git(repo, "rev-parse", "--show-object-format").decode().strip()
    seed = dict(seed_map or {})
    mapping: dict[str, str] = {}
    objects: dict[str, bytes] = {}
    with _RawCommits(repo) as reader:
        _validate_pairs(reader, seed, author_fixes)
        ancestors = _git(repo, "rev-list", "--topo-order", "--reverse", oldmain).decode().splitlines()
        for oid in ancestors:
            original = reader.get(oid)
            translated = _transform(oid, original, mapping, author_fixes)
            new = _hash(translated, algorithm)
            mapping[oid] = new
            if original != translated:
                objects[new] = translated
        for old, previous in seed.items():
            final = mapping.get(previous, previous)
            if old in mapping and mapping[old] != final:
                raise HistoryBridgeError(f"seed conflicts with candidate mapping: {old}")
            mapping[old] = final
        if set(author_fixes) - mapping.keys():
            raise HistoryBridgeError("author fix is outside the backed-up mapping")
        # Validate composition before writing either evidence or new Git objects.
        for old, new in mapping.items():
            expected = _transform(old, reader.get(old), mapping, author_fixes)
            actual = objects[new] if new in objects else reader.get(new)
            if expected != actual:
                raise HistoryBridgeError(f"composed raw transformation mismatch: {old}")
        _check_unmapped_ancestry(reader, mapping)
        backup_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_zip, "x", compression=zipfile.ZIP_STORED) as archive:
            for oid in sorted(mapping):
                archive.writestr(f"commits/{oid}", reader.get(oid))
        _write_objects(repo, objects)
    receipt = MappingReceipt(
        oldmain, mapping[oldmain], MappingProxyType(mapping), "", MappingProxyType(dict(backup_refs)),
        backup_zip, _file_digest(backup_zip), MappingProxyType(dict(author_fixes)), receipt_path,
    )
    payload = _payload(receipt)
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump({**payload, "digest": digest}, target, sort_keys=True, indent=2)
        target.write("\n")
    return read_mapping_receipt(repo, receipt_path)


def read_mapping_receipt(repo: Path, receipt_path: Path) -> MappingReceipt:
    """Verify the JSON, backup refs, ZIP, and every raw old/new commit pair."""
    try:
        receipt_path = Path(receipt_path).resolve()
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
        digest = value.pop("digest")
        if value.get("version") != 1 or hashlib.sha256(_canonical(value)).hexdigest() != digest:
            raise HistoryBridgeError("receipt digest mismatch")
        receipt = MappingReceipt(
            _oid(value["oldmain"]), _oid(value["newmain"]), MappingProxyType(dict(value["mapping"])), digest,
            MappingProxyType(dict(value["backup_refs"])), Path(value["backup_zip"]), value["zip_sha256"],
            MappingProxyType({oid: base64.b64decode(identity, validate=True) for oid, identity in value["author_fixes"].items()}),
            receipt_path,
        )
        if _payload(receipt) != value or not receipt.backup_zip.is_absolute():
            raise HistoryBridgeError("invalid receipt structure")
        if receipt.mapping.get(receipt.oldmain) != receipt.newmain or set(receipt.author_fixes) - receipt.mapping.keys():
            raise HistoryBridgeError("receipt main or author mapping mismatch")
        _check_backups(Path(repo), receipt.backup_refs, receipt.oldmain)
        if _file_digest(receipt.backup_zip) != receipt.zip_sha256:
            raise HistoryBridgeError("backup ZIP digest mismatch")
        ancestors = set(_git(Path(repo), "rev-list", receipt.oldmain).decode().splitlines())
        if not ancestors <= receipt.mapping.keys():
            raise HistoryBridgeError("receipt omits oldmain ancestors")
        with _RawCommits(Path(repo)) as reader, zipfile.ZipFile(receipt.backup_zip) as archive:
            expected = {f"commits/{oid}" for oid in receipt.mapping}
            if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
                raise HistoryBridgeError("backup ZIP commit inventory mismatch")
            for oid in receipt.mapping:
                if archive.read(f"commits/{oid}") != reader.get(oid):
                    raise HistoryBridgeError(f"raw commit backup mismatch: {oid}")
            _validate_pairs(reader, receipt.mapping, receipt.author_fixes)
        return receipt
    except HistoryBridgeError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, zipfile.BadZipFile) as error:
        raise HistoryBridgeError(f"invalid mapping receipt: {error}") from error


def _verified(repo: Path, receipt: MappingReceipt) -> MappingReceipt:
    verified = read_mapping_receipt(repo, receipt.receipt_path)
    if verified.digest != receipt.digest or _payload(verified) != _payload(receipt):
        raise HistoryBridgeError("in-memory receipt differs from its verified file")
    return verified


def translate_task_dag(repo: Path, task_tip: str, receipt: MappingReceipt) -> TranslationResult:
    """Translate task parents across known history; write objects only, never refs."""
    repo = Path(repo)
    receipt = _verified(repo, receipt)
    tip = _resolve(repo, task_tip)
    mapping = dict(receipt.mapping)
    # Already translated nodes are equally valid, immutable stopping boundaries.
    boundaries = set(mapping.values())
    algorithm = _git(repo, "rev-parse", "--show-object-format").decode().strip()
    objects: dict[str, bytes] = {}
    with _RawCommits(repo) as reader:
        pending = [(tip, False)]
        while pending:
            oid, visited = pending.pop()
            if oid in mapping:
                continue
            if oid in boundaries:
                mapping[oid] = oid
                continue
            raw = reader.get(oid)
            if not visited:
                # Reject all new bot attribution even if an unrelated fix is in the receipt.
                _transform(oid, raw, {}, {})
                pending.append((oid, True))
                pending.extend((parent, False) for parent in reversed(_parents(raw)) if parent not in mapping)
            else:
                translated = _transform(oid, raw, mapping, {})
                new = _hash(translated, algorithm)
                mapping[oid] = new
                if raw != translated:
                    objects[new] = translated
    _write_objects(repo, objects)
    return TranslationResult(mapping[tip], MappingProxyType(mapping))


def task_base(repo: Path, receipt: MappingReceipt, head: str = "HEAD") -> str:
    """Return the real old-history fork point; ambiguous/criss-cross bases fail."""
    receipt = _verified(Path(repo), receipt)
    bases = _git(Path(repo), "merge-base", "--all", receipt.oldmain, _resolve(Path(repo), head)).decode().splitlines()
    if len(bases) != 1:
        raise HistoryBridgeError("task history must have exactly one oldmain merge base")
    return _oid(bases[0])


def load_active_mapping(repo: Path) -> MappingReceipt | None:
    """Load the strict common-dir pointer; malformed/stale evidence never falls back."""
    repo = Path(repo)
    common = Path(os.fsdecode(_git(repo, "rev-parse", "--git-common-dir").strip()))
    if not common.is_absolute():
        common = repo / common
    directory = (common / "vibelution-cache" / "history-bridge").resolve()
    active = directory / "active.json"
    if not active.exists():
        return None
    try:
        pointer = json.loads(active.read_text(encoding="utf-8"))
        if set(pointer) != {"receipt", "digest"} or not isinstance(pointer["receipt"], str):
            raise HistoryBridgeError("invalid active history mapping pointer")
        path = Path(pointer["receipt"])
        if not path.is_absolute() or not path.resolve().is_relative_to(directory):
            raise HistoryBridgeError("active receipt must be inside the common history-bridge directory")
        receipt = read_mapping_receipt(repo, path)
        if receipt.digest != pointer["digest"]:
            raise HistoryBridgeError("active receipt digest mismatch")
        current_main = _resolve(repo, "refs/heads/main")
        if _is_ancestor(repo, receipt.newmain, current_main):
            return receipt
        if _is_ancestor(repo, receipt.oldmain, current_main):
            # The pointer is published before the main compare-and-swap. Until
            # that succeeds, existing task claims still use the original DAG.
            return None
        raise HistoryBridgeError("active receipt is unrelated to current main")
    except HistoryBridgeError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HistoryBridgeError(f"invalid active history mapping: {error}") from error
