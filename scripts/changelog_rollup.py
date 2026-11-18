"""Fold task-local `.changelog/*.md` declarations into CHANGELOG.md.

Parallel tasks declare their change in their own file so they never contend for
the single CHANGELOG.md claim. Before a merge, this script appends those lines
under ``## Unreleased`` and removes the task files it consumed.

Idempotent: a line already present in the Unreleased section is skipped, so
running it twice does not duplicate entries.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

CHANGELOG = "CHANGELOG.md"
DECLARATION_DIR = ".changelog"
UNRELEASED_HEADING = "## Unreleased"


def declaration_entries(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line.rstrip() for line in text.splitlines() if line.strip().startswith("-")]


def section_bounds(lines: list[str]) -> tuple[int, int]:
    start = None
    for index, line in enumerate(lines):
        if line.strip() == UNRELEASED_HEADING:
            start = index + 1
            break
    if start is None:
        raise SystemExit(f"[changelog-rollup] {CHANGELOG} has no '{UNRELEASED_HEADING}' heading")
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].strip().startswith("## "):
            end = index
            break
    while end > start and not lines[end - 1].strip():
        end -= 1
    return start, end


def rollup(repo: Path, *, dry_run: bool = False) -> dict[str, object]:
    changelog = repo / CHANGELOG
    if not changelog.is_file():
        raise SystemExit(f"[changelog-rollup] {CHANGELOG} not found in {repo}")
    lines = changelog.read_text(encoding="utf-8").splitlines()
    start, end = section_bounds(lines)
    existing = {line.strip() for line in lines[start:end]}

    collected: list[str] = []
    sources: list[Path] = []
    directory = repo / DECLARATION_DIR
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        entries = declaration_entries(path)
        if not entries:
            continue
        sources.append(path)
        for entry in entries:
            if entry.strip() not in existing:
                collected.append(entry)
                existing.add(entry.strip())

    if not collected:
        return {"inserted": 0, "sources": [path.name for path in sources]}

    lines[end:end] = collected
    if not dry_run:
        changelog.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        for path in sources:
            path.unlink(missing_ok=True)
    return {"inserted": len(collected), "sources": [path.name for path in sources]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be folded in without writing files.",
    )
    arguments = parser.parse_args(argv)
    repo = Path(arguments.repo).resolve()
    result = rollup(repo, dry_run=arguments.dry_run)
    if not result["inserted"]:
        print("[changelog-rollup] nothing to fold")
        return 0
    action = "would insert" if arguments.dry_run else "inserted"
    print(f"[changelog-rollup] {action} {result['inserted']} line(s) from {len(result['sources'])} file(s)")
    for name in result["sources"]:
        print(f"  - {DECLARATION_DIR}/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
