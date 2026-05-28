from __future__ import annotations

from pathlib import Path

from scripts.api_contract_audit import (
    build_report,
    find_backend_routes,
    find_frontend_calls,
    normalize_api_path,
    report_to_text,
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
