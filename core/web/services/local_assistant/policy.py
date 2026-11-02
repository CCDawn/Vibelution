"""Narrow development consent for a server-verified local assistant.

These predicates do not authenticate callers or replace executor validation.
Only a backend-bound local task or the native Launcher may consult them. Tests
and builds execute project code; this is a consent policy, not an OS sandbox.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import re
import shlex
import shutil
import sys
from typing import Any

from core.web.services.external_agent.policy import external_runtime_tool_grants
from core.web.services.tool_catalog import TOOL_CATALOG

LOCAL_RUNTIME_SOURCE_PREFIX = "launcher_assistant_task:"

_CLI_TOOLS = frozenset({"cli_tool", "exec_command", "write_stdin"})
_FILE_TOOLS = frozenset({"read_file_tool", "write_file_tool", "apply_diff_edit_tool"})
_READ_GRANTS = ("grep_search_tool", "glob_tool", "read_file_tool")
_WRITE_GRANTS = ("apply_diff_edit_tool", "apply_patch_tool", "write_file_tool")
_FORBIDDEN_TAGS = frozenset({
    "network_access", "model_cost", "delete_or_cleanup", "project_rollback",
    "permission_management", "organization_policy_change", "session_data_access",
    "research_database_access", "team_knowledge_access", "team_workflow_access",
})
_MANAGE_ACTIONS = frozenset({"dispatch_write", "dispatch_derived", "delegation_goal_create",
                            "delegation_goal_get", "delegation_goal_revoke", "dispatch_cancel"})
_SHELL_SYNTAX = re.compile(r"[\x00-\x1f\x7f;&|<>`$%!^(){}#]")
_COMMAND_SYNTAX = re.compile(r"[\x00-\x1f\x7f;|<>`$%!^(){}#]")
_MAX_COMMAND_SEGMENTS = 16
_PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", re.MULTILINE)
_GIT_READ = frozenset({"status", "diff", "log", "show", "ls-files", "ls-tree", "rev-parse",
                       "grep", "blame", "shortlog", "describe"})
_GIT_READ_FLAGS = frozenset({
    "--short", "--branch", "--porcelain", "--ignored", "--untracked-files", "--stat",
    "--numstat", "--shortstat", "--name-only", "--name-status", "--summary", "--raw",
    "--patch", "--no-patch", "--cached", "--staged", "--check", "--oneline", "--graph",
    "--decorate", "--no-decorate", "--abbrev-commit", "--no-abbrev-commit", "--all",
    "--branches", "--tags", "--remotes", "--reverse", "--date-order", "--topo-order",
    "--first-parent", "--no-merges", "--merges", "--color", "--no-color", "--pretty",
    "--format", "--abbrev", "--full-index", "--no-ext-diff", "--no-textconv",
    "--show-toplevel", "--show-prefix", "--git-dir", "--git-common-dir", "--abbrev-ref",
    "--verify", "--is-inside-work-tree", "--is-bare-repository", "--quiet", "--error-unmatch",
    "--others", "--exclude-standard", "--deleted", "--modified", "--stage", "--full-name",
})
_GIT_READ_VALUES = frozenset({
    "--max-count", "--since", "--until", "--after", "--before", "--author", "--committer",
    "--grep", "--date", "--encoding", "--diff-filter", "--unified", "--word-diff-regex",
})
_GIT_GREP_FLAGS = frozenset({
    "--line-number", "--column", "--fixed-strings", "--ignore-case", "--word-regexp",
    "--invert-match", "--files-with-matches", "--files-without-match", "--count",
    "--only-matching", "--text", "--extended-regexp", "--basic-regexp", "--perl-regexp",
    "--cached", "--untracked", "--no-exclude-standard", "--exclude-standard",
    "--full-name", "--name-only", "--null", "--color", "--no-color", "--quiet",
    "--break", "--heading", "--all-match", "--and", "--or", "--not", "--function-context",
})
_GIT_GREP_VALUES = frozenset({
    "--regexp", "--file", "--max-depth", "--threads", "--before-context", "--after-context", "--context",
})
_PYTEST_OPTIONS = {
    **dict.fromkeys(("-q", "-v", "-s", "-x", "--quiet", "--verbose", "--exitfirst",
                    "--collect-only", "--disable-warnings", "--no-header", "--no-summary",
                    "--lf", "--last-failed", "--ff", "--failed-first", "--strict-markers"), "flag"),
    **dict.fromkeys(("-k", "-m", "-p", "-r", "-W", "--maxfail", "--capture", "--tb",
                    "--color", "--durations", "--durations-min", "--import-mode"), "value"),
    **dict.fromkeys(("-c", "--config-file", "--rootdir", "--confcutdir", "--ignore",
                    "--ignore-glob", "--junitxml", "--junit-xml", "--log-file"), "path"),
    "-o": "ini", "--override-ini": "ini",
}
_UNITTEST_OPTIONS = {
    **dict.fromkeys(("-v", "-q", "-f", "-c", "-b", "--verbose", "--quiet", "--failfast",
                    "--catch", "--buffer", "--locals"), "flag"),
    "-k": "value", "-p": "value", "--pattern": "value",
    **dict.fromkeys(("-s", "--start-directory", "-t", "--top-level-directory"), "path"),
}
_COMPILEALL_OPTIONS = {
    **dict.fromkeys(("-q", "-f", "-l", "-b"), "flag"),
    "-j": "value", "-o": "value", "--invalidation-mode": "value",
}
_VITEST_OPTIONS = {
    **dict.fromkeys(("--root", "--dir", "--config", "-c", "--outputFile",
                    "--coverage.reportsDirectory", "--related"), "path"),
    **dict.fromkeys(("--passWithNoTests", "--coverage", "--silent", "--bail"), "bool"),
    **dict.fromkeys(("--changed", "--testNamePattern", "-t", "--maxWorkers", "--minWorkers",
                    "--pool", "--project"), "value"),
}
_TSC_OPTIONS = {
    **dict.fromkeys(("--outDir", "--outFile", "--rootDir", "--baseUrl", "--declarationDir",
                    "--tsBuildInfoFile", "--project", "-p", "--generateCpuProfile", "--generateTrace"), "path"),
    "--rootDirs": "paths", "--typeRoots": "paths",
    **dict.fromkeys(("-b", "--build", "-f", "--force"), "flag"),
    **dict.fromkeys(("--pretty", "--noEmit", "--incremental", "--composite", "--declaration",
                    "--declarationMap", "--sourceMap", "--listFiles", "--listEmittedFiles",
                    "--diagnostics", "--extendedDiagnostics", "--skipLibCheck", "--strict"), "bool"),
    **dict.fromkeys(("--target", "--module", "--moduleResolution", "--lib", "--types", "--jsx"), "value"),
}
_NPM_SCRIPT_OPTIONS = {
    **dict.fromkeys(("--run", "-q", "-v", "--verbose", "--silent", "--passWithNoTests"), "flag"),
    "--pretty": "bool", "--noEmit": "bool",
}


def _ordinary_metadata(tool_name: str) -> bool:
    metadata = TOOL_CATALOG.get(tool_name)
    return bool(isinstance(metadata, dict)
                and metadata.get("risk") not in {"network", "destructive"}
                and not _FORBIDDEN_TAGS.intersection(metadata.get("riskTags") or ())
                and "network" not in (metadata.get("capabilityTags") or ()))


def local_runtime_tool_grants(permission_profile: str) -> tuple[str, ...]:
    """Reuse the external workspace ceiling without exposing external data tools."""
    if permission_profile not in {"read_only", "workspace_write"}:
        raise ValueError("Local assistant requires read_only or workspace_write")
    external = set(external_runtime_tool_grants(permission_profile))
    desired = _READ_GRANTS + (_WRITE_GRANTS if permission_profile == "workspace_write" else ())
    names = [name for name in desired if name in external and _ordinary_metadata(name)]
    if permission_profile == "workspace_write":
        names.extend(name for name in sorted(_CLI_TOOLS) if _ordinary_metadata(name))
    return tuple(dict.fromkeys(names))


def _contained_path(value: Any, base: Path, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if not resolved.is_relative_to(root) or any(
        part.rstrip(" .").casefold() == ".git" for part in resolved.relative_to(root).parts
    ):
        return None
    return resolved


def _simple_argv(command: Any) -> list[str]:
    if not isinstance(command, str) or _SHELL_SYNTAX.search(command):
        return []
    try:
        lexer = shlex.shlex(command, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.escape = ""  # Windows paths retain their literal backslashes.
        tokens = list(lexer)
    except ValueError:
        return []
    return tokens if all(tokens) else []


def _command_sequence(command: Any) -> list[tuple[list[str], bool]]:
    """Parse the common cmd/native argv subset, never a general shell program.

    Only unquoted ``&&`` separates commands. Single-quote shell quoting and
    backslash-escaped double quotes differ between cmd, CRT and Bash, so these
    ambiguous spellings retain approval. Literal operators inside quotes do too.
    ``_simple_argv`` is reserved for pytest's nested ini argument language.
    """
    if not isinstance(command, str) or _COMMAND_SYNTAX.search(command):
        return []
    segments: list[tuple[list[str], bool]] = []
    argv: list[str] = []
    token: list[str] = []
    quoted, started, executable_quoted = False, False, False
    index = 0
    while index < len(command):
        character = command[index]
        if character == '"':
            if index and command[index - 1] == "\\":
                return []
            if not argv:
                executable_quoted = True
            quoted = not quoted
            started = True
        elif character == "&":
            if quoted or command[index:index + 2] != "&&":
                return []
            if started:
                argv.append("".join(token))
                token, started = [], False
            if not argv or not all(argv):
                return []
            segments.append((argv, executable_quoted))
            if len(segments) >= _MAX_COMMAND_SEGMENTS:
                return []
            argv = []
            executable_quoted = False
            index += 1
        elif character == "'" and not quoted:
            return []
        elif character.isspace() and not quoted:
            if started:
                argv.append("".join(token))
                token, started = [], False
        else:
            token.append(character)
            started = True
        index += 1
    if quoted:
        return []
    if started:
        argv.append("".join(token))
    return [*segments, (argv, executable_quoted)] if argv and all(argv) else []


def _trusted_tool(executable: str, cwd: Path, root: Path) -> str | None:
    leaf = executable.replace("\\", "/").rsplit("/", 1)[-1].lower()
    suffix = Path(leaf).suffix
    name = leaf[:-len(suffix)] if suffix in {".exe", ".cmd", ".bat", ".com", ".ps1"} else leaf
    python = bool(re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", name))
    if name not in {"git", "pytest", "npm", "npx", "node", "ls", "pwd"} and not python:
        return None
    trusted: set[Path] = set()
    found = shutil.which(name)
    if found:
        installed = Path(found).resolve(strict=True)
        if not installed.is_relative_to(root):
            trusted.add(installed)
    if python:
        trusted.update(Path(path).resolve(strict=True) for path in
                       (sys.executable, getattr(sys, "_base_executable", "")) if path)
    if "/" in executable or "\\" in executable or Path(executable).is_absolute():
        candidate = Path(executable)
        candidate = (candidate if candidate.is_absolute() else cwd / candidate).resolve(strict=True)
        return name if candidate.is_file() and candidate in trusted else None
    # Windows shells can prefer a same-name file in cwd over the PATH identity.
    extensions = {"", ".exe", ".com", ".cmd", ".bat", ".ps1"}
    extensions.update(ext.casefold() for ext in os.environ.get("PATHEXT", "").split(";") if ext)
    shadows = {name + ext for ext in extensions}
    if any(entry.name.casefold() in shadows and (entry.is_file() or entry.is_symlink())
           for entry in cwd.iterdir()):
        return None
    actual = shutil.which(executable)
    return name if actual and Path(actual).resolve(strict=True) in trusted else None


def _git_options_allowed(argv: list[str], flags: frozenset[str], values: frozenset[str],
                         short_flags: str, short_values: str) -> bool:
    index = 0
    while index < len(argv):
        token = argv[index]
        index += 1
        if token == "--":
            return True
        if not token.startswith("-") or token == "-":
            continue
        if token.startswith("--"):
            option, equals, _ = token.partition("=")
            if option in flags:
                continue
            if option not in values:
                return False
            needs_value = not equals
        else:
            if token[1:].isdigit():
                continue
            needs_value = False
            for offset, letter in enumerate(token[1:], 2):
                if letter in short_flags:
                    continue
                if letter not in short_values:
                    return False
                needs_value = offset == len(token)
                break
        if needs_value:
            # Never hide a following option behind an optional/ambiguous value.
            if index >= len(argv) or argv[index].startswith("-"):
                return False
            index += 1
    return True


def _pytest_ini(value: str, cwd: Path, root: Path, depth: int) -> bool:
    key, separator, content = value.partition("=")
    if not separator:
        return False
    if key == "addopts":
        if depth >= 2:
            return False
        tokens = _simple_argv(content)
        return (not content or bool(tokens)) and _scoped_arguments(
            tokens, _PYTEST_OPTIONS, cwd, root, depth=depth + 1)
    if key in {"cache_dir", "log_file"}:
        return _contained_path(content, cwd, root) is not None
    if key in {"testpaths", "pythonpath"}:
        paths = _simple_argv(content)
        return bool(paths) and all(_contained_path(path, cwd, root) is not None for path in paths)
    return key in {"asyncio_mode", "asyncio_default_fixture_loop_scope", "filterwarnings",
                   "markers", "log_cli", "log_cli_level", "log_level", "junit_family",
                   "console_output_style", "xfail_strict", "minversion", "required_plugins"}


def _scoped_arguments(argv: list[str], schema: dict[str, str], cwd: Path, root: Path,
                      *, depth: int = 0) -> bool:
    """Finite option grammar: known flags, scalar values and resolved path values.

    Unknown options and response files stay with native approval. Delimited
    positionals are paths, including pytest node IDs and unittest module names.
    """
    index, options = 0, True
    while index < len(argv):
        token = argv[index]
        index += 1
        if options and token == "--":
            options = False
            continue
        if not options or not token.startswith("-"):
            if token.startswith("@") or _contained_path(token.split("::", 1)[0], cwd, root) is None:
                return False
            continue
        option, equals, value = token.partition("=")
        kind = schema.get(option)
        supplied = bool(equals)
        if kind is None and not token.startswith("--") and len(token) > 2:
            option, value = token[:2], token[2:].removeprefix("=")
            kind = schema.get(option)
            supplied = True
            if kind == "flag" and all(schema.get("-" + letter) == "flag" for letter in token[1:]):
                continue
        if kind is None:
            return False
        if kind == "flag":
            if supplied:
                return False
            continue
        if kind == "optional":  # Known Git flags may take an attached display value.
            continue
        if kind == "bool":
            if not supplied and index < len(argv) and argv[index] in {"true", "false"}:
                value, supplied = argv[index], True
                index += 1
            if supplied and value not in {"true", "false"}:
                return False
            continue
        if not supplied:
            if index >= len(argv) or argv[index].startswith("-"):
                return False
            value = argv[index]
            index += 1
        if not value or value.startswith("@"):
            return False
        if kind == "path" and _contained_path(value, cwd, root) is None:
            return False
        if kind == "paths" and any(_contained_path(path, cwd, root) is None for path in value.split(",")):
            return False
        if kind == "ini" and not _pytest_ini(value, cwd, root, depth):
            return False
    return True


def _git_development(argv: list[str], cwd: Path, root: Path) -> bool:
    index = 0
    while index < len(argv):
        if argv[index] == "-C" and index + 1 < len(argv):
            new_cwd = _contained_path(argv[index + 1], cwd, root)
            if new_cwd is None or not new_cwd.is_dir():
                return False
            cwd = new_cwd
            index += 2
        elif argv[index] == "--no-pager":
            index += 1
        else:
            break
    if index >= len(argv):
        return False
    action, rest = argv[index], argv[index + 1:]
    if action == "grep":
        schema = {**dict.fromkeys(_GIT_GREP_FLAGS, "optional"),
                  **dict.fromkeys(_GIT_GREP_VALUES, "value"),
                  **dict.fromkeys(("-" + letter for letter in "nFiwvhHlLczqoIaEGPpW"), "flag"),
                  **dict.fromkeys(("-e", "-A", "-B", "-C"), "value"),
                  "-f": "path", "--file": "path"}
        return _scoped_arguments(rest, schema, cwd, root)
    if action in _GIT_READ:
        return _git_options_allowed(rest, _GIT_READ_FLAGS, _GIT_READ_VALUES,
                                    "abcehilnopqrtuvwzBCDEHILNPSVW", "UfeGS")
    if action == "add":
        return _git_options_allowed(rest, frozenset({"--all", "--intent-to-add", "--verbose",
                                    "--dry-run", "--update", "--renormalize"}), frozenset(), "ANvnu", "")
    if action == "commit":
        return _git_options_allowed(rest, frozenset({"--all", "--allow-empty", "--allow-empty-message"}),
                                    frozenset({"--message"}), "avq", "m")
    if action == "branch":
        return all(not token.startswith("-") or token in {"--list", "--show-current", "-v", "-vv"}
                   for token in rest)
    if action == "switch":
        return bool(rest) and all(not token.startswith("-") or token in {"-c", "--create"}
                                  for token in rest)
    if action == "merge":
        return len(rest) == 2 and rest[0] == "--ff-only" and not rest[1].startswith("-")
    if action == "stash":
        return bool(rest) and rest[0] in {"list", "show"} and _git_options_allowed(
            rest[1:], _GIT_READ_FLAGS, _GIT_READ_VALUES, "abcehilnopqrtuvwzBCDEHILNPSVW", "UfeGS")
    return False


def _vitest_run(argv: list[str], cwd: Path, root: Path) -> bool:
    return bool(argv) and argv[0] == "run" and _scoped_arguments(argv[1:], _VITEST_OPTIONS, cwd, root)


def _tsc_build(argv: list[str], cwd: Path, root: Path) -> bool:
    return _scoped_arguments(argv, _TSC_OPTIONS, cwd, root)


def _local_node_tool(name: str, cwd: Path, root: Path) -> bool:
    entry = "vitest/vitest.mjs" if name == "vitest" else "typescript/bin/tsc"
    anchor = cwd
    while anchor.is_relative_to(root):
        # npm exec selects an existing extensionless .bin entry before it
        # considers fetching/installing a package. Package source alone is not proof.
        if ((anchor / "node_modules" / entry).is_file()
                and (anchor / "node_modules" / ".bin" / name).is_file()):
            return True
        if anchor == root:
            break
        anchor = anchor.parent
    return False


def _development_argv(argv: list[str], cwd: Path, root: Path) -> bool:
    executable = _trusted_tool(argv[0], cwd, root)
    argv = argv[1:]
    if executable is None:
        return False
    if executable == "pwd":
        return not argv or len(argv) == 1 and argv[0] in {"-L", "-P", "--logical", "--physical"}
    if executable == "ls":
        # No shell globs, recursion or symlink dereferencing. Resolve each
        # concrete listing target before the executable receives it.
        if any(any(character in token for character in "*?[]") for token in argv):
            return False
        schema = {**dict.fromkeys(("-" + flag for flag in "aAldhnrtSU1FpQis"), "flag"),
                  **dict.fromkeys(("--all", "--almost-all", "--directory", "--human-readable",
                                   "--numeric-uid-gid", "--reverse", "--size", "--inode",
                                   "--classify"), "flag")}
        return _scoped_arguments(argv, schema, cwd, root)
    if executable == "git":
        return _git_development(argv, cwd, root)
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable):
        if len(argv) < 2 or argv[0] != "-m" or argv[1] not in {"pytest", "unittest", "compileall"}:
            return False
        module, arguments = argv[1], argv[2:]
        if module == "unittest" and arguments[:1] == ["discover"]:
            arguments = arguments[1:]
        schema = {"pytest": _PYTEST_OPTIONS, "unittest": _UNITTEST_OPTIONS, "compileall": _COMPILEALL_OPTIONS}[module]
        return _scoped_arguments(arguments, schema, cwd, root)
    if executable == "pytest":
        return _scoped_arguments(argv, _PYTEST_OPTIONS, cwd, root)
    if executable == "npm":
        if len(argv) < 2 or argv[0] != "run" or argv[1] not in {"test", "build", "typecheck", "lint", "check"}:
            return False
        forwarded = argv[2:]
        return not forwarded or (forwarded[0] == "--" and "--" not in forwarded[1:]
                                 and _scoped_arguments(forwarded[1:], _NPM_SCRIPT_OPTIONS, cwd, root))
    if executable == "npx":
        no_install = argv[:1] == ["--no-install"]
        if no_install:
            argv.pop(0)
        if not argv or argv[0] not in {"vitest", "tsc"}:
            return False
        if not no_install and not _local_node_tool(argv[0], cwd, root):
            return False
        if argv[0] == "tsc":
            return _tsc_build(argv[1:], cwd, root)
        return _vitest_run(argv[1:], cwd, root)
    if executable == "node" and argv:
        entry = _contained_path(argv[0], cwd, root)
        if entry is None:
            return False
        parts = entry.relative_to(root).parts
        if parts[-3:] == ("node_modules", "vitest", "vitest.mjs"):
            return _vitest_run(argv[1:], cwd, root)
        if parts[-4:] == ("node_modules", "typescript", "bin", "tsc"):
            return _tsc_build(argv[1:], cwd, root)
    return False


def _cmd_directory_check(argv: list[str], cwd: Path, root: Path) -> Path | None:
    if argv[0].casefold() == "cd":
        arguments = argv[1:]
        change_drive = bool(arguments and arguments[0].casefold() == "/d")
        if change_drive:
            arguments = arguments[1:]
        if not arguments:
            return None if change_drive else cwd
        if len(arguments) != 1 or arguments[0].startswith("/"):
            return None
        target = _contained_path(arguments[0], cwd, root)
        if (target is None or not target.is_dir()
                or not change_drive and target.drive.casefold() != cwd.drive.casefold()):
            return None
        return target
    flags = {"/a", "/b", "/w", "/d", "/l", "/n", "/q", "/r", "/x", "/4", "/c", "/-c", "/o"}
    for argument in argv[1:]:
        lowered = argument.casefold()
        if lowered.startswith("/"):
            if lowered not in flags and not re.fullmatch(r"/(?:a:?-?[drahsiol]+|o:?-?[negsd]+|t:[caw])", lowered):
                return None
        elif (any(character in argument for character in "*?[]")
              or _contained_path(argument, cwd, root) is None):
            return None
    return cwd


def _development_command(command: Any, cwd: Path, root: Path) -> bool:
    segments = _command_sequence(command)
    if not segments:
        return False
    if os.name == "nt" and len(segments) > 1:
        # The executor routes mixed native/Unix-tool chains to Bash depending
        # on the first segment. Do not apply cmd's cd/path rules to that route.
        for argv, _ in segments:
            leaf = argv[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if re.fullmatch(r"(?:ls|pwd)(?:\.(?:exe|cmd|bat|com|ps1))?", leaf):
                return False
    for argv, executable_quoted in segments:
        if os.name == "nt" and argv[0].casefold() in {"cd", "dir"}:
            # cmd only recognizes the original, unquoted builtin spelling;
            # otherwise it may search for an external same-name executable.
            if executable_quoted:
                return False
            next_cwd = _cmd_directory_check(argv, cwd, root)
            if next_cwd is None:
                return False
            cwd = next_cwd
        elif not _development_argv(argv, cwd, root):
            return False
    return True


def normal_development_call(tool_name: str, args: Mapping[str, Any], workspace_root: Path | str) -> bool:
    """Whether ordinary local development consent covers this already-bound call."""
    if not isinstance(tool_name, str) or not isinstance(args, Mapping) or not _ordinary_metadata(tool_name):
        return False
    try:
        if not isinstance(workspace_root, (Path, str)) or not str(workspace_root).strip():
            return False
        if not Path(workspace_root).is_absolute():
            return False
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            return False
        if tool_name == "write_stdin":
            return args.get("chars", "") == "" and bool(args.get("session_id"))
        if tool_name in _FILE_TOOLS:
            file_path = args.get("file_path")
            if tool_name == "write_file_tool" and isinstance(file_path, str) and not Path(file_path).is_absolute():
                # create_file retains a legacy workspace-prefix normalization.
                if file_path.startswith("workspace"):
                    file_path = file_path[len("workspace"):].lstrip("/\\")
            return _contained_path(file_path, root, root) is not None
        if tool_name == "apply_patch_tool":
            base = _contained_path(args.get("cwd") or ".", root, root)
            patch = args.get("patch_text")
            if base is None or not isinstance(patch, str) or "*** Delete File:" in patch:
                return False
            targets = _PATCH_PATH.findall(patch)
            return bool(targets) and all(_contained_path(path, base, root) is not None for path in targets)
        if tool_name in {"cli_tool", "exec_command"}:
            raw_cwd = args.get("cwd", "")
            if not isinstance(raw_cwd, str):
                return False
            cwd = _contained_path(raw_cwd or ".", root, root)
            command = args.get("command" if tool_name == "cli_tool" else "cmd")
            return cwd is not None and cwd.is_dir() and _development_command(command, cwd, root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return False


def normal_assistant_manage_call(action: str, args: Mapping[str, Any]) -> bool:
    """Allow only the existing closed ordinary-dispatch DTOs; executor owns ACLs."""
    if not isinstance(action, str) or action not in _MANAGE_ACTIONS or not isinstance(args, Mapping):
        return False
    from pydantic import ValidationError
    from core.assistant_runtime.actions import DispatchCancel
    from core.assistant_runtime.delegation import DerivedDispatch, GoalCreate, GoalQuery
    from core.assistant_runtime.dispatch_approval import DispatchWrite

    models = {"dispatch_write": DispatchWrite, "dispatch_derived": DerivedDispatch,
              "delegation_goal_create": GoalCreate, "delegation_goal_get": GoalQuery,
              "delegation_goal_revoke": GoalQuery, "dispatch_cancel": DispatchCancel}
    try:
        models[action].model_validate(dict(args), strict=True)
    except (ValidationError, TypeError, ValueError):
        return False
    return True
