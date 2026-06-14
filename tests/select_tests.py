#!/usr/bin/env python3
"""Select focused validation commands from changed file paths.

The selector is intentionally dependency-light. It can use PyYAML when it is
available, but the checked-in matrix is limited to a tiny YAML subset so the
tool still works in a fresh Python environment.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = Path(__file__).with_name("test_matrix.yaml")


def _strip_inline_comment(line: str) -> str:
    in_quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if in_quote == char:
                in_quote = None
            elif in_quote is None:
                in_quote = char
            continue
        if char == "#" and in_quote is None:
            return line[:index].rstrip()
    return line.rstrip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if value.isdigit():
        return int(value)
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace(r"\\", "\\").replace(r"\"", '"')
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _parse_yaml_subset(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by tests/test_matrix.yaml.

    Supported shape:
      top_key:
        list_key:
          - "value"
      rules:
        - id: "rule"
          paths:
            - "glob"
    """

    data: dict[str, Any] = {}
    current_section: str | None = None
    current_section_key: str | None = None
    current_rule: dict[str, Any] | None = None
    current_rule_key: str | None = None

    for raw_line in text.splitlines():
        line = _strip_inline_comment(raw_line)
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            key, sep, value = stripped.partition(":")
            if not sep:
                raise ValueError(f"Invalid matrix line: {raw_line!r}")
            current_section = key
            current_section_key = None
            current_rule = None
            current_rule_key = None
            if value.strip():
                data[key] = _parse_scalar(value)
            elif key == "rules":
                data[key] = []
            else:
                data[key] = {}
            continue

        if current_section == "rules":
            rules = data.setdefault("rules", [])
            if indent == 2 and stripped.startswith("- "):
                current_rule = {}
                rules.append(current_rule)
                current_rule_key = None
                rest = stripped[2:].strip()
                if rest:
                    key, sep, value = rest.partition(":")
                    if not sep:
                        raise ValueError(f"Invalid rule line: {raw_line!r}")
                    current_rule[key] = _parse_scalar(value)
                continue
            if current_rule is None:
                raise ValueError(f"Rule property without rule: {raw_line!r}")
            if indent == 4:
                key, sep, value = stripped.partition(":")
                if not sep:
                    raise ValueError(f"Invalid rule property: {raw_line!r}")
                current_rule_key = key
                if value.strip():
                    current_rule[key] = _parse_scalar(value)
                else:
                    current_rule[key] = []
                continue
            if indent == 6 and stripped.startswith("- "):
                if current_rule_key is None:
                    raise ValueError(f"List item without key: {raw_line!r}")
                current_rule.setdefault(current_rule_key, []).append(
                    _parse_scalar(stripped[2:])
                )
                continue
            raise ValueError(f"Unsupported matrix line: {raw_line!r}")

        section = data.get(current_section or "")
        if not isinstance(section, dict):
            raise ValueError(f"Unsupported section line: {raw_line!r}")
        if indent == 2:
            key, sep, value = stripped.partition(":")
            if not sep:
                raise ValueError(f"Invalid section property: {raw_line!r}")
            current_section_key = key
            if value.strip():
                section[key] = _parse_scalar(value)
            else:
                section[key] = []
            continue
        if indent == 4 and stripped.startswith("- "):
            if current_section_key is None:
                raise ValueError(f"List item without section key: {raw_line!r}")
            section.setdefault(current_section_key, []).append(_parse_scalar(stripped[2:]))
            continue
        raise ValueError(f"Unsupported matrix line: {raw_line!r}")

    return data


def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _parse_yaml_subset(text)
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Matrix must be a mapping: {path}")
    return loaded


def normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_matches(pattern: str, changed_path: str) -> bool:
    pattern = normalize_path(pattern)
    changed_path = normalize_path(changed_path)
    if not pattern:
        return False
    if pattern == changed_path:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return changed_path == prefix or changed_path.startswith(prefix + "/")
    if "/" not in pattern and "/" in changed_path:
        return False
    return fnmatch.fnmatchcase(changed_path, pattern)


def _dedupe_commands(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def select_tests(
    changed_files: list[str],
    matrix: dict[str, Any],
    *,
    include_always: bool = True,
) -> dict[str, Any]:
    normalized_files = [normalize_path(path) for path in changed_files if path.strip()]
    matched_rules: list[dict[str, Any]] = []
    commands: list[str] = []
    notes: list[str] = []

    if include_always:
        always = matrix.get("always", {})
        if isinstance(always, dict):
            commands.extend(str(command) for command in always.get("commands", []))
            notes.extend(str(note) for note in always.get("notes", []))

    for rule in matrix.get("rules", []):
        if not isinstance(rule, dict):
            continue
        patterns = [str(pattern) for pattern in rule.get("paths", [])]
        matched_files = [
            changed_file
            for changed_file in normalized_files
            if any(path_matches(pattern, changed_file) for pattern in patterns)
        ]
        if not matched_files:
            continue
        matched_rule = {
            "id": rule.get("id"),
            "description": rule.get("description", ""),
            "matchedFiles": matched_files,
        }
        matched_rules.append(matched_rule)
        commands.extend(str(command) for command in rule.get("commands", []))
        notes.extend(str(note) for note in rule.get("notes", []))

    if not matched_rules:
        default = matrix.get("default", {})
        if isinstance(default, dict):
            commands.extend(str(command) for command in default.get("commands", []))
            notes.extend(str(note) for note in default.get("notes", []))

    return {
        "changedFiles": normalized_files,
        "matchedRules": matched_rules,
        "commands": _dedupe_commands(commands),
        "notes": _dedupe_commands(notes),
    }


def _git_name_output(args: list[str], cwd: Path) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_files_from_git(
    base: str,
    cwd: Path = PROJECT_ROOT,
    *,
    include_untracked: bool = True,
) -> list[str]:
    changed_files = _git_name_output(["diff", "--name-only", base], cwd)
    if include_untracked:
        changed_files.extend(
            _git_name_output(["ls-files", "--others", "--exclude-standard"], cwd)
        )
    return _dedupe_commands(changed_files)


def changed_files_from_file(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select focused Vibelution validation commands for changed files."
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX,
        help="Path to the impact test matrix.",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Changed file path. Can be passed multiple times.",
    )
    parser.add_argument(
        "--changed-files-from",
        type=Path,
        help="Text file containing one changed path per line.",
    )
    parser.add_argument(
        "--from-git",
        metavar="BASE",
        help="Read changed files from git diff --name-only BASE.",
    )
    parser.add_argument(
        "--no-untracked",
        action="store_true",
        help="When using --from-git, ignore untracked files.",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON output.")
    parser.add_argument(
        "--commands-only",
        action="store_true",
        help="Print only selected commands, one per line.",
    )
    parser.add_argument(
        "--no-always",
        action="store_true",
        help="Do not include always-on hygiene commands.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    changed_files = list(args.changed_file)
    if args.changed_files_from:
        changed_files.extend(changed_files_from_file(args.changed_files_from))
    if args.from_git:
        changed_files.extend(
            changed_files_from_git(args.from_git, include_untracked=not args.no_untracked)
        )

    if not changed_files:
        parser.error("Provide --changed-file, --changed-files-from, or --from-git.")

    result = select_tests(
        changed_files,
        load_matrix(args.matrix),
        include_always=not args.no_always,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.commands_only:
        print("\n".join(result["commands"]))
    else:
        print("Changed files:")
        for changed_file in result["changedFiles"]:
            print(f"  - {changed_file}")
        print("Matched rules:")
        if result["matchedRules"]:
            for rule in result["matchedRules"]:
                print(f"  - {rule['id']}: {', '.join(rule['matchedFiles'])}")
        else:
            print("  - default")
        print("Commands:")
        for command in result["commands"]:
            print(f"  - {command}")
        if result["notes"]:
            print("Notes:")
            for note in result["notes"]:
                print(f"  - {note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
