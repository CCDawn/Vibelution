"""Block product-facing commits that do not declare an unreleased change.

Settlement only advances when the declaration text actually changes. Without a
guard, an undeclared merge looks identical to an already-settled one and is
skipped in silence forever. This check makes that rule explicit at the only
place every commit must pass: the pre-commit hook.

Declarations live in ``.changelog/<branch>.md`` by default so parallel tasks
never contend for the single ``CHANGELOG.md`` file. Writing the line directly
under ``## Unreleased`` stays supported for single-task work and for merges.

Tests, docs and scripts stay free of the requirement so ordinary hygiene work
does not inflate the version cadence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

CHANGELOG = "CHANGELOG.md"
DECLARATION_DIR = ".changelog"
UNRELEASED_HEADING = "## Unreleased"
PRODUCT_PREFIXES = ("core/", "web/src/", "config/", "tools/", "agent.py")
EXEMPT_PREFIXES = ("tests/", "docs/", "scripts/", DECLARATION_DIR + "/")
EXEMPT_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml", ".lock")
TEMPLATE = """\
Declare the change in one of two places.

Preferred: write the line in your own task file, no shared-file claim needed.

    .changelog/<branch-with-dashes>.md
    - <what a user-visible change does and why>

Also accepted: add the line under "## Unreleased" in CHANGELOG.md.

    ## Unreleased
    - <what a user-visible change does and why>

The version ledger settles exactly one change per distinct declaration, so an
undeclared commit can never advance the version. ``scripts/changelog_rollup.py``
folds task files into CHANGELOG.md before a merge.
"""


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


def is_product_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    if normalized.startswith(EXEMPT_PREFIXES):
        return False
    if normalized.endswith(EXEMPT_SUFFIXES):
        return False
    name = normalized.rsplit("/", 1)[-1]
    if ".test." in name or ".spec." in name:
        return False
    return normalized.startswith(PRODUCT_PREFIXES)


def unreleased_section(text: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == UNRELEASED_HEADING:
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if line.strip().startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected)


def declaration_lines(section: str) -> list[str]:
    return [
        line.strip()
        for line in section.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def has_new_declaration(old_text: str, new_text: str) -> bool:
    old_lines = set(declaration_lines(unreleased_section(old_text)))
    return any(line not in old_lines for line in declaration_lines(unreleased_section(new_text)))


def staged_paths(repo: Path) -> list[str]:
    output = _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()]


def file_at(repo: Path, revision: str) -> str:
    try:
        return _git(repo, "show", f"{revision}:{CHANGELOG}")
    except RuntimeError:
        return ""


def current_branch(repo: Path) -> str:
    try:
        return _git(repo, "branch", "--show-current").strip()
    except RuntimeError:
        return ""


def declaration_path_for_branch(branch: str) -> str:
    slug = branch.strip().replace("\\", "/").replace("/", "-")
    return f"{DECLARATION_DIR}/{slug}.md"


def declaration_has_line(repo: Path, path: str) -> bool:
    try:
        text = _git(repo, "show", f":0:{path}")
    except RuntimeError:
        try:
            text = (repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    return any(line.strip().startswith("-") for line in text.splitlines())


def branch_already_declared(repo: Path) -> bool:
    """True when this branch already declared a change versus main."""

    try:
        merge_base = _git(repo, "merge-base", "main", "HEAD").strip()
    except RuntimeError:
        return False
    if not merge_base:
        return False
    if has_new_declaration(file_at(repo, merge_base), file_at(repo, "HEAD")):
        return True
    try:
        diff = _git(repo, "diff", f"{merge_base}...HEAD", "--", DECLARATION_DIR)
    except RuntimeError:
        return False
    return any(
        line.startswith("+") and line[1:].strip().startswith("-")
        for line in diff.splitlines()
    )


def evaluate(repo: Path) -> tuple[bool, str]:
    staged = staged_paths(repo)
    product_paths = [path for path in staged if is_product_path(path)]
    if not product_paths:
        return True, ""
    if CHANGELOG in staged and has_new_declaration(file_at(repo, "HEAD"), file_at(repo, ":0")):
        return True, ""
    declaration = declaration_path_for_branch(current_branch(repo))
    if declaration in staged and declaration_has_line(repo, declaration):
        return True, ""
    if branch_already_declared(repo):
        return True, ""
    listed = "\n".join(f"  - {path}" for path in product_paths[:12])
    return False, (
        "[changelog-guard] this commit changes product code without a declaration:\n"
        f"{listed}\n\n{TEMPLATE}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Print a ready-to-paste declaration line for the staged files.",
    )
    arguments = parser.parse_args(argv)
    repo = Path(arguments.repo).resolve()
    if arguments.suggest:
        product_paths = [path for path in staged_paths(repo) if is_product_path(path)]
        if not product_paths:
            print("[changelog-guard] nothing staged that needs a declaration")
            return 0
        branch = current_branch(repo) or "codex/<task-slug>"
        target = declaration_path_for_branch(branch)
        scopes = sorted({path.split("/")[0] for path in product_paths})
        print(f"Suggested line for {target}:")
        print()
        print(f"- {"、".join(scopes)}：<一句话说明这次改了什么、用户能感知到什么>")
        return 0
    ok, detail = evaluate(repo)
    if ok:
        return 0
    print(detail, file=sys.stderr)
    print(detail)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
