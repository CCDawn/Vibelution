#!/usr/bin/env python3
"""Advisory frontend/backend API contract scanner for the web workbench."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROUTE_RE = re.compile(r"@(router|app)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
FRONTEND_CALL_PATTERNS = (
    ("fetchJson", re.compile(r"fetchJson(?:<([^>]+)>)?\(\s*(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')")),
    ("requestJson", re.compile(r"requestJson(?:<([^>]+)>)?\(\s*(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')")),
    ("EventSource", re.compile(r"new\s+EventSource\(\s*(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')")),
)
INTERPOLATION_RE = re.compile(r"\$\{([^}]+)\}")
PATH_PARAM_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


@dataclass(frozen=True)
class ApiEndpoint:
    method: str
    path: str
    file: str
    line: int
    kind: str = "backend"
    value_type: str = ""
    raw_path: str = ""
    dynamic: bool = False
    classification: str = ""


@dataclass(frozen=True)
class ApiContractReport:
    backend_route_count: int
    backend_unique_path_count: int
    frontend_call_count: int
    frontend_unique_path_count: int
    frontend_without_backend: list[ApiEndpoint]
    backend_without_frontend: list[ApiEndpoint]
    classified_backend_without_frontend: list[ApiEndpoint]
    dynamic_frontend_calls: list[ApiEndpoint]
    backend_prefix_counts: dict[str, int]
    frontend_prefix_counts: dict[str, int]

    @property
    def potential_drift_count(self) -> int:
        return len(self.frontend_without_backend) + len(self.backend_without_frontend)


@dataclass(frozen=True)
class FrontendTypeConflict:
    method: str
    path: str
    types: list[str]
    calls: list[ApiEndpoint]


@dataclass(frozen=True)
class FrontendTypeContractReport:
    frontend_call_count: int
    typed_call_count: int
    endpoint_count: int
    conflict_count: int
    conflicts: list[FrontendTypeConflict]
    dynamic_frontend_calls: list[ApiEndpoint]

    @property
    def potential_drift_count(self) -> int:
        return self.conflict_count


def normalize_api_path(raw_path: str) -> str:
    path = str(raw_path or "").strip()
    path = INTERPOLATION_RE.sub("{param}", path)
    path = PATH_PARAM_RE.sub("{param}", path)
    path = re.sub(r"\?.*$", "", path)
    path = path.rstrip("/")
    return path or "/"


def route_regex(path_template: str) -> re.Pattern[str]:
    escaped = re.escape(path_template)
    escaped = escaped.replace(r"\{param\}", r"[^/]+")
    return re.compile(rf"^{escaped}$")


def relative_path(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def iter_python_route_files(project_root: Path) -> Iterable[Path]:
    yield project_root / "core" / "web" / "app.py"
    routes_dir = project_root / "core" / "web" / "routes"
    if routes_dir.exists():
        yield from sorted(routes_dir.glob("*.py"))


def iter_frontend_source_files(project_root: Path) -> Iterable[Path]:
    src_dir = project_root / "web" / "src"
    if not src_dir.exists():
        return
    yield from sorted(path for path in src_dir.rglob("*") if path.suffix in {".ts", ".tsx"})


def is_frontend_test_file(path: Path) -> bool:
    name = path.name
    return name.endswith(".test.ts") or name.endswith(".test.tsx")


def find_backend_routes(project_root: Path) -> list[ApiEndpoint]:
    endpoints: list[ApiEndpoint] = []
    for path in iter_python_route_files(project_root):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in BACKEND_ROUTE_RE.finditer(text):
            endpoint = match.group(3)
            if match.group(1) == "router":
                endpoint = f"/api{endpoint}"
            endpoints.append(
                ApiEndpoint(
                    method=match.group(2).upper(),
                    path=normalize_api_path(endpoint),
                    raw_path=endpoint,
                    file=relative_path(path, project_root),
                    line=line_number(text, match.start()),
                )
            )
    return endpoints


def _frontend_match_path(match: re.Match[str], kind: str) -> tuple[str, str]:
    if kind == "EventSource":
        return "", str(match.group(1) or match.group(2) or match.group(3) or "")
    return str(match.group(1) or "").strip(), str(match.group(2) or match.group(3) or match.group(4) or "")


def _is_unresolved_dynamic_call(raw_path: str) -> bool:
    interpolations = [item.strip() for item in INTERPOLATION_RE.findall(raw_path)]
    if not interpolations:
        return False
    for expression in interpolations:
        lowered = expression.lower()
        if lowered in {"suffix", "endpoint", "action"} or lowered.endswith("suffix"):
            return True
    return False


def find_frontend_calls(project_root: Path) -> list[ApiEndpoint]:
    calls: list[ApiEndpoint] = []
    for path in iter_frontend_source_files(project_root):
        if is_frontend_test_file(path):
            continue
        text = path.read_text(encoding="utf-8")
        for kind, pattern in FRONTEND_CALL_PATTERNS:
            for match in pattern.finditer(text):
                value_type, raw_path = _frontend_match_path(match, kind)
                if not raw_path.startswith("/api/"):
                    continue
                calls.append(
                    ApiEndpoint(
                        method="",
                        path=normalize_api_path(raw_path),
                        raw_path=raw_path,
                        file=relative_path(path, project_root),
                        line=line_number(text, match.start()),
                        kind=kind,
                        value_type=value_type,
                        dynamic=_is_unresolved_dynamic_call(raw_path),
                    )
                )
    return calls


def _call_argument_tail(text: str, match_end: int) -> str:
    depth = 1
    quote = ""
    escaped = False
    chars: list[str] = []
    for char in text[match_end:]:
        chars.append(char)
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth <= 0:
                break
    return "".join(chars)


def _infer_frontend_call_method(text: str, match_end: int, kind: str) -> str:
    if kind == "EventSource":
        return "GET"
    window = _call_argument_tail(text, match_end)
    method_match = re.search(r"method\s*:\s*['\"]([A-Za-z]+)['\"]", window)
    if method_match:
        return method_match.group(1).upper()
    return "GET"


def find_frontend_typed_calls(project_root: Path) -> list[ApiEndpoint]:
    calls: list[ApiEndpoint] = []
    for path in iter_frontend_source_files(project_root):
        if is_frontend_test_file(path):
            continue
        text = path.read_text(encoding="utf-8")
        for kind, pattern in FRONTEND_CALL_PATTERNS:
            if kind == "EventSource":
                continue
            for match in pattern.finditer(text):
                value_type, raw_path = _frontend_match_path(match, kind)
                if not raw_path.startswith("/api/"):
                    continue
                calls.append(
                    ApiEndpoint(
                        method=_infer_frontend_call_method(text, match.end(), kind),
                        path=normalize_api_path(raw_path),
                        raw_path=raw_path,
                        file=relative_path(path, project_root),
                        line=line_number(text, match.start()),
                        kind=kind,
                        value_type=value_type,
                        dynamic=_is_unresolved_dynamic_call(raw_path),
                    )
                )
    return calls


def prefix_counts(endpoints: Iterable[ApiEndpoint]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for endpoint in endpoints:
        parts = endpoint.path.split("/")
        prefix = parts[2] if len(parts) > 2 else ""
        counts[prefix] = counts.get(prefix, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _classify_backend_without_frontend(endpoint: ApiEndpoint) -> str:
    path = endpoint.path
    if path == "/api/control-token":
        return "direct_fetch_control_token"
    if path == "/api/runtime/browser-telemetry":
        return "direct_fetch_browser_telemetry"
    if path == "/api/runtime/events":
        return "optional_runtime_sse"
    if path == "/api/config/language":
        return "legacy_or_external_config_action"
    if path in {"/api/evolution/self/active-run", "/api/evolution/self/audit", "/api/evolution/self/candidates"}:
        return "self_evolution_auxiliary_api"
    if path == "/api/research/knowledge-base":
        return "agent_memory_source_api"
    if path == "/api/research/organization/proposals":
        return "research_org_agent_proposal_api"
    if path in {"/api/config/draft/add-model", "/api/config/draft/update-model"}:
        return "dynamic_config_model_editor"
    if path in {"/api/evolution/chat-review/{param}/approve", "/api/evolution/chat-review/{param}/reject"}:
        return "legacy_chat_review_action"
    if path.startswith("/api/config/avatar-image/"):
        return "binary_or_url_resource"
    if path.startswith("/api/sessions/{param}/artifacts/"):
        return "binary_or_url_resource"
    if path.startswith("/api/agents/{param}/messages"):
        return "agent_inbox_api"
    if path.startswith("/api/agent-mode-bindings/{param}/"):
        return "dynamic_agent_mode_binding"
    if path.startswith("/api/evolution/worktree-runs/{param}"):
        return "worktree_run_detail_or_sse_api"
    if path.startswith("/api/memory/items/{param}/{param}"):
        return "dynamic_memory_mutation"
    if path.startswith("/api/prompt-templates/{param}/reset"):
        return "prompt_template_reset_api"
    if path.startswith("/api/research/theme-discovery/sessions/{param}/"):
        return "dynamic_research_action"
    if path.startswith("/api/tools/generated/{param}/validate"):
        return "generated_tool_validation_api"
    return ""


def build_report(project_root: Path) -> ApiContractReport:
    backend = find_backend_routes(project_root)
    frontend = find_frontend_calls(project_root)
    backend_by_path: dict[str, list[ApiEndpoint]] = {}
    frontend_by_path: dict[str, list[ApiEndpoint]] = {}
    for endpoint in backend:
        backend_by_path.setdefault(endpoint.path, []).append(endpoint)
    for endpoint in frontend:
        frontend_by_path.setdefault(endpoint.path, []).append(endpoint)

    backend_matchers = [(path, route_regex(path)) for path in backend_by_path]
    frontend_matchers = [(path, route_regex(path)) for path in frontend_by_path]

    frontend_without_backend: list[ApiEndpoint] = []
    dynamic_frontend_calls: list[ApiEndpoint] = []
    for path, endpoints in frontend_by_path.items():
        if any(endpoint.dynamic for endpoint in endpoints):
            dynamic_frontend_calls.extend(endpoint for endpoint in endpoints if endpoint.dynamic)
            continue
        if not any(matcher.match(path) for _, matcher in backend_matchers):
            frontend_without_backend.extend(endpoints)

    backend_without_frontend: list[ApiEndpoint] = []
    classified_backend_without_frontend: list[ApiEndpoint] = []
    for path, endpoints in backend_by_path.items():
        if not path.startswith("/api/"):
            continue
        if any(matcher.match(path) for _, matcher in frontend_matchers):
            continue
        for endpoint in endpoints:
            classification = _classify_backend_without_frontend(endpoint)
            if classification:
                classified_backend_without_frontend.append(
                    ApiEndpoint(**{**asdict(endpoint), "classification": classification})
                )
            else:
                backend_without_frontend.append(endpoint)

    return ApiContractReport(
        backend_route_count=len(backend),
        backend_unique_path_count=len(backend_by_path),
        frontend_call_count=len(frontend),
        frontend_unique_path_count=len(frontend_by_path),
        frontend_without_backend=sorted(frontend_without_backend, key=lambda item: (item.path, item.file, item.line)),
        backend_without_frontend=sorted(backend_without_frontend, key=lambda item: (item.path, item.file, item.line)),
        classified_backend_without_frontend=sorted(
            classified_backend_without_frontend,
            key=lambda item: (item.classification, item.path, item.file, item.line),
        ),
        dynamic_frontend_calls=sorted(dynamic_frontend_calls, key=lambda item: (item.path, item.file, item.line)),
        backend_prefix_counts=prefix_counts(backend),
        frontend_prefix_counts=prefix_counts(frontend),
    )


def build_type_report(project_root: Path) -> FrontendTypeContractReport:
    calls = find_frontend_typed_calls(project_root)
    typed_calls = [call for call in calls if call.value_type and not call.dynamic]
    dynamic_frontend_calls = [call for call in calls if call.dynamic]
    by_endpoint: dict[tuple[str, str], list[ApiEndpoint]] = {}
    for call in typed_calls:
        by_endpoint.setdefault((call.method or "GET", call.path), []).append(call)

    conflicts: list[FrontendTypeConflict] = []
    for (method, path), endpoint_calls in by_endpoint.items():
        types = sorted({call.value_type for call in endpoint_calls if call.value_type})
        if len(types) <= 1:
            continue
        conflicts.append(
            FrontendTypeConflict(
                method=method,
                path=path,
                types=types,
                calls=sorted(endpoint_calls, key=lambda item: (item.value_type, item.file, item.line)),
            )
        )

    conflicts.sort(key=lambda item: (item.path, item.method))
    return FrontendTypeContractReport(
        frontend_call_count=len(calls),
        typed_call_count=len(typed_calls),
        endpoint_count=len(by_endpoint),
        conflict_count=len(conflicts),
        conflicts=conflicts,
        dynamic_frontend_calls=sorted(dynamic_frontend_calls, key=lambda item: (item.path, item.file, item.line)),
    )


def report_to_json(report: ApiContractReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)


def type_report_to_json(report: FrontendTypeContractReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)


def report_to_text(report: ApiContractReport) -> str:
    lines = [
        "API Contract Audit",
        f"- backend routes: {report.backend_route_count} ({report.backend_unique_path_count} unique paths)",
        f"- frontend calls: {report.frontend_call_count} ({report.frontend_unique_path_count} unique paths)",
        f"- potential drift: {report.potential_drift_count}",
        f"- classified backend-only or dynamic resources: {len(report.classified_backend_without_frontend)}",
        f"- dynamic frontend calls skipped from drift: {len(report.dynamic_frontend_calls)}",
    ]
    if report.frontend_without_backend:
        lines.append("\nFrontend calls without backend match:")
        lines.extend(
            f"- {item.path} ({item.kind}, {item.file}:{item.line})" for item in report.frontend_without_backend
        )
    if report.backend_without_frontend:
        lines.append("\nBackend routes without frontend match:")
        lines.extend(
            f"- {item.method} {item.path} ({item.file}:{item.line})" for item in report.backend_without_frontend
        )
    if report.dynamic_frontend_calls:
        lines.append("\nDynamic frontend calls skipped from drift:")
        lines.extend(f"- {item.raw_path} ({item.file}:{item.line})" for item in report.dynamic_frontend_calls)
    return "\n".join(lines)


def type_report_to_text(report: FrontendTypeContractReport) -> str:
    lines = [
        "Frontend Type Contract Audit",
        f"- frontend JSON calls: {report.frontend_call_count}",
        f"- typed non-dynamic calls: {report.typed_call_count}",
        f"- typed method+path endpoints: {report.endpoint_count}",
        f"- type conflicts: {report.conflict_count}",
        f"- dynamic frontend calls skipped from type drift: {len(report.dynamic_frontend_calls)}",
    ]
    if report.conflicts:
        lines.append("\nMethod+path endpoints with multiple frontend types:")
        for conflict in report.conflicts:
            lines.append(f"- {conflict.method} {conflict.path}: {', '.join(conflict.types)}")
            for call in conflict.calls:
                lines.append(f"  - {call.value_type} ({call.kind}, {call.file}:{call.line})")
    if report.dynamic_frontend_calls:
        lines.append("\nDynamic frontend calls skipped from type drift:")
        lines.extend(f"- {item.raw_path} ({item.file}:{item.line})" for item in report.dynamic_frontend_calls)
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan advisory frontend/backend API contract drift.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="Project root to scan.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--types", action="store_true", help="Scan frontend generic type consistency by method+path.")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit with status 1 when unclassified potential drift is found. Off by default.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.types:
        report = build_type_report(Path(args.project_root).resolve())
        print(type_report_to_json(report) if args.json else type_report_to_text(report))
        return 1 if args.fail_on_drift and report.potential_drift_count else 0
    report = build_report(Path(args.project_root).resolve())
    print(report_to_json(report) if args.json else report_to_text(report))
    return 1 if args.fail_on_drift and report.potential_drift_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
