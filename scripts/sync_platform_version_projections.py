"""Project the platform-version ledger tail into the repository files.

The append-only ledger outside the checkout is the version authority (see
``core/platform_version/ledger.py``). ``VERSION``, ``web/package.json``,
``web/package-lock.json`` and ``CHANGELOG.md`` are projections that only move
when a caller explicitly asks for a sync. This script is that caller:

1. Settle any pending ``## Unreleased`` declaration through
   ``VersionLedger.settle`` -- the exact dedup rules (head SHA plus changelog
   digest) the in-product watcher uses, so a settlement that already happened
   is never counted twice.
2. When the ledger tail differs from ``VERSION``, rewrite the three version
   files so ``tests/test_product_version.py`` stays true, and archive the
   consumed Unreleased entries verbatim under ``## <version> - <date>``.
3. Commit everything as one atomic commit (``release: record product version
   X.Y.Z``). On ``main`` the commit moves the guarded ref through the
   integration permit path (``commit-tree`` plus a claim-bound permit)
   instead of a plain ``git commit``.

Anti-loop property: the sync commit leaves ``## Unreleased`` empty, so the
settler has nothing to consume on the sync commit itself, and the digest
dedup refuses to resettle archived content. Running the sync twice is a
no-op with zero commits.

Cadence boundaries: when the projection crosses a minor (5 patches) or major
(10 minors) edge, the result carries a ``boundary`` payload with the
``vX.Y.0`` tag name and the CHANGELOG text of the version range, for the
closeout step to turn into an annotated tag and a GitHub release.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.no_console_git import run_git
from core.platform_version.ledger import (
    Cadence,
    VersionLedger,
    advance,
    extract_unreleased,
    parse_version,
    read_changelog,
    read_version_file,
)

COMMIT_MESSAGE_PREFIX = "release: record product version"
VERSION_FILES = ("VERSION", str(Path("web") / "package.json"), str(Path("web") / "package-lock.json"))
_CHANGELOG = "CHANGELOG.md"
_UNRELEASED_HEADING = "## Unreleased"
_RELEASED_HEADING_RE = re.compile(r"^##\s+v?(\d+)\.(\d+)\.(\d+)\s*-\s*(\S.*)?$")


class SyncError(RuntimeError):
    """One bounded, actionable sync failure surfaced in the result envelope."""


class _GitError(SyncError):
    pass


def _git(root: Path, *args: str, timeout: float = 15.0) -> str:
    result = run_git(list(args), cwd=root, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise _GitError(f"git {' '.join(args[:3])} failed: {detail[:200]}")
    return result.stdout.strip()


def _resolve_head(root: Path) -> tuple[str, str] | None:
    try:
        sha = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
        subject = _git(root, "log", "-1", "--format=%s", sha)
    except SyncError:
        return None
    return sha, subject


def _released_blocks(changelog_text: str) -> list[tuple[tuple[int, int, int], list[str]]]:
    """Return ``((major, minor, patch), block_lines)`` for every released block."""

    lines = changelog_text.splitlines()
    headings = [
        (index, _RELEASED_HEADING_RE.match(line.strip()))
        for index, line in enumerate(lines)
        if line.strip().startswith("## ")
    ]
    blocks: list[tuple[tuple[int, int, int], list[str]]] = []
    for position, (index, match) in enumerate(headings):
        if match is None:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        block = [line for line in lines[index:end]]
        while block and not block[-1].strip():
            block.pop()
        version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        blocks.append((version, block))
    return blocks


def archive_unreleased(
    changelog_text: str,
    *,
    version: str,
    date_label: str,
) -> tuple[str, list[str]]:
    """Move the Unreleased body verbatim under ``## <version> - <date>``.

    Returns the new changelog text and the archived lines. Interior blank
    lines and wording are preserved exactly; only leading and trailing blank
    lines of the section are dropped.
    """

    lines = changelog_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == _UNRELEASED_HEADING:
            start = index
            break
    if start is None:
        raise SyncError(f"{_CHANGELOG} has no '{_UNRELEASED_HEADING}' heading")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("## "):
            end = index
            break
    body = lines[start + 1 : end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        return changelog_text, []
    heading = f"## {version} - {date_label}"
    rebuilt = [*lines[: start + 1], "", heading, *body, "", *lines[end:]]
    return "\n".join(rebuilt) + "\n", body


def _json_with_version(path: Path, version: str) -> str:
    """Rewrite the top-level (and lockfile root-package) version in place.

    ``json.dumps(indent=2)`` is byte-identical to npm's own formatting for
    these files (verified by round-trip tests), so the resulting diff touches
    the version fields only.
    """

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    payload["version"] = version
    packages = payload.get("packages")
    if isinstance(packages, dict) and "" in packages and isinstance(packages[""], dict):
        packages[""]["version"] = version
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _already_recorded(
    entries: list[Any],
    *,
    unreleased_digest: str,
    head_sha: str,
) -> bool:
    return any(
        (entry.changelog_digest and entry.changelog_digest == unreleased_digest)
        or (head_sha and entry.head_sha and entry.head_sha == head_sha)
        for entry in entries
    )


def _predict_settlement(
    ledger: VersionLedger,
    root: Path,
    *,
    unreleased_digest: str,
    head_sha: str,
) -> tuple[bool, str]:
    """The version the ledger tail will have after settlement, without writing.

    Mirrors ``VersionLedger.settle``: the digest/head dedup first, then one
    advance from the current position (seeding the baseline from ``VERSION``
    when the ledger is still empty).
    """

    entries = ledger.read()
    if _already_recorded(entries, unreleased_digest=unreleased_digest, head_sha=head_sha):
        current = entries[-1].version if entries else (read_version_file(root) or "0.0.0")
        return False, current
    if entries:
        tail = parse_version(entries[-1].version) or Cadence()
        base = Cadence(tail.major, tail.minor, tail.patch, entries[-1].build)
    else:
        base = parse_version(read_version_file(root) or "") or Cadence()
    return True, advance(base).version


def _boundary(
    old_version: str,
    new_version: str,
    changelog_text: str,
) -> dict[str, Any] | None:
    old = parse_version(old_version or "") or Cadence()
    new = parse_version(new_version or "")
    if new is None:
        return None
    if (new.major, new.minor) == (old.major, old.minor):
        return None
    kind = "major" if new.major != old.major else "minor"
    old_tuple = (old.major, old.minor, old.patch)
    new_tuple = (new.major, new.minor, new.patch)
    notes: list[str] = []
    for version, block in _released_blocks(changelog_text):
        if old_tuple < version <= new_tuple:
            notes.append("\n".join(block))
    return {
        "kind": kind,
        "version": new.version,
        "tag": f"v{new.major}.{new.minor}.0",
        "notes": "\n\n".join(notes),
    }


def _commit_sync(
    root: Path,
    files: Sequence[str],
    message: str,
    *,
    integration_claim_id: str,
) -> tuple[str, str]:
    """Stage ``files`` and commit them as exactly one commit. Returns (sha, mode).

    On a task branch this is a plain ``git commit`` (the pre-commit guard
    auto-claims the staged paths). On ``main`` a plain commit is rejected by
    the reference-transaction guard, so the commit is built with plumbing and
    moved through a claim-bound main-update permit instead.
    """

    branch = _git(root, "branch", "--show-current")
    _git(root, "add", "--", *files)
    if branch != "main":
        _git(root, "commit", "-m", message)
        return _git(root, "rev-parse", "HEAD"), "commit"
    if not integration_claim_id:
        raise SyncError(
            "main_update_permit_required: syncing on main needs --integration-claim-id"
        )
    from scripts import git_claim_guard as claim_guard

    old_sha = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "write-tree")
    new_sha = _git(root, "commit-tree", tree, "-p", old_sha, "-m", message)
    claim_guard.issue_main_permit(
        root,
        old_sha=old_sha,
        new_sha=new_sha,
        integration_claim_id=integration_claim_id,
    )
    try:
        _git(root, "update-ref", "refs/heads/main", new_sha, old_sha)
    finally:
        claim_guard.clear_main_permit(root)
    return new_sha, "permit"


def sync_version_projections(
    repo: Path | str,
    *,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
    commit: bool = True,
    integration_claim_id: str = "",
    today: str | None = None,
) -> dict[str, Any]:
    """Settle + project the ledger tail. Returns one JSON-ready payload."""

    root = Path(repo).resolve()
    date_label = today or datetime.now().strftime("%Y-%m-%d")
    warnings: list[str] = []
    errors: list[str] = []
    result: dict[str, Any] = {
        "ok": False,
        "dryRun": dry_run,
        "repo": str(root),
        "ledgerPath": "",
        "settled": False,
        "settleDigest": None,
        "oldVersion": "",
        "newVersion": "",
        "versionChanged": False,
        "archive": {"needed": False, "lines": 0},
        "changedFiles": [],
        "committed": False,
        "commitSha": "",
        "commitMessage": "",
        "boundary": None,
        "warnings": warnings,
        "errors": errors,
    }
    try:
        ledger = VersionLedger(root, ledger_path=ledger_path)
        result["ledgerPath"] = str(ledger.path)
        changelog_text = read_changelog(root)
        old_version = read_version_file(root)
        unreleased = extract_unreleased(changelog_text)
        head = _resolve_head(root)
        head_sha = head[0] if head else ""

        if unreleased is None:
            planned_settled, planned_version = False, ""
            tail = ledger.tail()
            if tail is None:
                warnings.append("ledger_empty: nothing settled yet; run the product once or seed VERSION")
                planned_version = old_version or "0.0.0"
            else:
                planned_version = tail.version
        else:
            planned_settled, planned_version = _predict_settlement(
                ledger,
                root,
                unreleased_digest=unreleased.digest,
                head_sha=head_sha,
            )
        result["settleDigest"] = unreleased.digest if unreleased is not None else None
        result["oldVersion"] = old_version
        result["newVersion"] = planned_version
        result["settled"] = planned_settled

        if dry_run:
            # The plan is what the real run would do with the same inputs:
            # settle the pending declaration (unless already recorded) and
            # project the predicted tail.
            consumed = unreleased is not None and (
                planned_settled
                or _already_recorded(
                    ledger.read(),
                    unreleased_digest=unreleased.digest,
                    head_sha=head_sha,
                )
            )
            result["archive"] = {"needed": consumed, "lines": 0}
            new_changelog = changelog_text
            version_changed = bool(planned_version) and planned_version != old_version
            if version_changed:
                result["versionChanged"] = True
                result["changedFiles"] = list(VERSION_FILES)
            if consumed and planned_version:
                new_changelog, archived = archive_unreleased(
                    changelog_text, version=planned_version, date_label=date_label,
                )
                result["archive"] = {"needed": True, "lines": len(archived)}
                if _CHANGELOG not in result["changedFiles"]:
                    result["changedFiles"].append(_CHANGELOG)
            if version_changed:
                result["boundary"] = _boundary(old_version, planned_version, new_changelog)
            result["ok"] = True
            return result

        settled = False
        if unreleased is not None:
            if head is None:
                warnings.append("unreleased_pending_head_unresolved: cannot settle without HEAD")
            else:
                entry = ledger.settle(
                    head_sha=head_sha,
                    head_subject=head[1],
                    unreleased=unreleased,
                )
                settled = entry is not None
        result["settled"] = settled

        tail = ledger.tail()
        if tail is None:
            errors.append("ledger_empty: no settlement available to project")
            return result
        new_version = tail.version
        result["newVersion"] = new_version
        entries = ledger.read()
        consumed = (
            settled
            or (
                unreleased is not None
                and _already_recorded(
                    entries,
                    unreleased_digest=unreleased.digest,
                    head_sha=head_sha,
                )
            )
        )

        new_changelog = changelog_text
        changed_files: list[str] = []
        version_changed = new_version != old_version
        if version_changed:
            (root / "VERSION").write_text(f"{new_version}\n", encoding="utf-8", newline="\n")
            (root / "web" / "package.json").write_text(
                _json_with_version(root / "web" / "package.json", new_version),
                encoding="utf-8",
                newline="\n",
            )
            (root / "web" / "package-lock.json").write_text(
                _json_with_version(root / "web" / "package-lock.json", new_version),
                encoding="utf-8",
                newline="\n",
            )
            changed_files.extend(VERSION_FILES)
        if unreleased is not None and consumed:
            new_changelog, archived = archive_unreleased(
                changelog_text, version=new_version, date_label=date_label,
            )
            result["archive"] = {"needed": True, "lines": len(archived)}
            if archived:
                (root / _CHANGELOG).write_text(new_changelog, encoding="utf-8", newline="\n")
                changed_files.append(_CHANGELOG)
        elif unreleased is not None:
            warnings.append(
                "unreleased_not_consumed: the ledger has not recorded this "
                "declaration; leaving it in place for the settler"
            )
        result["versionChanged"] = version_changed
        result["changedFiles"] = changed_files
        if version_changed:
            result["boundary"] = _boundary(old_version, new_version, new_changelog)

        if changed_files and commit:
            message = f"{COMMIT_MESSAGE_PREFIX} {new_version}"
            sha, mode = _commit_sync(
                root,
                changed_files,
                message,
                integration_claim_id=integration_claim_id,
            )
            result["committed"] = True
            result["commitSha"] = sha
            result["commitMessage"] = message
            result["commitMode"] = mode
        result["ok"] = True
        return result
    except SyncError as error:
        errors.append(str(error))
        return result
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"{type(error).__name__}: {str(error)[:200]}")
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project the platform-version ledger into VERSION, web metadata and CHANGELOG.md.",
    )
    parser.add_argument("--repo", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ledger", type=Path, default=None, help="Explicit ledger path override.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing anything.")
    parser.add_argument("--no-commit", action="store_true", help="Write files but leave them uncommitted.")
    parser.add_argument(
        "--integration-claim-id",
        default="",
        help="Integration claim id backing the main-update permit when syncing on main.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    payload = sync_version_projections(
        arguments.repo,
        ledger_path=arguments.ledger,
        dry_run=arguments.dry_run,
        commit=not arguments.no_commit,
        integration_claim_id=arguments.integration_claim_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
