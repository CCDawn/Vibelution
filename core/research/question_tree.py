"""STORM-inspired, deterministic multi-perspective research question trees."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


_LOCK = threading.RLock()
_REQUIRED_PERSPECTIVES = (
    ("mechanism", "Mechanism", "Identify the proposed mechanism, its source claims, and operational definitions"),
    ("empirical", "Empirical evidence", "Find primary experiments, datasets, measurements, and replication evidence"),
    ("alternatives", "Alternatives", "Find competing explanations, negative results, and contradictory evidence"),
    ("implementation", "Implementation", "Map the claim to algorithms, controls, costs, and reproducible implementation choices"),
    ("falsification", "Falsification", "Identify tests and observations that would reject or narrow the claim"),
)


class ResearchQuestionTreeError(ValueError):
    """Raised when a question tree violates bounded research planning rules."""


class ResearchQuestionTreeStore:
    def __init__(self, project_root: str | os.PathLike[str]) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    def create(
        self,
        team_id: str,
        *,
        research_question: str,
        created_by_agent: str,
        custom_perspectives: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        team = _safe_id(team_id, "teamId")
        question = _required_text(research_question, "researchQuestion", 1200)
        creator = _required_text(created_by_agent, "createdByAgent", 200)
        perspectives = _perspectives(question, custom_perspectives or [])
        tree_id = f"question-tree-{_stable_hash({'teamId': team, 'question': question, 'perspectives': perspectives})[:20]}"
        path = self._path(team)
        with _LOCK:
            records = _read_json(path)
            existing = next((item for item in records if item.get("questionTreeId") == tree_id), None)
            if existing is not None:
                return existing
            now = _now_utc()
            required_ids = {item[0] for item in _REQUIRED_PERSPECTIVES}
            observed_ids = {item["perspectiveId"] for item in perspectives}
            tree = {
                "schemaVersion": 1,
                "questionTreeId": tree_id,
                "teamId": team,
                "researchQuestion": question,
                "perspectives": perspectives,
                "coverage": {
                    "requiredPerspectiveCount": len(required_ids),
                    "coveredRequiredPerspectiveCount": len(required_ids & observed_ids),
                    "requiredPerspectiveCoverage": round(len(required_ids & observed_ids) / len(required_ids), 4),
                    "totalPerspectiveCount": len(perspectives),
                },
                "status": "planned",
                "createdByAgent": creator,
                "createdAt": now,
                "updatedAt": now,
                "boundaries": {
                    "externalSearchTriggered": False,
                    "writesCandidateStore": False,
                    "writesFormalKnowledge": False,
                    "requiresExplicitExecution": True,
                },
            }
            records.append(tree)
            _write_json_atomic(path, records)
        _record_event(
            "research_question_tree.generated",
            {"teamId": team, "questionTreeId": tree_id, "perspectiveCount": len(perspectives)},
        )
        return tree

    def list(self, team_id: str) -> list[dict[str, Any]]:
        team = _safe_id(team_id, "teamId")
        with _LOCK:
            return _read_json(self._path(team))

    def _path(self, team_id: str) -> Path:
        return self.project_root / "workspace" / "teams" / team_id / "research_question_trees" / "index.json"


def _perspectives(question: str, custom: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [
        {
            "perspectiveId": perspective_id,
            "label": label,
            "prompt": prompt,
            "query": f"{question} — {prompt}.",
            "source": "storm_inspired_required_perspective",
        }
        for perspective_id, label, prompt in _REQUIRED_PERSPECTIVES
    ]
    seen = {item["perspectiveId"] for item in rows}
    for raw in list(custom)[:8]:
        item = raw if isinstance(raw, dict) else {}
        perspective_id = _safe_id(item.get("perspectiveId"), "perspectiveId")
        if perspective_id in seen:
            continue
        label = _required_text(item.get("label"), "label", 120)
        prompt = _required_text(item.get("prompt"), "prompt", 500)
        rows.append(
            {
                "perspectiveId": perspective_id,
                "label": label,
                "prompt": prompt,
                "query": f"{question} — {prompt}.",
                "source": "user_defined_perspective",
            }
        )
        seen.add(perspective_id)
    return rows


def _read_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ResearchQuestionTreeError("Research question tree index is invalid.")
    return payload


def _write_json_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _required_text(value: Any, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ResearchQuestionTreeError(f"{field} is required.")
    if len(text) > max_length:
        raise ResearchQuestionTreeError(f"{field} exceeds maximum length {max_length}.")
    return text


def _safe_id(value: Any, field: str) -> str:
    text = _required_text(value, field, 160)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", text):
        raise ResearchQuestionTreeError(f"{field} contains unsupported characters.")
    return text


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_event(event_code: str, fields: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "research_question_tree",
            "planning",
            event_code,
            message=event_code,
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return
