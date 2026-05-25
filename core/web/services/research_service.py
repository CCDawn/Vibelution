"""Web service facade for Research theme discovery."""

from __future__ import annotations

from typing import Any

from core.research import ResearchThemeDiscoveryService
from core.infrastructure.workspace_manager import get_workspace


_SERVICE = ResearchThemeDiscoveryService()
_RESEARCH_PROMPT_FILES = {
    "broad": "broad.md",
    "deep": "deep.md",
    "review": "review.md",
    "themes": "themes.md",
    "card": "card.md",
}


def list_theme_discovery_sessions() -> dict[str, Any]:
    return _SERVICE.list_sessions()


def create_theme_discovery_session(payload: dict[str, Any]) -> dict[str, Any]:
    return _SERVICE.create_session(payload)


def get_theme_discovery_session(session_id: str) -> dict[str, Any]:
    return _SERVICE.get_session(session_id)


def run_broad_theme_search(session_id: str) -> dict[str, Any]:
    return _SERVICE.run_broad_search(session_id)


def run_deep_theme_search(session_id: str) -> dict[str, Any]:
    return _SERVICE.run_deep_search(session_id)


def extract_theme_discovery_evidence(session_id: str) -> dict[str, Any]:
    return _SERVICE.extract_evidence(session_id)


def generate_candidate_themes(session_id: str) -> dict[str, Any]:
    return _SERVICE.generate_themes(session_id)


def run_theme_discovery_draft(session_id: str) -> dict[str, Any]:
    return _SERVICE.run_draft(session_id)


def select_candidate_theme(session_id: str, theme_id: str) -> dict[str, Any]:
    return _SERVICE.select_theme(session_id, theme_id)


def generate_theme_card(session_id: str, theme_id: str) -> dict[str, Any]:
    return _SERVICE.generate_theme_card(session_id, theme_id)


def approve_theme_card(session_id: str, card_id: str) -> dict[str, Any]:
    return _SERVICE.approve_theme_card(session_id, card_id)


def list_research_prompts() -> dict[str, Any]:
    workspace = get_workspace()
    prompts: list[dict[str, Any]] = []
    for key, filename in _RESEARCH_PROMPT_FILES.items():
        prompts.append(
            {
                "key": key,
                "filename": filename,
                "path": str(workspace.get_research_prompt_path(filename)),
                "content": workspace.read_research_prompt(filename),
            }
        )
    return {
        "root": str(workspace.research_prompts_dir()),
        "prompts": prompts,
    }


def save_research_prompt(key: str, content: str) -> dict[str, Any]:
    normalized = str(key or "").strip().lower()
    if normalized not in _RESEARCH_PROMPT_FILES:
        raise ValueError(f"Unknown research prompt key: {key}")
    workspace = get_workspace()
    filename = _RESEARCH_PROMPT_FILES[normalized]
    if not workspace.write_research_prompt(filename, str(content or "")):
        raise ValueError("Failed to write research prompt.")
    return list_research_prompts()
