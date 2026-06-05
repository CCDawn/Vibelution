"""Serializable models for the Research theme discovery MVP."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


SessionStatus = Literal["draft", "running", "reviewing", "selected", "archived", "failed"]
SearchPhase = Literal["broad", "deep"]
SearchStatus = Literal["draft", "running", "completed", "failed"]
SourceKind = Literal["paper", "github", "dataset", "web"]
SourceReliability = Literal["verified", "normal", "weak"]
EvidenceType = Literal["method", "dataset", "result", "gap", "implementation", "background"]
EvidenceConfidence = Literal["high", "medium", "low"]
NoveltyPath = Literal["problem_perspective", "method_transfer", "discipline_combination", "application_scenario"]
ThemeStatus = Literal["draft", "shortlisted", "selected", "rejected", "stale"]
ThemeCardStatus = Literal["draft", "approved", "stale"]

ALLOWED_SESSION_STATUSES = {"draft", "running", "reviewing", "selected", "archived", "failed"}
ALLOWED_SEARCH_PHASES = {"broad", "deep"}
ALLOWED_SEARCH_STATUSES = {"draft", "running", "completed", "failed"}
ALLOWED_SOURCE_KINDS = {"paper", "github", "dataset", "web"}
ALLOWED_SOURCE_RELIABILITY = {"verified", "normal", "weak"}
ALLOWED_EVIDENCE_TYPES = {"method", "dataset", "result", "gap", "implementation", "background"}
ALLOWED_EVIDENCE_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_NOVELTY_PATHS = {
    "problem_perspective",
    "method_transfer",
    "discipline_combination",
    "application_scenario",
}
ALLOWED_THEME_STATUSES = {"draft", "shortlisted", "selected", "rejected", "stale"}
ALLOWED_THEME_CARD_STATUSES = {"draft", "approved", "stale"}

DEFAULT_DISCOVERY_GOAL = (
    "For XH-202619, develop a novel computer-science-plus-domain research theme where Vibelution acts as an "
    "AI Scientist platform and closes the loop from source input to verifiable scientific hypothesis and research "
    "plan output."
)
DEFAULT_DISCOVERY_CONSTRAINTS = (
    "Use a domestic open-source foundation model, especially Qwen; model calls should be explainable through "
    "Alibaba Cloud Bailian evidence or screenshots; the system should be a super-agent or multi-agent architecture "
    "with problem understanding, knowledge integration, association discovery, and verifiable hypothesis generation. "
    "The research-plan output should cover Problem Statement, Rationale, Technical Details, Datasets with Source "
    "and Target, Paper Title, Paper Abstract, Methods, Experiments, Baselines, Metrics, Results, and real References. "
    "A student team should be able to build an MVP before September 5, 2026."
)
DEFAULT_DISCOVERY_PREFERENCES = (
    "Prioritize upstream scientific research themes where the AI Scientist identifies knowledge gaps, proposes "
    "falsifiable hypotheses, designs experiments, evaluates results, and iterates. Align with scientific value, "
    "technical depth, and application potential; reject generic RAG, literature-review tools, hallucinated "
    "references, unreproducible datasets, and concepts without experimental metrics."
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(prefix or "id").strip().lower()).strip("-") or "id"
    return f"{normalized}-{uuid.uuid4().hex[:12]}"


def validate_safe_id(value: str, *, label: str = "id") -> str:
    normalized = str(value or "").strip()
    if not normalized or not _SAFE_ID_RE.fullmatch(normalized):
        raise ValueError(f"Invalid {label}.")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid {label}.")
    return normalized


def clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score < 0:
        return 0.0
    if score > 100:
        return 100.0
    return round(score, 2)


def normalize_nonempty_text(value: Any, *, label: str, max_length: int = 4000) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required.")
    if len(normalized) > max_length:
        return normalized[:max_length].rstrip()
    return normalized


def _validate_choice(value: str, allowed: set[str], *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unknown {label}: {value}")
    return normalized


def _list_of_strings(values: Any) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for raw in values if isinstance(values, list) else [values]:
        item = str(raw or "").strip()
        if item and item not in result:
            result.append(item)
    return result


@dataclass
class ResearchDiscoverySession:
    session_id: str
    open_goal: str = DEFAULT_DISCOVERY_GOAL
    constraints: str = DEFAULT_DISCOVERY_CONSTRAINTS
    preferences: str = DEFAULT_DISCOVERY_PREFERENCES
    candidate_count: int = 5
    status: SessionStatus = "draft"
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    selected_theme_id: str | None = None

    def __post_init__(self) -> None:
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.open_goal = normalize_nonempty_text(self.open_goal, label="open goal")
        self.constraints = normalize_nonempty_text(self.constraints, label="constraints")
        self.preferences = normalize_nonempty_text(self.preferences, label="preferences")
        self.candidate_count = max(1, min(10, int(self.candidate_count or 5)))
        self.status = _validate_choice(self.status, ALLOWED_SESSION_STATUSES, label="session status")  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchDiscoverySession":
        return cls(**_snakeize_dict(payload))


@dataclass
class SearchRun:
    run_id: str
    session_id: str
    phase: SearchPhase
    queries: list[str] = field(default_factory=list)
    provider: str = "deterministic"
    status: SearchStatus = "draft"
    started_at: str = field(default_factory=utcnow_iso)
    completed_at: str | None = None
    model_profile: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.run_id = validate_safe_id(self.run_id, label="search run id")
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.phase = _validate_choice(self.phase, ALLOWED_SEARCH_PHASES, label="search phase")  # type: ignore[assignment]
        self.status = _validate_choice(self.status, ALLOWED_SEARCH_STATUSES, label="search status")  # type: ignore[assignment]
        self.queries = _list_of_strings(self.queries)

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SearchRun":
        return cls(**_snakeize_dict(payload))


@dataclass
class ResearchSource:
    source_id: str
    session_id: str
    search_run_id: str
    kind: SourceKind
    title: str
    url: str
    snippet: str
    reliability: SourceReliability
    retrieved_at: str = field(default_factory=utcnow_iso)

    def __post_init__(self) -> None:
        self.source_id = validate_safe_id(self.source_id, label="source id")
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.search_run_id = validate_safe_id(self.search_run_id, label="search run id")
        self.kind = _validate_choice(self.kind, ALLOWED_SOURCE_KINDS, label="source kind")  # type: ignore[assignment]
        self.title = normalize_nonempty_text(self.title, label="source title", max_length=500)
        self.url = str(self.url or "").strip()
        self.snippet = str(self.snippet or "").strip()[:2000]
        self.reliability = _validate_choice(  # type: ignore[assignment]
            self.reliability,
            ALLOWED_SOURCE_RELIABILITY,
            label="source reliability",
        )

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSource":
        return cls(**_snakeize_dict(payload))


@dataclass
class EvidenceRecord:
    evidence_id: str
    session_id: str
    source_id: str
    claim: str
    evidence_type: EvidenceType
    confidence: EvidenceConfidence
    note: str = ""

    def __post_init__(self) -> None:
        self.evidence_id = validate_safe_id(self.evidence_id, label="evidence id")
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.source_id = validate_safe_id(self.source_id, label="source id")
        self.claim = normalize_nonempty_text(self.claim, label="evidence claim", max_length=1000)
        self.evidence_type = _validate_choice(  # type: ignore[assignment]
            self.evidence_type,
            ALLOWED_EVIDENCE_TYPES,
            label="evidence type",
        )
        self.confidence = _validate_choice(  # type: ignore[assignment]
            self.confidence,
            ALLOWED_EVIDENCE_CONFIDENCE,
            label="evidence confidence",
        )
        self.note = str(self.note or "").strip()[:1000]

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceRecord":
        return cls(**_snakeize_dict(payload))


@dataclass
class CandidateTheme:
    theme_id: str
    session_id: str
    title: str
    one_line: str
    interdisciplinary_combination: list[str]
    core_question: str
    novelty_path: NoveltyPath
    scores: dict[str, float]
    recommendation_score: float
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    uncertainty: str = ""
    agent_review: str = ""
    status: ThemeStatus = "draft"
    version: int = 1
    parent_run_id: str = ""

    def __post_init__(self) -> None:
        self.theme_id = validate_safe_id(self.theme_id, label="theme id")
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.title = normalize_nonempty_text(self.title, label="theme title", max_length=240)
        self.one_line = normalize_nonempty_text(self.one_line, label="one line", max_length=500)
        self.interdisciplinary_combination = _list_of_strings(self.interdisciplinary_combination)
        if not self.interdisciplinary_combination:
            self.interdisciplinary_combination = ["computer science", "scientific discovery"]
        self.core_question = normalize_nonempty_text(self.core_question, label="core question", max_length=1000)
        self.novelty_path = _validate_choice(  # type: ignore[assignment]
            self.novelty_path,
            ALLOWED_NOVELTY_PATHS,
            label="novelty path",
        )
        self.scores = {str(key): clamp_score(value) for key, value in dict(self.scores or {}).items()}
        self.recommendation_score = clamp_score(self.recommendation_score)
        self.source_ids = [validate_safe_id(item, label="source id") for item in _list_of_strings(self.source_ids)]
        self.evidence_ids = [
            validate_safe_id(item, label="evidence id") for item in _list_of_strings(self.evidence_ids)
        ]
        self.status = _validate_choice(self.status, ALLOWED_THEME_STATUSES, label="theme status")  # type: ignore[assignment]
        self.version = max(1, int(self.version or 1))
        if self.parent_run_id:
            self.parent_run_id = validate_safe_id(self.parent_run_id, label="parent run id")

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateTheme":
        return cls(**_snakeize_dict(payload))


@dataclass
class ThemeCard:
    card_id: str
    session_id: str
    theme_id: str
    title: str
    one_line: str
    core_scientific_question: str
    why_novel: str
    why_competition_fit: str
    interdisciplinary_combination: list[str] = field(default_factory=list)
    possible_datasets: list[str] = field(default_factory=list)
    possible_methods: list[str] = field(default_factory=list)
    possible_experiments: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    next_research_steps: list[str] = field(default_factory=list)
    agent_review: str = ""
    status: ThemeCardStatus = "draft"
    version: int = 1

    def __post_init__(self) -> None:
        self.card_id = validate_safe_id(self.card_id, label="theme card id")
        self.session_id = validate_safe_id(self.session_id, label="session id")
        self.theme_id = validate_safe_id(self.theme_id, label="theme id")
        self.title = normalize_nonempty_text(self.title, label="theme card title", max_length=240)
        self.one_line = normalize_nonempty_text(self.one_line, label="one line", max_length=500)
        self.core_scientific_question = normalize_nonempty_text(
            self.core_scientific_question,
            label="core scientific question",
            max_length=1000,
        )
        self.why_novel = normalize_nonempty_text(self.why_novel, label="why novel", max_length=1500)
        self.why_competition_fit = normalize_nonempty_text(
            self.why_competition_fit,
            label="why competition fit",
            max_length=1500,
        )
        self.interdisciplinary_combination = _list_of_strings(self.interdisciplinary_combination)
        self.possible_datasets = _list_of_strings(self.possible_datasets)
        self.possible_methods = _list_of_strings(self.possible_methods)
        self.possible_experiments = _list_of_strings(self.possible_experiments)
        self.risks = _list_of_strings(self.risks)
        self.references = _list_of_strings(self.references)
        self.next_research_steps = _list_of_strings(self.next_research_steps)
        self.status = _validate_choice(self.status, ALLOWED_THEME_CARD_STATUSES, label="theme card status")  # type: ignore[assignment]
        self.version = max(1, int(self.version or 1))

    def to_dict(self) -> dict[str, Any]:
        return _camelize_dict(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ThemeCard":
        return cls(**_snakeize_dict(payload))


def _camelize_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {_snake_to_camel(key): value for key, value in payload.items()}


def _snakeize_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {_camel_to_snake(key): value for key, value in payload.items()}


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
