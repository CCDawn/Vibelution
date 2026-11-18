"""Backfill the platform version ledger for merges that predate the guard.

The ledger advances only when the ``## Unreleased`` section actually changes.
Every merge that landed without a declaration was therefore skipped forever.
This tool replays the recent merge history as explicit ``backfill`` entries so
the version number reflects what actually shipped instead of stalling at the
last declared change.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.platform_version.ledger import Cadence, VersionEntry, VersionLedger, advance, parse_version


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def _unit_subject(subject: str) -> str:
    """Keep the conventional-commit subject; merges only carry sync noise."""

    text = subject.strip()
    if text.startswith("Merge branch '") or text.startswith("Merge remote-tracking"):
        return ""
    return text


def collect_units(repo: Path, *, limit: int, known: set[str]) -> list[tuple[str, str]]:
    output = _git(repo, "log", "--no-merges", "--format=%H%x1f%s", "-n", str(limit * 6), "main")
    units: list[tuple[str, str]] = []
    for line in output.splitlines():
        sha, _, subject = line.partition("\x1f")
        if not sha or sha in known:
            continue
        text = _unit_subject(subject)
        if not text:
            continue
        units.append((sha, text))
        if len(units) >= limit:
            break
    return units


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill platform version entries from merge history.")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    ledger = VersionLedger(repo)
    entries = ledger.read()
    if not entries:
        print("backfill: ledger is empty; run the watcher once to seed a baseline first")
        return 1

    known = {entry.head_sha for entry in entries if entry.head_sha}
    units = collect_units(repo, limit=max(1, args.limit), known=known)
    if not units:
        print("backfill: nothing to add")
        return 0

    base = entries[-1]
    cadence = parse_version(base.version) or Cadence()
    cadence = Cadence(cadence.major, cadence.minor, cadence.patch, base.build)
    seq = base.seq
    planned: list[tuple[int, str, int, str, str]] = []
    for sha, subject in reversed(units):
        cadence = advance(cadence)
        seq += 1
        planned.append((seq, cadence.version, cadence.build, sha, subject))

    if args.dry_run:
        for seq_value, version, build, sha, subject in planned:
            print(f"  {version} build {build}  {sha[:12]}  {subject}")
        print(f"backfill: would add {len(planned)} entries")
        return 0

    for seq_value, version, build, sha, subject in planned:
        ledger.append(
            VersionEntry(
                seq=seq_value,
                version=version,
                build=build,
                head_sha=sha,
                head_subject=subject,
                kind="backfill",
                summary=subject,
                changelog_digest=f"backfill:{sha[:16]}",
                recorded_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
                anchor="backfill",
            )
        )

    final = planned[-1]
    print(f"backfill: appended {len(planned)} entries; version now {final[1]} build {final[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
