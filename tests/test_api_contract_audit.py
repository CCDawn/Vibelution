from __future__ import annotations

from pathlib import Path

from scripts.api_contract_audit import (
    build_inventory_report,
    build_type_report,
    build_report,
    find_backend_routes,
    find_frontend_calls,
    inventory_report_to_json,
    inventory_report_to_text,
    normalize_api_path,
    report_to_text,
    type_report_to_text,
)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_normalize_api_path_collapses_backend_and_frontend_dynamic_segments():
    assert normalize_api_path("/api/sessions/{session_id}/events") == "/api/sessions/{param}/events"
    assert normalize_api_path("/api/sessions/${encodeURIComponent(sessionId)}/events") == (
        "/api/sessions/{param}/events"
    )
    assert normalize_api_path("/api/git/status?limit=500") == "/api/git/status"


def test_contract_audit_scans_routes_fetch_request_json_and_event_source(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health():
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "sessions.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.get("/sessions/{session_id}/events")
def events(session_id: str):
    return {}

@router.post("/config/draft/preview")
def preview():
    return {}
""",
    )
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        """
fetchJson<BackendHealth>("/api/health");
requestJson<ConfigWorkspace>("/api/config/draft/preview", { method: "POST" });
new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/events`);
""",
    )

    backend = find_backend_routes(tmp_path)
    frontend = find_frontend_calls(tmp_path)
    report = build_report(tmp_path)

    assert {item.path for item in backend} == {
        "/api/health",
        "/api/sessions/{param}/events",
        "/api/config/draft/preview",
    }
    assert {item.kind for item in frontend} == {"fetchJson", "requestJson", "EventSource"}
    assert report.potential_drift_count == 0


def test_contract_audit_treats_dynamic_research_suffix_as_skipped_not_drift(tmp_path):
    write_text(tmp_path / "core" / "web" / "app.py", "")
    write_text(
        tmp_path / "core" / "web" / "routes" / "research.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/research/theme-discovery/sessions/{session_id}/run-broad-search")
def broad(session_id: str):
    return {}
""",
    )
    write_text(
        tmp_path / "web" / "src" / "ResearchRoute.tsx",
        """
const suffix = "run-broad-search";
fetchJson<ResearchDiscoverySessionPayload>(
  `/api/research/theme-discovery/sessions/${encodeURIComponent(sessionId)}/${suffix}`,
  { method: "POST" },
);
""",
    )

    report = build_report(tmp_path)

    assert report.frontend_without_backend == []
    assert report.dynamic_frontend_calls
    assert "${suffix}" in report.dynamic_frontend_calls[0].raw_path


def test_contract_audit_classifies_expected_non_json_or_direct_fetch_routes(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/control-token")
def control_token():
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "runtime.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/runtime/browser-telemetry")
def browser_telemetry():
    return {}
""",
    )
    write_text(tmp_path / "web" / "src" / "empty.ts", "")

    report = build_report(tmp_path)

    assert report.backend_without_frontend == []
    assert {item.classification for item in report.classified_backend_without_frontend} == {
        "direct_fetch_control_token",
        "direct_fetch_browser_telemetry",
    }


def test_contract_audit_ignores_spa_fallback_and_classifies_dynamic_helpers(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def index():
    return {}

@app.get("/{full_path:path}")
def fallback(full_path: str):
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "config.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/config/draft/add-model")
def add_model():
    return {}

@router.patch("/memory/items/{section_id}/{item_id}")
def patch_memory(section_id: str, item_id: str):
    return {}
""",
    )
    write_text(tmp_path / "web" / "src" / "empty.ts", "")

    report = build_report(tmp_path)

    assert report.backend_without_frontend == []
    assert {item.classification for item in report.classified_backend_without_frontend} == {
        "dynamic_config_model_editor",
        "dynamic_memory_mutation",
    }


def test_contract_audit_reports_unclassified_potential_drift(tmp_path):
    write_text(tmp_path / "core" / "web" / "app.py", "")
    write_text(
        tmp_path / "core" / "web" / "routes" / "agents.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/agents/{agent_id}/messages")
def create_message(agent_id: str):
    return {}

@router.get("/unowned/internal")
def unowned():
    return {}
""",
    )
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        'fetchJson<Missing>("/api/unknown");',
    )

    report = build_report(tmp_path)
    text = report_to_text(report)

    assert report.potential_drift_count == 2
    assert "/api/unknown" in text
    assert "GET /api/unowned/internal" in text


def test_contract_audit_classifies_known_backend_only_ownership_paths(tmp_path):
    write_text(tmp_path / "core" / "web" / "app.py", "")
    write_text(
        tmp_path / "core" / "web" / "routes" / "ownership.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.get("/agents/{agent_id}/messages")
def agent_messages(agent_id: str):
    return {}

@router.put("/config/language")
def language():
    return {}

@router.post("/evolution/chat-review/{candidate_id}/approve")
def approve(candidate_id: str):
    return {}

@router.get("/evolution/self/audit")
def audit():
    return {}

@router.get("/evolution/worktree-runs/{run_id}/events")
def worktree_events(run_id: str):
    return {}

@router.post("/prompt-templates/{template_id}/reset")
def prompt_reset(template_id: str):
    return {}

@router.get("/research/knowledge-base")
def knowledge_base():
    return {}

@router.post("/research/organization/proposals")
def proposal():
    return {}

@router.post("/tools/generated/{tool_id}/validate")
def validate_tool(tool_id: str):
    return {}
""",
    )
    write_text(tmp_path / "web" / "src" / "empty.ts", "")

    report = build_report(tmp_path)

    assert report.backend_without_frontend == []
    assert {item.classification for item in report.classified_backend_without_frontend} == {
        "agent_inbox_api",
        "legacy_or_external_config_action",
        "legacy_chat_review_action",
        "self_evolution_auxiliary_api",
        "worktree_run_detail_or_sse_api",
        "prompt_template_reset_api",
        "agent_memory_source_api",
        "research_org_agent_proposal_api",
        "generated_tool_validation_api",
    }


def test_type_contract_audit_separates_same_path_by_method(tmp_path):
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        """
fetchJson<SessionSummary[]>("/api/sessions");
fetchJson<SessionDetail>("/api/sessions", { method: "POST" });
""",
    )

    report = build_type_report(tmp_path)

    assert report.conflict_count == 0
    assert report.endpoint_count == 2


def test_type_contract_audit_reports_same_method_path_type_conflicts(tmp_path):
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        """
fetchJson<AgentInstance[]>("/api/agents");
fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents");
requestJson<AgentInstance[]>("/api/agents");
""",
    )

    report = build_type_report(tmp_path)
    text = type_report_to_text(report)

    assert report.conflict_count == 1
    assert "GET /api/agents" in text
    assert "AgentConfigWorkspaceAgent[]" in text
    assert "AgentInstance[]" in text


def test_type_contract_audit_ignores_frontend_test_files_and_dynamic_suffixes(tmp_path):
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        """
const suffix = "run-broad-search";
fetchJson<ResearchDiscoverySessionPayload>(
  `/api/research/theme-discovery/sessions/${encodeURIComponent(sessionId)}/${suffix}`,
  { method: "POST" },
);
""",
    )
    write_text(
        tmp_path / "web" / "src" / "Route.test.ts",
        """
fetchJson<TestOnlyType>("/api/agents");
fetchJson<AnotherTestOnlyType>("/api/agents");
""",
    )

    report = build_type_report(tmp_path)

    assert report.conflict_count == 0
    assert report.typed_call_count == 0
    assert len(report.dynamic_frontend_calls) == 1


def test_contract_audit_recursively_discovers_nested_route_modules(tmp_path):
    write_text(tmp_path / "core" / "web" / "app.py", "")
    write_text(
        tmp_path / "core" / "web" / "routes" / "team_workflows" / "research_projects.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.get("/teams/{team_id}/workflow-orchestration/research-projects")
def list_projects(team_id: str):
    return {}

@router.post("/teams/{team_id}/workflow-orchestration/research-projects")
def create_project(team_id: str):
    return {}
""",
    )
    write_text(tmp_path / "web" / "src" / "empty.ts", "")

    backend = find_backend_routes(tmp_path)

    assert len(backend) == 2
    assert {item.path for item in backend} == {
        "/api/teams/{param}/workflow-orchestration/research-projects"
    }
    assert {item.method for item in backend} == {"GET", "POST"}
    assert {item.file for item in backend} == {
        "core/web/routes/team_workflows/research_projects.py"
    }


def test_inventory_report_lists_every_endpoint_and_deterministic_counts(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health():
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "sessions.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    return {}

@router.post("/sessions")
def create_session():
    return {}

@router.post("/sessions/{session_id}/events")
def events(session_id: str):
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "team_workflows" / "orchestration.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.put("/teams/{team_id}/workflow-orchestration/state")
def set_state(team_id: str):
    return {}
""",
    )

    report = build_inventory_report(tmp_path)

    assert report.route_count == 5
    assert report.route_module_count == 3
    assert report.prefix_count == 3
    assert [(item.method, item.path) for item in report.endpoints] == [
        ("GET", "/api/health"),
        ("GET", "/api/sessions/{param}"),
        ("POST", "/api/sessions"),
        ("POST", "/api/sessions/{param}/events"),
        ("PUT", "/api/teams/{param}/workflow-orchestration/state"),
    ]
    assert report.method_counts == {"GET": 2, "POST": 2, "PUT": 1}
    assert report.route_module_counts == {
        "core/web/routes/sessions.py": 3,
        "core/web/app.py": 1,
        "core/web/routes/team_workflows/orchestration.py": 1,
    }
    assert report.prefix_counts == {"sessions": 3, "health": 1, "teams": 1}


def test_inventory_report_is_deterministic_across_runs(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health():
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "team_workflows" / "experiment.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/teams/{team_id}/workflow-orchestration/experiments/{experiment_id}/complete")
def complete(team_id: str, experiment_id: str):
    return {}
""",
    )

    first = build_inventory_report(tmp_path)
    second = build_inventory_report(tmp_path)

    assert first == second
    assert inventory_report_to_json(first) == inventory_report_to_json(second)


def test_inventory_report_text_output_contains_all_counts(tmp_path):
    write_text(
        tmp_path / "core" / "web" / "app.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health():
    return {}
""",
    )
    write_text(
        tmp_path / "core" / "web" / "routes" / "team_workflows" / "research_ops.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/teams/{team_id}/workflow-orchestration/research-ops/scan")
def scan(team_id: str):
    return {}
""",
    )

    text = inventory_report_to_text(build_inventory_report(tmp_path))

    assert "Backend API Inventory" in text
    assert "- backend endpoints: 2" in text
    assert "- GET /api/health" in text
    assert "POST /api/teams/{param}/workflow-orchestration/research-ops/scan" in text
    assert "Counts by method:" in text
    assert "Counts by route module:" in text
    assert "Counts by API prefix:" in text
    assert "core/web/routes/team_workflows/research_ops.py: 1" in text


def test_contract_audit_preserves_drift_semantics_with_recursive_discovery(tmp_path):
    write_text(tmp_path / "core" / "web" / "app.py", "")
    write_text(
        tmp_path / "core" / "web" / "routes" / "team_workflows" / "stage_rounds.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/teams/{team_id}/workflow-orchestration/stage-rounds/{round_id}/complete")
def complete(team_id: str, round_id: str):
    return {}
""",
    )
    write_text(
        tmp_path / "web" / "src" / "Route.tsx",
        'fetchJson<Missing>("/api/unknown");',
    )

    report = build_report(tmp_path)

    assert report.backend_route_count == 1
    assert {item.path for item in report.backend_without_frontend} == {
        "/api/teams/{param}/workflow-orchestration/stage-rounds/{param}/complete"
    }
    assert {item.path for item in report.frontend_without_backend} == {"/api/unknown"}
    assert report.potential_drift_count == 2
