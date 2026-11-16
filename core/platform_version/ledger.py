"""Local platform-version ledger.

The product version is a local evolution cadence, not a distributable release
identity: nothing in this module participates in packaging, publishing or update
admission. The append-only ledger is the authority. ``VERSION`` and
``CHANGELOG.md`` are projections that are written only when a caller explicitly
asks for a sync, so a settled version can legitimately run ahead of both files.

Ratified cadence (operator decision):

* every settled user-visible change advances one small version (PATCH);
* five small versions collapse into one middle version (MINOR);
* ten middle versions collapse into one major version (MAJOR);
* tests, docs-only edits and pure refactors do not settle, because they do not
  leave a ``## Unreleased`` entry for the settler to consume.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PATCH_PER_MINOR = 5
MINOR_PER_MAJOR = 10
LEDGER_FILENAME = "ledger.jsonl"
VERSION_FILENAME = "VERSION"
CHANGELOG_FILENAME = "CHANGELOG.md"

_LEDGER_LOCK = threading.Lock()
_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)\s*$")
_UNRELEASED_RE = re.compile(r"^##\s+Unreleased\s*$", re.MULTILINE)
_HEADING_TWO_RE = re.compile(r"^##\s+\S", re.MULTILINE)
_HEADING_THREE_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Cadence:
    """A strict-carry version position plus a monotonic build counter."""

    major: int = 0
    minor: int = 0
    patch: int = 0
    build: int = 0

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class UnreleasedEntry:
    """The settled slice of ``CHANGELOG.md``'s Unreleased section."""

    digest: str
    summary: str
    kind: str
    body: str


@dataclass(frozen=True)
class VersionEntry:
    """One ledger record. ``anchor`` is baseline, settle or sync."""

    seq: int
    version: str
    build: int
    head_sha: str
    head_subject: str
    kind: str
    summary: str
    changelog_digest: str
    recorded_at: str
    anchor: str

    def to_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "version": self.version,
            "build": self.build,
            "head_sha": self.head_sha,
            "head_subject": self.head_subject,
            "kind": self.kind,
            "summary": self.summary,
            "changelog_digest": self.changelog_digest,
            "recorded_at": self.recorded_at,
            "anchor": self.anchor,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> VersionEntry:
        return cls(
            seq=int(payload.get("seq", 0)),
            version=str(payload.get("version", "0.0.0")),
            build=int(payload.get("build", 0)),
            head_sha=str(payload.get("head_sha", "")),
            head_subject=str(payload.get("head_subject", "")),
            kind=str(payload.get("kind", "fix")),
            summary=str(payload.get("summary", "")),
            changelog_digest=str(payload.get("changelog_digest", "")),
            recorded_at=str(payload.get("recorded_at", "")),
            anchor=str(payload.get("anchor", "settle")),
        )


def advance(cadence: Cadence) -> Cadence:
    """Advance exactly one small version, carrying at 5 and 10."""

    patch = cadence.patch + 1
    minor = cadence.minor
    major = cadence.major
    if patch >= PATCH_PER_MINOR:
        patch = 0
        minor += 1
        if minor >= MINOR_PER_MAJOR:
            minor = 0
            major += 1
    return Cadence(major=major, minor=minor, patch=patch, build=cadence.build + 1)


def parse_version(value: str) -> Cadence | None:
    """Parse ``X.Y.Z`` (a leading ``v`` is tolerated) or return ``None``."""

    match = _VERSION_RE.match(value or "")
    if match is None:
        return None
    return Cadence(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        build=0,
    )


def _normalize_block(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed: list[str] = []
    for line in lines:
        if not line.strip() and (not collapsed or not collapsed[-1].strip()):
            continue
        collapsed.append(line)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()
    return "\n".join(collapsed).strip()


def _section_bodies(block: str) -> dict[str, str]:
    matches = list(_HEADING_THREE_RE.finditer(block))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        sections[match.group(1).strip().lower()] = block[match.end():end].strip()
    return sections


def _classify(block: str) -> str:
    sections = _section_bodies(block)
    if sections.get("breaking", "").strip():
        return "breaking"
    if sections.get("added", "").strip():
        return "feature"
    return "fix"


def _summary(block: str) -> str:
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("-", "*")):
            stripped = stripped[1:].strip()
        return stripped[:160]
    return ""


def extract_unreleased(changelog: str) -> UnreleasedEntry | None:
    """Return the Unreleased slice, or ``None`` when nothing is declared.

    An empty Unreleased section is the normal state for tests, docs-only edits
    and pure refactors, which is exactly how "do not number tests" is enforced:
    the settler has nothing to consume.
    """

    start = _UNRELEASED_RE.search(changelog or "")
    if start is None:
        return None
    rest = changelog[start.end():]
    following = _HEADING_TWO_RE.search(rest)
    body = rest[: following.start()] if following is not None else rest
    normalized = _normalize_block(body)
    if not normalized:
        return None
    return UnreleasedEntry(
        digest=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        summary=_summary(normalized),
        kind=_classify(normalized),
        body=normalized,
    )


def read_changelog(project_root: Path) -> str:
    try:
        return (Path(project_root) / CHANGELOG_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return ""


def read_version_file(project_root: Path) -> str:
    try:
        return (Path(project_root) / VERSION_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def resolve_ledger_path(project_root: Path | str) -> Path:
    """Resolve the ledger path outside the checkout.

    The ledger never enters Git, so it cannot dirty ``main`` and cannot become a
    second source of truth for a packaged product that does not exist.
    """

    override = os.environ.get("VIBELUTION_PLATFORM_VERSION_ROOT", "").strip()
    if override:
        return Path(override).expanduser() / LEDGER_FILENAME
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        base = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    workspace = Path(project_root).expanduser().resolve(strict=False)
    token = os.path.normcase(str(workspace)).replace("\\", "/")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]
    return root / "Vibelution" / "projects" / digest / "platform-version" / LEDGER_FILENAME


class VersionLedger:
    """Append-only version ledger owned by this workspace."""

    def __init__(self, project_root: Path | str, *, ledger_path: Path | str | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve(strict=False)
        self.path = Path(ledger_path) if ledger_path is not None else resolve_ledger_path(self.project_root)

    def read(self) -> list[VersionEntry]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        entries: list[VersionEntry] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                entries.append(VersionEntry.from_json(payload))
        entries.sort(key=lambda entry: entry.seq)
        return entries

    def append(self, entry: VersionEntry) -> VersionEntry:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_json(), ensure_ascii=False, separators=(",", ":"))
        with _LEDGER_LOCK, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def tail(self) -> VersionEntry | None:
        entries = self.read()
        return entries[-1] if entries else None

    def baseline_version(self) -> str:
        return read_version_file(self.project_root) or "0.0.0"

    def ensure_baseline(self, *, build_hint: int = 0) -> VersionEntry:
        """Seed the ledger from ``VERSION`` exactly once.

        Existing tags are deliberately not replayed: they predate the ledger and
        replaying them would invent history that was never settled.
        """

        entries = self.read()
        if entries:
            return entries[0]
        version = self.baseline_version()
        cadence = parse_version(version) or Cadence()
        entry = VersionEntry(
            seq=1,
            version=cadence.version,
            build=max(0, int(build_hint)),
            head_sha="",
            head_subject="baseline from VERSION",
            kind="baseline",
            summary=f"Ledger baseline adopted at {cadence.version}.",
            changelog_digest="",
            recorded_at=_now(),
            anchor="baseline",
        )
        self.append(entry)
        return entry

    def settle(
        self,
        *,
        head_sha: str,
        head_subject: str,
        unreleased: UnreleasedEntry,
    ) -> VersionEntry | None:
        """Record one settled change. Returns ``None`` when already recorded."""

        entries = self.read()
        if any(entry.head_sha and entry.head_sha == head_sha for entry in entries):
            return None
        if any(entry.changelog_digest and entry.changelog_digest == unreleased.digest for entry in entries):
            return None
        if entries:
            base = parse_version(entries[-1].version) or Cadence()
            base = Cadence(base.major, base.minor, base.patch, entries[-1].build)
            seq = entries[-1].seq + 1
        else:
            seeded = self.ensure_baseline()
            base = parse_version(seeded.version) or Cadence()
            base = Cadence(base.major, base.minor, base.patch, seeded.build)
            seq = seeded.seq + 1
        nxt = advance(base)
        entry = VersionEntry(
            seq=seq,
            version=nxt.version,
            build=nxt.build,
            head_sha=head_sha,
            head_subject=head_subject,
            kind=unreleased.kind,
            summary=unreleased.summary,
            changelog_digest=unreleased.digest,
            recorded_at=_now(),
            anchor="settle",
        )
        return self.append(entry)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def snapshot(project_root: Path | str, *, ledger_path: Path | str | None = None) -> dict[str, Any]:
    """Project the ledger plus the on-disk anchor for the UI."""

    ledger = VersionLedger(project_root, ledger_path=ledger_path)
    entries = ledger.read()
    tail = entries[-1] if entries else None
    file_version = read_version_file(Path(project_root))
    unreleased = extract_unreleased(read_changelog(Path(project_root)))
    cadence = parse_version(tail.version) if tail is not None else (parse_version(file_version) or Cadence())
    assert cadence is not None
    return {
        "ledgerPath": str(ledger.path),
        "currentVersion": tail.version if tail is not None else cadence.version,
        "build": tail.build if tail is not None else 0,
        "cadence": {
            "major": cadence.major,
            "minor": cadence.minor,
            "patch": cadence.patch,
            "patchPerMinor": PATCH_PER_MINOR,
            "minorPerMajor": MINOR_PER_MAJOR,
        },
        "progress": {
            "patchInMinor": cadence.patch,
            "minorInMajor": cadence.minor,
        },
        "fileVersion": file_version,
        "fileBehind": bool(file_version and file_version != (tail.version if tail is not None else cadence.version)),
        "unreleasedPending": unreleased is not None,
        "unreleasedSummary": unreleased.summary if unreleased is not None else "",
        "entries": [entry.to_json() for entry in reversed(entries[-20:])],
    }
