"""JSON repository for Research theme discovery sessions."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, TypeVar

from core.infrastructure.workspace_manager import get_workspace

from .models import (
    CandidateTheme,
    EvidenceRecord,
    ResearchDiscoverySession,
    ResearchSource,
    SearchRun,
    ThemeCard,
    validate_safe_id,
)


T = TypeVar("T")


class ResearchRepository:
    def __init__(self, root: Path | None = None):
        project_root = get_workspace().project_root.resolve()
        self.root = (root or project_root / "workspace" / "research" / "theme_discovery").resolve()

    @property
    def sessions_root(self) -> Path:
        return self.root / "sessions"

    def list_sessions(self) -> list[ResearchDiscoverySession]:
        if not self.sessions_root.exists():
            return []
        sessions: list[ResearchDiscoverySession] = []
        for path in sorted(self.sessions_root.glob("*/session.json")):
            payload = _load_json(path, fallback={})
            if isinstance(payload, dict) and payload:
                try:
                    sessions.append(ResearchDiscoverySession.from_dict(payload))
                except ValueError:
                    continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def save_session(self, session: ResearchDiscoverySession) -> None:
        _atomic_write_json(self._session_dir(session.session_id) / "session.json", session.to_dict())

    def load_session(self, session_id: str) -> ResearchDiscoverySession:
        session_id = validate_safe_id(session_id, label="session id")
        payload = _load_json(self._session_dir(session_id) / "session.json", fallback={})
        if not isinstance(payload, dict) or not payload:
            raise FileNotFoundError("Research discovery session not found.")
        return ResearchDiscoverySession.from_dict(payload)

    def delete_session(self, session_id: str) -> None:
        session_id = validate_safe_id(session_id, label="session id")
        session_dir = self._session_dir(session_id).resolve()
        sessions_root = self.sessions_root.resolve()
        if session_dir.parent != sessions_root:
            raise ValueError("Invalid session path.")
        if not (session_dir / "session.json").exists():
            raise FileNotFoundError("Research discovery session not found.")
        shutil.rmtree(session_dir)

    def save_search_runs(self, session_id: str, items: list[SearchRun]) -> None:
        _atomic_write_json_list(self._session_dir(session_id) / "search_runs.json", [item.to_dict() for item in items])

    def load_search_runs(self, session_id: str) -> list[SearchRun]:
        return _load_list(self._session_dir(session_id) / "search_runs.json", SearchRun.from_dict)

    def save_sources(self, session_id: str, items: list[ResearchSource]) -> None:
        _atomic_write_json_list(self._session_dir(session_id) / "sources.json", [item.to_dict() for item in items])

    def load_sources(self, session_id: str) -> list[ResearchSource]:
        return _load_list(self._session_dir(session_id) / "sources.json", ResearchSource.from_dict)

    def save_evidence(self, session_id: str, items: list[EvidenceRecord]) -> None:
        _atomic_write_json_list(self._session_dir(session_id) / "evidence.json", [item.to_dict() for item in items])

    def load_evidence(self, session_id: str) -> list[EvidenceRecord]:
        return _load_list(self._session_dir(session_id) / "evidence.json", EvidenceRecord.from_dict)

    def save_candidate_themes(self, session_id: str, items: list[CandidateTheme]) -> None:
        _atomic_write_json_list(
            self._session_dir(session_id) / "candidate_themes.json",
            [item.to_dict() for item in items],
        )

    def load_candidate_themes(self, session_id: str) -> list[CandidateTheme]:
        return _load_list(self._session_dir(session_id) / "candidate_themes.json", CandidateTheme.from_dict)

    def save_theme_cards(self, session_id: str, items: list[ThemeCard]) -> None:
        _atomic_write_json_list(self._session_dir(session_id) / "theme_cards.json", [item.to_dict() for item in items])

    def load_theme_cards(self, session_id: str) -> list[ThemeCard]:
        return _load_list(self._session_dir(session_id) / "theme_cards.json", ThemeCard.from_dict)

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        events = _load_json(self._session_dir(session_id) / "events.json", fallback=[])
        if not isinstance(events, list):
            events = []
        events.append(event)
        _atomic_write_json_list(self._session_dir(session_id) / "events.json", events)

    def replace_event(self, session_id: str, event_code: str, event: dict[str, Any]) -> None:
        events = _load_json(self._session_dir(session_id) / "events.json", fallback=[])
        if not isinstance(events, list):
            events = []
        for index in range(len(events) - 1, -1, -1):
            item = events[index]
            if isinstance(item, dict) and item.get("eventCode") == event_code:
                events[index] = event
                _atomic_write_json_list(self._session_dir(session_id) / "events.json", events)
                return
        events.append(event)
        _atomic_write_json_list(self._session_dir(session_id) / "events.json", events)

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        payload = _load_json(self._session_dir(session_id) / "events.json", fallback=[])
        return payload if isinstance(payload, list) else []

    def load_snapshot(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        return {
            "session": session.to_dict(),
            "searchRuns": [item.to_dict() for item in self.load_search_runs(session.session_id)],
            "sources": [item.to_dict() for item in self.load_sources(session.session_id)],
            "evidence": [item.to_dict() for item in self.load_evidence(session.session_id)],
            "candidateThemes": [item.to_dict() for item in self.load_candidate_themes(session.session_id)],
            "themeCards": [item.to_dict() for item in self.load_theme_cards(session.session_id)],
            "events": self.load_events(session.session_id),
        }

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_root / validate_safe_id(session_id, label="session id")


def _load_list(path: Path, factory: Callable[[dict[str, Any]], T]) -> list[T]:
    payload = _load_json(path, fallback=[])
    if not isinstance(payload, list):
        return []
    result: list[T] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            result.append(factory(item))
        except ValueError:
            continue
    return result


def _load_json(path: Path, *, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _atomic_write_json_list(path: Path, payload: list[Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
