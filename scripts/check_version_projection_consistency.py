"""Exit nonzero when VERSION and the web package metadata disagree.

This is the CI-side projection gate: a checkout has no platform-version
ledger, so only the repo-internal projection equality is checked here
(``VERSION == web/package.json == web/package-lock.json``). The closeout-side
check (``scripts/task_closeout.py``) additionally compares against the ledger
when it is readable, as a warning only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _package_versions(path: Path) -> tuple[str, str | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    root_version = str(payload.get("version", ""))
    packages = payload.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    lock_version = str(root_package.get("version", "")) if isinstance(root_package, dict) else None
    return root_version, lock_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    root = arguments.repo
    values: dict[str, str] = {}
    errors: list[str] = []

    try:
        values["VERSION"] = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as error:
        errors.append(f"VERSION unreadable: {error}")
    for name in ("web/package.json", "web/package-lock.json"):
        try:
            version, lock_version = _package_versions(root / name)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{name} unreadable: {error}")
            continue
        values[name] = version
        if lock_version is not None:
            values[f"{name} (packages root)"] = lock_version

    distinct = {value for value in values.values() if value}
    if len(distinct) > 1:
        listed = ", ".join(f"{key}={value}" for key, value in sorted(values.items()))
        errors.append(f"projection mismatch: {listed}")
    elif not distinct:
        errors.append("no version found in any projection file")

    if errors:
        for error in errors:
            print(f"[version-consistency] {error}", file=sys.stderr)
        return 1
    print(f"[version-consistency] ok: all projections at {next(iter(distinct))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
