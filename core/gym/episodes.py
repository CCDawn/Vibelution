# -*- coding: utf-8 -*-
"""Persistence helpers for Gym v1 improvement episodes."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Optional

from core.infrastructure.workspace_manager import get_workspace

from .models import Attempt, ImprovementEpisode, PromotionProposal, Trace, utcnow_iso

_SAFE_GYM_FILE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WINDOWS_RESERVED_FILE_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _gym_workspace(project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    return root / "workspace" / "gym"


def decision_path_for_episode_id(episode_id: str, *, project_root: Optional[Path] = None) -> Path:
    return _gym_workspace(project_root) / "decisions" / f"{_safe_gym_file_stem(episode_id, default='episode')}.json"


def trace_index_path_for_episode_id(episode_id: str, *, project_root: Optional[Path] = None) -> Path:
    return _gym_workspace(project_root) / "traces" / _safe_gym_file_stem(episode_id, default="episode") / "index.json"


def record_improvement_episode(episode: ImprovementEpisode, *, project_root: Optional[Path] = None) -> Path:
    base_dir = _gym_workspace(project_root)
    decisions_dir = base_dir / "decisions"
    proposals_dir = base_dir / "promotion_proposals"
    decision_path = decision_path_for_episode_id(episode.episode_id, project_root=project_root)
    trace_index_path = trace_index_path_for_episode_id(episode.episode_id, project_root=project_root)
    traces_dir = trace_index_path.parent
    decisions_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)

    if episode.decision == "PROMOTE":
        proposal_id = f"{episode.episode_id}:{episode.candidate_improvement.improvement_id}"
        proposal_path = proposals_dir / f"{_safe_gym_file_stem(proposal_id, default='proposal')}.json"
        proposal = PromotionProposal(
            proposal_id=proposal_id,
            episode_id=episode.episode_id,
            candidate_improvement_id=episode.candidate_improvement.improvement_id,
            status="proposed",
            action="write_promotion_proposal",
            created_at=utcnow_iso(),
            proposal_path=str(proposal_path),
        )
        episode.promotion_proposal = proposal
        proposal_payload = proposal.to_dict()
        proposal_payload["decision_path"] = str(decision_path)
        proposal_payload["trace_index_path"] = str(trace_index_path)
        proposal_path.write_text(json.dumps(proposal_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _write_trace_index(episode, traces_dir=traces_dir, trace_index_path=trace_index_path)
    decision_path.write_text(json.dumps(episode.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return decision_path


def trace_index_path_for_decision(decision_path: Path) -> Path:
    """Return the trace index path that belongs to a persisted Gym decision."""

    episode_id = decision_path.stem
    gym_root = decision_path.parent.parent
    return gym_root / "traces" / episode_id / "index.json"


def _write_trace_index(episode: ImprovementEpisode, *, traces_dir: Path, trace_index_path: Path) -> None:
    entries = []
    attempts_by_trace_id: dict[str, Attempt] = {
        attempt.trace_id: attempt for attempt in [*episode.baseline_attempts, *episode.candidate_attempts]
    }
    for role, traces in (("baseline", episode.baseline_traces), ("candidate", episode.candidate_traces)):
        for trace in traces:
            trace_path = traces_dir / _trace_filename(trace)
            trace_path.write_text(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            attempt = attempts_by_trace_id.get(trace.trace_id)
            entries.append(
                {
                    "role": role,
                    "case_id": trace.case_id,
                    "trace_id": trace.trace_id,
                    "attempt_id": attempt.attempt_id if attempt else "",
                    "path": str(trace_path),
                }
            )
    trace_index = {
        "episode_id": episode.episode_id,
        "created_at": utcnow_iso(),
        "traces": entries,
    }
    trace_index_path.write_text(json.dumps(trace_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trace_filename(trace: Trace) -> str:
    return f"{_safe_gym_file_stem(trace.trace_id or trace.case_id, default='trace')}.json"


def _safe_gym_file_stem(value: str, *, default: str) -> str:
    raw = str(value or "").strip()
    stem = _SAFE_GYM_FILE_STEM_RE.sub("-", raw).strip("._-")
    if not stem:
        stem = default
    base_name = stem.split(".", 1)[0].upper()
    should_hash = stem != raw or len(stem) > 140 or base_name in _WINDOWS_RESERVED_FILE_STEMS
    if base_name in _WINDOWS_RESERVED_FILE_STEMS:
        stem = f"{default}-{stem}"
    if should_hash:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        stem = f"{stem[:128].rstrip('._-') or default}-{digest}"
    return stem
