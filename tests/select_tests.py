#!/usr/bin/env python3
"""Select focused validation commands from changed file paths.

The selector is intentionally dependency-light. It can use PyYAML when it is
available, but the checked-in matrix is limited to a tiny YAML subset so the
tool still works in a fresh Python environment.
"""

from __future__ import annotations

import argparse
import ast
import copy
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = Path(__file__).with_name("test_matrix.yaml")
MAX_SELECTED_PYTEST_WORKERS = 4
LOCAL_PARALLEL_COMMAND = (
    '.\\.venv\\Scripts\\python.exe -m pytest tests/ -n 8 --dist loadfile -m "not serial" -q'
)
LOCAL_SERIAL_COMMAND = '.\\.venv\\Scripts\\python.exe -m pytest tests/ -m serial -q'
REMOTE_DISTRIBUTED_COMMAND = (
    ".\\.venv\\Scripts\\python.exe scripts/remote_test_runner.py --backend docker --distributed"
)
FRONTEND_BUILD_COMMAND = "npm --prefix web run build"
FRONTEND_TEST_COMMAND = "node web/node_modules/vitest/vitest.mjs run"
FRONTEND_TEST_ROOT_ARGUMENT = "--root web"
PYTHON_PRODUCT_ROOTS = ("core", "config", "tools")
PYTHON_TEST_COMMAND_PREFIX = ".\\.venv\\Scripts\\python.exe -m pytest"
LLM_PROVIDER_CONFIG_V2_RULE = {
    "id": "llm-provider-config-v2",
    "description": "Provider-scoped config, catalog, discovery, protocol, migration, and frontend convergence.",
    "paths": [
        "config/llm_*.py",
        "config/model_catalog.py",
        "config/model_config_migration.py",
        "core/llm/provider_discovery/**",
        "core/web/services/provider_config_service.py",
        "web/src/routes/ConfigProvider*.tsx",
        "web/src/routes/configProviderLogic.ts",
    ],
    "commands": [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_llm_config_v2_integration.py tests/test_llm_config_schema_v2.py tests/test_llm_provider_registry.py tests/test_model_catalog.py tests/test_provider_discovery_adapters.py tests/test_llm_protocol_resolver.py tests/test_provider_config_service.py tests/test_model_config_migration.py -q",
        f"{FRONTEND_TEST_COMMAND} src/routes/configProviderLogic.test.ts src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts {FRONTEND_TEST_ROOT_ARGUMENT}",
        FRONTEND_BUILD_COMMAND,
    ],
    "notes": [
        "Do not read or migrate the real operator config during automated validation.",
    ],
    "executionLayers": ["focused", "frontend"],
}

VALIDATION_LAYER_DESCRIPTIONS = {
    "hygiene": "Diff hygiene and cheap structural checks.",
    "focused": "Focused commands selected by changed-file ownership.",
    "local-parallel": "Local pytest-xdist lane for tests that are safe with not serial.",
    "local-serial": "Local-only serial lane for Launcher, ports, processes, Git, config, or shared state.",
    "remote-distributed": "Optional server/Docker acceleration for Python not-serial regression only.",
    "frontend": "Frontend Vitest/build lane; never covered by Python remote testing.",
}


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
        loaded = _parse_yaml_subset(text)
    else:
        loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Matrix must be a mapping: {path}")
    rules = loaded.setdefault("rules", [])
    if isinstance(rules, list) and not any(
        isinstance(rule, dict) and rule.get("id") == LLM_PROVIDER_CONFIG_V2_RULE["id"]
        for rule in rules
    ):
        rules.append(copy.deepcopy(LLM_PROVIDER_CONFIG_V2_RULE))
    return loaded


def normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_python_product_path(path: str) -> bool:
    normalized = normalize_path(path)
    if not normalized.endswith(".py"):
        return False
    return normalized == "agent.py" or any(
        normalized.startswith(f"{root}/") for root in PYTHON_PRODUCT_ROOTS
    )


def _is_python_test_path(path: str) -> bool:
    normalized = normalize_path(path)
    return (
        normalized.startswith("tests/")
        and normalized.endswith(".py")
        and Path(normalized).name.startswith("test_")
    )


def _module_name_for_python_path(path: str) -> str | None:
    """Return the importable module name for a supported product source path."""
    normalized = normalize_path(path)
    if not _is_python_product_path(normalized):
        return None
    module_name = normalized.removesuffix(".py").replace("/", ".")
    if module_name.endswith(".__init__"):
        return module_name.removesuffix(".__init__")
    return module_name


def _python_test_import_index(
    project_root: Path,
    source_modules: set[str],
) -> tuple[dict[str, set[str]], set[str]]:
    """Build a conservative source-module to test-file index without importing code.

    Only tests containing an import spelling relevant to a changed module are
    parsed.  `from package import child` is indexed as `package.child` only
    when that exact child is among the changed source modules, which avoids
    guesses based on arbitrary imported symbols.
    """
    index: dict[str, set[str]] = {}
    serial_tests: set[str] = set()
    tests_root = project_root / "tests"
    if not tests_root.is_dir() or not source_modules:
        return index, serial_tests

    source_module_parents = {
        module_name.rpartition(".")[0]
        for module_name in source_modules
        if "." in module_name
    }
    import_fragments = {
        fragment
        for module_name in source_modules
        for fragment in (f"import {module_name}", f"from {module_name}")
    }
    import_fragments.update(
        f"from {parent_module} import" for parent_module in source_module_parents
    )

    for test_path in tests_root.rglob("test_*.py"):
        relative_path = test_path.relative_to(project_root).as_posix()
        try:
            source = test_path.read_text(encoding="utf-8")
            if not any(fragment in source for fragment in import_fragments):
                continue
            tree = ast.parse(source, filename=relative_path)
        except (OSError, UnicodeDecodeError, SyntaxError):
            # A broken test must be fixed by its owner.  Treating it as an
            # import edge would hide that separate collection failure.
            continue
        if "pytest.mark.serial" in source:
            serial_tests.add(relative_path)

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(
                    alias.name for alias in node.names if alias.name in source_modules
                )
                continue
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module in source_modules:
                imported_modules.add(node.module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{node.module}.{alias.name}"
                if candidate in source_modules:
                    imported_modules.add(candidate)

        for module_name in imported_modules:
            index.setdefault(module_name, set()).add(relative_path)

    return index, serial_tests


def _pytest_command(test_files: list[str]) -> str:
    return f"{PYTHON_TEST_COMMAND_PREFIX} {' '.join(test_files)} -q"


def _python_fallback_selection(
    changed_files: list[str],
    explicitly_owned_files: set[str],
    project_root: Path,
) -> dict[str, Any]:
    """Return fallback validation for Python paths left out of the matrix.

    The matrix remains the authority for known high-risk surfaces.  This
    fallback handles only the uncovered remainder and never claims that the
    generic runner smoke validates a product file.
    """
    fallback_rules: list[dict[str, Any]] = []
    commands: list[str] = []
    layers: list[str] = []
    notes: list[str] = []
    coverage_gaps: list[dict[str, str]] = []

    changed_test_files = sorted(
        path
        for path in changed_files
        if _is_python_test_path(path) and path not in explicitly_owned_files
    )
    if changed_test_files:
        fallback_rules.append(
            {
                "id": "changed-python-test-fallback",
                "description": "Run changed Python test files not owned by a matrix rule.",
                "matchedFiles": changed_test_files,
                "selectedTests": changed_test_files,
            }
        )
        commands.append(_pytest_command(changed_test_files))
        layers.append("focused")

    uncovered_sources = sorted(
        path
        for path in changed_files
        if _is_python_product_path(path) and path not in explicitly_owned_files
    )
    if not uncovered_sources:
        return {
            "matchedRules": fallback_rules,
            "commands": commands,
            "layers": layers,
            "notes": notes,
            "coverageGaps": coverage_gaps,
        }

    source_modules = {
        module_name
        for source_path in uncovered_sources
        if (module_name := _module_name_for_python_path(source_path))
    }
    import_index, serial_tests = _python_test_import_index(project_root, source_modules)
    source_tests: dict[str, list[str]] = {}
    for source_path in uncovered_sources:
        module_name = _module_name_for_python_path(source_path)
        selected_tests = sorted(import_index.get(module_name or "", set()))
        if selected_tests:
            source_tests[source_path] = selected_tests
            continue
        coverage_gaps.append(
            {
                "path": source_path,
                "reason": "no-static-test-import",
            }
        )

    if source_tests:
        selected_tests = sorted(
            {test_path for tests in source_tests.values() for test_path in tests}
        )
        parallel_tests = [
            test_path for test_path in selected_tests if test_path not in serial_tests
        ]
        serial_selected_tests = [
            test_path for test_path in selected_tests if test_path in serial_tests
        ]
        fallback_rules.append(
            {
                "id": "python-import-fallback",
                "description": "Tests that statically import uncovered Python product modules.",
                "matchedFiles": sorted(source_tests),
                "selectedTests": selected_tests,
            }
        )
        if parallel_tests:
            commands.append(_parallelize_pytest_command(_pytest_command(parallel_tests)))
            layers.append("focused")
            if len(parallel_tests) > 1:
                layers.append("local-parallel")
        if serial_selected_tests:
            commands.append(_pytest_command(serial_selected_tests))
            layers.extend(["focused", "local-serial"])

    if coverage_gaps:
        notes.append(
            "No static test import was found for the listed Python product files; "
            "add a focused matrix rule or a direct test import before treating them as covered."
        )
    return {
        "matchedRules": fallback_rules,
        "commands": commands,
        "layers": layers,
        "notes": notes,
        "coverageGaps": coverage_gaps,
    }


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


def _parallelize_pytest_command(command: str) -> str:
    if " -m pytest " not in command:
        return command
    if re.search(r"(?:^|\s)(?:-n|--numprocesses)(?:\s|=)", command):
        return command
    pytest_arguments = command.split(" -m pytest ", 1)[1].split()
    test_files: set[str] = set()
    for token in pytest_arguments:
        normalized = token.strip("'\"").replace("\\", "/")
        if normalized.startswith("tests/") and normalized.lower().endswith(".py"):
            test_files.add(normalized)
    workers = min(MAX_SELECTED_PYTEST_WORKERS, len(test_files))
    if workers < 2:
        return command
    return f'{command} -n {workers} --dist loadfile -m "not serial"'


def _rule_commands(rule: dict[str, Any]) -> list[str]:
    commands = [str(command) for command in rule.get("commands", [])]
    layers = _execution_layers(rule, ["focused"])
    if "local-parallel" not in layers or "local-serial" in layers:
        return commands
    return [_parallelize_pytest_command(command) for command in commands]


def _execution_layers(source: dict[str, Any], fallback: list[str]) -> list[str]:
    raw_layers = source.get("executionLayers", fallback)
    if isinstance(raw_layers, list):
        return [str(layer) for layer in raw_layers if str(layer).strip()]
    if isinstance(raw_layers, str) and raw_layers.strip():
        return [raw_layers.strip()]
    return list(fallback)


def _rule_matches(rule: dict[str, Any], changed_files: list[str]) -> list[str]:
    patterns = [str(pattern) for pattern in rule.get("paths", [])]
    excluded_patterns = [str(pattern) for pattern in rule.get("excludePaths", [])]
    return [
        changed_file
        for changed_file in changed_files
        if any(path_matches(pattern, changed_file) for pattern in patterns)
        and not any(path_matches(pattern, changed_file) for pattern in excluded_patterns)
    ]


def _is_frontend_specialized_rule(rule: dict[str, Any]) -> bool:
    """Return whether a rule owns a frontend surface instead of being a fallback.

    Frontend fallback suppression is deliberately file-based.  A mixed change
    can contain both a route with a focused owner and a shared frontend file
    without one rule being allowed to hide validation for the other file.
    """

    return (
        "frontend" in _execution_layers(rule, [])
        and not bool(rule.get("fallback", False))
    )


def build_execution_plan(layers: list[str]) -> dict[str, Any]:
    return {
        "layers": layers,
        "descriptions": {
            layer: VALIDATION_LAYER_DESCRIPTIONS.get(layer, "")
            for layer in layers
        },
        "localParallel": {
            "recommended": "local-parallel" in layers,
            "command": LOCAL_PARALLEL_COMMAND,
            "scope": "Python pytest not-serial tests only.",
        },
        "localSerial": {
            "required": "local-serial" in layers,
            "command": LOCAL_SERIAL_COMMAND,
            "scope": "Required when tests touch real processes, ports, Launcher/runtime lifecycle, Git, config, or shared workspace state.",
        },
        "remoteDistributed": {
            "recommended": "remote-distributed" in layers,
            "command": REMOTE_DISTRIBUTED_COMMAND,
            "isCompleteGate": False,
            "scope": "Speed path for Python pytest not-serial only; it excludes serial pytest, frontend Vitest, and frontend build gates.",
        },
        "frontend": {
            "required": "frontend" in layers,
            "buildCommand": FRONTEND_BUILD_COMMAND,
            "scope": "Run the selected Vitest/build commands from the focused command list.",
        },
    }


def select_tests(
    changed_files: list[str],
    matrix: dict[str, Any],
    *,
    include_always: bool = True,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    normalized_files = [normalize_path(path) for path in changed_files if path.strip()]
    matched_rules: list[dict[str, Any]] = []
    commands: list[str] = []
    notes: list[str] = []
    validation_layers: list[str] = []

    if include_always:
        always = matrix.get("always", {})
        if isinstance(always, dict):
            commands.extend(str(command) for command in always.get("commands", []))
            notes.extend(str(note) for note in always.get("notes", []))
            validation_layers.extend(_execution_layers(always, ["hygiene"]))

    rule_matches: list[tuple[dict[str, Any], list[str]]] = []
    for rule in matrix.get("rules", []):
        if not isinstance(rule, dict):
            continue
        matched_files = _rule_matches(rule, normalized_files)
        if not matched_files:
            continue
        rule_matches.append((rule, matched_files))

    specialized_frontend_files = {
        changed_file
        for rule, matched_files in rule_matches
        if _is_frontend_specialized_rule(rule)
        for changed_file in matched_files
    }
    explicitly_owned_files = {
        changed_file for _rule, matched_files in rule_matches for changed_file in matched_files
    }
    for rule, matched_files in rule_matches:
        if rule.get("fallback", False):
            # Keep only files not owned by a focused frontend rule.  This is
            # what makes a Chat/Teams-only edit cheap while preserving the
            # generic frontend checks for a mixed route + shared-file change.
            matched_files = [
                changed_file
                for changed_file in matched_files
                if changed_file not in specialized_frontend_files
            ]
            if not matched_files:
                continue
        matched_rule = {
            "id": rule.get("id"),
            "description": rule.get("description", ""),
            "matchedFiles": matched_files,
        }
        matched_rules.append(matched_rule)
        commands.extend(_rule_commands(rule))
        notes.extend(str(note) for note in rule.get("notes", []))
        validation_layers.extend(_execution_layers(rule, ["focused"]))

    python_fallback = _python_fallback_selection(
        normalized_files,
        explicitly_owned_files,
        project_root,
    )
    matched_rules.extend(python_fallback["matchedRules"])
    commands.extend(python_fallback["commands"])
    notes.extend(python_fallback["notes"])
    validation_layers.extend(python_fallback["layers"])

    if not matched_rules and not python_fallback["coverageGaps"]:
        default = matrix.get("default", {})
        if isinstance(default, dict):
            commands.extend(str(command) for command in default.get("commands", []))
            notes.extend(str(note) for note in default.get("notes", []))
            validation_layers.extend(_execution_layers(default, ["focused"]))

    validation_layers = _dedupe_commands(validation_layers)

    return {
        "changedFiles": normalized_files,
        "matchedRules": matched_rules,
        "commands": _dedupe_commands(commands),
        "notes": _dedupe_commands(notes),
        "coverageGaps": python_fallback["coverageGaps"],
        "validationLayers": validation_layers,
        "executionPlan": build_execution_plan(validation_layers),
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
        for gap in result["coverageGaps"]:
            print(
                "Coverage gap: "
                f"{gap['path']} ({gap['reason']}); add a focused matrix rule "
                "or a direct test import.",
                file=sys.stderr,
            )
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
        if result["validationLayers"]:
            print("Validation layers:")
            for layer in result["validationLayers"]:
                description = result["executionPlan"]["descriptions"].get(layer, "")
                print(f"  - {layer}: {description}")
        if result["notes"]:
            print("Notes:")
            for note in result["notes"]:
                print(f"  - {note}")
        if result["coverageGaps"]:
            print("Coverage gaps:")
            for gap in result["coverageGaps"]:
                print(f"  - {gap['path']}: {gap['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
